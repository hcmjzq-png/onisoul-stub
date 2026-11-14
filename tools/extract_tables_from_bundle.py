#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从客户端 UnityWeb 资产包里抽出清单声明的配置表。

PC 客户端的 108 张配置表不是单独文件，而是作为 JSON 文本内嵌在场景包
（`scene/*.unity3d`，本机缓存里是 `scene/1243ea6aa6…`，解压后约 100 MB）里，
形如 `{"<root_key>": {"<行id>": {...}, ...}}`。服务端要用同一批数据，就得把它们
按 `docs/analysis/table_list.tsv` 的声明抠出来落盘。

包格式（Unity 3.5.6f4 / UnityWeb）
--------------------------------
    "UnityWeb" + uint32 + "3.x.x" + nul + "3.5.6f4" + nul + 若干大小字段
    之后是 LZMA 块：props `5d 00 00 80 00`（lc3/lp0/pb2，字典 8 MB）+ 8 字节原始长度 + 数据

用法
----
    python3 tools/extract_tables_from_bundle.py \
        --bundle /path/to/scene_xxx.unity3d \
        --out /opt/onisoul/assets/pc/tables

脚本会按清单逐张校验：能找到 root_key 且解析成功才落盘，末尾打印成功/缺失清单。
表文件含玩家/角色数据，不进 git（`.gitignore` 已排除 `assets/pc/tables`）。
"""

from __future__ import annotations

import argparse
import csv
import json
import lzma
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT_MANIFEST = os.path.join(ROOT, 'docs', 'analysis', 'table_list.tsv')
SERVER_MANIFEST = os.path.join(ROOT, 'docs', 'analysis', 'server_tables.tsv')
LZMA_PROPS = b'\x5d\x00\x00\x80\x00'


def decompress_bundle(path: str) -> bytes:
    blob = open(path, 'rb').read()
    idx = blob.find(b'UnityWeb')
    if idx < 0:
        raise SystemExit('不是 UnityWeb 包: %s' % path)
    off = blob.find(LZMA_PROPS, idx)
    if off < 0:
        raise SystemExit('找不到 LZMA 块: %s' % path)
    return lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(blob[off:])


def strip_trailing_commas(text: str) -> str:
    return re.sub(r',\s*([}\]])', r'\1', text)


def read_manifest(path: str) -> list[dict[str, str]]:
    with open(path, encoding='utf-8', newline='') as handle:
        return [row for row in csv.DictReader(handle, delimiter='\t')
                if (row.get('table_file') or '').strip() and (row.get('root_key') or '').strip()]


def extract_table(text: str, root_key: str) -> dict | None:
    marker = '"%s"' % root_key
    decoder = json.JSONDecoder()
    pos = 0
    while True:
        idx = text.find(marker, pos)
        if idx < 0:
            return None
        brace = text.find('{', idx + len(marker))
        if brace < 0:
            return None
        if text[idx + len(marker):brace].strip() != ':':
            pos = idx + 1
            continue
        chunk = strip_trailing_commas(text[brace:brace + 8_000_000])
        try:
            obj = decoder.raw_decode(chunk)[0]
        except json.JSONDecodeError:
            pos = idx + 1
            continue
        if isinstance(obj, dict) and obj:
            # 表体直接就是 行id -> 记录，外面补 root_key
            return obj if root_key in obj else {root_key: obj}
        pos = idx + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, help='UnityWeb 包路径（scene/*.unity3d）')
    parser.add_argument('--out', required=True, help='表目录，默认对应服务端 assets/pc/tables')
    parser.add_argument('--only-missing', action='store_true', help='只补写目录里还没有的表')
    args = parser.parse_args()

    text = decompress_bundle(args.bundle).decode('ascii', 'replace')
    print('解压后: %d 字符' % len(text))

    entries = read_manifest(CLIENT_MANIFEST) + read_manifest(SERVER_MANIFEST)
    os.makedirs(args.out, exist_ok=True)

    ok, miss, skip = [], [], []
    for row in entries:
        name = row['table_file'].strip()
        root_key = row['root_key'].strip()
        target = os.path.join(args.out, name)
        if args.only_missing and os.path.exists(target):
            skip.append(name)
            continue
        table = extract_table(text, root_key)
        if table is None:
            miss.append((name, root_key))
            continue
        payload = json.dumps(table, ensure_ascii=False).encode('utf-8')
        with open(target, 'wb') as handle:
            handle.write(payload)
        ok.append((name, len(table[root_key]), len(payload)))

    print('写出 %d 张，合计 %d 字节；跳过 %d 张；缺失 %d 张' % (
        len(ok), sum(size for _, _, size in ok), len(skip), len(miss)))
    for name, root_key in miss:
        print('   MISS %-34s root=%s' % (name, root_key))
    return 0 if not miss else 1


if __name__ == '__main__':
    sys.exit(main())
