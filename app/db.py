"""MySQL 连接层（pymysql，延迟导入以便无依赖时仍可跑协议层单测）。

连接参数来自环境变量（见 app.config.DBConfig），密码不硬编码。
"""
from __future__ import annotations

import contextlib
from typing import Iterator

from app import config


def _connect():
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确提示
        raise RuntimeError(
            "缺少 pymysql，请先 `pip install -r requirements.txt`"
        ) from exc

    db = config.load_config().db
    return pymysql.connect(
        host=db.host,
        port=db.port,
        user=db.user,
        password=db.password,
        database=db.name,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=8,
    )


@contextlib.contextmanager
def connection() -> Iterator:
    """事务连接：正常退出提交，异常回滚，最后关闭。"""
    con = _connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_schema(schema_path: str | None = None) -> None:
    """执行 db/schema.sql 建库建表。部署时也可手动导入该文件。"""
    import os

    if schema_path is None:
        schema_path = os.path.join(config.ROOT_DIR, "db", "schema.sql")
    with open(schema_path, encoding="utf-8") as fh:
        sql = fh.read()

    # pymysql 默认不支持一次执行多语句；按分号切分并逐条执行。
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with connection() as con:
        with con.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
