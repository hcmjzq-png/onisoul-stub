"""服务入口：组装配置、注册表与 HTTP 服务。

用法：
    python -m app.main                 # 读环境变量
    python -m app.main --host 0.0.0.0 --port 18080
    python -m app.main --init-schema   # 启动前导入 db/schema.sql
"""
from __future__ import annotations

import argparse

from app import config, db
from app.business.registry import Registry
from app.transport import http_server


def build_registry() -> Registry:
    """注册业务接口。骨架阶段为空，待 dump / 抓包后在此填充。"""
    return Registry()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OniSoul Stub server")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--init-schema", action="store_true", help="启动前导入建表 SQL")
    args = parser.parse_args(argv)

    cfg = config.load_config()
    host = args.host or cfg.host
    port = args.port or cfg.port

    if args.init_schema:
        db.init_schema()

    registry = build_registry()
    httpd = http_server.serve(host, port, registry)
    print(f"[stub] 监听 {host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[stub] 退出")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
