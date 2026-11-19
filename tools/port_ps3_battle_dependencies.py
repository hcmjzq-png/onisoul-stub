"""Convert the shipped texture and material dependencies of the PS3 battle bundles."""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_building_bundle import read_tree, swap_words
from tools.port_ps3_battle_scene import NAMES, ptrs
from tools.port_ps3_quest_scene import load, pack, serialize, sha

DEPENDENCIES = (
    ("fb01ce789263f841e681f582cb313dff", "db42fdbc951a99140bc2753a0415c848",
     "7a892869c6080ec17d00f98643a8226d3ed8eacb0f9501ea679e33d9efc27591"),
    ("cf0be0e7a5a33ecb2dad5c7ee625bb1f", "93d24dff681cc6d47bffb82416c85b83",
     "16917c6948f3509558d403545062682c3de6e11588d48fb23a619ec176a1c5de"),
    ("801689503012efa6d492ec49dfca6918", "3e876c123e40ffc4194f33f182af40c1",
     "24e29ada0f412c54d7270e6241d78db8c913769adfdb816cb20c3717b88ff666"),
)
BUILTIN = "library/unity default resources"
CONSTANT_SHADER = 327
VERTEX_SHADER = 330


def visit_references(value, sf):
    for reference in ptrs(value):
        fid, pid = reference["m_FileID"], reference["m_PathID"]
        if pid:
            yield (sf.externals[fid - 1].path if fid else sf.name).casefold(), pid


def select_nodes(sources, manifests):
    required, builtin = defaultdict(set), set()
    pending = deque((name, pid) for manifest in manifests
                    for name, ids in manifest["unportedDependencies"].items()
                    for pid in ids if pid)
    while pending:
        name, pid = pending.popleft()
        if name == BUILTIN:
            builtin.add(pid)
        elif pid not in required[name]:
            sf = sources[name]
            required[name].add(pid)
            pending.extend(visit_references(read_tree(sf.objects[pid])[0], sf))
    return required, sorted(builtin)


def reduce_index(value, retained):
    if value["m_MainAsset"]["asset"]["m_PathID"] or value["m_ScriptCompatibility"]:
        raise ValueError("unverified dependency bundle index")
    preload, container = [], []
    for name, entry in value["m_Container"]:
        reference = entry["asset"]
        if reference["m_FileID"] or reference["m_PathID"] not in retained:
            continue
        start = entry["preloadIndex"]
        size = entry["preloadSize"]
        block = value["m_PreloadTable"][start:start + size]
        if len(block) != size:
            raise ValueError(f"invalid preload index for {name}")
        kept = [ref for ref in block if ref["m_FileID"] or ref["m_PathID"] in retained]
        container.append((name, dict(entry, preloadIndex=len(preload), preloadSize=len(kept))))
        preload.extend(kept)
    value.update(m_Container=container, m_PreloadTable=preload, m_ClassCompatibility=[])


def texture_payload(value):
    width, height = value["m_Width"], value["m_Height"]
    fmt = value["m_TextureFormat"]
    raw = value["image data"]
    if fmt not in (3, 7, 10, 12) or not width or not height:
        raise ValueError(f"unverified battle texture format {fmt}")
    pixels = (3 if fmt == 3 else 2) * width * height
    blocks = (width + 3) // 4 * ((height + 3) // 4) * (8 if fmt == 10 else 16)
    top_level = blocks if fmt in (10, 12) else pixels
    if len(raw) != value["m_CompleteImageSize"] or len(raw) < top_level:
        raise ValueError("battle texture payload length differs")
    if fmt == 7:
        value["image data"] = swap_words(bytes(raw), 2)


def shader_value(obj, source, native):
    if obj.path_id == VERTEX_SHADER and source["m_Name"] == native["m_Name"] == "Sprite Vertex Colored, Fast":
        return native
    if obj.path_id != CONSTANT_SHADER or source["m_Name"] != "Transparent Constant":
        raise ValueError(f"unverified battle shader {obj.path_id}")
    script = source["m_Script"].replace("\r\n", "\n")
    beginning, programs = script.split('Program "vp" {', 1)
    if (not beginning.startswith('Shader "Transparent/Constant" {')
            or 'sce_vp_rsx // 6 instructions' not in programs
            or 'sce_fp_rsx // 3 instructions' not in programs
            or 'Vector 467 [_Color]' not in programs
            or 'SetTexture 0 [_MainTex] 2D' not in programs):
        raise ValueError("unexpected PS3 Transparent/Constant pass")
    # The original pass samples _MainTex and multiplies it by _Color.
    # Encode the same pass with Unity 3.5's PC fixed-function texture stage.
    script = beginning + "  SetTexture [_MainTex] { ConstantColor [_Color] combine texture * constant }\n }\n}\n}\n"
    return dict(source, m_Script=script)


def read_source(root):
    sources, names = {}, {}
    for key, internal, checksum in DEPENDENCIES:
        path = root / (key + ".unity3d")
        if sha(path.read_bytes()) != checksum:
            raise ValueError(f"unverified original dependency {key}")
        sf, = load(path, 10).files.values()
        name = "customassetbundle-" + internal
        if sf.name.casefold() != name:
            raise ValueError(f"unexpected internal dependency name for {key}")
        sources[name] = sf
        names[name] = key
    return sources, names


def convert(root, manifests, template, pc_global, out):
    from UnityPy.helpers.TypeTreeHelper import write_typetree
    from UnityPy.streams import EndianBinaryWriter

    sources, names = read_source(root)
    selected, builtin = select_nodes(sources, manifests)
    if set(selected) != set(sources):
        raise ValueError("expected manifests for the battle scene and prefabs")
    global_sf, = load(pc_global, 7).files.values()
    native_shader = read_tree(global_sf.objects[110])[0]
    schemas = {obj.type.name: obj.get_typetree_nodes() for obj in global_sf.objects.values()
               if obj.type.name in ("AssetBundle", "Material", "Shader", "Texture2D")}
    out.mkdir(parents=True, exist_ok=False)
    report = {"format": "offline PC", "builtinResourceIds": builtin, "bundles": {}}
    for name, sf in sources.items():
        source_ids = selected[name]
        objects = []
        for pid in sorted(source_ids | {1}):
            obj = sf.objects[pid]
            kind = obj.type.name
            value = read_tree(obj)[0]
            if kind == "AssetBundle":
                reduce_index(value, source_ids)
            elif kind == "Texture2D":
                texture_payload(value)
            elif kind == "Shader":
                value = shader_value(obj, value, native_shader)
            nodes = schemas[kind]
            raw = write_typetree(value, nodes, EndianBinaryWriter(endian="<")).bytes
            objects.append((pid, obj.class_id, obj.class_id, nodes, raw))
        target = out / (names[name] + ".unity3d")
        data = pack({sf.name: serialize(objects, sf.externals)}, template)
        target.write_bytes(data)
        checked, = load(target, 7).files.values()
        if set(checked.objects) != source_ids | {1} or checked.name != sf.name:
            raise ValueError(f"dependency roundtrip inventory differs for {target.name}")
        for pid, _, _, _, raw in objects:
            obj = checked.objects[pid]
            if obj.get_raw_data() != raw:
                raise ValueError(f"dependency roundtrip byte mismatch for {target.name} #{pid}")
            value = read_tree(obj)[0]
            for ref_name, ref_id in visit_references(value, checked):
                if ref_name != BUILTIN and ref_id not in selected[ref_name]:
                    raise ValueError(f"unresolved reference {ref_name} #{ref_id} from {target.name} #{pid}")
        report["bundles"][target.name] = {"internalName": sf.name, "objects": len(objects), "sha256": sha(data)}
    return report


def join_scene(scene_path, dependency_dir, template):
    """Keep referenced files inside the scene loaded by the existing PC scene loader."""
    scene = load(scene_path, 7)
    originals = {name: sf.reader.bytes for name, sf in scene.files.items()}
    nodes = dict(originals)
    for key, _, _ in DEPENDENCIES:
        sf, = load(dependency_dir / (key + ".unity3d"), 7).files.values()
        nodes[sf.name] = serialize([
            (obj.path_id, obj.class_id, obj.class_id, obj.get_typetree_nodes(), obj.get_raw_data())
            for obj in sf.objects.values() if obj.type.name != "AssetBundle"
        ], sf.externals)
    data = pack(nodes, template)
    import UnityPy
    checked, = UnityPy.load(data).files.values()
    if set(checked.files) != set(nodes) or any(sf.reader.bytes != nodes[name] for name, sf in checked.files.items()):
        raise ValueError("battle scene dependency attachment did not roundtrip")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("root", "scene", "prefabs", "pc-template", "pc-global", "out"):
        parser.add_argument("--" + key, required=True, type=Path)
    args = parser.parse_args()
    manifests = [json.loads((path / "manifest.json").read_bytes()) for path in (args.scene, args.prefabs)]
    template = args.pc_template.read_bytes()
    report = convert(args.root, manifests, template, args.pc_global, args.out)
    scene_name = NAMES["scene"][0] + ".unity3d"
    scene = join_scene(args.scene / scene_name, args.out, template)
    (args.out / scene_name).write_bytes(scene)
    report["scene"] = {"name": scene_name, "sha256": sha(scene)}
    (args.out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
