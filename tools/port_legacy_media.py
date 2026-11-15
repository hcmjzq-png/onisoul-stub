#!/usr/bin/env python3
"""Decode named Android/PS3 media and rebuild it using an original PC template.

Offline only. Requires UnityPy (verified with 1.10.18), Pillow and etcpak for
textures; FFmpeg with libvorbis for audio. Does not port scenes/scripts/meshes.
Inputs are never overwritten. Names must match the source object exactly.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import io
import json
import lzma
import math
from pathlib import Path
import struct
import subprocess
import sys
import wave
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.repair_unityweb_lzma import MAX_PAYLOAD, layout, repair


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unpack_pc(blob: bytes) -> tuple[bytes, str, bytes]:
    """Read a bounded, single-node/single-level UnityWeb v3 PC template."""
    header, compressed, size = layout(blob)
    if struct.unpack_from('>I', blob, 9)[0] != 3:
        raise ValueError('verified UnityWeb v3 template required')
    props, dictionary, declared = struct.unpack_from('<BIQ', blob, header)
    if declared != size or props >= 225 or dictionary > MAX_PAYLOAD:
        raise ValueError('PC template must have a bounded, known LZMA length')
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
        filters=[dict(id=lzma.FILTER_LZMA1, dict_size=dictionary,
        lc=props % 9, lp=props // 9 % 5, pb=props // 45)])
    # Original Unity encoders can omit EOS when the exact output size is known.
    payload = decoder.decompress(blob[header + 13:header + compressed], max_length=size + 1)
    if len(payload) != size or decoder.unused_data:
        raise ValueError('PC template LZMA length/bounds mismatch')
    if struct.unpack_from('>I', payload)[0] != 1:
        raise ValueError('single serialized-file template required')
    end = payload.index(b'\0', 4)
    name = payload[4:end].decode('ascii')
    offset, length = struct.unpack_from('>II', payload, end + 1)
    if offset < end + 9 or offset + length > size:
        raise ValueError('invalid serialized-file bounds')
    return blob[:header], name, payload[offset:offset + length]


def pack_pc(header: bytes, name: str, node: bytes) -> bytes:
    directory = struct.pack('>I', 1) + name.encode('ascii') + b'\0'
    offset = (len(directory) + 8 + 3) & ~3
    directory += struct.pack('>II', offset, len(node))
    payload = directory.ljust(offset, b'\0') + node
    if len(payload) > MAX_PAYLOAD:
        raise ValueError('output exceeds offline media limit')
    comp = lzma.compress(payload, format=lzma.FORMAT_ALONE,
        filters=[dict(id=lzma.FILTER_LZMA1, dict_size=1 << 23, lc=3, lp=0, pb=2)])
    comp = comp[:5] + struct.pack('<Q', len(payload)) + comp[13:]
    pos = 13
    for _ in range(2):
        pos = header.index(b'\0', pos) + 1
    result = bytearray(header)
    struct.pack_into('>IIIIIIII', result, pos, len(header) + len(comp),
        len(header), 1, 1, len(comp), len(payload), len(header) + len(comp), offset)
    blob = bytes(result) + comp
    _same, proof = repair(blob)
    if proof['changed']:
        raise ValueError('unknown LZMA output length')
    return blob


def repack_serialized(raw: bytes, sf, replacements: dict[int, bytes]) -> bytes:
    """Preserve v9 metadata; change only object offsets/sizes and file length.

    UnityPy records metadata offsets in the parent reader's address space, so
    subtract byte_base_offset. Verify both original values before writing them.
    """
    if sf.header.version != 9 or sf.header.endian != '<' or int(sf.target_platform) != 7:
        raise ValueError('little-endian v9 WebPlayerStreamed PC template required')
    if not 20 <= sf.header.data_offset <= len(raw) or sf.header.file_size != len(raw):
        raise ValueError('invalid PC serialized-file bounds')
    if not replacements.keys() <= sf.objects.keys():
        raise ValueError('replacement references an unknown object')
    out = bytearray(raw[:sf.header.data_offset])
    previous_end = sf.header.data_offset
    for obj in sorted(sf.objects.values(), key=lambda o: o.byte_start):
        if obj.byte_start < previous_end or obj.byte_start + obj.byte_size > len(raw):
            raise ValueError('overlapping or truncated PC template object')
        previous_end = obj.byte_start + obj.byte_size
        out += b'\0' * (-len(out) % 8)
        relative = len(out) - sf.header.data_offset
        data = replacements.get(obj.path_id, raw[obj.byte_start:obj.byte_start + obj.byte_size])
        for field, previous, updated in (
            ('byte_start_offset', obj.byte_start - sf.header.data_offset, relative),
            ('byte_size_offset', obj.byte_size, len(data)),
        ):
            position, width = getattr(obj, field)
            position -= obj.byte_base_offset
            if width != 4 or not 20 <= position <= sf.header.data_offset - 4:
                raise ValueError('unsupported object metadata offset')
            if struct.unpack_from('<I', raw, position)[0] != previous:
                raise ValueError('object metadata does not match the PC template')
            struct.pack_into('<I', out, position, updated)
        out += data
    struct.pack_into('>I', out, 4, len(out))
    return bytes(out)


def ffmpeg(command: Path, data: bytes, options: list[str]) -> bytes:
    proc = subprocess.run([str(command), '-hide_banner', '-loglevel', 'error',
        '-nostdin', '-i', 'pipe:0', *options, 'pipe:1'], input=data,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if proc.returncode:
        raise ValueError('FFmpeg failed: ' + proc.stderr.decode('utf-8', 'replace')[-1200:])
    return proc.stdout


def pcm(command: Path, data: bytes) -> tuple[bytes, int, int]:
    decoded = ffmpeg(command, data, ['-map', '0:a:0', '-c:a', 'pcm_s16le', '-f', 'wav'])
    with wave.open(io.BytesIO(decoded)) as wav:
        if wav.getsampwidth() != 2:
            raise ValueError('16-bit PCM verification required')
        return wav.readframes(wav.getnframes()), wav.getframerate(), wav.getnchannels()


def transcode(command: Path, data: bytes) -> tuple[bytes, dict]:
    before, rate, channels = pcm(command, data)
    ogg = ffmpeg(command, data, ['-map', '0:a:0', '-map_metadata', '-1',
        '-fflags', '+bitexact', '-flags:a', '+bitexact', '-c:a', 'libvorbis',
        '-q:a', '10', '-f', 'ogg'])
    after, rate_after, channels_after = pcm(command, ogg)
    if not ogg.startswith(b'OggS') or (rate, channels) != (rate_after, channels_after):
        raise ValueError('Vorbis output changed sample rate/channels')
    a, b = array('h', before), array('h', after)
    if sys.byteorder != 'little':
        a.byteswap(); b.byteswap()
    if not a or abs(len(a) - len(b)) > channels * 128:
        raise ValueError('decoded output length changed')
    n = min(len(a), len(b))
    energy = sum(v * v for v in a[:n])
    error = sum((x - y) ** 2 for x, y in zip(a[:n], b[:n]))
    if not energy:
        raise ValueError('source is silent; do not publish as restored voice')
    snr = 10 * math.log10(energy / max(error, 1))
    if snr < 24:
        raise ValueError(f'decoded signal differs: SNR {snr:.2f} dB')
    return ogg, dict(sample_rate=rate, channels=channels, source_samples=len(a) // channels,
        output_samples=len(b) // channels, seconds=len(a) / channels / rate,
        decoded_snr_db=round(snr, 3), source_audio_sha256=digest(data),
        output_audio_sha256=digest(ogg))


def convert(source: Path, template: Path, name: str, *, member: str | None = None,
            command: Path | None = None) -> tuple[bytes, dict]:
    import UnityPy
    source_blob = source.read_bytes()
    data = source_blob
    if member:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            data = archive.read(member)
    proof = dict(source=str(source), source_sha256=digest(source_blob), member=member,
        member_sha256=digest(data), name=name, template=str(template),
        template_sha256=digest(template.read_bytes()))
    if source.suffix.lower() in ('.tga', '.png') and not member:
        from PIL import Image
        if source.stem != name:
            raise ValueError('source image basename must match the requested name')
        image = Image.open(io.BytesIO(data)).convert('RGBA')
        kind = 'Texture2D'
        proof.update(source_platform='raster', source_version=None)
    else:
        matches = [o for o in UnityPy.load(data).objects if o.type.name in
            ('AudioClip', 'Texture2D') and o.read().m_Name == name]
        if len(matches) != 1:
            raise ValueError('exactly one source object with the requested name required')
        original = matches[0]
        obj = original.read()
        kind = original.type.name
        proof.update(source_platform=int(original.platform),
            source_version=original.assets_file.unity_version)
        if int(original.platform) not in (7, 10, 13):
            raise ValueError('only verified PC/PS3/Android source platforms supported')
        if kind == 'Texture2D':
            image = obj.image.convert('RGBA')
            proof['source_texture_format'] = int(obj.m_TextureFormat)
        else:
            if not command:
                raise ValueError('--ffmpeg is required for audio conversion')
            audio, audio_proof = transcode(command, bytes(obj.m_AudioData))
            proof.update(audio_proof)
    template_blob = template.read_bytes()
    header, _node_name, raw = unpack_pc(template_blob)
    env = UnityPy.load(template_blob)
    objects = list(env.objects)
    targets = [o for o in objects if o.type.name == kind]
    containers = [o for o in objects if o.type.name == 'AssetBundle']
    if len(targets) != 1 or len(containers) != 1 or len(objects) != 2:
        raise ValueError('PC template must contain one media object and its AssetBundle')
    target, container = targets[0], containers[0]
    tree = target.read_typetree()
    tree['m_Name'] = name
    if kind == 'AudioClip':
        tree.update(m_Format=2, m_Type=14, m_3D=False, m_UseHardware=False,
                    m_Stream=0, m_AudioData=audio)
    else:
        import etcpak
        from PIL import Image
        width, height = image.size
        pixels = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
        # BC3 requires complete 4x4 blocks. Preserve arbitrary Android UI sizes
        # with PC RGBA32 rather than silently resizing them.
        texture_format = 12 if width % 4 == 0 and height % 4 == 0 else 4
        pixels = etcpak.compress_bc3(pixels, width, height) if texture_format == 12 else pixels
        tree.update(m_Width=width, m_Height=height, m_CompleteImageSize=len(pixels),
                    m_TextureFormat=texture_format, m_MipMap=False)
        tree['image data'] = pixels
        proof.update(width=width, height=height, pc_texture_format=texture_format)
    container_tree = container.read_typetree()
    entries = container_tree['m_Container']
    if len(entries) != 1 or entries[0][1]['asset']['m_PathID'] != target.path_id:
        raise ValueError('template container does not point at its media object')
    container_tree['m_Container'] = [(name, entries[0][1])]
    replacements = {target.path_id: target.save_typetree(tree),
                    container.path_id: container.save_typetree(container_tree)}
    node = repack_serialized(raw, target.assets_file, replacements)
    # Every generated bundle needs a distinct archive name while simultaneously
    # loaded; retaining a shared template GUID can collide in the old player.
    archive_name = 'CustomAssetBundle-' + hashlib.md5(name.encode('utf-16le')).hexdigest()
    result = pack_pc(header, archive_name, node)
    checked = list(UnityPy.load(result).objects)
    media = next(o for o in checked if o.type.name == kind)
    readback = media.read()
    if readback.m_Name != name or int(media.platform) != 7:
        raise ValueError('PC object name/platform verification failed')
    if kind == 'AudioClip':
        if bytes(readback.m_AudioData) != audio or int(readback.m_Type) != 14:
            raise ValueError('PC audio serialization changed the converted stream')
    else:
        got = readback.image.convert('RGBA')
        if got.size != image.size:
            raise ValueError('PC texture dimensions changed')
        mae = sum(abs(x-y) for x,y in zip(image.tobytes(), got.tobytes())) / (width * height * 4)
        proof['pixel_mae'] = round(mae, 4)
        if mae > 8:
            raise ValueError(f'PC texture orientation/color verification failed: MAE {mae}')
    proof.update(kind=kind, pc_platform=7, pc_version=media.assets_file.unity_version,
        pc_archive=archive_name, output_bytes=len(result), output_sha256=digest(result),
        structural_readback=True, native_player_verified=False)
    return result, proof


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--member', help='Serialized-file entry inside an Android APK')
    ap.add_argument('--template', type=Path, required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--ffmpeg', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if args.output.resolve() in (args.source.resolve(), args.template.resolve()):
        ap.error('output must differ from both source and template')
    blob, proof = convert(args.source, args.template, args.name,
                         member=args.member, command=args.ffmpeg)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(blob)
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
