"""Convert the pinned PS3 quest scene to an offline PC WebPlayer candidate.

The companion questAssets bundle and original stq scripts are separate. This
tool never writes into a running server, and structural readback is not a
claim that the scene starts in the original client.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import lzma
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_building_bundle import read_tree, swap_words
from tools.repair_unityweb_lzma import layout, repair

PS3_SHA = "5ad48ca50f346f5f14e55b218f0d9c373d7627093a39915047d3d0620571b2ab"
MAIN = "BuildPlayer-quest"
SHARED = MAIN + ".sharedAssets"
GLOBAL = "customassetbundle-da41e0742f66de848aa2e71ed6ca65e0"
PC_GROUP = {153: 137, 160: 143, 167: 150, 193: 169, 199: 174, 200: 175}
GLOBAL_IDS = {77: 40, 80: 43, 113: 107, 114: 108, 117: 112, 118: 113, **PC_GROUP}
HUD = ("advanceRatio_", "itemBinder_", "deckConstructor_", "titleText_", "backPoliticButton_",
       "backButton_", "deckButton_", "raidBossButton_", "itemButton_", "questButton_", "autoSkip_",
       "fullAutoSkip_", "cautionPrefab_")
PTRL = {"SceneStarter": 24, "SceneResources": 23, "UIManager": 27}
HEAD_FIELDS = {"m_GameObject", "m_Enabled", "m_Script", "m_Name"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path, platform):
    import UnityPy
    bundle, = UnityPy.load(path.read_bytes()).files.values()
    for sf in bundle.files.values():
        if not sf.objects or sf.header.version != 9 or sf.target_platform != platform:
            raise ValueError(f"unexpected source layout: {path.name}, {sf.name}")
        if sf.header.endian != (">" if platform == 10 else "<"):
            raise ValueError("unexpected source byte order")
    return bundle


def read_managed(obj, nodes):
    from ctypes import c_uint32
    from UnityPy.helpers.TypeTreeHelper import read_value
    obj.reset()
    tree = read_value(nodes, obj, c_uint32(0))
    if obj.Position - obj.byte_start != obj.byte_size:
        raise ValueError(f"layout does not consume {obj.path_id}: {obj.Position - obj.byte_start}/{obj.byte_size}")
    return tree


def node(n, **changes):
    from UnityPy.helpers.TypeTreeHelper import TypeTreeNode
    properties = {f: getattr(n, f) for f in (
        "m_Level", "m_Type", "m_Name", "m_ByteSize", "m_Index", "m_TypeFlags", "m_Version", "m_MetaFlag")}
    return TypeTreeNode(**(properties | changes))


def subgroup(nodes, name):
    start = next(i for i, n in enumerate(nodes) if n.m_Level == 1 and n.m_Name == name)
    end = next((i for i in range(start + 1, len(nodes)) if nodes[i].m_Level == 1), len(nodes))
    return list(nodes[start:end])


def mesh_pc(tree):
    v = tree["m_VertexData"]
    streams = [v[f"m_Streams[{i}]"] for i in range(4)]
    if tree["m_MeshCompression"] or tree["m_Skin"] or tree["m_BindPose"]:
        raise ValueError("not a static, uncompressed quest mesh")
    if any(p["m_NumItems"] for p in tree["m_CompressedMesh"].values()):
        raise ValueError("packed quest mesh is not supported")
    if streams[0]["offset"] or any(s["offset"] or s["stride"] or s["channelMask"] for s in streams[1:]):
        raise ValueError("unexpected quest mesh streams")
    indices, vertices = bytes(tree["m_IndexBuffer"]), bytes(v["m_DataSize"])
    count = v["m_VertexCount"]
    if not count:
        if indices or vertices or (v["m_CurrentChannels"], streams[0]["channelMask"], streams[0]["stride"]) != (0, 63, 60):
            raise ValueError("unexpected placeholder mesh")
        return
    if (v["m_CurrentChannels"], streams[0]["channelMask"], streams[0]["stride"]) != (15, 15, 36):
        raise ValueError("unexpected quest vertex layout")
    if len(vertices) != count * 36 or len(indices) % 2 or any(x >= count for x, in struct.iter_unpack(">H", indices)):
        raise ValueError("quest mesh buffer size or index mismatch")
    tree["m_IndexBuffer"] = list(swap_words(indices, 2))
    # Three position floats, three normal floats, four Color32 bytes, two UV floats.
    v["m_DataSize"] = b"".join(swap_words(vertices[i:i + 24], 4) + vertices[i + 24:i + 28]
                              + swap_words(vertices[i + 28:i + 36], 4)
                              for i in range(0, len(vertices), 36))


def remap(value, mapping, local, seen):
    if isinstance(value, dict):
        if set(value) == {"m_FileID", "m_PathID"}:
            source = (value["m_FileID"], value["m_PathID"])
            if source == (0, 0):
                return
            if source[0] == 0:
                if source[1] not in local:
                    raise ValueError(f"bad local reference: {source}")
            else:
                target = mapping[source]
                seen[source] = target
                value["m_FileID"], value["m_PathID"] = target
        else:
            for child in value.values():
                remap(child, mapping, local, seen)
    elif isinstance(value, (list, tuple)):
        for child in value:
            remap(child, mapping, local, seen)


def write_node(w, nodes):
    for i, n in enumerate(nodes):
        children = 0
        for child in nodes[i + 1:]:
            if child.m_Level <= n.m_Level:
                break
            if child.m_Level == n.m_Level + 1:
                children += 1
        w.write_string_to_null(n.m_Type)
        w.write_string_to_null(n.m_Name)
        w.write_bytes(struct.pack("<6i", n.m_ByteSize, i, n.m_TypeFlags, n.m_Version, n.m_MetaFlag, children))


def serialize(objects, externals):
    from UnityPy.streams import EndianBinaryWriter
    m, d = EndianBinaryWriter(endian="<"), EndianBinaryWriter(endian="<")
    # Unity 3.5 looks up path IDs in order. Keep the AssetBundle index (ID 1)
    # ahead of its prefabs even when the caller constructs it last.
    objects = sorted(objects, key=lambda entry: entry[0])
    m.write_string_to_null("3.5.6f4")
    m.write_int(7)
    schemas = {}
    for _, type_id, _, nodes, _ in objects:
        schemas.setdefault(type_id, nodes)
    m.write_int(len(schemas))
    for type_id, nodes in sorted(schemas.items()):
        m.write_int(type_id)
        write_node(m, nodes)
    m.write_int(0)  # 32-bit path IDs
    m.write_int(len(objects))
    for path_id, type_id, cls_id, _, raw in objects:
        m.write_bytes(struct.pack("<iIIiHH", path_id, d.Position, len(raw), type_id, cls_id, 0))
        d.write_bytes(raw)
        d.align_stream(8)
    m.write_int(len(externals))
    for external in externals:
        external.write(type("Header", (), {"version": 9})(), m)
    m.write_string_to_null("")
    off = (20 + len(m.bytes) + 15) & ~15
    return (struct.pack(">IIII", len(m.bytes), off + len(d.bytes), 9, off)
            + b"\0" * 4 + m.bytes).ljust(off, b"\0") + d.bytes


def pack(nodes, template):
    prefix_len, _, _ = layout(template)
    prefix = bytearray(template[:prefix_len])
    index_len = (4 + sum(len(name) + 9 for name in nodes) + 3) & ~3
    index = bytearray(struct.pack(">I", len(nodes)))
    payload = bytearray()
    for name, raw in nodes.items():
        index += name.encode("ascii") + b"\0" + struct.pack(">II", index_len + len(payload), len(raw))
        payload += raw
    plain = index.ljust(index_len, b"\0") + payload
    comp = lzma.compress(plain, format=lzma.FORMAT_ALONE,
                         filters=[dict(id=lzma.FILTER_LZMA1, dict_size=1 << 23, lc=3, lp=0, pb=2)])
    pos = prefix.index(0, prefix.index(0, 13) + 1) + 1
    total = len(prefix) + len(comp)
    struct.pack_into(">8I", prefix, pos, total, len(prefix), 1, 1, len(comp), len(plain), total, index_len)
    result, _ = repair(bytes(prefix) + comp)
    return result


def script_key(value):
    return value["m_AssemblyName"], value["m_Namespace"], value["m_ClassName"]


def convert(ps3_path, pc_select_path, pc_global_path, pc_audio_path, pc_app_path):
    import UnityPy
    from PIL import Image
    from UnityPy.helpers.TypeTreeHelper import write_typetree
    from UnityPy.streams import EndianBinaryWriter
    if sha(ps3_path.read_bytes()) != PS3_SHA:
        raise ValueError("PS3 input is not the verified original quest scene")
    src = load(ps3_path, 10)
    select, shared = load(pc_select_path, 7), src.files[SHARED]
    global_sf, = load(pc_global_path, 7).files.values()
    if global_sf.name.casefold() != GLOBAL:
        raise ValueError("unexpected PC global asset signature")
    global_objects = {
        40: ("Material", "12_rpm_0"), 43: ("Material", "font"), 64: ("Texture2D", "font12_18_24"),
        107: ("Shader", "PydFont_R"), 108: ("Shader", "PydFont_G"),
        110: ("Shader", "Sprite Vertex Colored, Fast"), 112: ("TextAsset", "12_rpm.fnt"),
        113: ("TextAsset", "18_syo.fnt"), 137: ("MonoScript", "AsyncLoadSprite"),
        143: ("MonoScript", "PackedSprite"), 150: ("MonoScript", "UIProgressBar"),
        169: ("MonoScript", "SimpleSprite"), 174: ("MonoScript", "SpriteText"), 175: ("MonoScript", "UIButton"),
    }
    for path_id, (kind, name) in global_objects.items():
        obj = global_sf.objects[path_id]
        if obj.type.name != kind or read_tree(obj)[0]["m_Name"] != name:
            raise ValueError(f"unexpected PC global resource: {path_id} should be {kind}/{name}")
    audio = load(pc_audio_path, 7)
    native = {}
    scripts, managed = {}, {}
    identity = lambda obj: struct.unpack_from("<ii", obj.get_raw_data(), 12)
    for sf in (global_sf, *select.files.values(), *audio.files.values()):
        for obj in sf.objects.values():
            if not obj.serialized_type or not obj.serialized_type.nodes:
                continue
            if obj.type.name == "MonoBehaviour":
                local = {script_id: name for name, script_id in PTRL.items()}
                if sf is global_sf:
                    fid, pid = identity(obj)
                    if fid != 0 or pid not in PC_GROUP.values():
                        continue
                    script = read_tree(sf.objects[pid])[0]
                    managed[script["m_ClassName"]] = obj
                elif sf.name == "BuildPlayer-questSelect":
                    fid, pid = identity(obj)
                    if fid == 1 and pid in local:
                        managed[local[pid]] = obj
            else:
                native.setdefault(obj.class_id, obj.get_typetree_nodes())
    for obj in UnityPy.load(pc_app_path.read_bytes()).objects:
        if obj.type.name == "MonoScript":
            fields = read_tree(obj)[0]
            scripts[script_key(fields)] = fields
    local_script = {o.path_id: read_tree(o)[0] for o in shared.objects.values() if o.type.name == "MonoScript"}
    for pid in PC_GROUP.values():
        fields = read_tree(global_sf.objects[pid])[0]
        scripts[script_key(fields)] = fields
    names = {p: v["m_ClassName"] for p, v in local_script.items()}
    head = managed["SceneStarter"].get_typetree_nodes()[:len(managed["SceneStarter"].get_typetree_nodes()) - 1]
    pp = subgroup(managed["AsyncLoadSprite"].get_typetree_nodes(), "camera_")
    def pointer_fields(fields):
        nodes = list(head)
        for name, typ in fields:
            nodes += [node(n, m_Type=typ, m_Name=name) if j == 0 else n for j, n in enumerate(pp)]
        return nodes
    created = {name: head for name in ("ScriptButtonEventMediator", "QuestDeckConstructor",
                                       "QuestShowItemBinder", "QuestAdvanceRatio")}
    created["Quest"] = pointer_fields([("hudController_", "PPtr<$QuestHUDController>")])
    created["QuestHUDController"] = pointer_fields(zip(HUD, [
        "PPtr<$QuestAdvanceRatio>", "PPtr<$QuestShowItemBinder>", "PPtr<$QuestDeckConstructor>", "PPtr<$SpriteText>",
        *(["PPtr<$UIButton>"] * 6), "PPtr<$ToggleButton>", "PPtr<$ToggleButton>", "PPtr<$GameObject>",
    ]))
    main_pc = select.files["BuildPlayer-questSelect"]
    shared_pc = select.files["BuildPlayer-questSelect.sharedAssets"]
    link = copy.copy(main_pc.externals[0])
    link.path = SHARED.casefold()
    mapped_main = {(1, i): (1, i) for i in shared.objects} | {(2, a): (2, b) for a, b in GLOBAL_IDS.items()}
    mapped_shared = {(1, 30): (1, 30), (1, 34): (1, 34), (2, 246): (2, 64), (3, 330): (2, 110)}
    mapped_shared.update({(4, a): (2, b) for a, b in GLOBAL_IDS.items()})
    for _, (_, pid) in mapped_shared.items():
        if pid not in (30, 34) and pid not in global_sf.objects:
            raise ValueError("unresolved native global resource")
    built, refs, texture_proof, expected = {}, {}, [], {}
    for sf in src.files.values():
        is_shared = sf.name == SHARED
        linked = shared_pc.externals if is_shared else [link, main_pc.externals[1]]
        mappings = mapped_shared if is_shared else mapped_main
        rewritten, objects, component_types = {}, [], {}
        for obj in sf.objects.values():
            kind = obj.type.name
            type_id = obj.type_id
            schema = native.get(obj.class_id) if kind != "MonoBehaviour" else None
            if kind == "MonoBehaviour":
                fid, pid = struct.unpack_from(">ii", obj.get_raw_data(), 12)
                name = names[pid] if fid == 1 else read_tree(global_sf.objects[PC_GROUP[pid]])[0]["m_ClassName"]
                type_id = component_types.setdefault(name, -(len(component_types) + 1))
                if name in created:
                    schema = created[name]
                    tree = read_managed(obj, schema)
                else:
                    sample = managed[name]
                    schema = sample.get_typetree_nodes()
                    if name == "SpriteText":
                        i = next(i for i, n in enumerate(schema) if n.m_Level == 1 and n.m_Name == "isClone")
                        source_nodes = schema[:i] + [node(schema[i], m_Name="endlineWhiteSpace")] + schema[i:]
                        tree = read_managed(obj, source_nodes)
                        del tree["endlineWhiteSpace"]
                    elif name == "AsyncLoadSprite":
                        tree = read_managed(obj, head)
                        defaults = read_tree(sample)[0]
                        tree.update({n: v for n, v in defaults.items() if n not in HEAD_FIELDS})
                    else:
                        tree = read_managed(obj, schema)
            else:
                tree, _ = read_tree(obj)
                if schema is None:
                    raise ValueError(f"class absent from PC references: {kind}")
                if kind == "Mesh":
                    mesh_pc(tree)
                elif kind == "MonoScript":
                    tree = scripts[script_key(tree)]
                elif kind == "Texture2D":
                    image = obj.read().image.convert("RGBA")
                    data = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
                    tree.update(m_TextureFormat=4, m_MipMap=False, m_CompleteImageSize=len(data))
                    tree["image data"] = data
                    texture_proof.append((obj.path_id, sha(image.tobytes())))
                elif kind == "AssetBundle":
                    compat = []
                    global_bundle = next(o for o in global_sf.objects.values() if o.type.name == "AssetBundle")
                    classes = {x["first"]: x["second"] for x in read_tree(global_bundle)[0]["m_ClassCompatibility"]}
                    used = {script_key(s) for s in local_script.values()}
                    used.update(script_key(read_tree(global_sf.objects[p])[0]) for p in PC_GROUP.values())
                    for key in sorted(used):
                        asm, ns, cls = key
                        compat.append(dict(assemblyName=asm, nameSpace=ns, className=cls,
                                           hash=scripts[key]["m_PropertiesHash"]))
                    tree["m_ScriptCompatibility"] = compat
                    tree["m_ClassCompatibility"] = [
                        {"first": row["first"], "second": classes.get(row["first"], row["second"])}
                        for row in tree["m_ClassCompatibility"]
                    ]
            tree = copy.deepcopy(tree)
            remap(tree, mappings, sf.objects, rewritten)
            raw = write_typetree(tree, schema, EndianBinaryWriter(endian="<")).bytes
            objects.append((obj.path_id, type_id, obj.class_id, schema, raw))
        expected[sf.name] = {o[0]: (o[1], o[2], sha(o[4])) for o in objects}
        built[sf.name] = serialize(objects, linked)
        refs[sf.name] = [list(old + new) for old, new in sorted(rewritten.items())]
    result = pack(built, pc_select_path.read_bytes())
    check, = UnityPy.load(result).files.values()
    for sf in check.files.values():
        if sf.target_platform != 7 or sf.header.endian != "<":
            raise ValueError("PC tag readback failed")
        observed = {o.path_id: (o.type_id, o.class_id, sha(o.get_raw_data())) for o in sf.objects.values()}
        if observed != expected[sf.name]:
            raise ValueError("object inventory or bytes changed on readback")
        for obj in sf.objects.values():
            try:
                read_tree(obj)
            except ValueError as exc:
                raise ValueError(f"{sf.name} object {obj.path_id}, type {obj.type_id}: {exc}") from exc
    for pid, digest in texture_proof:
        if sha(check.files[SHARED].objects[pid].read().image.tobytes()) != digest:
            raise ValueError("texture pixel verification failed")
    hud = read_tree(check.files[MAIN].objects[245])[0]
    scene = check.files[MAIN]
    expected_button = {"m_FileID": 0, "m_PathID": 226}
    if (scene.objects[245].byte_size != 128 or hud["questButton_"] != expected_button
            or read_tree(scene.objects[226])[0]["m_Script"] != {"m_FileID": 2, "m_PathID": 175}
            or read_tree(scene.objects[212])[0]["hudController_"] != {"m_FileID": 0, "m_PathID": 245}
            or read_tree(scene.objects[203])[0]["assetFileName_"] != ["questAssets.unity3d"]):
        raise ValueError("native story scene bindings were lost")
    return result, {"format": "PC UnityWeb candidate", "engineVerified": False, "sha256": sha(result),
                    "inputs": {name: sha(path.read_bytes()) for name, path in (
                        ("ps3", ps3_path), ("pc-select", pc_select_path), ("pc-global", pc_global_path),
                        ("pc-audio", pc_audio_path), ("pc-app", pc_app_path),
                    )},
                    "objects": {n: len(records) for n, records in expected.items()}, "references": refs,
                    "textures": texture_proof, "hud": {name: hud[name] for name in HUD},
                    "missing": ["questAssets (PC port pending)", "stq0_main", "stq0_100010", "stq0_300001"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    keys = ("ps3", "pc-select", "pc-global", "pc-audio", "pc-app", "out")
    for key in keys:
        parser.add_argument("--" + key, required=True, type=Path)
    args = parser.parse_args()
    result, proof = convert(*(getattr(args, k.replace("-", "_")) for k in keys[:-1]))
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "9af398d6690a6b65145bb21a3c61ac43.unity3d").write_bytes(result)
    (args.out / "manifest.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
