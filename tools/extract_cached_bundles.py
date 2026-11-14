#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从客户端的 QtWebKit 磁盘缓存里把 PC 版 AssetBundle 还原出来。

用途
----
原站 `client-onisoul.86joy.com` 已不可访问，客户端的 `.unity3d` 资产包只能靠跑过
原服的机器上的缓存副本还原。本脚本把 `cache/data7` 里的 `.d` 记录解析成资产包文件，
按 `assets/pc/bundles/<目录>/<hash>.unity3d` 落盘，供服务端静态层直接下发。

`.d` 记录格式（QtWebKit 4.x 磁盘缓存，一条记录 = 一笔 HTTP 事务）
------------------------------------------------------------------
    偏移 0   4 字节  记录长度
    偏移 4   4 字节  版本标记（观测值 0x00000007）
    偏移 8   4 字节  URL 长度（大端）
    偏移 12  N 字节  URL 明文（ASCII）
    ...              状态行 + 响应头（键值对，ASCII）
    ...              响应体

URL 按 MD5 的首字符分到 `data7/0` ~ `data7/f` 共 16 个桶，文件名是 8 字符短名，
与 URL 无直接关系，所以只能逐条读 URL 来判断它是什么资源。

响应体有两种形态，脚本按顺序尝试
--------------------------------
1. 明文：包体本身以 `UnityWeb` 开头，直接在整条记录里 `find(b"UnityWeb")`；
   app.unity3d 这类 4 MB 的包就是这样（魔数落在记录内偏移 304 附近）。
2. 压缩：记录里存的是 zlib（`78 9c`）或 gzip（`1f 8b`）流，解压后以 `UnityWeb` 开头。

用法
----
    python3 tools/extract_cached_bundles.py \
        --cache-dir "D:/鬼武者魂/cache/data7" \
        --out ./assets/pc/bundles

    # 只统计不落盘
    python3 tools/extract_cached_bundles.py --cache-dir ... --out ... --dry-run

落盘时会做两件事：写文件前校验包体以 `UnityWeb` 开头；结束时打印按目录的条数与字节
数汇总，以及仍然缺失的 URL（用来和服务端日志里的 404 清单对账）。
"""

from __future__ import annotations

import argparse
import gzip
import os
import re
import struct
import sys
import zlib

ASSET_RE = re.compile(r"/assets/([A-Za-z0-9_]+)/([0-9a-f]{32})\.unity3d")
MAGIC = b"UnityWeb"


def read_record(path: str) -> str:
    """读出记录里的 URL；解析失败返回空串。"""
    with open(path, "rb") as handle:
        head = handle.read(4096)
    try:
        url_len = struct.unpack(">I", head[8:12])[0]
        return head[12:12 + url_len].decode("ascii", "replace")
    except (struct.error, IndexError):
        return ""


def extract_body(blob: bytes) -> tuple[bytes | None, str]:
    """从整条记录里取出资产包体。返回 (包体, 命中方式)。"""
    idx = blob.find(MAGIC)
    if idx > 0:
        return blob[idx:], "plain"

    for sig, decoder, label in (
        (b"x\x9c", zlib.decompress, "zlib"),
        (b"\x1f\x8b", gzip.decompress, "gzip"),
    ):
        pos = blob.find(sig, 12)
        while pos > 0:
            try:
                data = decoder(blob[pos:])
            except Exception:
                pos = blob.find(sig, pos + 1)
                continue
            if data[: len(MAGIC)] == MAGIC:
                return data, label
            pos = blob.find(sig, pos + 1)
    return None, "miss"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, help="cache/data7 目录")
    parser.add_argument("--out", required=True, help="落盘根目录（对应服务端 assets/pc/bundles）")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    args = parser.parse_args()

    stats: dict[str, list[int]] = {}
    hits = {"plain": 0, "zlib": 0, "gzip": 0}
    missing: list[str] = []
    records = 0

    for bucket in sorted(os.listdir(args.cache_dir)):
        bucket_dir = os.path.join(args.cache_dir, bucket)
        if not os.path.isdir(bucket_dir):
            continue
        for name in sorted(os.listdir(bucket_dir)):
            path = os.path.join(bucket_dir, name)
            if not os.path.isfile(path):
                continue
            records += 1
            url = read_record(path)
            match = ASSET_RE.search(url)
            if not match:
                continue
            with open(path, "rb") as handle:
                blob = handle.read()
            body, how = extract_body(blob)
            if body is None:
                missing.append(url)
                continue
            hits[how] += 1
            group, digest = match.group(1), match.group(2)
            count, total = stats.setdefault(group, [0, 0])
            stats[group] = [count + 1, total + len(body)]
            if args.dry_run:
                continue
            out_dir = os.path.join(args.out, group)
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, digest + ".unity3d"), "wb") as handle:
                handle.write(body)

    print("扫描记录: %d 条" % records)
    print("命中资产包: %d 个（plain %d / zlib %d / gzip %d）" %
          (sum(v[0] for v in stats.values()), hits["plain"], hits["zlib"], hits["gzip"]))
    print("合计字节: %d" % sum(v[1] for v in stats.values()))
    for group in sorted(stats):
        count, total = stats[group]
        print("  %-10s %3d 个  %10d B" % (group, count, total))
    if missing:
        print("未能解出的记录 %d 条：" % len(missing))
        for url in missing[:20]:
            print("  " + url)
    return 0 if stats else 1


if __name__ == "__main__":
    sys.exit(main())
