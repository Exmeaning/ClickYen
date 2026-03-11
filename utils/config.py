import os
import json
from pathlib import Path

VERSION = "1.0.0"


class Config:
    def __init__(self):
        self.app_dir = Path.home() / ".clickyen"
        self.app_dir.mkdir(exist_ok=True)

        self.config_file = self.app_dir / "config.json"

        self.default_config = {
            # 窗口设置
            "window_size": [1400, 900],
            "always_on_top": False,
            "window_x": None,
            "window_y": None,

            # 目标窗口（上次选择）
            "last_target_window_title": "",
            "last_target_window_class": "",
            "last_crop_rect": None,

            # Interception 设置
            "cursor_lock_mode": False,
            "input_delay_ms": 10,
            "filter_system_keys": True,
            "input_mode": "interception",  # "interception" | "postmessage"

            # 录制设置
            "default_record_mode": "both",

            # 随机化
            "random_position_range": 5,
            "random_delay_range": 10,
            "random_long_press_range": 10,

            # 免责声明
            "disclaimer_accepted": False,
        }

        self.load()

    def load(self):
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                self.config = {**self.default_config, **loaded}
        else:
            self.config = self.default_config
            self.save()

    def save(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save()


config = Config()
