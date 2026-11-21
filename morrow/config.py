"""
Morrow 配置管理器 (Configuration Manager)
负责 config.json 的加载、默认值初始化与持久化保存。
"""

import os
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, Any

DEFAULT_CONFIG: Dict[str, Any] = {
    "ws_token": "",
    "rest_token": "",
    "ui_mode": "study",          # "study" (全功能卡片) 或 "disguise" (摸鱼模式)
    "auto_play_audio": True,     # 第一屏自动播放单词真人发音
    "auto_play_example": False,  # 第二屏自动朗读第一条例句
    "accent": "US",              # "US" (美音) 或 "UK" (英音)
    "data_dir": "data",          # 数据与缓存根目录
    "record_enabled": True,      # 记录学习历史
    "hide_judge_hint": False     # 是否隐藏底栏判答提示
}

class Config:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path).resolve()
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        self._data = dict(DEFAULT_CONFIG)
        try:
            with self.config_path.open(encoding="utf-8-sig") as f:
                user_data = json.load(f)
            if not isinstance(user_data, dict):
                raise ValueError("配置必须为 JSON 对象")
        except FileNotFoundError:
            self.save()
            return
        except (OSError, ValueError) as e:
            print(f"[警告] 读取配置文件失败: {e}，使用默认配置")
            return

        for key, value in user_data.items():
            if key not in DEFAULT_CONFIG or type(value) is type(DEFAULT_CONFIG[key]):
                self._data[key] = value

        mode = self._data["ui_mode"].strip().lower()
        self._data["ui_mode"] = mode if mode in {"study", "disguise"} else "study"
        accent = self._data["accent"].strip().upper()
        self._data["accent"] = accent if accent in {"US", "UK"} else "US"

    def save(self) -> bool:
        pending_path = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.config_path.parent,
                prefix=f".{self.config_path.name}.", suffix=".tmp", delete=False,
            ) as f:
                pending_path = Path(f.name)
                json.dump(self._data, f, ensure_ascii=False, indent=4)
                f.write("\n")
            os.replace(pending_path, self.config_path)
            return True
        except (OSError, TypeError, ValueError) as e:
            print(f"[错误] 保存配置文件失败: {e}")
            return False
        finally:
            if pending_path is not None:
                try:
                    pending_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def update(self, **changes: Any) -> bool:
        previous = self._data.copy()
        self._data.update(changes)
        if self.save():
            return True
        self._data = previous
        return False

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    @property
    def ws_token(self) -> str:
        token = self._data["ws_token"].strip()
        return "" if token == "YOUR_MAIMEMO_WS_TOKEN_HERE" else token

    @property
    def rest_token(self) -> str:
        token = self._data["rest_token"].strip()
        return "" if token == "YOUR_MAIMEMO_REST_TOKEN_HERE" else token

    @property
    def ui_mode(self) -> str:
        return str(self._data.get("ui_mode", "study")).lower()

    @property
    def auto_play_audio(self) -> bool:
        return bool(self._data.get("auto_play_audio", True))

    @property
    def auto_play_example(self) -> bool:
        return bool(self._data.get("auto_play_example", False))

    @property
    def accent(self) -> str:
        return str(self._data.get("accent", "US")).upper()

    @property
    def data_dir(self) -> str:
        return self._data["data_dir"].strip() or "data"

    @property
    def record_enabled(self) -> bool:
        return bool(self._data.get("record_enabled", True))

    @property
    def hide_judge_hint(self) -> bool:
        return bool(self._data.get("hide_judge_hint", False))
