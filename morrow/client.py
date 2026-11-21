"""
Morrow 学习客户端 (Morrow Learning Client)
封装与墨墨官方 WebSocket 网关与 REST API 的双向交互协议。
"""

import os
import ssl
import time
import json
import asyncio
import urllib.request
import websockets
from typing import Optional, Dict, Any, List

# 墨墨官方 API 端点
WS_URL = "wss://tc-apis.maimemo.com/webstudy"
REST_USER_INFO_URL = "https://tc-apis.maimemo.com/api/v1/user/info"

# WebSocket 事件定义
EV_SYSTEM_PING = 2
EV_SYSTEM_READY = 3
EV_WEBSTUDY_INIT_STUDY = 1000
EV_WEBSTUDY_GET_WORD = 1001
EV_WEBSTUDY_SUBMIT_WORD = 1002
EV_WEBSTUDY_ADD_WORDS = 1006

# 反作弊耗时上下限保护 (ms)
MIN_DURATION_MS = 250
MAX_DURATION_MS = 300000

# ---------------------------------------------------------------------------
# Protobuf 底层编码与解码
# ---------------------------------------------------------------------------

def _encode_varint(v: int) -> bytes:
    if v < 0:
        v += 1 << 64
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)

def _decode_varint(buf: bytes, offset: int):
    val = 0
    shift = 0
    idx = offset
    while idx < len(buf):
        b = buf[idx]
        val |= (b & 0x7F) << shift
        idx += 1
        if not (b & 0x80):
            return val, idx
        shift += 7
        if shift > 64:
            raise ValueError("Varint 溢出")
    raise ValueError("Varint 截断")

def _enc_field(num: int, wire: int, payload: bytes) -> bytes:
    tag = (num << 3) | wire
    return _encode_varint(tag) + payload

def _enc_int32(num: int, val: int) -> bytes:
    return _enc_field(num, 0, _encode_varint(val))

def _enc_bool(num: int, val: bool) -> bytes:
    return _enc_field(num, 0, _encode_varint(1 if val else 0))

def _enc_string(num: int, s: str) -> bytes:
    b = s.encode("utf-8")
    return _enc_field(num, 2, _encode_varint(len(b)) + b)

def _enc_bytes(num: int, b: bytes) -> bytes:
    return _enc_field(num, 2, _encode_varint(len(b)) + b)

def _decode_message(buf: bytes) -> Dict[int, List[Any]]:
    fields: Dict[int, List[Any]] = {}
    idx = 0
    l = len(buf)
    while idx < l:
        tag, idx = _decode_varint(buf, idx)
        fnum = tag >> 3
        wire = tag & 0x7
        if wire == 0:
            val, idx = _decode_varint(buf, idx)
            fields.setdefault(fnum, []).append(val)
        elif wire == 2:
            length, idx = _decode_varint(buf, idx)
            val = buf[idx : idx + length]
            idx += length
            fields.setdefault(fnum, []).append(val)
        else:
            break
    return fields

def _get_str(fields: Dict[int, List[Any]], fnum: int, default: str = "") -> str:
    vals = fields.get(fnum)
    if not vals:
        return default
    v = vals[0]
    return v.decode("utf-8", errors="replace") if isinstance(v, (bytes, bytearray)) else str(v)

def _get_int(fields: Dict[int, List[Any]], fnum: int, default: int = 0) -> int:
    vals = fields.get(fnum)
    return vals[0] if vals else default

def _get_bytes_list(fields: Dict[int, List[Any]], fnum: int) -> List[bytes]:
    return [v for v in fields.get(fnum, []) if isinstance(v, (bytes, bytearray))]


def encode_envelope(msg_id: str, event: int, data: bytes = b"") -> bytes:
    out = _enc_string(1, msg_id)
    out += _enc_int32(3, event)
    if data:
        out += _enc_bytes(4, data)
    return out

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
        self.ws = None
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

        self._connected = False
        self._msg_seq = 0
        self._pending: Dict[str, asyncio.Future] = {}
        self._recv_task: Optional[asyncio.Task] = None
        self._ready_event: Optional[asyncio.Event] = None
        self._last_word_received_at: Optional[float] = None
        self.last_next_word: Optional[Dict[str, Any]] = None
        self.last_error: str = ""
        self.progress: Dict[str, int] = {}

    def _next_id(self) -> str:
        self._msg_seq += 1
        return f"morrow-{self._msg_seq}"

    @property
    def is_alive(self) -> bool:
        return self._connected and self.ws is not None

    async def connect(self) -> bool:
        if self._connected and self.ws is not None:
            return True
        url = f"{WS_URL}?token={self.ws_token}"
        try:
            self.ws = await websockets.connect(url, ssl=self._ssl_ctx)
        except Exception as e:
            self.last_error = f"连接网关失败: {e}"
            return False

        self._connected = True
        self._ready_event = asyncio.Event()
        self._recv_task = asyncio.create_task(self._recv_loop())
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            self.last_error = "等待 SYSTEM_READY 握手超时"
            await self.close()
            return False

        self.last_error = ""
        return True

    async def close(self):
        self._connected = False
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.ws = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("连接已关闭"))
        self._pending.clear()

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
        try:
            await self.ws.send(frame)
        except Exception:
            pass

    async def _recv_loop(self):
        try:
            while self._connected and self.ws is not None:
                try:
                    frame = await self.ws.recv()
                except websockets.exceptions.ConnectionClosed as e:
                    self._connected = False
                    reason = (e.reason or "").strip()
                    self.last_error = f"连接断开 (code={e.code}, reason={reason})"
                    break
                if not isinstance(frame, (bytes, bytearray)):
                    continue
                env = parse_envelope(bytes(frame))
                event = env["event"]
                reply_id = env["reply_id"]

                if event == EV_SYSTEM_PING:
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
            pass
        except Exception as e:
            self._connected = False
            self.last_error = f"接收异常: {e}"
        finally:
            self._connected = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("连接断开"))
            self._pending.clear()

    async def _request(self, event: int, data: bytes = b"", timeout: float = 12) -> Optional[Dict[str, Any]]:
        if not self._connected or self.ws is None:
            return None
        msg_id = self._next_id()
        fut = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        try:
            await self._send_envelope(msg_id, event, data)
            return await asyncio.wait_for(fut, timeout=timeout)
        except Exception as e:
            self._pending.pop(msg_id, None)
            return None

    # 业务接口
    async def initialize(self) -> bool:
        env = await self._request(EV_WEBSTUDY_INIT_STUDY, b"", timeout=15)
        return env is not None and env.get("success", False)

    async def get_word(self, back: bool = False) -> Optional[Dict[str, Any]]:
        data = _enc_bool(1, back)
        env = await self._request(EV_WEBSTUDY_GET_WORD, data, timeout=10)
        if env is None:
            return None
        result = parse_get_word_response(env.get("data", b""))
        if result.get("id"):
            self._last_word_received_at = time.monotonic()
        if result.get("progress"):
            self.progress = result["progress"]
        return result

    async def submit_response(
        self,
        word_id: str,
        result: str,
        sm_n: int = 0,
        recall_duration: int = 0,
        study_duration: int = 0,
    ) -> bool:
        if self._last_word_received_at is not None:
            now = time.monotonic()
            elapsed_ms = int((now - self._last_word_received_at) * 1000)
            if recall_duration > elapsed_ms:
                recall_duration = max(MIN_DURATION_MS, elapsed_ms)
            if study_duration > elapsed_ms:
                study_duration = max(MIN_DURATION_MS, elapsed_ms)

        recall_duration = max(MIN_DURATION_MS, min(MAX_DURATION_MS, recall_duration))
        study_duration = max(MIN_DURATION_MS, min(MAX_DURATION_MS, study_duration))

        # 构造 Submit Request
        body = _enc_string(1, word_id) + _enc_string(2, result)
        if sm_n:
            body += _enc_int32(3, sm_n)
        if recall_duration:
            body += _enc_int32(4, recall_duration)
        if study_duration:
            body += _enc_int32(5, study_duration)

        env = await self._request(EV_WEBSTUDY_SUBMIT_WORD, body, timeout=15)
        if env is None or not env.get("success"):
            return False

        # 解析返回包含的下一个词与进度
        self.last_next_word = None
        data = env.get("data", b"")
        if data:
            f = _decode_message(data)
            prog_bufs = _get_bytes_list(f, 22)
            if prog_bufs:
                pf = _decode_message(prog_bufs[0])
                self.progress = {
                    "finished": _get_int(pf, 1),
                    "total": _get_int(pf, 2),
                }
            next_word_bufs = _get_bytes_list(f, 21)
            if next_word_bufs:
                self.last_next_word = parse_get_word_response(next_word_bufs[0])
                if self.last_next_word.get("id"):
                    self._last_word_received_at = time.monotonic()

        return True

    async def add_words(self, count: int, mode: int = 2) -> Optional[int]:
        if count <= 0:
            return 0
        inner = _enc_int32(1, count) + _enc_int32(2, mode)
        env = await self._request(EV_WEBSTUDY_ADD_WORDS, _enc_bytes(2, inner), timeout=15)
        if env is None or not env.get("success"):
            return None
        f = _decode_message(env.get("data", b""))
        return _get_int(f, 1)

    def fetch_user_streak(self) -> Dict[str, Any]:
        """通过 REST API 获取连续打卡天数与基础信息"""
        if not self.rest_token:
            return {"streak": 1, "is_signed": False}
        try:
            req = urllib.request.Request(
                REST_USER_INFO_URL,
                headers={
                    "Authorization": f"Bearer {self.rest_token}",
                    "User-Agent": "Mozilla/5.0"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                user = data.get("data", {}).get("user", {})
                streak = user.get("continuous_sign_days", 1)
                is_signed = bool(user.get("today_signed", False))
                return {"streak": streak, "is_signed": is_signed, "user": user}
        except Exception:
            return {"streak": 1, "is_signed": False}
