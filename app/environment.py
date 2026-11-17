"""Operator-defined environment identity; not fields from the original game API."""
from __future__ import annotations

import html
import os
import re

LABELS = {'local-test': '本地测试服', 'cloud': '云端正式服'}


def identity() -> dict[str, str]:
    role = os.environ.get('ONI_ENVIRONMENT', '')
    if not role:
        return {}
    if role not in LABELS:
        raise ValueError('ONI_ENVIRONMENT must be local-test or cloud')
    instance = os.environ.get('ONI_INSTANCE_ID', '')
    build = os.environ.get('ONI_BUILD_ID', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{8,80}', instance):
        raise ValueError('a distinct ONI_INSTANCE_ID is required')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', build):
        raise ValueError('ONI_BUILD_ID is required')
    return {'environment': role, 'instance_id': instance, 'build_id': build}


def mark_html(body: bytes) -> bytes:
    info = identity()
    if not info or not body:
        return body
    text = body.decode('utf-8')
    label = html.escape(LABELS[info['environment']])
    text = re.sub(r'(<title>)(.*?)(</title>)',
        lambda m: m[1] + m[2] + '｜' + label + m[3], text, count=1, flags=re.S)
    # Reuse the existing header/notice row; no new row or canvas resize.
    text = re.sub(r'(<p class="header">\s*<span>)(.*?)(</span>)',
        lambda m: m[1] + m[2] + '｜' + label + m[3], text, count=1, flags=re.S)
    text = text.replace('本地 stub 已接管登录页与账号校验',
        label + ('：存档仅保存在本机' if info['environment'] == 'local-test' else '：连接云端玩家存档'), 1)
    if info['environment'] == 'local-test':
        text = text.replace('http://127.0.0.1:19765/credentials', 'http://127.0.0.1:19766/credentials')
    return text.encode('utf-8')
