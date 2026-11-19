"""Convert the original PS3 battle replay return scene to the PC WebPlayer format."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_building_bundle import read_tree
from tools.port_ps3_quest_scene import HEAD_FIELDS, load, pack, read_managed, remap, serialize, sha

KEY = "00a497ac4a5104413178b565d9ebe4f2"
SOURCE = "1668e7923fc1688b2818c59f43339904a12c627b13adc71b7ab40f04563baccd"
SCENE = "BuildPlayer-vsBattleReturn"
SHARED = SCENE + ".sharedAssets"
SCRIPT = "BattleTransToBattle"


def convert(ps3: Path, pc_quest: Path, pc_app: Path) -> tuple[bytes, dict]:
    import UnityPy
    from UnityPy.helpers.TypeTreeHelper import write_typetree
    from UnityPy.streams import EndianBinaryWriter

    if sha(ps3.read_bytes()) != SOURCE:
        raise ValueError("unexpected PS3 battle return scene")
    source = load(ps3, 10).files
    if set(source) != {SCENE, SHARED} or len(source[SHARED].objects) != 3:
        raise ValueError("unexpected battle return scene inventory")

    template = load(pc_quest, 7).files
    guide = template["BuildPlayer-quest"]
    header_type = guide.objects[242].get_typetree_nodes()
    if {field.m_Name for field in header_type if field.m_Level == 1} != HEAD_FIELDS:
        raise ValueError("need a header-only PC managed component")
    schemas = {obj.class_id: obj.get_typetree_nodes() for sf in template.values()
               for obj in sf.objects.values() if obj.type.name != "MonoBehaviour"}
    original_script = read_tree(source[SHARED].objects[3])[0]
    key = tuple(original_script[field] for field in ("m_AssemblyName", "m_Namespace", "m_ClassName"))
    if key[2] != SCRIPT:
        raise ValueError("unexpected PS3 return component")
    pc_scripts = [read_tree(obj)[0] for obj in UnityPy.load(pc_app.read_bytes()).objects
                  if obj.type.name == "MonoScript"]
    pc_script, = [script for script in pc_scripts
                  if tuple(script[field] for field in ("m_AssemblyName", "m_Namespace", "m_ClassName")) == key]
    link = copy.copy(guide.externals[0])
    link.path = SHARED.casefold()
    external_map = {(1, 3): (1, 3)}
    converted = {}
    for name, sf in source.items():
        objects = []
        for obj in sf.objects.values():
            kind = obj.type.name
            if kind == "MonoBehaviour":
                nodes, type_id = header_type, -1
                value = read_managed(obj, nodes)
                if value["m_Script"] != {"m_FileID": 1, "m_PathID": 3}:
                    raise ValueError("unexpected return script reference")
            else:
                nodes, type_id = schemas[obj.class_id], obj.class_id
                value = pc_script if kind == "MonoScript" else read_tree(obj)[0]
                if kind == "AssetBundle":
                    value["m_ScriptCompatibility"] = [
                        {"assemblyName": key[0], "nameSpace": key[1], "className": key[2],
                         "hash": pc_script["m_PropertiesHash"]},
                    ]
                    pc_bundle = template["BuildPlayer-quest.sharedAssets"].objects[2]
                    compatible = {entry["first"]: entry for entry in read_tree(pc_bundle)[0]["m_ClassCompatibility"]}
                    value["m_ClassCompatibility"] = [compatible[entry["first"]]
                        for entry in value["m_ClassCompatibility"] if entry["first"] in compatible]
            remap(value, external_map if name == SCENE else {}, sf.objects, {})
            data = write_typetree(value, nodes, EndianBinaryWriter(endian="<")).bytes
            objects.append((obj.path_id, type_id, obj.class_id, nodes, data))
        converted[name] = serialize(objects, [link] if name == SCENE else [])
    result = pack(converted, pc_quest.read_bytes())
    check, = UnityPy.load(result).files.values()
    for name, node in check.files.items():
        if int(node.target_platform) != 7 or node.header.endian != "<" or set(node.objects) != set(source[name].objects):
            raise ValueError("converted node inventory or platform differs")
        for obj in node.objects.values():
            read_tree(obj)
    return result, {"source": SOURCE, "sha256": sha(result), "script": SCRIPT,
                    "objects": {name: len(sf.objects) for name, sf in check.files.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("ps3", "pc-quest", "pc-app", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result, proof = convert(args.ps3, args.pc_quest, args.pc_app)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / (KEY + ".unity3d")).write_bytes(result)
    (args.out / "manifest.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
