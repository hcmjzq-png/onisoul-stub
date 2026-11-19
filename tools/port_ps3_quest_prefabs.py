"""Port the native story HUD prefabs and first event effect from PS3 into PC questAssets.

Builds only the documented subset. The output is an offline candidate, not an
original PC archive and not a complete story, treasure or battle effects pack.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_building_bundle import read_tree, swap_words
from tools.port_ps3_quest_scene import (
    GLOBAL, GLOBAL_IDS, HEAD_FIELDS, load, node, pack, read_managed, remap, serialize, sha, subgroup,
)

SOURCE_SHA = "47044ff1c0f5f96175c4d5c920ce51449fbb7ba0110e4e969d53109528b099eb"
KEY = "4313f662f5b84d1790d4e7f1836b45ad"
ROOTS = ("autoskip", "fullautoskip", "caution", "letterboxmask", "itemicon",
         "iconimage", "questbutton", "eff1_100004_01", "eff1_100004_02", "eff1_100005_01")
CAUTION_TEXTS = (
    "textCaution_", "textItemRoot_", "textMissionPoint_", "textGoldKey_", "textSilverKey_",
    "textBronzeKey_", "textTreasureBoxRoot_", "textGoldTreasureBoxA_", "textGoldTreasureBoxB_",
    "textGoldTreasureBoxC_", "textSilverTreasureBoxA_", "textSilverTreasureBoxB_", "textSilverTreasureBoxC_",
    "textBronzeTreasureBoxA_", "textBronzeTreasureBoxB_", "textBronzeTreasureBoxC_", "textCharacterExplain_",
    "textCharacterAmount_", "textInBoxExplain_", "textInBoxAmount_", "textDecideButton_", "textCancelButton_",
)


def effect_mesh(tree):
    v = tree["m_VertexData"]
    streams = [v[f"m_Streams[{i}]"] for i in range(4)]
    raw, idx = bytes(v["m_DataSize"]), bytes(tree["m_IndexBuffer"])
    count = v["m_VertexCount"]
    if (tree["m_MeshCompression"] or tree["m_Skin"] or tree["m_BindPose"]
            or any(x["m_NumItems"] for x in tree["m_CompressedMesh"].values())
            or (v["m_CurrentChannels"], streams[0]["channelMask"], streams[0]["stride"]) != (11, 11, 32)
            or streams[0]["offset"] or any(s["offset"] or s["stride"] or s["channelMask"] for s in streams[1:])
            or count <= 0 or len(raw) != count * 32 or len(idx) % 2
            or any(i >= count for i, in struct.iter_unpack(">H", idx))):
        raise ValueError("unverified event effect mesh")
    v["m_DataSize"] = swap_words(raw, 4)
    tree["m_IndexBuffer"] = list(swap_words(idx, 2))


def convert(ps3, pc_global, pc_app, pc_quest, pc_anim, pc_audio):
    import UnityPy
    from PIL import Image
    from UnityPy.helpers.TypeTreeHelper import write_typetree
    from UnityPy.streams import EndianBinaryWriter

    if sha(ps3.read_bytes()) != SOURCE_SHA:
        raise ValueError("unrecognized PS3 questAssets")
    source, = load(ps3, 10).files.values()
    glob, = load(pc_global, 7).files.values()
    if glob.name.casefold() != GLOBAL:
        raise ValueError("unexpected PC global asset signature")
    scene = load(pc_quest, 7)
    if "BuildPlayer-quest" not in scene.files:
        raise ValueError("use the verified converted quest scene as schema input")
    anim = load(pc_anim, 7)
    audio = load(pc_audio, 7)
    idx = {o.class_id: o.get_typetree_nodes() for sf in (*scene.files.values(), *anim.files.values(),
            *audio.files.values(), glob) for o in sf.objects.values() if o.type.name != "MonoBehaviour"
            and o.serialized_type and o.serialized_type.nodes}
    scripts = {}
    for obj in UnityPy.load(pc_app.read_bytes()).objects:
        if obj.type.name == "MonoScript":
            record = read_tree(obj)[0]
            scripts[record["m_ClassName"]] = record
    game = scene.files["BuildPlayer-quest"]
    # Use the same PC layouts already verified against every object in the main scene.
    native = {}
    global_schemas = GLOBAL_IDS | {79: 42, 112: 106, 116: 111}
    for o in game.objects.values():
        if o.type.name != "MonoBehaviour":
            continue
        fid, pid = struct.unpack_from("<ii", o.get_raw_data(), 12)
        if fid == 2:
            native[pid] = read_tree(glob.objects[pid])[0], o.get_typetree_nodes()
    head = game.objects[242].get_typetree_nodes()
    pptr = subgroup(native[137][1], "camera_")
    # Array payload consists of two PPtr<UIButton> entries in each source button.
    # Clone a real PC object-pointer vector layout rather than inventing metadata.
    pptr_vector = subgroup(game.objects[202].get_typetree_nodes(), "uiCameras")
    step = next(i for i, x in enumerate(pptr_vector) if x.m_Name == "data")
    arr = [node(x, m_Name="buttons_") if i == 0 else x for i, x in enumerate(pptr_vector[:step])]
    arr += [node(x, m_Level=x.m_Level + 2, **({"m_Name": "data", "m_Type": "PPtr<$UIButton>"} if i == 0 else {}))
            for i, x in enumerate(pptr)]
    toggle_nodes = head + arr

    def ptr_fields(names):
        return head + [node(n, m_Name=name, m_Type=kind) if i == 0 else n
                       for name, kind in names for i, n in enumerate(pptr)]
    caution_nodes = ptr_fields([("maskObj_", "PPtr<$BoxCollider>"),
                                *((name, "PPtr<$SpriteText>") for name in CAUTION_TEXTS)])
    global_maps = {(2, a): (2, b) for a, b in global_schemas.items()}
    global_maps.update({(1, 330): (2, 110), (3, 246): (2, 64), (4, 30): (1, 30), (4, 34): (1, 34)})
    ab, = [o for o in source.objects.values() if o.type.name == "AssetBundle"]
    original = read_tree(ab)[0]
    tree = {**original, "m_Container": [], "m_PreloadTable": []}
    chosen = {}
    global_ab, = [o for o in glob.objects.values() if o.type.name == "AssetBundle"]
    global_compat = {r["first"]: r["second"] for r in read_tree(global_ab)[0]["m_ClassCompatibility"]}
    for name, entry in original["m_Container"]:
        if name not in ROOTS:
            continue
        if name in chosen or entry["asset"]["m_FileID"]:
            raise ValueError(f"unverified prefab entry {name}")
        start, size = entry["preloadIndex"], entry["preloadSize"]
        block = original["m_PreloadTable"][start:start + size]
        chosen[name] = entry["asset"]["m_PathID"]
        tree["m_Container"].append((name, {**entry, "preloadIndex": len(tree["m_PreloadTable"])}))
        tree["m_PreloadTable"].extend(block)
    if set(chosen) != set(ROOTS) or tree["m_MainAsset"]["asset"]["m_PathID"] != 0:
        raise ValueError("companion prefab inventory mismatch")
    included = {p["m_PathID"] for p in tree["m_PreloadTable"] if p["m_FileID"] == 0} | {ab.path_id}
    compatibility = {}
    converted, type_ids, bound, textures = [], {}, {}, []
    for path_id in sorted(included):
        obj = source.objects[path_id]
        kind, cls = obj.type.name, obj.class_id
        type_id = cls
        if kind == "MonoBehaviour":
            fid, pid = struct.unpack_from(">ii", obj.get_raw_data(), 12)
            if fid == 0:
                name = read_tree(source.objects[pid])[0]["m_ClassName"]
                schema = {"ToggleButton": toggle_nodes, "QuestFullAutoSkipCaution": caution_nodes}[name]
                data = read_managed(obj, schema)
                fields = scripts[name]
            elif fid == 2:
                fields, schema = native[global_schemas[pid]]
                name = fields["m_ClassName"]
                if name == "SpriteText":
                    i = next(i for i, n in enumerate(schema) if n.m_Level == 1 and n.m_Name == "isClone")
                    data = read_managed(obj, schema[:i] + [node(schema[i], m_Name="endlineWhiteSpace")] + schema[i:])
                    del data["endlineWhiteSpace"]
                elif name == "AsyncLoadSprite":
                    data = read_managed(obj, head)
                    sample = next(o for o in game.objects.values() if o.type.name == "MonoBehaviour"
                                  and struct.unpack_from("<ii", o.get_raw_data(), 12) == (2, 137))
                    data.update({k: v for k, v in read_tree(sample)[0].items() if k not in HEAD_FIELDS})
                else:
                    data = read_managed(obj, schema)
            else:
                raise ValueError("unresolved companion managed component")
            compatibility[name] = fields
            type_id = type_ids.setdefault(name, -(len(type_ids) + 1))
        else:
            schema = idx[cls]
            data = tree if kind == "AssetBundle" else read_tree(obj)[0]
            if kind == "MonoScript":
                data = scripts[data["m_ClassName"]]
            if kind == "Mesh":
                effect_mesh(data)
            if kind == "AnimationClip" and (data["m_Compressed"] or data["m_CompressedRotationCurves"]):
                raise ValueError("unverified compressed effect animation")
            if kind == "Texture2D":
                im = obj.read().image.convert("RGBA")
                pixels = im.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
                data.update(m_TextureFormat=4, m_MipMap=False, m_CompleteImageSize=len(pixels))
                data["image data"] = pixels
                textures.append((path_id, sha(im.tobytes())))
        if kind != "AssetBundle":
            remap(data, global_maps, included, bound)
            converted.append((path_id, type_id, cls, schema,
                              write_typetree(data, schema, EndianBinaryWriter(endian="<")).bytes))
    tree["m_ScriptCompatibility"] = [
        {"className": name, "nameSpace": script["m_Namespace"], "assemblyName": script["m_AssemblyName"],
         "hash": script["m_PropertiesHash"]} for name, script in sorted(compatibility.items())]
    keep = {row[2] for row in converted} | {ab.class_id}
    tree["m_ClassCompatibility"] = [
        {**r, "second": global_compat.get(r["first"], r["second"])}
        for r in tree["m_ClassCompatibility"] if r["first"] in keep]
    remap(tree, global_maps, included, bound)
    converted.append((ab.path_id, ab.class_id, ab.class_id, idx[ab.class_id],
                      write_typetree(tree, idx[ab.class_id], EndianBinaryWriter(endian="<")).bytes))
    rebuilt = serialize(converted, scene.files["BuildPlayer-quest.sharedAssets"].externals)
    archive_name = "CustomAssetBundle-" + hashlib.md5(rebuilt).hexdigest()
    blob = pack({archive_name: rebuilt}, pc_quest.read_bytes())
    check, = UnityPy.load(blob).files.values()
    sf, = check.files.values()
    if sf.target_platform != 7 or sf.header.endian != "<" or list(sf.objects) != sorted(included):
        raise ValueError("companion platform or object readback mismatch")
    for pid, typ, cls, _, raw in converted:
        o = sf.objects[pid]
        if (o.type_id, o.class_id, o.get_raw_data()) != (typ, cls, raw):
            raise ValueError(f"companion object changed: {pid}")
        read_tree(o)
    for pid, expected in textures:
        if sha(sf.objects[pid].read().image.convert("RGBA").tobytes()) != expected:
            raise ValueError(f"texture verification failed: {pid}")
    actual = read_tree(sf.objects[ab.path_id])[0]
    if {k: ent["asset"]["m_PathID"] for k, ent in actual["m_Container"]} != chosen:
        raise ValueError("companion prefab names changed")
    return blob, {"prefabs": chosen, "objects": len(included), "textures": textures, "sha256": sha(blob),
                  "inputs": {name: sha(file.read_bytes()) for name, file in (
                      ("ps3", ps3), ("pc-global", pc_global), ("pc-app", pc_app), ("pc-quest", pc_quest),
                      ("pc-anim", pc_anim), ("pc-audio", pc_audio))},
                  "externalReferences": [list(before + after) for before, after in sorted(bound.items())],
                  "engineVerified": False, "scope": "questAssets startup HUD/first event; no full battle or treasure effects"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    keys = ("ps3", "pc-global", "pc-app", "pc-quest", "pc-anim", "pc-audio", "out")
    for key in keys:
        p.add_argument("--" + key, type=Path, required=True)
    args = p.parse_args()
    data, proof = convert(*(getattr(args, key.replace("-", "_")) for key in keys[:-1]))
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / (KEY + ".unity3d")).write_bytes(data)
    (args.out / "manifest.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
