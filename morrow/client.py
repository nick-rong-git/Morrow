"""
Morrow 核心学习客户端 (Morrow Learning Client)
封装与墨墨官方 WebSocket 网关与 REST API 的双向交互协议。
"""

from __future__ import annotations

import ssl
import time
import json
import asyncio
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional, Dict, Any, List

import websockets
from websockets.exceptions import ConnectionClosed

# ---------------------------------------------------------------------------
# 协议常量
# ---------------------------------------------------------------------------

WS_URL = "wss://tc-apis.maimemo.com/study/ws/webstudy"
REST_PROGRESS_URL = "https://open.maimemo.com/open/api/v1/study/get_study_progress"

EV_SYSTEM_READY = 1
EV_SYSTEM_PING = 2
EV_SYSTEM_SUBSCRIBE_TOPICS = 3
EV_WEBSTUDY_INIT_STUDY = 1001
EV_WEBSTUDY_GET_WORD = 1002
EV_WEBSTUDY_SUBMIT_RESPONSE = 1003
EV_WEBSTUDY_ADD_WORDS = 1011

EVENT_NAMES: Dict[int, str] = {
    1: "SYSTEM_READY",
    2: "SYSTEM_PING",
    3: "SYSTEM_SUBSCRIBE_TOPICS",
    1001: "WEBSTUDY_INIT_STUDY",
    1002: "WEBSTUDY_GET_WORD",
    1003: "WEBSTUDY_SUBMIT_RESPONSE",
    1011: "WEBSTUDY_ADD_WORDS",
}

# 学习反馈枚举
STUDY_RESPONSE: Dict[str, int] = {
    "FAMILIAR": 1,
    "VAGUE": 2,
    "FORGET": 3,
    "WELL_FAMILIAR": 4,
    "CANCEL_WELL_FAMILIAR": 5,
    "RECOGNIZE": 1,
    "FUZZY": 2,
}
STUDY_METHOD: Dict[str, int] = {"STUDY_EN_CN": 0, "STUDY_CN_EN": 1}

# ---------------------------------------------------------------------------
# Protobuf 编解码
# ---------------------------------------------------------------------------

def _enc_varint(v: int) -> bytes:
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)

def _enc_tag(field: int, wire: int) -> bytes:
    return _enc_varint((field << 3) | wire)

def _enc_string(field: int, s: str) -> bytes:
    data = s.encode("utf-8")
    return _enc_tag(field, 2) + _enc_varint(len(data)) + data

def _enc_bytes(field: int, b: bytes) -> bytes:
    return _enc_tag(field, 2) + _enc_varint(len(b)) + b

def _enc_int32(field: int, v: int) -> bytes:
    return _enc_tag(field, 0) + _enc_varint(v & 0xFFFFFFFFFFFFFFFF)

def _enc_bool(field: int, v: bool) -> bytes:
    return _enc_tag(field, 0) + _enc_varint(1 if v else 0)

def _dec_varint(buf: bytes, pos: int):
    result = 0
    for shift in range(0, 70, 7):
        if pos >= len(buf):
            raise ValueError("Varint 截断")
        b = buf[pos]
        pos += 1
        if shift == 63 and b > 1:
            raise ValueError("Varint 溢出")
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
    raise ValueError("Varint 溢出")

def _decode_message(buf: bytes) -> Dict[int, list]:
    out: Dict[int, list] = {}
    pos = 0
    while pos < len(buf):
        tag, pos = _dec_varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if not 0 < field < (1 << 29):
            raise ValueError("无效的 Protobuf 字段编号")
        if wire == 0:
            val, pos = _dec_varint(buf, pos)
        elif wire == 2:
            length, pos = _dec_varint(buf, pos)
            val = buf[pos:pos + length]
            pos += length
        elif wire == 1:
            val = buf[pos:pos + 8]
            pos += 8
        elif wire == 5:
            val = buf[pos:pos + 4]
            pos += 4
        else:
            raise ValueError("不支持的 Protobuf 字段类型")
        if pos > len(buf):
            raise ValueError("Protobuf 字段截断")
        out.setdefault(field, []).append(val)
    return out

def _get_str(fields: Dict[int, list], num: int, default: str = "") -> str:
    v = fields.get(num)
    if not v:
        return default
    raw = v[0]
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)

def _get_int(fields: Dict[int, list], num: int, default: int = 0) -> int:
    v = fields.get(num)
    return int(v[0]) if v else default

def _get_bytes_list(fields: Dict[int, list], num: int) -> List[bytes]:
    return [v for v in fields.get(num, []) if isinstance(v, (bytes, bytearray))]

def encode_envelope(msg_id: str, event: int, data: bytes = b"") -> bytes:
    return (
        _enc_string(1, msg_id)
        + _enc_int32(3, event)
        + _enc_bytes(4, data)
        + _enc_bool(5, True)
    )

def encode_get_word_request(back: bool) -> bytes:
    return _enc_bool(1, True) if back else b""

def encode_submit_request(
    voc_id: str, response: str, study_method: str,
    recall_duration: int, study_duration: int,
) -> bytes:
    out = b""
    if voc_id:
        out += _enc_string(1, voc_id)
    resp_n = STUDY_RESPONSE.get(response, 1)
    if resp_n:
        out += _enc_int32(2, resp_n)
    sm_n = STUDY_METHOD.get(study_method, 0)
    if sm_n:
        out += _enc_int32(3, sm_n)
    if recall_duration:
        out += _enc_int32(4, recall_duration)
    if study_duration:
        out += _enc_int32(5, study_duration)
    return out

def encode_add_words_request(count: int, mode: int = 2) -> bytes:
    inner = _enc_int32(1, count) + _enc_int32(2, mode)
    return _enc_bytes(2, inner)

def parse_envelope(buf: bytes) -> Dict[str, Any]:
    f = _decode_message(buf)
    errors = []
    for err_buf in _get_bytes_list(f, 6):
        ef = _decode_message(err_buf)
        err = {}
        for fnum, vals in ef.items():
            for v in vals:
                err[fnum] = v.decode("utf-8", errors="replace") if isinstance(v, (bytes, bytearray)) else v
        errors.append(err)
    data_list = _get_bytes_list(f, 4)
    return {
        "id": _get_str(f, 1),
        "reply_id": _get_str(f, 2),
        "event": _get_int(f, 3),
        "data": data_list[0] if data_list else b"",
        "success": bool(_get_int(f, 5, 0)),
        "errors": errors,
    }

def parse_web_study_word(buf: bytes) -> Dict[str, Any]:
    f = _decode_message(buf)
    speeches: Dict[str, str] = {}
    for ab in _get_bytes_list(f, 11):
        af = _decode_message(ab)
        accent = _get_str(af, 2).strip().upper()
        url = _get_str(af, 3).strip()
        if accent and url:
            speeches[accent] = url

    return {
        "id": _get_str(f, 1),
        "voc_id": _get_int(f, 2),
        "spelling": _get_str(f, 3),
        "phonetic_us": _get_str(f, 4),
        "phonetic_uk": _get_str(f, 5),
        "hyphenation": _get_str(f, 6),
        "difficulty": _get_int(f, 7),
        "speeches": speeches,
        "audio_us": speeches.get("US", ""),
        "audio_uk": speeches.get("UK", ""),
    }

def parse_get_word_response(buf: bytes) -> Dict[str, Any]:
    f = _decode_message(buf)
    word_bufs = _get_bytes_list(f, 1)
    word = parse_web_study_word(word_bufs[0]) if word_bufs else {}

    interpretations: List[str] = []
    interp_tags: List[str] = []
    for ib in _get_bytes_list(f, 2):
        fi = _decode_message(ib)
        text = _get_str(fi, 3)
        if text:
            interpretations.append(text)
        for tb in _get_bytes_list(fi, 5):
            t_str = tb.decode("utf-8", errors="replace").strip()
            if t_str and t_str not in interp_tags:
                interp_tags.append(t_str)

    phrases: List[Dict[str, Any]] = []
    for pb in _get_bytes_list(f, 3):
        pf = _decode_message(pb)
        en = _get_str(pf, 3)
        cn = _get_str(pf, 4)
        if not en:
            continue
        tags = []
        for tb in _get_bytes_list(pf, 7):
            t_str = tb.decode("utf-8", errors="replace").strip()
            if t_str and t_str not in tags:
                tags.append(t_str)
        hl_raw = _get_bytes_list(pf, 6)
        hl = None
        if hl_raw and len(hl_raw[0]) >= 2:
            hl = (hl_raw[0][0], hl_raw[0][1])
        phrases.append({
            "en": en,
            "cn": cn,
            "tags": tags,
            "highlight": hl,
        })

    notes: List[Dict[str, str]] = []
    for nb in _get_bytes_list(f, 4):
        nf = _decode_message(nb)
        title = _get_str(nf, 3)
        content = _get_str(nf, 4)
        if title or content:
            notes.append({"title": title, "content": content})

    progress: Dict[str, int] = {}
    prog_bufs = _get_bytes_list(f, 22)
    if prog_bufs:
        pf = _decode_message(prog_bufs[0])
        progress = {
            "finished": _get_int(pf, 1),
            "total": _get_int(pf, 2),
        }

    return {
        "id": word.get("id", ""),
        "voc_id": word.get("voc_id", 0),
        "spelling": word.get("spelling", ""),
        "phonetic_us": word.get("phonetic_us", ""),
        "phonetic_uk": word.get("phonetic_uk", ""),
        "hyphenation": word.get("hyphenation", ""),
        "difficulty": word.get("difficulty", 0),
        "speeches": word.get("speeches", {}),
        "audio_us": word.get("audio_us", ""),
        "audio_uk": word.get("audio_uk", ""),
        "interpretation": "\n".join(interpretations),
        "interpretations": interpretations,
        "interp_tags": interp_tags,
        "phrases": phrases,
        "notes": notes,
        "study_time_ms": _get_int(f, 23),
        "progress": progress,
    }


class MorrowClient:
    """Morrow 核心网络客户端，支持长连接保持与异常自愈"""
    def __init__(self, ws_token: str, rest_token: str = ""):
        self.ws_token = ws_token.strip()
        self.rest_token = rest_token.strip()
        self.rest_auth_failed = False
        self.ws = None
        self._ssl_ctx = ssl.create_default_context()

        self._connected = False
        self._msg_seq = 0
        self._pending: Dict[str, asyncio.Future] = {}
        self._recv_task: Optional[asyncio.Task] = None
        self._ready_event: Optional[asyncio.Event] = None
        self._last_word_received_at: Optional[float] = None
        self.last_next_word: Optional[Dict[str, Any]] = None
        self.last_request_rejected = False
        self.last_error: str = ""
        self.progress: Dict[str, int] = {}

    def _next_id(self) -> str:
        self._msg_seq += 1
        return f"morrow-{self._msg_seq}"

    @property
    def is_alive(self) -> bool:
        return self._connected and self.ws is not None

    async def connect(self) -> bool:
        if self.is_alive:
            return True
        if self.ws is not None:
            await self.close()
        if not self.ws_token:
            self.last_error = "尚未配置 ws_token"
            return False

        query = urllib.parse.urlencode({"token": urllib.parse.unquote(self.ws_token)})
        url = f"{WS_URL}?{query}"
        self.last_error = ""
        try:
            self.ws = await websockets.connect(url, ssl=self._ssl_ctx)
        except Exception as e:
            self.last_error = f"连接网关失败: {type(e).__name__}"
            response = getattr(e, "response", None)
            status = getattr(response, "status_code", None) or getattr(e, "status_code", None)
            if status is not None:
                self.last_error += f" (HTTP {status})"
            return False

        self._connected = True
        self._ready_event = asyncio.Event()
        self._recv_task = asyncio.create_task(self._recv_loop())
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            self.last_error = "等待 SYSTEM_READY 握手超时"
        except asyncio.CancelledError:
            await self.close()
            raise
        else:
            if self.is_alive:
                return True
        await self.close()
        return False

    async def close(self):
        self._connected = False
        recv_task, self._recv_task = self._recv_task, None
        if recv_task and not recv_task.done():
            recv_task.cancel()
            try:
                await recv_task
            except asyncio.CancelledError:
                pass
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.ws = None

    async def _send_envelope(self, msg_id: str, event: int, data: bytes = b""):
        await self.ws.send(encode_envelope(msg_id, event, data))

    async def _reply_ping(self, ping_id: str):
        frame = (
            _enc_string(1, "")
            + _enc_string(2, ping_id)
            + _enc_int32(3, EV_SYSTEM_PING)
            + _enc_bytes(4, b"")
            + _enc_bool(5, True)
        )
        await self.ws.send(frame)

    async def _recv_loop(self):
        try:
            while self._connected and self.ws is not None:
                frame = await self.ws.recv()
                if not isinstance(frame, (bytes, bytearray)):
                    continue
                env = parse_envelope(bytes(frame))
                event = env["event"]
                reply_id = env["reply_id"]

                if event == EV_SYSTEM_PING and not reply_id:
                    await self._reply_ping(env["id"])
                    continue
                if event == EV_SYSTEM_READY:
                    if self._ready_event is not None:
                        self._ready_event.set()
                    continue
                if reply_id and reply_id in self._pending:
                    fut = self._pending.pop(reply_id)
                    if not fut.done():
                        fut.set_result(env)
        except asyncio.CancelledError:
            raise
        except ConnectionClosed as e:
            code = e.rcvd.code if e.rcvd else 1006
            self.last_error = f"连接断开 (code={code})"
        except Exception as e:
            self.last_error = f"接收异常: {type(e).__name__}"
        finally:
            self._connected = False
            if self._ready_event is not None:
                self._ready_event.set()
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_result(None)
            self._pending.clear()

    async def _request(self, event: int, data: bytes = b"", timeout: float = 12) -> Optional[Dict[str, Any]]:
        self.last_request_rejected = False
        if not self.is_alive:
            self.last_error = self.last_error or "连接已断开"
            return None
        name = EVENT_NAMES.get(event, event)
        msg_id = self._next_id()
        fut = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        try:
            await self._send_envelope(msg_id, event, data)
            env = await asyncio.wait_for(fut, timeout=timeout)
            if env is None:
                self.last_error = self.last_error or "连接已断开"
            elif not env["success"]:
                self.last_request_rejected = True
                errors = repr(env["errors"])
                for token in {self.ws_token, urllib.parse.unquote(self.ws_token), self.rest_token} - {""}:
                    errors = errors.replace(token, "…")
                self.last_error = f"服务端拒绝 {name}: {errors}" if env["errors"] else f"服务端拒绝 {name}"
            else:
                self.last_error = ""
            return env
        except asyncio.TimeoutError:
            self.last_error = f"{name} 请求超时"
            return None
        except Exception as e:
            self.last_error = f"{name} 请求失败: {type(e).__name__}"
            return None
        finally:
            self._pending.pop(msg_id, None)
            fut.cancel()

    # 业务接口
    async def initialize(self) -> bool:
        env = await self._request(EV_WEBSTUDY_INIT_STUDY, b"", timeout=15)
        return env is not None and env.get("success", False)

    async def get_word(self, back: bool = False) -> Optional[Dict[str, Any]]:
        data = encode_get_word_request(back)
        env = await self._request(EV_WEBSTUDY_GET_WORD, data, timeout=10)
        if env is None or not env["success"]:
            return None
        try:
            result = parse_get_word_response(env["data"])
        except ValueError:
            self.last_error = "无法解析服务端的取词响应"
            return None
        if result.get("id"):
            self._last_word_received_at = time.monotonic()
        if result.get("progress"):
            self.progress = result["progress"]
        return result

    async def submit_response(
        self,
        word_id: str,
        response: str = "FAMILIAR",
        recall_duration: int = 1000,
        study_duration: int = 2000,
        study_method: str = "STUDY_CN_EN",
    ) -> bool:
        self.last_next_word = None
        MIN_DURATION_MS = 300
        recall_duration = max(recall_duration, MIN_DURATION_MS)
        study_duration = max(study_duration, MIN_DURATION_MS)

        if self._last_word_received_at is not None:
            elapsed_ms = int((time.monotonic() - self._last_word_received_at) * 1000)
            budget_ms = elapsed_ms - 100
            total = recall_duration + study_duration
            if total > budget_ms:
                ratio = max(0, budget_ms) / total
                recall_duration = max(MIN_DURATION_MS, int(recall_duration * ratio))
                study_duration = max(MIN_DURATION_MS, int(study_duration * ratio))
                if recall_duration + study_duration > budget_ms:
                    need_ms = (recall_duration + study_duration) - budget_ms
                    await asyncio.sleep(need_ms / 1000)

        data = encode_submit_request(
            voc_id=word_id,
            response=response,
            study_method=study_method,
            recall_duration=recall_duration,
            study_duration=study_duration,
        )
        env = await self._request(EV_WEBSTUDY_SUBMIT_RESPONSE, data, timeout=10)
        if env is None:
            return False
        if not env["success"]:
            return False

        try:
            body = _decode_message(env["data"])
            next_bufs = _get_bytes_list(body, 1)
            self.last_next_word = parse_get_word_response(next_bufs[0]) if next_bufs else None
        except ValueError:
            # 判答已获确认。让调用方重新取词，避免重复提交。
            self.last_error = "判答已保存，但无法解析下一张词卡"
        else:
            if self.last_next_word is None:
                self.last_next_word = {}
        if self.last_next_word and self.last_next_word.get("id"):
            self._last_word_received_at = time.monotonic()
        if self.last_next_word and self.last_next_word.get("progress"):
            self.progress = self.last_next_word["progress"]
        return True

    async def add_words(self, count: int, mode: int = 2) -> Optional[int]:
        if count <= 0:
            return 0
        if count > 2**31 - 1:
            self.last_error = "复习数量超出允许范围"
            return None
        data = encode_add_words_request(count, mode)
        env = await self._request(EV_WEBSTUDY_ADD_WORDS, data, timeout=15)
        if env is None or not env.get("success"):
            return None
        try:
            f = _decode_message(env["data"])
            return _get_int(f, 1)
        except ValueError:
            self.last_error = "无法解析服务端的加词响应"
            return None

    def fetch_study_progress(self) -> Dict[str, int]:
        """通过开放 API 获取今日学习进度。"""
        self.rest_auth_failed = False
        if not self.rest_token:
            return {}
        try:
            req = urllib.request.Request(
                REST_PROGRESS_URL,
                method="POST",
            )
            req.add_unredirected_header("Authorization", f"Bearer {self.rest_token}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.load(resp)
            progress = result["data"]["progress"]
            finished, total = progress["finished"], progress["total"]
            if result.get("success") and type(finished) is int and type(total) is int and 0 <= finished <= total:
                return {"finished": finished, "total": total}
        except urllib.error.HTTPError as exc:
            self.rest_auth_failed = exc.code in (401, 403)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return {}
