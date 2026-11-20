"""Build PC compatibility scripts for tutorials 14 and 16 from installed dialogue keys."""
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
class Tutorial:
    mission_number: int
    reward_title: int

    @property
    def mission(self) -> str:
        return f"po_mission_{self.mission_number:05}"

    @property
    def script(self) -> str:
        return f"scr1_{self.mission_number:06}"

    def keys(self, part: str, count: int) -> tuple[str, ...]:
        return tuple(f"POM_MES_{self.mission_number:06}_{part}_{i:03}" for i in range(1, count + 1))


TUTORIALS = {14: Tutorial(24, 9), 16: Tutorial(269, 8)}


def script(tutorial: Tutorial, part: str) -> str:
    name = f"{tutorial.script}_{part}"

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
        block.append(call("politic_waitEnterMenu", *(message(key) for key in tutorial.keys("02", 4))))
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
        keys = tutorial.keys(part, 3) if part == "01" else tutorial.keys(part, tutorial.reward_title)[:-1]
        flow.extend(call("politic_drawNavigatorMessage", node("string", key)) for key in keys)
        if part == "01":
            menu = f"{tutorial.script}_02"
            flow.extend([node("import", ident=menu), call(f"{menu}:event")])
        else:
            title = tutorial.keys("03", tutorial.reward_title)[-1]
            flow.extend([
                call("politic_playNavigatorVoice", node("string", "Admiration")),
                call("politic_waitRewardMenu", message(title)),
            ])
        flow.extend([
            call("setVisibleMessage", node("boolean", "false")),
            call("removeObject", node("var", "navigator")),
        ])
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def verify_client_inputs(tables: Path, bundles: Path, icon_index: int) -> int:
    import UnityPy

    tutorial = TUTORIALS[icon_index]
    row = table(tables, "politicMission")[tutorial.mission]
    if (row["iconFileName"], row["iconIndex"], row["enterScript"], row["exitScript"]) != (
        "mission_000002", icon_index, tutorial.script + "_01", tutorial.script + "_03",
    ):
        raise ValueError(f"unexpected PC tutorial {icon_index} table row")

    filenames = {row["messageFile"] + ".json" for row in table(tables, "navigator").values()
                 if row["messageFile"] != "none"}
    scene = UnityPy.load(str(bundles / "scene" / TABLE_SCENE))
    keys = tutorial.keys("01", 3) + tutorial.keys("02", 4) + tutorial.keys("03", tutorial.reward_title)
    tables_seen = set()
    for obj in scene.objects:
        if obj.type.name != "TextAsset":
            continue
        asset = obj.read()
        if asset.m_Name not in filenames:
            continue
        rows = parse_json_document(bytes(asset.m_Script).decode("utf-8-sig"))["naviMessage"]
        for key in keys:
            if not rows.get(key, {}).get("tw"):
                raise ValueError(f"missing client message {asset.m_Name}: {key}")
        tables_seen.add(asset.m_Name)
    if tables_seen != filenames:
        raise ValueError(f"missing client navigator tables: {sorted(filenames - tables_seen)}")
    return len(tables_seen)


def build(template: bytes, tutorial: Tutorial) -> bytes:
    import UnityPy

    payloads = {}
    for part in ("01", "02", "03"):
        name = f"{tutorial.script}_{part}"
        payloads[name] = script(tutorial, part)
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
        name = tutorial.script + old_name[len(TEMPLATE):]
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
    parser.add_argument("--tutorial", type=int, choices=TUTORIALS, default=14)
    for name in ("tables", "bundles", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    tutorial = TUTORIALS[args.tutorial]
    navigator_count = verify_client_inputs(args.tables, args.bundles, args.tutorial)
    template = args.bundles / "scr" / (asset_id(TEMPLATE) + ".unity3d")
    blob = build(template.read_bytes(), tutorial)
    output = args.out / "scr" / (asset_id(tutorial.script) + ".unity3d")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(blob)
    print(f"{output.relative_to(args.out)} SHA-256 {hashlib.sha256(blob).hexdigest()}")
    print(f"Verified six PC TextAssets and {navigator_count} installed navigator message tables")


if __name__ == "__main__":
    main()
