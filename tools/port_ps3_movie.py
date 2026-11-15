#!/usr/bin/env python3
"""Remux the observed PAMF/MPEG-2 PS3 movie to PC MPG without re-encoding.

This produces a standard video file, not a Unity MovieTexture AssetBundle.
Every decoded frame/timestamp must match the source. Requires FFmpeg.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


def run(command: Path, options: list[str]) -> bytes:
    result = subprocess.run([str(command), '-hide_banner', '-nostdin', '-loglevel', 'error', *options],
                            capture_output=True, timeout=300)
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8', 'replace')[-2000:])
    return result.stdout


def decoded_frames(command: Path, source: Path, *, pamf: bool = False) -> list[str]:
    options = ['-f', 'mpeg'] if pamf else []
    data = run(command, [*options, '-i', str(source), '-map', '0:v:0', '-fps_mode', 'passthrough',
                         '-f', 'framemd5', 'pipe:1']).decode('utf-8')
    frames = [line for line in data.splitlines() if line and not line.startswith('#')]
    if not frames:
        raise ValueError('movie has no decoded video frames')
    return frames


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'output', 'proof', 'ffmpeg'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    paths = [args.source.resolve(), args.output.resolve(), args.proof.resolve()]
    if len(set(paths)) != 3 or args.output.exists() or args.proof.exists():
        parser.error('source/output/proof must differ; existing outputs are never overwritten')
    if args.output.suffix.lower() != '.mpg':
        parser.error('the verified target container is .mpg')
    source = args.source.read_bytes()
    if len(source) < 16 or source[:8] != b'PAMF0041':
        raise ValueError('verified PAMF0041 source required')
    stream_offset = struct.unpack_from('>I', source, 8)[0] * 2048
    if source[stream_offset:stream_offset + 4] != b'\0\0\1\xba':
        raise ValueError('PAMF does not point to the observed MPEG program stream')
    probe = subprocess.run([str(args.ffmpeg), '-hide_banner', '-nostdin', '-f', 'mpeg', '-i', str(args.source),
                            '-t', '0', '-f', 'null', '-'], capture_output=True, timeout=60)
    description = probe.stderr.decode('utf-8', 'replace').split('Stream mapping:')[0]
    streams = re.findall(r'^\s*Stream #0:\d+.*?: (Video|Audio|Subtitle|Data):', description, re.MULTILINE)
    if probe.returncode or streams != ['Video']:
        raise ValueError('verified video-only PAMF required; do not discard additional streams')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run(args.ffmpeg, ['-n', '-f', 'mpeg', '-i', str(args.source), '-map', '0:v:0',
                     '-c:v', 'copy', '-f', 'mpeg', str(args.output)])
    before = decoded_frames(args.ffmpeg, args.source, pamf=True)
    after = decoded_frames(args.ffmpeg, args.output)
    if before != after:
        raise ValueError('decoded video frames/timestamps differ; do not publish this output')
    result = dict(source=str(args.source.resolve()), source_sha256=hashlib.sha256(source).hexdigest(),
                  source_container='PAMF0041', stream_offset=stream_offset,
                  output=str(args.output.resolve()), output_bytes=args.output.stat().st_size,
                  output_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
                  codec='MPEG-2 video', operation='stream copy', frames=len(before),
                  decoded_frames_and_timestamps_identical=True,
                  decoded_frame_index_sha256=hashlib.sha256('\n'.join(before).encode()).hexdigest(),
                  unity_movie_texture_verified=False)
    args.proof.parent.mkdir(parents=True, exist_ok=True)
    with args.proof.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(frames=len(before), identical=True, bytes=result['output_bytes'])))


if __name__ == '__main__':
    main()
