"""Build explicitly synthetic initial-city backgrounds using the verified PC model.

Each authored input is a 2:1 sheet: distant_view on the left, foreground on the
right, with the original atlas layout. Preserve foreground alpha, original grass,
model geometry, object references, and country37. Compile distant/sky cyclic
joins from one authored view, rather than stitching unrelated scenery. Offline
only; this command never changes live assets, tables, or player state.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_legacy_media import pack_pc, unpack_pc
from tools.background_atlas_layout import continuous_distant, preserve_grass_pixels, preserve_grass_bc3, join_error, GRASS_BOX

TEMPLATE_SHA256 = '3b2f6a9ed3af1f8c635bce0103a350489129bfc5cbb4372875089363b61b7e8e'
TEMPLATE_NAME = 'pbm37_01'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def initial_background(country: str, row: dict) -> str:
    if not country.startswith('country') or not country[7:].isdigit():
        raise ValueError('unexpected country key')
    backdrop = row.get('backdrop')
    if backdrop != 'pbm' + country[7:]:
        raise ValueError('country backdrop differs from the verified original table')
    return backdrop + '_01'


def export_geometry(template: bytes) -> dict:
    """Export only the verified legacy vertex/strip layout for offline previews."""
    import struct
    import UnityPy
    meshes = []
    for obj in UnityPy.load(template).objects:
        if obj.type.name != 'Mesh':
            continue
        tree = obj.read_typetree()
        vertices = tree['m_VertexData']
        stream = vertices['m_Streams[0]']
        if vertices['m_CurrentChannels'] != 43 or stream['stride'] != 48:
            raise ValueError('unverified background vertex layout')
        data = bytes(vertices['m_DataSize'])
        indices = bytes(tree['m_IndexBuffer'])
        meshes.append(dict(id=obj.path_id, name=tree['m_Name'],
            vertices=list(struct.unpack('<' + 'f' * (len(data) // 4), data)),
            indices=list(struct.unpack('<' + 'H' * (len(indices) // 2), indices)),
            triangleCount=tree['m_SubMeshes'][0]['triangleCount']))
    return dict(source_sha256=sha(template), meshes=meshes)


def rebuild(template: bytes, logical_name: str, sheet_path: Path):
    import etcpak
    import UnityPy
    from PIL import Image

    if sha(template) != TEMPLATE_SHA256:
        raise ValueError('verified original PC background template required')
    if len(logical_name) != len(TEMPLATE_NAME) or not logical_name.endswith('_01'):
        raise ValueError('only the original 30 by 30 initial-city variation is supported')
    header, _archive, node = unpack_pc(template)
    original = list(UnityPy.load(template).objects)
    textures = [obj for obj in original if obj.type.name == 'Texture2D']
    if {obj.read().m_Name for obj in textures} != {'distant_view', 'foreground'}:
        raise ValueError('unexpected template texture names')
    with Image.open(sheet_path) as source:
        if source.width != source.height * 2 or source.width < 1024:
            raise ValueError('input must be a 2:1 atlas sheet, at least 1024 pixels wide')
        source = source.convert('RGBA').resize((2048, 1024), Image.Resampling.LANCZOS)
    targets, diagnostics = {}, []
    for obj in textures:
        texture = obj.read()
        if (texture.m_Width, texture.m_Height, texture.m_TextureFormat) != (1024, 1024, 12):
            raise ValueError('expected original 1024-square DXT5 texture')
        old_pixels = bytes(texture.image_data)
        if len(old_pixels) != 1024 * 1024 or node.count(old_pixels) != 1:
            raise ValueError('template DXT5 block is not unique or has an unexpected size')
        offset = 0 if texture.m_Name == 'distant_view' else 1024
        image = source.crop((offset, 0, offset + 1024, 1024))
        reference = texture.image.convert('RGBA')
        # Atlas export, rather than an artistic edit: keep the original model's
        # exact transparent footprint. Fill generated transparent holes from the
        # source template instead of introducing black texels or alpha fringes.
        missing = image.getchannel('A').point(lambda value: 255 if value < 16 else 0)
        image.paste(reference, mask=missing)
        image.putalpha(reference.getchannel('A'))
        if texture.m_Name == 'distant_view':
            image = continuous_distant(image)
        else:
            image = preserve_grass_pixels(image, reference)
        targets[texture.m_Name] = image
        encoded = etcpak.compress_bc3(image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes(), 1024, 1024)
        if texture.m_Name == 'foreground':
            encoded = preserve_grass_bc3(encoded, old_pixels)
        if len(encoded) != len(old_pixels):
            raise ValueError('DXT5 block size changed')
        node = node.replace(old_pixels, encoded)
        diagnostics.append(dict(name=texture.m_Name, transparent_hole_pixels=sum(missing.histogram()[1:])))
    before = TEMPLATE_NAME.encode('ascii')
    after = logical_name.encode('ascii')
    renames = node.count(before)
    if renames < 4:
        raise ValueError('expected original prefab and AssetBundle lookup names')
    node = node.replace(before, after)
    archive = 'CustomAssetBundle-' + hashlib.md5(node).hexdigest()
    blob = pack_pc(header, archive, node)
    decoded = list(UnityPy.load(blob).objects)
    if Counter(o.type.name for o in original) != Counter(o.type.name for o in decoded):
        raise ValueError('model component inventory changed')
    original_by_id = {o.path_id: o for o in original}
    proof = []
    prefabs = set()
    for obj in decoded:
        previous = original_by_id[obj.path_id]
        if obj.type.name != 'Texture2D':
            # Every mesh, material, animation, transform and reference is kept;
            # only equal-length prefab/container strings can change here.
            if bytes(obj.get_raw_data()) != bytes(previous.get_raw_data()).replace(before, after):
                raise ValueError('non-texture object changed unexpectedly')
        if obj.type.name == 'GameObject':
            prefabs.add(obj.read().m_Name)
        elif obj.type.name == 'Texture2D':
            texture = obj.read()
            image = texture.image.convert('RGBA')
            expected = targets[texture.m_Name]
            from PIL import ImageChops, ImageStat
            difference = ImageStat.Stat(ImageChops.difference(image, expected)).mean
            if max(difference) > 12:
                raise ValueError('decoded DXT5 pixels differ excessively from exported art')
            proof.append(dict(name=texture.m_Name, width=image.width, height=image.height,
                rgba_mae=[round(value, 4) for value in difference], pixel_sha256=sha(image.tobytes())))
            if texture.m_Name == 'foreground':
                old_image = previous.read().image.convert('RGBA')
                if image.crop(GRASS_BOX).tobytes() != old_image.crop(GRASS_BOX).tobytes():
                    raise ValueError('original grass pixels were not preserved exactly')
                proof[-1]['original_grass_pixels_preserved'] = True
            else:
                seams = join_error(image)
                if max(value for seam in seams for value in seam) > 8:
                    raise ValueError('decoded distant joins exceed the seam threshold')
                proof[-1]['cyclic_join_rgba_mae'] = [[round(v, 4) for v in seam] for seam in seams]
    if not {logical_name + '_1', logical_name + '_2'} <= prefabs:
        raise ValueError('required near/far prefab names missing')
    return blob, dict(archive=archive, renamed_occurrences=renames, textures=proof,
        atlas_export=diagnostics, object_counts=dict(Counter(o.type.name for o in decoded)),
        non_texture_objects_preserved=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--countries', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--themes', type=Path, required=True)
    parser.add_argument('--messages', type=Path, help='Optional original countryMessage.json for display names')
    parser.add_argument('--country', action='append', help='Limit an isolated sample build')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    template = args.template.read_bytes()
    if sha(template) != TEMPLATE_SHA256:
        parser.error('original template fingerprint mismatch')
    rows = json.loads(args.countries.read_text(encoding='utf-8'))['country_setting']
    themes = json.loads(args.themes.read_text(encoding='utf-8'))
    messages_path = args.messages or args.countries.with_name('countryMessage.json')
    messages = json.loads(messages_path.read_text(encoding='utf-8'))['message'] if messages_path.is_file() else {}
    selected = sorted(args.country or rows)
    if len(rows) != 47 or not set(selected) <= rows.keys():
        parser.error('47-country original table and known country keys required')
    if args.output.exists():
        parser.error('output must be a new isolated directory')
    required = [args.sources / (country + '.png') for country in selected if country != 'country37']
    if any(not path.is_file() for path in required):
        parser.error('authored atlas input is missing; no generic-success placeholders are generated')
    args.output.mkdir(parents=True)
    (args.output / 'geometry.json').write_text(json.dumps(export_geometry(template), separators=(',', ':')), encoding='utf-8')
    files = []
    for country in selected:
        name = initial_background(country, rows[country])
        relative = 'bundles/pbm/' + hashlib.md5(name.encode('utf-16le')).hexdigest() + '.unity3d'
        destination = args.output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if country == 'country37':
            blob, proof = template, {'original_preserved': True}
        else:
            source = args.sources / (country + '.png')
            blob, proof = rebuild(template, name, source)
            proof.update(source_sha256=sha(source.read_bytes()), source_file=source.name)
        destination.write_bytes(blob)
        import UnityPy
        texture_paths = {}
        for obj in UnityPy.load(blob).objects:
            if obj.type.name == 'Texture2D':
                texture = obj.read()
                relative_texture = f'textures/{country}/{texture.m_Name}.png'
                texture_path = args.output / relative_texture
                texture_path.parent.mkdir(parents=True, exist_ok=True)
                texture.image.save(texture_path)
                texture_paths[texture.m_Name] = relative_texture
        files.append(dict(country=country, logical_name=name, relative=relative,
            country_name=messages.get(rows[country]['oldCountryName'], {}).get('tw', country),
            modern_name=messages.get(rows[country]['newCountryName'], {}).get('tw', ''),
            url='/client/pc/jp/assets/' + relative.removeprefix('bundles/'),
            provenance='original_pc_preserved' if country == 'country37' else 'synthetic_imagegen_shared_original_model',
            theme=themes[country], sha256=sha(blob), bytes=len(blob), preview_textures=texture_paths, proof=proof))
        print(country, name, len(blob), flush=True)
    manifest = dict(scope='47 countries; initial 30x30 main city; variation 01 only',
        original_template_sha256=TEMPLATE_SHA256, generated_art_is_not_original_recovery=True,
        source_method='built-in image_gen; one authored two-atlas sheet per missing country',
        geometry='original country37 meshes, UVs, materials, transforms and animation preserved',
        exclusions=['map expansion variations 02-06', 'subcities', 'other API or resource gaps'], files=files)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
