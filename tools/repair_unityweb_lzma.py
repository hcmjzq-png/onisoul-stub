#!/usr/bin/env python3
"""Repair unknown LZMA lengths for the legacy Unity WebPlayer, without repacking.

Python FORMAT_ALONE emits UINT64_MAX (unknown size). Unity 4.3.7 truncates it to
UINT32_MAX and eagerly allocates size/102400+1 buffers. Only replace these eight
length bytes after bounded decompression agrees with the UnityWeb level length.
Always write a separate output; the source bundle remains available for rollback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
from pathlib import Path
import struct

MAX_PAYLOAD = 256 * 1024 * 1024
UNKNOWN_SIZE = (1 << 64) - 1


def layout(blob: bytes) -> tuple[int, int, int]:
    if not blob.startswith(b'UnityWeb\0'):
        raise ValueError('UnityWeb bundle required')
    version = struct.unpack_from('>I', blob, 9)[0]
    if version not in (1, 2, 3):
        raise ValueError('unsupported UnityWeb format version')
    pos = 13
    for _ in range(2):
        pos = blob.index(b'\0', pos) + 1
    minimum, header, streaming, levels = struct.unpack_from('>IIII', blob, pos)
    if levels != 1:
        raise ValueError('only verified single-level bundles are supported')
    compressed, size = struct.unpack_from('>II', blob, pos + 16)
    if header < pos + 24 or compressed < 13 or header + compressed != len(blob):
        raise ValueError('invalid UnityWeb level bounds')
    if not 0 < size <= MAX_PAYLOAD:
        raise ValueError('uncompressed level exceeds the analysis limit')
    return header, compressed, size


def repair(blob: bytes) -> tuple[bytes, dict]:
    offset, compressed, size = layout(blob)
    declared = struct.unpack_from('<Q', blob, offset + 5)[0]
    if declared not in (size, UNKNOWN_SIZE):
        raise ValueError('LZMA and UnityWeb uncompressed lengths disagree')
    # Decode RAW explicitly: older liblzma rejects a known-size ALONE header
    # with an EOS marker, although Unity consumes this raw coding stream.
    props, dictionary = struct.unpack_from('<BI', blob, offset)
    if props >= 225 or dictionary > MAX_PAYLOAD:
        raise ValueError('unsupported LZMA properties or dictionary size')
    filters = [{'id': lzma.FILTER_LZMA1, 'dict_size': dictionary,
                'lc': props % 9, 'lp': props // 9 % 5, 'pb': props // 45}]
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
    payload = decoder.decompress(blob[offset + 13:offset + compressed], max_length=size + 1)
    if len(payload) != size or not decoder.eof or decoder.unused_data:
        raise ValueError('LZMA payload does not match its bounded UnityWeb level')
    fixed = blob[:offset + 5] + struct.pack('<Q', size) + blob[offset + 13:]
    if lzma.decompress(fixed[offset + 13:], format=lzma.FORMAT_RAW, filters=filters) != payload:
        raise ValueError('repair changed the decoded payload')
    return fixed, {'changed': fixed != blob, 'lzma_length_offset': offset + 5,
        'declared_before': declared, 'declared_after': size,
        'before_sha256': hashlib.sha256(blob).hexdigest(),
        'after_sha256': hashlib.sha256(fixed).hexdigest(),
        'payload_sha256': hashlib.sha256(payload).hexdigest(),
        'payload_bytes': len(payload), 'payload_unchanged': True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    fixed, result = repair(args.source.read_bytes())
    if args.output:
        if args.source.resolve() == args.output.resolve():
            parser.error('output must differ from source')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('xb') as stream:
            stream.write(fixed)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
