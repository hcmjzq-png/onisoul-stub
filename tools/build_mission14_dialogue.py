"""Build PC mission compatibility scripts from installed dialogue keys."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.minijson import parse_json_document
from tools.build_quest_collection_icons import asset_id, table
from tools.port_legacy_media import pack_pc, repack_serialized
from tools.repair_unityweb_lzma import layout


TEMPLATE = "scr1_000485"
TABLE_SCENE = "1243ea6aa67634ac98d68538c84a3a84.unity3d"


@dataclass(frozen=True)
class Dialogue:
    mission_number: int
    reward_title: int
    icon_index: int
    enter_pages: int = 3
    icon_file: str = "mission_000002"
    blank_menu_rows: tuple[int, ...] = ()

    @property
    def mission(self) -> str:
        return f"po_mission_{self.mission_number:05}"

    @property
    def script(self) -> str:
        return f"scr1_{self.mission_number:06}"

    def keys(self, part: str, count: int) -> tuple[str, ...]:
        return tuple(f"POM_MES_{self.mission_number:06}_{part}_{i:03}" for i in range(1, count + 1))


TUTORIALS = {14: Dialogue(24, 9, 14), 16: Dialogue(269, 8, 16), 17: Dialogue(13, 3, 17, enter_pages=1)}
COMMISSIONS = {"po_mission_00020": Dialogue(20, 12, -1, icon_file="mission_000016")}


def script(dialogue: Dialogue, part: str) -> str:
    name = f"{dialogue.script}_{part}"

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
        block.append(call("politic_waitEnterMenu", *(
            node("string", "") if i in dialogue.blank_menu_rows else message(key)
            for i, key in enumerate(dialogue.keys("02", 4), 1)
        )))
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
        keys = dialogue.keys(part, dialogue.enter_pages) if part == "01" else dialogue.keys(part, dialogue.reward_title)[:-1]
        flow.extend(call("politic_drawNavigatorMessage", node("string", key)) for key in keys)
        if part == "01":
            menu = f"{dialogue.script}_02"
            flow.extend([node("import", ident=menu), call(f"{menu}:event")])
        else:
            title = dialogue.keys("03", dialogue.reward_title)[-1]
            flow.extend([
                call("politic_playNavigatorVoice", node("string", "Admiration")),
                call("politic_waitRewardMenu", message(title)),
            ])
        flow.extend([
            call("setVisibleMessage", node("boolean", "false")),
            call("removeObject", node("var", "navigator")),
        ])
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def navigator_messages(tables: Path, bundles: Path) -> dict:
    import UnityPy

    filenames = {row["messageFile"] + ".json" for row in table(tables, "navigator").values()
                 if row["messageFile"] != "none"}
    if not filenames:
        raise ValueError("PC navigator table does not name any message files")
    scene = UnityPy.load(str(bundles / "scene" / TABLE_SCENE))
    messages = {}
    for obj in scene.objects:
        if obj.type.name != "TextAsset":
            continue
        asset = obj.read()
        if asset.m_Name not in filenames:
            continue
        messages[asset.m_Name] = parse_json_document(bytes(asset.m_Script).decode("utf-8-sig"))["naviMessage"]
    if messages.keys() != filenames:
        raise ValueError(f"missing client navigator tables: {sorted(filenames - messages.keys())}")
    return messages


def verify_client_inputs(tables: Path, bundles: Path, dialogue: Dialogue) -> int:
    row = table(tables, "politicMission")[dialogue.mission]
    if (row["iconFileName"], row["iconIndex"], row["enterScript"], row["exitScript"]) != (
        dialogue.icon_file, dialogue.icon_index, dialogue.script + "_01", dialogue.script + "_03",
    ):
        raise ValueError(f"unexpected PC mission table row: {dialogue.mission}")

    messages = navigator_messages(tables, bundles)
    keys = dialogue.keys("01", dialogue.enter_pages) + dialogue.keys("02", 4) + dialogue.keys("03", dialogue.reward_title)
    for filename, rows in messages.items():
        for key in keys:
            if not rows.get(key, {}).get("tw"):
                raise ValueError(f"missing client message {filename}: {key}")
    return len(messages)


def build(template: bytes, dialogue: Dialogue) -> bytes:
    import UnityPy

    payloads = {}
    for part in ("01", "02", "03"):
        name = f"{dialogue.script}_{part}"
        payloads[name] = script(dialogue, part)
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
        name = dialogue.script + old_name[len(TEMPLATE):]
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
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--tutorial", type=int, choices=TUTORIALS, default=14)
    selection.add_argument("--commission", choices=COMMISSIONS)
    for name in ("tables", "bundles", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    dialogue = COMMISSIONS[args.commission] if args.commission else TUTORIALS[args.tutorial]
    navigator_count = verify_client_inputs(args.tables, args.bundles, dialogue)
    template = args.bundles / "scr" / (asset_id(TEMPLATE) + ".unity3d")
    blob = build(template.read_bytes(), dialogue)
    output = args.out / "scr" / (asset_id(dialogue.script) + ".unity3d")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(blob)
    print(f"{output.relative_to(args.out)} SHA-256 {hashlib.sha256(blob).hexdigest()}")
    print(f"Verified six PC TextAssets and {navigator_count} installed navigator message tables")


if __name__ == "__main__":
    main()
