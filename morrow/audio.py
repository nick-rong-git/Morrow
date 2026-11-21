"""单词和例句的音频缓存、预取与 Windows 播放。"""

import asyncio
from concurrent.futures import Future
import ctypes
import hashlib
from http.client import HTTPException
import os
import sys
from tempfile import NamedTemporaryFile
import threading
from typing import Optional
import urllib.parse
import urllib.request

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    import pythoncom
    import win32com.client
except ImportError:
    pythoncom = None


NEURAL_VOICES = {
    "US": "en-US-JennyNeural",
    "UK": "en-GB-SoniaNeural",
}


class AudioEngine:
    def __init__(self, cache_dir: str = "data/audio_cache"):
        self.cache_dir = cache_dir
        self._lock = threading.Lock()
        self._play_lock = threading.Lock()
        self._cancelled = threading.Event()
        self._downloads = {}
        self._prefetch_slots = threading.BoundedSemaphore(3)
        self._winmm = ctypes.windll.winmm if sys.platform == "win32" else None

    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, hashlib.md5(key.encode("utf-8")).hexdigest() + ".mp3")

    def _get_sentence_cache_path(self, text: str, accent: str) -> str:
        return self._cache_path(f"sent_{accent.upper()}_{text.strip()}")

    @staticmethod
    def _is_mp3(path: str) -> bool:
        try:
            with open(path, "rb") as f:
                header = f.read(4)
                size = f.seek(0, os.SEEK_END)
            return len(header) == 4 and size > 200 and (
                header.startswith(b"ID3") or (header[0] == 0xFF and header[1] & 0xE0 == 0xE0)
            )
        except OSError:
            return False

    def _cache_mp3(self, path: str, fetch) -> Optional[str]:
        with self._lock:
            if self._is_mp3(path):
                return path
            job = self._downloads.get(path)
            if job is None:
                job = Future()
                self._downloads[path] = job
                owner = True
            else:
                owner = False

        if not owner:
            return job.result()

        temp_path = None
        result = None
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with NamedTemporaryFile(dir=self.cache_dir, suffix=".tmp.mp3", delete=False) as f:
                temp_path = f.name
            if fetch(temp_path) and self._is_mp3(temp_path):
                os.replace(temp_path, path)
                result = path
        except OSError:
            pass
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            with self._lock:
                job.set_result(result)
                del self._downloads[path]
        return result

    @staticmethod
    def _download(url: str, path: str) -> bool:
        try:
            if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
                return False
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = resp.read()
            with open(path, "wb") as f:
                f.write(data)
            return True
        except (OSError, ValueError, HTTPException):
            return False

    def download_url_if_needed(self, url: str) -> Optional[str]:
        if not url:
            return None
        if url.startswith("//"):
            url = "https:" + url
        return self._cache_mp3(self._cache_path(url), lambda path: self._download(url, path))

    def _play_file_sync(self, path: str, cancelled: threading.Event) -> bool:
        if self._winmm is None:
            return False
        with self._play_lock:
            if cancelled.is_set():
                return False
            send = self._winmm.mciSendStringW
            alias = "morrow_speech"
            if send(f'open "{os.path.abspath(path)}" type mpegvideo alias {alias}', None, 0, None):
                return False
            try:
                if send(f"play {alias}", None, 0, None):
                    return False
                mode = ctypes.create_unicode_buffer(32)
                while not cancelled.wait(0.05):
                    if send(f"status {alias} mode", mode, len(mode), None):
                        return False
                    if mode.value not in ("playing", "seeking"):
                        break
                return True
            finally:
                send(f"close {alias}", None, 0, None)

    def stop(self) -> None:
        with self._lock:
            self._cancelled.set()

    def _play(self, worker, args: tuple, background: bool) -> None:
        if self._winmm is None:
            return
        with self._lock:
            self._cancelled.set()
            cancelled = self._cancelled = threading.Event()
        if background:
            threading.Thread(target=worker, args=(*args, cancelled), daemon=True).start()
        else:
            worker(*args, cancelled)

    def play_word(
        self, url: str, async_play: bool = True, *, fallback_text: str = "", accent: str = "US", example: str = "",
    ) -> None:
        example = example.strip()
        if url or fallback_text or example:
            self._play(self._play_word_sync, (url, fallback_text, accent, example), async_play)

    def _play_word_sync(self, url, fallback_text, accent, example, cancelled) -> None:
        if cancelled.is_set():
            return
        path = self.download_url_if_needed(url)
        played = path is not None and self._play_file_sync(path, cancelled)
        if not played and fallback_text and not cancelled.is_set():
            self._speak_sentence_sync(fallback_text, accent, cancelled)
        if example and not cancelled.is_set():
            self._speak_sentence_sync(example, accent, cancelled)

    async def _async_synth_edge(self, text: str, voice: str, path: str) -> bool:
        if edge_tts is None:
            return False
        try:
            await asyncio.wait_for(edge_tts.Communicate(text, voice).save(path), timeout=6)
            return self._is_mp3(path)
        except Exception:
            return False

    def _synth_sentence(self, text: str, accent: str, path: str) -> bool:
        voice = NEURAL_VOICES.get(accent, NEURAL_VOICES["US"])
        if asyncio.run(self._async_synth_edge(text, voice, path)):
            return True
        query = urllib.parse.urlencode({
            "lan": "uk" if accent == "UK" else "en",
            "text": text, "spd": 3, "source": "web",
        })
        return self._download(f"https://fanyi.baidu.com/gettts?{query}", path)

    def _ensure_sentence_mp3(self, text: str, accent: str) -> Optional[str]:
        return self._cache_mp3(
            self._get_sentence_cache_path(text, accent),
            lambda path: self._synth_sentence(text, accent, path),
        )

    def prefetch_sentence(self, text: str, accent: str = "US") -> None:
        text, accent = text.strip(), accent.upper()
        if self._winmm is None or not text or self._is_mp3(self._get_sentence_cache_path(text, accent)):
            return
        if not self._prefetch_slots.acquire(blocking=False):
            return

        def prefetch():
            try:
                self._ensure_sentence_mp3(text, accent)
            finally:
                self._prefetch_slots.release()

        threading.Thread(target=prefetch, daemon=True).start()

    def speak_sentence(self, text: str, async_play: bool = True, accent: str = "US") -> None:
        if text.strip():
            self._play(self._speak_sentence_sync, (text.strip(), accent.upper()), async_play)

    def _speak_sentence_sync(self, text: str, accent: str, cancelled: threading.Event) -> None:
        if cancelled.is_set():
            return
        path = self._ensure_sentence_mp3(text, accent)
        if path and self._play_file_sync(path, cancelled):
            return
        self._sapi_fallback(text, cancelled)

    def _sapi_fallback(self, text: str, cancelled: threading.Event) -> None:
        if pythoncom is None:
            return
        with self._play_lock:
            if cancelled.is_set():
                return
            try:
                pythoncom.CoInitialize()
                try:
                    speaker = win32com.client.Dispatch("SAPI.SpVoice")
                    for voice in speaker.GetVoices():
                        if any(name in voice.GetDescription() for name in ("English", "Zira", "David")):
                            speaker.Voice = voice
                            break
                    speaker.Speak(text, 1)
                    while not cancelled.is_set() and not speaker.WaitUntilDone(50):
                        pass
                    if cancelled.is_set():
                        speaker.Speak("", 3)
                finally:
                    pythoncom.CoUninitialize()
            except Exception:
                pass


audio_engine = AudioEngine()
