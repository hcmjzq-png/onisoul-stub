"""Port the shipped PS3 battle scene/prefabs to an offline Unity 3.5 PC candidate."""
from __future__ import annotations

import argparse
from collections import defaultdict
import copy
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_building_bundle import read_tree, swap_words
from tools.port_ps3_quest_scene import GLOBAL, HEAD_FIELDS, load, node, pack, read_managed, script_key, serialize, sha

NAMES = {
    "scene": ("ec7eb72b0c3a6d0d07f2445ffe4645e9",
              "683118ed81af5544d209dc34766dd18a8e3e43004446123dd2289cece97272c1"),
    "prefabs": ("56f270161dfd00d357c585cd7c9f4407",
                "6ac5be7bcc8a94a5d1d7b17595aa114f18afaf0e0e82c7802f5cc00e9498e6a6"),
}
GLOBAL_KEY = "7536912f38fca927a22a16bdbefcdc07"
PS3_GLOBAL = "customassetbundle-fcffaf73bfc60a442a63756405623ea6"
ALIGN = 0x4000
MANAGED = 0x800
PRIMITIVES = {
    "int": ("SInt32", 4), "uint": ("UInt32", 4), "float": ("float", 4),
    "short": ("SInt16", 2), "ushort": ("UInt16", 2), "byte": ("UInt8", 1),
    "sbyte": ("SInt8", 1), "bool": ("UInt8", 1),
}
STRUCTS = {
    "Vector2": "xy", "Vector3": "xyz", "Vector4": "xyzw", "Quaternion": "xyzw",
    "Color": "rgba", "Rect": "xywh", "Color32": "rgba",
}
VERTICES = {11: ((0, 32),), 13: ((0, 12), (16, 24)),
            15: ((0, 24), (28, 36)), 31: ((0, 24), (28, 44))}


def read_layout(path):
    layouts = json.loads(path.read_bytes())
    for name, fields in layouts.items():
        names = {key for key, _ in fields}
        # The legacy serializer stores the private _ser_ shadow rather than
        # the adjacent runtime mirror in the sprite classes.
        layouts[name] = [(key, kind) for key, kind in fields
                         if "_ser_" + key not in names
                         and not (name in ("SpriteRoot", "PackedSprite", "UIButton", "SimpleSprite")
                                  and key == "staticFrameInfo" and "_ser_stat_frame_info" in names)]
    return layouts


def managed_schema(head, fields, layouts, *, pc=False):
    seed = head[0]

    def entry(level, typ, name, size=-1, flags=0, array=False, version=1):
        return node(seed, m_Level=level, m_Type=typ, m_Name=name, m_ByteSize=size,
                    m_MetaFlag=flags | (MANAGED if pc else 0), m_TypeFlags=int(array), m_Version=version)

    def type_name(kind):
        return kind.split(":", 1)[-1].rsplit("+", 1)[-1].rsplit(".", 1)[-1]

    def dynamic(kind):
        return (kind == "string" or kind.startswith("array:") or kind.startswith("object:")
                and any(dynamic(child) for _, child in layouts[kind[7:]]))

    def emit(field, kind, level, in_array=False):
        if kind in PRIMITIVES:
            typ, size = PRIMITIVES[kind]
            if pc and kind == "int":
                typ = "int"
            alignment = ALIGN if size < 4 and not in_array else 0
            yield entry(level, typ, field, size, alignment | (0x100 if pc and kind == "bool" else 0))
        elif kind == "string":
            yield entry(level, "string", field, flags=0x8000 if pc else 0)
            yield entry(level + 1, "Array", "Array", flags=ALIGN | int(pc), array=True)
            yield entry(level + 2, "SInt32", "size", 4, flags=int(pc))
            yield entry(level + 2, "char", "data", 1, flags=int(pc))
        elif kind.startswith("ptr:"):
            yield entry(level, "PPtr<$" + kind[4:] + ">", field, 8)
            yield entry(level + 1, "SInt32", "m_FileID", 4, flags=int(pc))
            yield entry(level + 1, "SInt32", "m_PathID", 4, flags=int(pc))
        elif kind.startswith("array:"):
            element = kind[6:]
            nested = type_name(element) if pc and element.startswith("object:") else "vector"
            flags = 0x8000 if pc and dynamic(element) else 0
            yield entry(level, nested, field, flags=flags)
            alignment = ALIGN if not pc or (element in PRIMITIVES and PRIMITIVES[element][1] < 4) else 0
            yield entry(level + 1, "Array", "Array", flags=flags | alignment, array=True)
            yield entry(level + 2, "SInt32", "size", 4)
            yield from emit("data", element, level + 2, in_array=True)
        elif kind.startswith("object:"):
            children = [n for name, nested in layouts[kind[7:]] for n in emit(name, nested, level + 1)]
            fixed = [n for n in children if n.m_Level == level + 1]
            length = -1 if any(n.m_ByteSize < 0 for n in fixed) else sum(
                (n.m_ByteSize + 3) & ~3 if n.m_MetaFlag & ALIGN else n.m_ByteSize for n in fixed)
            label = type_name(kind) if pc and not in_array else "Generic Mono"
            yield entry(level, label, field, length if pc else -1, flags=0x8000 if pc and length < 0 else 0)
            yield from children
        elif kind == "unity:UnityEngine.LayerMask":
            yield entry(level, "BitField", field, 4)
            yield entry(level + 1, "UInt32", "m_Bits", 4)
        elif kind.startswith("unity:"):
            typ = kind.rsplit(".", 1)[-1]
            axes = STRUCTS[typ]
            label = {"Color": "ColorRGBA", "Vector2": "Vector2f", "Vector3": "Vector3f",
                     "Vector4": "Vector4f", "Quaternion": "Quaternionf"}.get(typ, typ) if pc else typ
            yield entry(level, label, field, 4 if typ == "Color32" else 4 * len(axes), flags=0x200000 if pc else 0)
            for axis in axes:
                yield entry(level + 1, "UInt8" if typ == "Color32" else "float", axis,
                            1 if typ == "Color32" else 4)
        else:
            raise ValueError(f"unsupported managed field type {kind}")

    return list(head) + [child for name, kind in fields for child in emit(name, kind, 1)]


def mesh_buffers(value):
    v = value["m_VertexData"]
    first = v["m_Streams[0]"]
    count, mask, width = v["m_VertexCount"], v["m_CurrentChannels"], first["stride"]
    raw, indices = bytes(v["m_DataSize"]), bytes(value["m_IndexBuffer"])
    if (mask not in VERTICES or first["channelMask"] != mask or first["offset"]
            or width != VERTICES[mask][-1][-1] or width * count != len(raw)
            or value["m_MeshCompression"] or value["m_BindPose"] or value["m_Skin"]
            or any(field["m_NumItems"] for field in value["m_CompressedMesh"].values())
            or len(indices) % 2 or any(i >= count for (i,) in struct.iter_unpack(">H", indices))):
        raise ValueError("unverified PS3 battle mesh encoding")
    for i in range(1, 4):
        stream = v[f"m_Streams[{i}]"]
        if stream["channelMask"] or stream["offset"] or stream["stride"]:
            raise ValueError("unverified secondary battle mesh stream")
    out = bytearray(raw)
    for i in range(0, len(raw), width):
        for start, end in VERTICES[mask]:
            out[i + start:i + end] = swap_words(raw[i + start:i + end], 4)
    v["m_DataSize"] = bytes(out)
    value["m_IndexBuffer"] = list(swap_words(indices, 2))


def ptrs(value):
    if isinstance(value, dict):
        if set(value) == {"m_FileID", "m_PathID"}:
            yield value
        else:
            for child in value.values():
                yield from ptrs(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from ptrs(child)


def native_global_indices(ps3, pc):
    """Map original global script identities and uniquely named native objects."""
    def key(obj):
        data = read_tree(obj)[0]
        if obj.type.name == "MonoScript":
            return (obj.type.name, *script_key(data))
        if data.get("m_Name"):
            return (obj.type.name, data["m_Name"])
        return None

    rows = defaultdict(list)
    for obj in pc.objects.values():
        if obj.type.name in {"MonoScript", "Material", "Shader", "Texture2D", "TextAsset", "AudioClip", "AnimationClip"}:
            rows[key(obj)].append(obj.path_id)
    mapped = {}
    for obj in ps3.objects.values():
        if obj.type.name in {"MonoScript", "Material", "Shader", "Texture2D", "TextAsset", "AudioClip", "AnimationClip"}:
            identity = key(obj)
            if identity and len(rows[identity]) == 1:
                mapped[obj.path_id] = rows[identity][0]
    return mapped


def native_managed_schemas(files, layouts):
    by_name = {sf.name.casefold(): sf for sf in files}
    schemas = {}
    for sf in files:
        for obj in sf.objects.values():
            if obj.type.name != "MonoBehaviour" or not obj.serialized_type.nodes:
                continue
            fid, pid = struct.unpack_from("<ii", obj.get_raw_data(), 12)
            owner = by_name.get(sf.externals[fid - 1].path.casefold()) if fid else sf
            if owner is None or pid not in owner.objects:
                continue
            script = owner_script(owner, pid)
            full_name = qualified(script_key(script))
            if full_name not in layouts:
                continue
            nodes = obj.get_typetree_nodes()
            if {n.m_Name for n in nodes if n.m_Level == 1} == HEAD_FIELDS | {n for n, _ in layouts[full_name]}:
                schemas.setdefault(full_name, nodes)
    if "UIManager" not in schemas:
        raise ValueError("expected an original PC UIManager schema")
    return schemas


def qualified(identity):
    return ".".join(filter(None, identity[1:]))


def add_empty_card(index, sf, objects, art, texture_schema, encode):
    from PIL import Image

    name = "card_image_enpty_001"  # The PC intro asks for this original spelling.
    if any(key == name for key, _ in index["m_Container"]):
        raise ValueError("battle bundle already contains the original empty card")
    original = read_tree(sf.objects[10])[0]
    if original["m_Name"] != "result_empty_card_001":
        raise ValueError("unexpected original card texture template")
    with Image.open(art) as source:
        image = source.convert("RGBA")
    if image.size != (256, 256) or sha(image.tobytes()) != "3cc4ad68c206ff5a8aa738c9a588905e23a4919e0e5d5f0ba6d420f6edcd3ae0":
        raise ValueError("unexpected original battle empty card pixels")
    pixels = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
    original.update(m_Name=name, m_Width=image.width, m_Height=image.height,
                    m_TextureFormat=4, m_MipMap=False, m_CompleteImageSize=len(pixels))
    original["image data"] = pixels
    pid = max(sf.objects) + 1
    cls = sf.objects[10].class_id
    objects.append((pid, cls, cls, texture_schema, encode(original, texture_schema)))
    pointer = {"m_FileID": 0, "m_PathID": pid}
    entry = {"preloadIndex": len(index["m_PreloadTable"]), "preloadSize": 1, "asset": pointer}
    index["m_Container"].append((name, entry))
    index["m_Container"].sort(key=lambda row: row[0])
    index["m_PreloadTable"].append(pointer)


def convert(group, root, ps_layout, pc_layout, pc_quest, pc_global, pc_app, empty_card_art=None):
    import UnityPy
    from PIL import Image
    from UnityPy.helpers.TypeTreeHelper import write_typetree
    from UnityPy.streams import EndianBinaryWriter

    def encode(value, schema):
        return write_typetree(value, schema, EndianBinaryWriter(endian="<")).bytes

    if empty_card_art and group != "prefabs":
        raise ValueError("the battle empty card belongs in the prefab bundle")
    key, source_sha = NAMES[group]
    path = root / (key + ".unity3d")
    if sha(path.read_bytes()) != source_sha:
        raise ValueError("unverified source battle bundle")
    source = load(path, 10).files
    ps3_global, = load(root / (GLOBAL_KEY + ".unity3d"), 10).files.values()
    native_global, = load(pc_global, 7).files.values()
    if ps3_global.name.casefold() != PS3_GLOBAL or native_global.name.casefold() != GLOBAL:
        raise ValueError("unexpected original global bundle identity")
    globals_map = native_global_indices(ps3_global, native_global)
    source_nodes = {name.casefold(): sf for name, sf in source.items()}
    source_nodes[PS3_GLOBAL] = ps3_global
    dst_layouts, src_layouts = read_layout(pc_layout), read_layout(ps_layout)
    guide = load(pc_quest, 7).files
    head = guide["BuildPlayer-quest"].objects[242].get_typetree_nodes()
    if {field.m_Name for field in head if field.m_Level == 1} != HEAD_FIELDS:
        raise ValueError("unexpected PC managed component header")
    native_trees = native_managed_schemas([*guide.values(), native_global], dst_layouts)
    builtin = {o.class_id: o.get_typetree_nodes() for sf in (*guide.values(), native_global)
               for o in sf.objects.values() if o.type.name != "MonoBehaviour" and o.serialized_type and o.serialized_type.nodes}
    pc_scripts = {}
    for item in UnityPy.load(pc_app.read_bytes()).objects:
        if item.type.name == "MonoScript":
            data = read_tree(item)[0]
            pc_scripts[script_key(data)] = data
    for item in native_global.objects.values():
        if item.type.name == "MonoScript":
            data = read_tree(item)[0]
            pc_scripts.setdefault(script_key(data), data)
    built, expected = {}, {}
    dependencies, fallback_types, deferred_globals = defaultdict(set), set(), set()
    for name, sf in source.items():
        ext = list(map(copy.copy, sf.externals))
        external_names = [entry.path.casefold() for entry in ext]
        for entry in ext:
            if entry.path.casefold() == PS3_GLOBAL:
                entry.path = GLOBAL
        used = {}
        compatibility = None
        objects = []
        for obj in sf.objects.values():
            kind, type_id = obj.type.name, obj.class_id
            try:
                if kind == "MonoBehaviour":
                    fid, pid = struct.unpack_from(">ii", obj.get_raw_data(), 12)
                    record = owner_script(sf if not fid else source_nodes[external_names[fid - 1]], pid)
                    identity = script_key(record)
                    fq = qualified(identity)
                    src_fields, dst_fields = src_layouts[fq], dst_layouts[fq]
                    native_tree = native_trees.get(fq)
                    src_tree = native_tree if native_tree and src_fields == dst_fields else managed_schema(head, src_fields, src_layouts)
                    value = read_managed(obj, src_tree)
                    if src_fields != dst_fields:
                        if fq != "SpriteText" or [f for f in src_fields if f[0] != "endlineWhiteSpace"] != dst_fields:
                            raise ValueError(f"unverified PC managed layout change: {fq}")
                        del value["endlineWhiteSpace"]
                    schema = native_tree or managed_schema(head, dst_fields, dst_layouts, pc=fq == "BattleEventTimeline")
                    type_id = used.setdefault(identity, -(len(used) + 1))
                else:
                    value = read_tree(obj)[0]
                    schema = builtin.get(obj.class_id)
                    if schema is None:
                        fallback_types.add(kind)
                        schema = obj.get_typetree_nodes()
                    if kind == "Mesh":
                        mesh_buffers(value)
                    elif kind == "MonoScript":
                        value = pc_scripts[script_key(value)]
                    elif kind == "Texture2D":
                        image = obj.read().image.convert("RGBA")
                        payload = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
                        value.update(m_TextureFormat=4, m_MipMap=False, m_CompleteImageSize=len(payload))
                        value["image data"] = payload
                    elif kind == "AssetBundle":
                        # PC's existing resource loading path does its own class
                        # checks. Cross-platform console compatibility rows do
                        # not describe the emitted PC type tree.
                        value["m_ClassCompatibility"] = []
                        compatibility = (len(objects), obj, schema, value)
                for reference in ptrs(value):
                    fid, pid = reference["m_FileID"], reference["m_PathID"]
                    if not fid:
                        if pid and pid not in sf.objects:
                            raise ValueError(f"unresolved local reference {pid}")
                    elif external_names[fid - 1] == PS3_GLOBAL:
                        if pid in globals_map:
                            reference["m_PathID"] = globals_map[pid]
                        elif pid:
                            missing = ps3_global.objects[pid]
                            label = read_tree(missing)[0].get("m_Name")
                            deferred_globals.add((pid, missing.type.name, label or ""))
                    elif external_names[fid - 1] not in source_nodes:
                        dependencies[external_names[fid - 1]].add(pid)
                raw = encode(value, schema)
                objects.append((obj.path_id, type_id, obj.class_id, schema, raw))
            except (ValueError, KeyError, IndexError, TypeError) as error:
                raise ValueError(f"{name}: object {obj.path_id} ({kind}): {error}") from error
        if compatibility:
            index, obj, schema, value = compatibility
            if empty_card_art:
                add_empty_card(value, sf, objects, empty_card_art, builtin[28], encode)
            value["m_ScriptCompatibility"] = [
                {"assemblyName": k[0], "nameSpace": k[1], "className": k[2],
                 "hash": pc_scripts[k]["m_PropertiesHash"]} for k in sorted(used)
            ]
            raw = encode(value, schema)
            objects[index] = (obj.path_id, obj.class_id, obj.class_id, schema, raw)
        expected[name] = {pid: (cls, sha(raw)) for pid, _, cls, _, raw in objects}
        built[name] = serialize(objects, ext)
    if deferred_globals:
        raise ValueError(f"unmatched PC global references: {sorted(deferred_globals)}")
    data = pack(built, pc_quest.read_bytes())
    checked, = UnityPy.load(data).files.values()
    for name, sf in checked.files.items():
        actual = {obj.path_id: (obj.class_id, sha(obj.get_raw_data())) for obj in sf.objects.values()}
        if sf.target_platform != 7 or sf.header.endian != "<" or actual != expected[name]:
            raise ValueError(f"PC roundtrip mismatch in {name}")
        for obj in sf.objects.values():
            read_tree(obj)
    return data, {"sourceSha256": source_sha, "sha256": sha(data), "format": "offline PC",
                  "objects": {n: len(v) for n, v in expected.items()},
                  "unportedDependencies": {n: sorted(ids) for n, ids in dependencies.items()
                                           if n != "library/unity default resources"},
                  "nativeManagedSchemas": sorted(native_trees),
                  "includesOriginalEmptyCard": bool(empty_card_art),
                  "structuresWithoutPCTemplate": sorted(fallback_types)}


def owner_script(sf, pid):
    record = sf.objects[pid]
    if record.type.name != "MonoScript":
        raise ValueError("managed binding does not point at a MonoScript")
    return read_tree(record)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=NAMES)
    for key in ("root", "ps-layout", "pc-layout", "pc-quest", "pc-global", "pc-app", "out"):
        parser.add_argument("--" + key, required=True, type=Path)
    parser.add_argument("--empty-card-art", type=Path)
    a = parser.parse_args()
    result, report = convert(a.group, a.root, a.ps_layout, a.pc_layout, a.pc_quest, a.pc_global, a.pc_app,
                             a.empty_card_art)
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / (NAMES[a.group][0] + ".unity3d")).write_bytes(result)
    (a.out / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
