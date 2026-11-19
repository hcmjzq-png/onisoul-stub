"""Rebuild the missing story flow for the isolated PC fixture (no original dialogue)."""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_country_fix import pack_app, replace_entry
from tools.oni_il import parse_unity_web_data
from tools.port_building_bundle import read_tree
from tools.port_legacy_media import pack_pc, repack_serialized
from tools.repair_unityweb_lzma import layout
from tools.verify_il_bodies import verify_assembly

NAME = "stq0_main_01"
SOURCE_APP = "593f03e241a9f9f7c3fa9939b3df9eb87f86e50b662093484f71af0027b9ed23"
SCRIPT_KEY = hashlib.md5("stq0_main".encode("utf-16le")).hexdigest()
PORTRAIT_SOURCE = "chara1_00001_01_3_01"
PORTRAIT_ALIAS = "cch1_00001_01_3_01"
PORTRAIT_KEY = hashlib.md5(PORTRAIT_ALIAS.encode("utf-16le")).hexdigest()


def script(*, battle=False, preview_backgrounds=None, dialogue=None):
    def val(kind, value):
        n = ET.Element(kind)
        n.text = str(value)
        return n

    def call(name, *args):
        n = ET.Element("call", id=name)
        if args:
            ET.SubElement(n, "value_list").extend(args)
        return n

    def assign(name, expr):
        n = ET.Element("assign", id=name)
        n.append(expr)
        return n

    def goto(name):
        n = ET.Element("goto")
        n.append(val("id", name))
        return n

    def branch(operator, left, right, action):
        n = ET.Element("if")
        ET.SubElement(n, operator).extend((left, right))
        n.append(action)
        return n

    root = ET.Element("root")
    seq = ET.SubElement(root, NAME)
    seq.extend([
        call("loadLayout", val("string", "quest_layout")),
        call("setVisibleMessage", val("boolean", "false")),
        call("quest_setVisibleMessageName", val("boolean", "false")),
        call("quest_start"),
        assign("oniBackgroundName", call("quest_getBGImageName")),
    ])
    if preview_backgrounds is not None:
        for name in preview_backgrounds:
            seq.append(branch("eq", val("var", "oniBackgroundName"), val("string", name), goto("previewBackground")))
        seq.extend([goto("previewAvatar"), ET.Element("label", id="previewBackground")])
    seq.append(
        assign("oniBackground", call("loadObject", val("string", "layer3"), val("var", "oniBackgroundName"))),
    )
    if preview_backgrounds is not None:
        seq.extend([call("waitLoad"), call("setVisible", val("var", "oniBackground"), val("boolean", "true")),
                    ET.Element("label", id="previewAvatar")])
    seq.extend([
        assign("oniAvatar", call("loadChara", val("string", "player"), call("quest_getMyAvatorName"))),
        call("waitLoad"),
    ])
    if preview_backgrounds is None:
        seq.append(call("setVisible", val("var", "oniBackground"), val("boolean", "true")))
    seq.extend([
        call("setVisible", val("var", "oniAvatar"), val("boolean", "true")),
        call("quest_setVisibleStatus", val("boolean", "true")),
        call("quest_setValidButtons", val("boolean", "true")),
        call("fadein", val("float", "0.2")),
    ])
    if preview_backgrounds is None:
        seq.extend(exploration(call, assign, branch, goto, val, battle))
    else:
        if dialogue:
            seq.append(assign("oniChapter", call("quest_previewDialogueChapter")))
            for chapter in dialogue:
                seq.append(branch("eq", val("var", "oniChapter"), val("integer", chapter),
                                  goto(f"previewDialogue{chapter}")))
            seq.append(goto("previewIdle"))
            for chapter, lines in dialogue.items():
                seq.extend([ET.Element("label", id=f"previewDialogue{chapter}"),
                            call("setVisibleMessage", val("boolean", "true")),
                            call("quest_setVisibleMessageName", val("boolean", "true"))])
                for line, (speaker, _) in enumerate(lines):
                    seq.extend([call("quest_setMessageName", val("string", speaker)),
                                ET.Element("message", id=f"preview_{chapter}_{line}")])
                seq.extend([call("clearMessage"), call("setVisibleMessage", val("boolean", "false")),
                            call("quest_setVisibleMessageName", val("boolean", "false")), goto("previewIdle")])
        # Ending the interpreter releases the layout and hides loaded artwork.
        # Keep it alive until the native return button unloads the quest scene.
        seq.extend([
            ET.Element("label", id="previewIdle"),
            call("waitSec", val("float", 1)),
            goto("previewIdle"),
        ])
    for line, instruction in enumerate(seq, 1):
        for n in instruction.iter():
            n.set("line", str(line))
            n.set("prefix", NAME)
    return ET.tostring(root, encoding="unicode")


def exploration(call, assign, branch, goto, val, battle):
    flow = [
        ET.Element("label", id="explore"),
        branch("ge", call("quest_localCurrentStep"), val("integer", 5 if battle else 4), goto("done")),
        call("quest_QuestButtonWait"),
        assign("oniHasPoints", call("quest_checkQuestActionPoint")),
        branch("eq", val("var", "oniHasPoints"), val("boolean", "false"), goto("explore")),
        call("quest_setValidButtons", val("boolean", "false")),
        assign("oniEvent", call("quest_stepNext", val("integer", 0), val("integer", 0))),
        *([branch("eq", call("quest_getLastEventId"), val("integer", 6), goto("battle"))] if battle else []),
        assign("oniNextBackgroundName", call("quest_getBGImageName")),
        branch("eq", val("var", "oniBackgroundName"), val("var", "oniNextBackgroundName"), goto("reward")),
        assign("oniNextBackground", call("loadObject", val("string", "layer3"), val("var", "oniNextBackgroundName"))),
        call("waitLoad"),
        call("removeObject", val("var", "oniBackground")),
        call("setVisible", val("var", "oniNextBackground"), val("boolean", "true")),
        assign("oniBackground", val("var", "oniNextBackground")),
        assign("oniBackgroundName", val("var", "oniNextBackgroundName")),
        ET.Element("label", id="reward"),
        call("quest_playItemGainDemo"),
        call("quest_setValidButtons", val("boolean", "true")),
        goto("explore"),
        ET.Element("label", id="done"),
        call("quest_transitionQuestSelect"),
    ]
    if battle:
        flow.extend([ET.Element("label", id="battle"), call("quest_transitionBattle")])
    return flow


def build_script(template, xml, dialogue=None):
    import UnityPy
    src = template.read_bytes()
    env = UnityPy.load(src)
    messages = {}
    for chapter, lines in (dialogue or {}).items():
        for line, (_, text) in enumerate(lines):
            # The native reader looks up the JP field in this script string table.
            # EffectiveText uses @ to render the page and wait for a click.
            heading = "〔补写对白〕" if line == 0 else ""
            messages[f"preview_{chapter}_{line}"] = {"JP": heading + text + "@"}
    string_table = json.dumps({"message": messages}, ensure_ascii=False, separators=(",", ":"))
    expected = {"scr2_000002_01": (NAME, xml), "scr2_000002_01_stringtable.json":
                (NAME + "_stringtable.json", string_table)}
    files = {}
    ab = None
    for obj in env.objects:
        data = read_tree(obj)[0]
        if obj.type.name == "TextAsset":
            data["m_Name"], data["m_Script"] = expected[data["m_Name"]]
            data["m_PathName"] = ""
            files[obj.path_id] = obj.save_typetree(data)
        elif obj.type.name == "AssetBundle":
            ab = obj
            bindings = data["m_Container"]
            data["m_Container"] = [(expected[n][0], e) for n, e in bindings]
            files[obj.path_id] = obj.save_typetree(data)
        else:
            raise ValueError("unexpected script template object")
    if len(files) != 3 or ab is None:
        raise ValueError("expected the original two-TextAsset PC script template")
    sf = ab.assets_file
    out = repack_serialized(sf.reader.bytes, sf, files)
    num, _, _ = layout(src)
    data = pack_pc(src[:num], "CustomAssetBundle-" + hashlib.md5(out).hexdigest(), out)
    result = {key: (int(ref.get_obj().platform), bytes(ref.read().m_Script).decode("utf-8"))
              for key, ref in UnityPy.load(data).container.items()}
    if result != {name: (7, text) for name, text in expected.values()}:
        raise ValueError("rebuilt script did not roundtrip")
    return data


def build_portrait_alias(source):
    """Expose the installed leader texture under the story lookup name."""
    import UnityPy

    original = source.read_bytes()
    env = UnityPy.load(original)
    portrait = env.container[PORTRAIT_SOURCE].get_obj()
    bundle, = [obj for obj in env.objects if obj.type.name == "AssetBundle"]
    if portrait.type.name != "Texture2D" or portrait.platform != 7 or portrait.assets_file != bundle.assets_file:
        raise ValueError("expected the installed PC leader portrait")
    texture = read_tree(portrait)[0]
    if (texture["m_Name"], texture["m_Width"], texture["m_Height"]) != (PORTRAIT_SOURCE, 1024, 1024):
        raise ValueError("unexpected full-size leader portrait")
    texture["m_Name"] = PORTRAIT_ALIAS
    bindings = read_tree(bundle)[0]
    entry, = [entry for name, entry in bindings["m_Container"] if name == PORTRAIT_SOURCE]
    if entry["asset"] != {"m_FileID": 0, "m_PathID": portrait.path_id}:
        raise ValueError("portrait index does not match its texture")
    bindings["m_Container"] = [(PORTRAIT_ALIAS, entry)]
    sf = bundle.assets_file
    node = repack_serialized(sf.reader.bytes, sf, {
        portrait.path_id: portrait.save_typetree(texture), bundle.path_id: bundle.save_typetree(bindings),
    })
    offset, _, _ = layout(original)
    result = pack_pc(original[:offset], "CustomAssetBundle-" + hashlib.md5(node).hexdigest(), node)
    exported = UnityPy.load(result).container[PORTRAIT_ALIAS].get_obj()
    if read_tree(exported)[0] != texture or exported.platform != 7:
        raise ValueError("story alias changed the PC portrait payload")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("app", "assembly", "template", "out"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--portrait-source", type=Path)
    p.add_argument("--battle", action="store_true")
    p.add_argument("--preview-backgrounds", type=Path)
    p.add_argument("--preview-dialogue", type=Path)
    a = p.parse_args()
    backgrounds = None
    if a.preview_backgrounds:
        if a.battle:
            p.error("chapter preview does not execute battles")
        names = json.loads(a.preview_backgrounds.read_bytes())
        if not isinstance(names, list) or not all(isinstance(n, str) and re.fullmatch(r"qbg\d+_\d+_\d+", n) for n in names):
            p.error("expected a list of installed preview background names")
        backgrounds = sorted(set(names))
    dialogue = None
    if a.preview_dialogue:
        if backgrounds is None:
            p.error("dialogue is available only in chapter preview")
        dialogue = json.loads(a.preview_dialogue.read_bytes())
        if not isinstance(dialogue, dict) or not all(
            re.fullmatch(r"(?:1|[1-8][1-5])", chapter) and isinstance(lines, list) and lines and all(
                isinstance(line, list) and len(line) == 2 and all(isinstance(part, str) and part.strip() for part in line)
                for line in lines) for chapter, lines in dialogue.items()
        ):
            p.error("expected preview dialogue keyed by story × 10 + chapter")
        dialogue = {int(chapter): lines for chapter, lines in dialogue.items()}
    original = a.app.read_bytes()
    if hashlib.sha256(original).hexdigest() != SOURCE_APP or not verify_assembly(a.assembly)["valid"]:
        raise ValueError("unexpected app base or invalid candidate DLL")
    n, _, _ = layout(original)
    body = lzma.decompress(original[n:], format=lzma.FORMAT_ALONE)
    changed, first = replace_entry(body, "Assembly-CSharp.dll", a.assembly.read_bytes())
    app = pack_app(original, changed, first)
    plain = lzma.decompress(app[layout(app)[0]:], format=lzma.FORMAT_ALONE)
    unchanged = {x.name: body[x.offset:x.end] for x in parse_unity_web_data(body).entries
                 if x.name != "Assembly-CSharp.dll"}
    if {x.name: plain[x.offset:x.end] for x in parse_unity_web_data(plain).entries
            if x.name != "Assembly-CSharp.dll"} != unchanged:
        raise ValueError("unrelated client files changed")
    xml = script(battle=a.battle, preview_backgrounds=backgrounds, dialogue=dialogue)
    script_bundle = build_script(a.template, xml, dialogue)
    portrait = build_portrait_alias(a.portrait_source) if a.portrait_source else None
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "app.unity3d").write_bytes(app)
    (a.out / (SCRIPT_KEY + ".unity3d")).write_bytes(script_bundle)
    (a.out / (NAME + ".xml")).write_text(xml + "\n", encoding="utf-8")
    if portrait is not None:
        (a.out / (PORTRAIT_KEY + ".unity3d")).write_bytes(portrait)
    manifest = {
        "app": hashlib.sha256(app).hexdigest(),
        "script": hashlib.sha256(script_bundle).hexdigest(),
        "scriptKey": SCRIPT_KEY, "battle": a.battle, "originalDialogueRecovered": False, "nativeVerified": False,
    }
    if backgrounds is not None:
        manifest["previewBackgrounds"] = backgrounds
    if dialogue is not None:
        manifest["originalWritingChapters"] = sorted(dialogue)
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
