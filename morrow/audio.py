"""
Morrow 高质量音频引擎 (Audio Engine)

核心能力：
1. 单词真人原声：播放墨墨官方 CDN 高清 MP3。
2. 例句神经语音 (Neural TTS)：
   - 首选：微软 Azure AI 神经语音 (en-US-JennyNeural / en-GB-SoniaNeural)，具备细腻自然的呼吸感与语调起伏。
   - 备用：百度神经网络多语种 TTS (毫秒级自动容灾)。
   - 保底：Windows 本地 SAPI。
3. 智能异步预取与本地磁盘缓存：
   当新单词呈现在屏幕时，后台线程已在静默预合成该单词的所有例句 MP3，按 [e] 或 [4/5/6] 听例句时 0 延时即按即播。
4. Windows 底层 MCI 原生解码：通过 mciSendStringW 驱动声卡直接硬件播放。
"""

import os
import sys
import ctypes
import hashlib
import threading
import asyncio
import urllib.request
import urllib.parse
from typing import Optional

try:
    import edge_tts
    _HAS_EDGE_TTS = True
except ImportError:
    _HAS_EDGE_TTS = False

try:
    import win32com.client
    import pythoncom
    _HAS_WIN32COM = True
except ImportError:
    _HAS_WIN32COM = False

NEURAL_VOICES = {
    "US": "en-US-JennyNeural",   # 美音：极度逼真、语调自然的女性声音
    "UK": "en-GB-SoniaNeural",   # 英音：纯正伦敦标准音 (RP)
}

class AudioEngine:
    def __init__(self, cache_dir: str = "data/audio_cache"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._is_windows = sys.platform == "win32"
        self._winmm = ctypes.windll.winmm if self._is_windows else None

    # -------------------------------------------------------------------------
    # 缓存与路径
    # -------------------------------------------------------------------------

    def _get_url_cache_path(self, url: str) -> str:
        h = hashlib.md5(url.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{h}.mp3")

    def _get_sentence_cache_path(self, text: str, accent: str) -> str:
        key = f"sent_{accent.upper()}_{text.strip()}"
        h = hashlib.md5(key.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{h}.mp3")

    def download_url_if_needed(self, url: str) -> Optional[str]:
        """下载官方单词真人 MP3"""
        if not url:
            return None
        local_path = self._get_url_cache_path(url)
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            return local_path
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = resp.read()
            if len(data) > 200:
                with open(local_path, "wb") as f:
                    f.write(data)
                return local_path
        except Exception:
            pass
        return None

    # -------------------------------------------------------------------------
    # 播放底层
    # -------------------------------------------------------------------------

    def _play_file_sync(self, local_path: str) -> None:
        if not local_path or not os.path.exists(local_path) or not self._is_windows or not self._winmm:
            return

        with self._lock:
            alias = "morrow_speech"
            self._winmm.mciSendStringW(f'close {alias}', None, 0, None)
            abs_path = os.path.abspath(local_path)
            res = self._winmm.mciSendStringW(f'open "{abs_path}" type mpegvideo alias {alias}', None, 0, None)
            if res == 0:
                self._winmm.mciSendStringW(f'play {alias} wait', None, 0, None)
                self._winmm.mciSendStringW(f'close {alias}', None, 0, None)

    def stop(self) -> None:
        """立刻打断/停止当前音频播放"""
        if self._is_windows and self._winmm:
            with self._lock:
                self._winmm.mciSendStringW('stop morrow_speech', None, 0, None)
                self._winmm.mciSendStringW('close morrow_speech', None, 0, None)

    # -------------------------------------------------------------------------
    # 单词发音
    # -------------------------------------------------------------------------

    def play_word(self, url: str, async_play: bool = True) -> None:
        """播放单词官方真人发音 MP3"""
        if not url:
            return
        if async_play:
            threading.Thread(target=self._play_word_sync, args=(url,), daemon=True).start()
        else:
            self._play_word_sync(url)

    def _play_word_sync(self, url: str) -> None:
        local_path = self.download_url_if_needed(url)
        if local_path:
            self._play_file_sync(local_path)

    # -------------------------------------------------------------------------
    # 例句朗读 (神经拟真人声)
    # -------------------------------------------------------------------------

    async def _async_synth_edge(self, text: str, voice: str, out_path: str) -> bool:
        if not _HAS_EDGE_TTS:
            return False
        try:
            comm = edge_tts.Communicate(text, voice)
            await asyncio.wait_for(comm.save(out_path), timeout=6.0)
            return os.path.exists(out_path) and os.path.getsize(out_path) > 1000
        except Exception:
            return False

    def _synth_baidu(self, text: str, accent: str, out_path: str) -> bool:
        lan = "uk" if accent.upper() == "UK" else "en"
        url = f"https://fanyi.baidu.com/gettts?lan={lan}&text={urllib.parse.quote(text)}&spd=3&source=web"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
            if len(data) > 1000:
                with open(out_path, "wb") as f:
                    f.write(data)
                return True
        except Exception:
            pass
        return False

    def _ensure_sentence_mp3(self, text: str, accent: str = "US") -> Optional[str]:
        clean_text = text.strip()
        if not clean_text:
            return None

        out_path = self._get_sentence_cache_path(clean_text, accent)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
            return out_path

        temp_path = out_path + f".tmp.{os.getpid()}_{threading.get_ident()}.mp3"
        voice = NEURAL_VOICES.get(accent.upper(), NEURAL_VOICES["US"])

        # 1. 微软 Azure 神经拟真人声
        try:
            success = asyncio.run(self._async_synth_edge(clean_text, voice, temp_path))
            if success and os.path.exists(temp_path):
                os.replace(temp_path, out_path)
                return out_path
        except Exception:
            pass

        # 2. 百度神经 TTS 备用
        try:
            success = self._synth_baidu(clean_text, accent, temp_path)
            if success and os.path.exists(temp_path):
                os.replace(temp_path, out_path)
                return out_path
        except Exception:
            pass
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

        return None

    def prefetch_sentence(self, text: str, accent: str = "US") -> None:
        """后台静默预合成并缓存例句音频"""
        if not text:
            return
        clean_text = text.strip()
        out_path = self._get_sentence_cache_path(clean_text, accent)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
            return

        threading.Thread(
            target=self._ensure_sentence_mp3,
            args=(clean_text, accent),
            daemon=True
        ).start()

    def speak_sentence(self, text: str, async_play: bool = True, accent: str = "US") -> None:
        """朗读例句或长文本"""
        if not text:
            return
        if async_play:
            threading.Thread(target=self._speak_sentence_sync, args=(text, accent), daemon=True).start()
        else:
            self._speak_sentence_sync(text, accent)

    def _speak_sentence_sync(self, text: str, accent: str = "US") -> None:
        clean_text = text.strip()
        if not clean_text:
            return

        mp3_path = self._ensure_sentence_mp3(clean_text, accent)
        if mp3_path and os.path.exists(mp3_path):
            self._play_file_sync(mp3_path)
            return

        # 离线保底 SAPI
        self._sapi_fallback(clean_text)

    def _sapi_fallback(self, text: str) -> None:
        if not self._is_windows or not _HAS_WIN32COM:
            return
        try:
            pythoncom.CoInitialize()
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            for v in speaker.GetVoices():
                desc = v.GetDescription()
                if "English" in desc or "Zira" in desc or "David" in desc:
                    speaker.Voice = v
                    break
            speaker.Rate = 0
            speaker.Volume = 100
            speaker.Speak(text)
        except Exception:
            pass
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


audio_engine = AudioEngine()
