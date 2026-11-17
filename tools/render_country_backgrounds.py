"""Render orthographic background-model previews from verified meshes and textures.

Requires Pillow and NumPy. These are offline asset previews, not screenshots or
an assertion that the original game's camera/gameplay has been reproduced.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import numpy as np
from PIL import Image

# Original model placement: PoliticBgModel.cs:119-123 and the template's
# transforms. Preview camera bounds are our own, showing the complete model.
PLACEMENT = {
    'foreground': (-.000244140625, -1048, -1199.9998315),
    'wood_01': (0, -1062.6447563, -900),
    'wood_02': (0, -1048, -600),
    'distant_view': (0, 152, -1199.9999992),
    'sky': (0, 212, -1314.7199402),
}


def triangles(mesh: dict) -> np.ndarray:
    indices = mesh['indices']
    result = [indices[i - 2:i + 1] for i in range(2, len(indices))
        if len(set(indices[i - 2:i + 1])) == 3]
    if len(result) != mesh['triangleCount']:
        raise ValueError('decoded triangle-strip count differs from original metadata')
    return np.asarray(result, dtype=np.int32)


def render(geometry: dict, texture_paths: dict, width: int = 960) -> Image.Image:
    scale = width / 4400
    height = round(2770 * scale)
    canvas = np.zeros((height, width, 4), dtype=np.float32)
    textures = {name: np.asarray(Image.open(path).convert('RGBA'), dtype=np.float32) / 255
        for name, path in texture_paths.items()}
    faces = []
    for mesh in geometry['meshes']:
        vertices = np.asarray(mesh['vertices'], dtype=np.float32).reshape(-1, 12)
        world = vertices[:, :3] + np.asarray(PLACEMENT[mesh['name']], dtype=np.float32)
        xy = np.stack(((world[:, 0] + 2200) * scale, (370 - world[:, 1]) * scale), axis=1)
        texture = textures['distant_view' if mesh['name'] in {'sky', 'distant_view'} else 'foreground']
        for triangle in triangles(mesh):
            faces.append((float(world[triangle, 2].mean()), xy[triangle], vertices[triangle, 6:8], texture))
    for _depth, p, uv, texture in sorted(faces, key=lambda item: item[0]):
        left = max(0, int(np.floor(p[:, 0].min())))
        right = min(width, int(np.ceil(p[:, 0].max())))
        top = max(0, int(np.floor(p[:, 1].min())))
        bottom = min(height, int(np.ceil(p[:, 1].max())))
        if right <= left or bottom <= top:
            continue
        denominator = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
        if abs(denominator) < .0001:
            continue
        x, y = np.meshgrid(np.arange(left, right) + .5, np.arange(top, bottom) + .5)
        a = ((p[1, 1] - p[2, 1]) * (x - p[2, 0]) + (p[2, 0] - p[1, 0]) * (y - p[2, 1])) / denominator
        b = ((p[2, 1] - p[0, 1]) * (x - p[2, 0]) + (p[0, 0] - p[2, 0]) * (y - p[2, 1])) / denominator
        c = 1 - a - b
        mask = (a >= -1e-5) & (b >= -1e-5) & (c >= -1e-5)
        if not mask.any():
            continue
        u = a * uv[0, 0] + b * uv[1, 0] + c * uv[2, 0]
        v = a * uv[0, 1] + b * uv[1, 1] + c * uv[2, 1]
        tx = np.clip(np.rint(u * (texture.shape[1] - 1)), 0, texture.shape[1] - 1).astype(np.int32)
        ty = np.clip(np.rint((1 - v) * (texture.shape[0] - 1)), 0, texture.shape[0] - 1).astype(np.int32)
        source = texture[ty, tx]
        alpha = source[:, :, 3:4] * mask[:, :, None]
        destination = canvas[top:bottom, left:right]
        destination[:, :, :3] = source[:, :, :3] * alpha + destination[:, :, :3] * (1 - alpha)
        destination[:, :, 3:4] = alpha + destination[:, :, 3:4] * (1 - alpha)
    # RGB above is premultiplied during compositing; export ordinary PNG RGBA.
    alpha = canvas[:, :, 3:4]
    canvas[:, :, :3] = np.divide(canvas[:, :, :3], alpha, out=np.zeros_like(canvas[:, :, :3]), where=alpha > 0)
    return Image.fromarray(np.rint(np.clip(canvas, 0, 1) * 255).astype(np.uint8))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--width', type=int, default=960)
    args = parser.parse_args()
    manifest = json.loads((args.release / 'manifest.json').read_text(encoding='utf-8'))
    geometry = json.loads((args.release / 'geometry.json').read_text(encoding='utf-8'))
    if geometry['source_sha256'] != manifest['original_template_sha256']:
        parser.error('preview geometry is not from the recorded original template')
    if not 320 <= args.width <= 1920:
        parser.error('preview width must be between 320 and 1920 pixels')
    output = args.release / 'previews'
    output.mkdir(exist_ok=True)
    for row in manifest['files']:
        result = render(geometry, {name: args.release / path for name, path in row['preview_textures'].items()}, args.width)
        result.save(output / (row['country'] + '.png'))
        print(row['country'], flush=True)
    cards = []
    for row in manifest['files']:
        name = html.escape(row['country_name'])
        modern = html.escape(row.get('modern_name', ''))
        theme = html.escape(row['theme']['label'])
        badge = '原版保留' if row['country'] == 'country37' else '自制背景'
        path = 'previews/' + row['country'] + '.png'
        cards.append(f'<article><a href="{path}" target="_blank"><img src="{path}" loading="lazy"></a>'
            f'<h2>{name} <small>{row["country"]}</small></h2><p>{modern} · {theme} · {badge}</p></article>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>47国主城背景预览</title><style>
body{margin:0;padding:28px;background:#151b18;color:#e9eee8;font:16px "Microsoft YaHei",sans-serif}
header{max-width:1350px;margin:auto auto 24px}h1{font-size:28px;margin:0 0 12px}header p{color:#b8c4ba}
input{font:inherit;padding:12px;width:320px;max-width:85%;border:1px solid #637869;background:#253129;color:white;border-radius:6px}
main{max-width:1350px;margin:auto;display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:18px}
article{background:#26332b;border:1px solid #425447;border-radius:8px;overflow:hidden}img{width:100%;display:block;background:#111714}
h2{font-size:19px;margin:13px 14px 8px}small{font-size:13px;font-weight:normal;color:#a9b9ac}article p{font-size:14px;margin:0 14px 17px;color:#c0cec2}
</style><header><h1>47 国初始主城背景</h1><p>46 国自制＋37 国原版。空地为主城建造区；离线模型预览，非游戏截图。点击图片查看大图。</p>
<input aria-label="筛选国家" placeholder="按国家、编号或主题筛选" oninput="document.querySelectorAll('article').forEach(x=>x.style.display=x.textContent.toLowerCase().includes(this.value.toLowerCase())?'':'none')"></header><main>'''
    (args.release / 'gallery.html').write_text(page + ''.join(cards) + '</main></html>', encoding='utf-8')


if __name__ == '__main__':
    main()
