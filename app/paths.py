"""目录路径配置：优先环境变量，缺省走仓库相对布局。"""
from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return os.path.abspath(value) if value else os.path.abspath(default)


APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = _env("ONI_ROOT", os.path.dirname(APP_DIR))

CONFIG_DIR = _env("ONI_CONFIG_DIR", os.path.join(ROOT_DIR, "config"))
DATA_DIR = _env("ONI_DATA_DIR", os.path.join(ROOT_DIR, "data"))
LOG_DIR = _env("ONI_LOG_DIR", os.path.join(ROOT_DIR, "logs"))
