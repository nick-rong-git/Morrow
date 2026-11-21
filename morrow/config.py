"""
Morrow 配置管理器 (Configuration Manager)
负责 config.json 的加载、默认值初始化与持久化保存。
"""

import os
import json
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
        self.config_path = config_path
        self._data: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    user_data = json.load(f)
                if isinstance(user_data, dict):
                    self._data.update(user_data)
            except Exception as e:
                print(f"[警告] 读取配置文件失败: {e}，使用默认配置")
        else:
            self.save()

    def save(self) -> bool:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"[错误] 保存配置文件失败: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    @property
    def ws_token(self) -> str:
        return str(self._data.get("ws_token", "")).strip()

    @property
    def rest_token(self) -> str:
        return str(self._data.get("rest_token", "")).strip()

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
        return str(self._data.get("data_dir", "data"))

    @property
    def record_enabled(self) -> bool:
        return bool(self._data.get("record_enabled", True))

    @property
    def hide_judge_hint(self) -> bool:
        return bool(self._data.get("hide_judge_hint", False))
