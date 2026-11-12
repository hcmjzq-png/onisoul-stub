"""运行配置：全部来自环境变量，代码内不写数据库密码。"""
from __future__ import annotations

import os
from dataclasses import dataclass

from app import paths


@dataclass(frozen=True)
class DBConfig:
    host: str
    port: int
    name: str
    user: str
    password: str


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    db: DBConfig


def _db_config() -> DBConfig:
    return DBConfig(
        host=os.environ.get("ONI_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("ONI_DB_PORT", "3306")),
        name=os.environ.get("ONI_DB_NAME", "game_db"),
        user=os.environ.get("ONI_DB_USER", "game_app"),
        password=os.environ.get("ONI_DB_PASSWORD", ""),
    )


def load_config() -> Config:
    return Config(
        host=os.environ.get("STUB_HOST", "127.0.0.1"),
        port=int(os.environ.get("STUB_PORT", "18080")),
        db=_db_config(),
    )


# 目录路径从 paths 暴露，便于其余模块复用。
CONFIG_DIR = paths.CONFIG_DIR
DATA_DIR = paths.DATA_DIR
LOG_DIR = paths.LOG_DIR
