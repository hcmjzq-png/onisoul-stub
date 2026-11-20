"""Build a PC compatibility script for tutorial 14 using installed dialogue keys."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.minijson import parse_json_document
from tools.build_quest_collection_icons import asset_id, table
from tools.port_legacy_media import pack_pc, repack_serialized
from tools.repair_unityweb_lzma import layout


MISSION = "po_mission_00024"
SCRIPT = "scr1_000024"
TEMPLATE = "scr1_000485"
TABLE_SCENE = "1243ea6aa67634ac98d68538c84a3a84.unity3d"
ENTER_KEYS = tuple(f"POM_MES_000024_01_{i:03}" for i in range(1, 4))
MENU_KEYS = tuple(f"POM_MES_000024_02_{i:03}" for i in range(1, 5))
EXIT_KEYS = tuple(f"POM_MES_000024_03_{i:03}" for i in range(1, 10))


def script(part: str) -> str:
    name = f"{SCRIPT}_{part}"

    def node(tag, value=None, *, ident=None):
        element = ET.Element(tag, {"line": "1", "prefix": name})
        if ident is not None:
            element.set("id", ident)
        element.text = value
        return element

    def call(ident, *args):
        command = node("call", ident=ident)
        if args:
            values = node("value_list")
            values.extend(args)
            command.append(values)
        return command

    def message(key):
        return call("politic_getNavigatorMessage", node("string", key))

    root = ET.Element("root")
    flow = ET.SubElement(root, name)
    if part == "02":
        event = node("function", ident=f"{name}:event")
        block = node("block")
        block.append(call("politic_waitEnterMenu", *(message(key) for key in MENU_KEYS)))
        event.extend([node("identifire_list"), block])
        flow.append(event)
    else:
        portrait = node("assign", ident="navigator")
        portrait.append(call("loadChara", node("string", "chara1_C"), call("game_getMyNavigator")))
        flow.extend([
            call("loadLayout", node("string", "talk_layout")),
            call("setMessageSpped", node("var", "MessageSlow")),
            call("setVisibleMessage", node("boolean", "false")),
            portrait,
            call("waitLoad"),
            call("setVisible", node("var", "navigator"), node("boolean", "true")),
            call("setVisibleMessage", node("boolean", "true")),
        ])
        keys = ENTER_KEYS if part == "01" else EXIT_KEYS[:-1]
        flow.extend(call("politic_drawNavigatorMessage", node("string", key)) for key in keys)
        if part == "01":
            flow.extend([node("import", ident=f"{SCRIPT}_02"), call(f"{SCRIPT}_02:event")])
        else:
            flow.extend([
                call("politic_playNavigatorVoice", node("string", "Admiration")),
                call("politic_waitRewardMenu", message(EXIT_KEYS[-1])),
            ])
        flow.extend([
            call("setVisibleMessage", node("boolean", "false")),
            call("removeObject", node("var", "navigator")),
        ])
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def verify_client_inputs(tables: Path, bundles: Path) -> int:
    import UnityPy

    row = table(tables, "politicMission")[MISSION]
    if (row["iconFileName"], row["iconIndex"], row["enterScript"], row["exitScript"]) != (
        "mission_000002", 14, SCRIPT + "_01", SCRIPT + "_03",
    ):
        raise ValueError("unexpected PC tutorial 14 table row")

    filenames = {row["messageFile"] + ".json" for row in table(tables, "navigator").values()
                 if row["messageFile"] != "none"}
    scene = UnityPy.load(str(bundles / "scene" / TABLE_SCENE))
    tables_seen = set()
    for obj in scene.objects:
        if obj.type.name != "TextAsset":
            continue
        asset = obj.read()
        if asset.m_Name not in filenames:
            continue
        rows = parse_json_document(bytes(asset.m_Script).decode("utf-8-sig"))["naviMessage"]
        for key in ENTER_KEYS + MENU_KEYS + EXIT_KEYS:
            if not rows.get(key, {}).get("tw"):
                raise ValueError(f"missing client message {asset.m_Name}: {key}")
        tables_seen.add(asset.m_Name)
    if tables_seen != filenames:
        raise ValueError(f"missing client navigator tables: {sorted(filenames - tables_seen)}")
    return len(tables_seen)


def build(template: bytes) -> bytes:
    import UnityPy

    payloads = {}
    for part in ("01", "02", "03"):
        name = f"{SCRIPT}_{part}"
        payloads[name] = script(part)
        payloads[name + "_stringtable.json"] = '{"message":{}}'

    assets = list(UnityPy.load(template).objects)
    container, = [obj for obj in assets if obj.type.name == "AssetBundle"]
    text_assets = [obj for obj in assets if obj.type.name == "TextAsset"]
    if len(text_assets) != len(payloads) or len(assets) != len(text_assets) + 1:
        raise ValueError("unexpected PC script template objects")

    names, replacements = {}, {}
    for obj in text_assets:
        tree = obj.read_typetree()
        old_name = tree["m_Name"]
        if not old_name.startswith(TEMPLATE + "_"):
            raise ValueError(f"unexpected template asset name: {old_name}")
        name = SCRIPT + old_name[len(TEMPLATE):]
        names[old_name] = name
        tree.update(m_Name=name, m_Script=payloads[name], m_PathName="")
        replacements[obj.path_id] = obj.save_typetree(tree)

    tree = container.read_typetree()
    if {name for name, _ in tree["m_Container"]} != names.keys():
        raise ValueError("unexpected PC script template bindings")
    tree["m_Container"] = [(names[name], ref) for name, ref in tree["m_Container"]]
    replacements[container.path_id] = container.save_typetree(tree)
    serialized = container.assets_file
    body = repack_serialized(serialized.reader.bytes, serialized, replacements)
    offset, _, _ = layout(template)
    blob = pack_pc(template[:offset], "CustomAssetBundle-" + hashlib.md5(body).hexdigest(), body)

    readback = {}
    for name, ptr in UnityPy.load(blob).container.items():
        asset = ptr.read()
        if ptr.get_obj().type.name != "TextAsset" or int(ptr.get_obj().platform) != 7 or asset.m_Name != name:
            raise ValueError(f"incorrect PC TextAsset binding: {name}")
        readback[name] = bytes(asset.m_Script).decode("utf-8")
    if readback != payloads:
        raise ValueError("published script content did not roundtrip")
    return blob


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tables", "bundles", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    navigator_count = verify_client_inputs(args.tables, args.bundles)
    template = args.bundles / "scr" / (asset_id(TEMPLATE) + ".unity3d")
    blob = build(template.read_bytes())
    output = args.out / "scr" / (asset_id(SCRIPT) + ".unity3d")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(blob)
    print(f"{output.relative_to(args.out)} SHA-256 {hashlib.sha256(blob).hexdigest()}")
    print(f"Verified six PC TextAssets and {navigator_count} installed navigator message tables")


if __name__ == "__main__":
    main()
