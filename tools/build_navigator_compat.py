"""Export an explicitly synthetic navigator atlas to isolated PC bundles.

Atlas input is a 3-column, 2-row transparent sheet (five sprites, last cell empty).
The inventory supplies the real PC names/URLs. Existing originals are copied with
their recorded digests; generated palettes never overwrite those originals.
This exports game texture layouts, not an original-art recovery or a deployment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_legacy_media import pack_pc, repack_serialized, unpack_pc


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def clone(value):
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, dict):
        return {k: clone(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clone(v) for v in value]
    if isinstance(value, tuple):
        return tuple(clone(v) for v in value)
    return value


def rebuild(template: bytes, textures: dict, *,
            name_map: dict[str, str] | None = None) -> tuple[bytes, list[dict]]:
    import UnityPy
    from PIL import Image

    header, _, raw = unpack_pc(template)
    objects = list(UnityPy.load(template).objects)
    targets = [o for o in objects if o.type.name == 'Texture2D']
    container = next(o for o in objects if o.type.name == 'AssetBundle')
    if len(objects) != len(textures) + 1 or len(targets) != len(textures):
        raise ValueError('template object count differs from supplied textures')
    if name_map is not None and (len(name_map) != len(textures)
                                 or set(name_map.values()) != set(textures)):
        raise ValueError('explicit names must map to each texture once')
    changes = {}
    container_tree = clone(container.read_typetree())
    old_to_new = {}
    for target in targets:
        tree = clone(target.read_typetree())
        old = tree['m_Name']
        if name_map is None:
            matches = [name for name in textures if name.endswith(old[-3:])]
            if len(matches) != 1:
                raise ValueError('texture suffix is not unique')
            name = matches[0]
        else:
            name = name_map[old]
        image = textures[name].convert('RGBA')
        pixels = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
        tree.update(m_Name=name, m_Width=image.width, m_Height=image.height,
                    m_CompleteImageSize=len(pixels), m_TextureFormat=4, m_MipMap=False)
        tree['image data'] = pixels
        changes[target.path_id] = target.save_typetree(tree)
        old_to_new[old.lower()] = name
    container_tree['m_Container'] = [
        (old_to_new[name.lower()].lower(), binding) for name, binding in container_tree['m_Container']]
    changes[container.path_id] = container.save_typetree(container_tree)
    node = repack_serialized(raw, targets[0].assets_file, changes)
    archive = 'CustomAssetBundle-' + hashlib.md5(node).hexdigest()
    blob = pack_pc(header, archive, node)
    proof = []
    for obj in UnityPy.load(blob).objects:
        if obj.type.name != 'Texture2D':
            continue
        texture = obj.read()
        image = texture.image.convert('RGBA')
        expected = textures[texture.m_Name]
        if int(obj.platform) != 7 or image.size != expected.size or image.tobytes() != expected.tobytes():
            raise ValueError('PC pixel/name/platform readback failed')
        proof.append(dict(name=texture.m_Name, kind='Texture2D', width=image.width,
                          height=image.height, pixel_mae=0, pixel_sha256=sha(image.tobytes())))
    return blob, proof


def export_sprite(sheet, color: int):
    from PIL import Image

    width, height = sheet.size
    if width % 3 or height % 2 or sheet.mode != 'RGBA':
        raise ValueError('transparent 3 by 2 atlas required')
    cw, ch = width // 3, height // 2
    index = color - 1
    cell = sheet.crop((index % 3 * cw, index // 3 * ch,
                       (index % 3 + 1) * cw, (index // 3 + 1) * ch))
    # Ignore nearly transparent pixels only when measuring the export bounds;
    # keep the generated alpha itself unchanged, including anti-aliased edges.
    bbox = cell.getchannel('A').point(lambda value: 255 if value >= 32 else 0).getbbox()
    if not bbox or cell.getchannel('A').getextrema() != (0, 255):
        raise ValueError('empty or nontransparent sprite cell')
    sprite = cell.crop(bbox)
    result = {}
    # Original human-female PC templates: bust bottom-centred at y=1024,
    # icon content near x=20,y=12 in 128; 64 is its half-sized counterpart.
    for role, canvas_size, content_height, center_x, bottom in (
        ('bust', 1024, 565, 512, 1024),
        ('icon02', 128, 108, 46, 120),
        ('icon01', 64, 54, 23, 60),
    ):
        scale = content_height / sprite.height
        resized = sprite.resize((round(sprite.width * scale), content_height), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (canvas_size, canvas_size))
        left = round(center_x - resized.width / 2)
        if left < 0 or left + resized.width > canvas_size:
            raise ValueError('sprite exceeds the known PC texture layout')
        canvas.paste(resized, (left, bottom - content_height))
        result[role] = canvas
    return result, bbox


def main() -> None:
    from PIL import Image
    import UnityPy

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--atlases', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--bundles', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output must be a new isolated directory')
    inputs = json.loads(args.atlases.read_text(encoding='utf-8'))
    atlas_root = Path(inputs['source_root'])
    if not atlas_root.is_absolute():
        atlas_root = args.atlases.parent / atlas_root
    inventory = list(csv.DictReader(args.inventory.open(encoding='utf-8'), delimiter='\t'))
    if len(inventory) != 80 or len({r['url'] for r in inventory}) != 80:
        raise ValueError('expected the 80 distinct PR82 image paths')
    templates = {
        'bust': args.bundles/'cch/c3f01d7176ce520dab9bd1a8328acb1f.unity3d',
        'icon': args.bundles/'item/54c91a46ea23ba587f2ad4c540df3a61.unity3d',
    }
    args.output.mkdir(parents=True)
    files, probes, sprites = [], [], {}
    for row in inventory:
        relative = row['url'].split('/assets/', 1)[1]
        target = args.output/'bundles'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        nid, color = row['navigator'], int(row['color'])
        if nid not in {f'navi8000{n}01' for n in range(1, 9)}:
            raise ValueError('unexpected navigator ID in original inventory')
        family = nid[8]
        original = row['status'] == '200'
        detail = dict(navigator=nid, color=color, role=row['role'], url=row['url'],
                      relative=relative, preserved_original=original)
        if original:
            blob = (args.bundles/relative).read_bytes()
            if sha(blob) != row['sha256']:
                raise ValueError('original inventory fingerprint mismatch: ' + relative)
            proof = []
            for obj in UnityPy.load(blob).objects:
                if obj.type.name == 'Texture2D':
                    texture = obj.read()
                    proof.append(dict(name=texture.m_Name,kind='Texture2D',
                                      width=texture.m_Width,height=texture.m_Height))
            detail['provenance'] = 'original_pc_preserved'
        else:
            key = (nid, color)
            atlas_path = atlas_root/inputs['files'][family]
            atlas_blob = atlas_path.read_bytes()
            if key not in sprites:
                sheet = Image.open(atlas_path).convert('RGBA')
                sprites[key] = export_sprite(sheet, color)
                atlas_copy = args.output/'atlases'/f'navi8000{family}01.png'
                atlas_copy.parent.mkdir(exist_ok=True)
                if not atlas_copy.exists():
                    shutil.copyfile(atlas_path, atlas_copy)
            layouts, bbox = sprites[key]
            if row['role'] == 'bust':
                textures = {row['texture']: layouts['bust']}
            else:
                textures = {row['texture'][:-3]+'_01': layouts['icon01'],
                            row['texture']: layouts['icon02']}
            for name, image in textures.items():
                raster = args.output/'textures'/(name+'.png')
                raster.parent.mkdir(exist_ok=True)
                image.save(raster)
            template_blob = templates[row['role']].read_bytes()
            blob, proof = rebuild(template_blob, textures)
            detail.update(provenance='ai_reference_compatibility', atlas_sha256=sha(atlas_blob),
                          atlas_cell_bbox=bbox, template_sha256=sha(template_blob),
                          palette_original_verified=False)
        target.write_bytes(blob)
        detail.update(sha256=sha(blob), bytes=len(blob),textures=proof)
        files.append(detail)
        for item in proof:
            probes.append(dict(item,id=item['name'],output=str(target.resolve()),
                               output_sha256=sha(blob),output_bytes=len(blob)))
    result = dict(schema=1,kind='navigator_compatibility_candidate',
        summary=dict(bundles=len(files),preserved_originals=sum(r['preserved_original'] for r in files),
                     generated_bundles=sum(not r['preserved_original'] for r in files),
                     textures=len(probes),native_verified=False,deployed=False),files=files)
    (args.output/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output/'native-manifest.json').write_text(json.dumps(dict(converted=probes),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
