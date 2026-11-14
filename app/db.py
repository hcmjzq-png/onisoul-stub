"""MySQL 连接层（pymysql，延迟导入以便无依赖时仍可跑协议层单测）。

连接参数来自环境变量（见 app.config.DBConfig），密码不硬编码。
"""
from __future__ import annotations

import contextlib
from typing import Iterator

from app import config, paths


def _connect(*, select_database: bool = True):
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
        database=db.name if select_database else None,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=8,
        read_timeout=10,
        write_timeout=10,
    )


@contextlib.contextmanager
def connection(*, select_database: bool = True) -> Iterator:
    """事务连接：正常退出提交，异常回滚，最后关闭。"""
    con = _connect(select_database=select_database)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_schema(schema_path: str | None = None) -> None:
    """按 ONI_DB_NAME 建库，再执行只包含表定义的 db/schema.sql。

    初始化连接不预选数据库，因此首次运行时目标库可以尚不存在。
    MySQL DDL 会隐式提交；失败后可以重跑 IF NOT EXISTS 语句，不保证 DDL 回滚。
    """
    import os

    if schema_path is None:
        schema_path = os.path.join(paths.ROOT_DIR, "db", "schema.sql")
    with open(schema_path, encoding="utf-8") as fh:
        sql = fh.read()

    # pymysql 默认不支持一次执行多语句；按分号切分并逐条执行。
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    # 数据库名属于 SQL 标识符，不能使用值参数占位符；转义其中的反引号。
    database = "`" + config.load_config().db.name.replace("`", "``") + "`"
    with connection(select_database=False) as con:
        with con.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS {database} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
            cur.execute(f"USE {database}")
            for stmt in statements:
                cur.execute(stmt)
