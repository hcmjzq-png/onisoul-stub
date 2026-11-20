"""Rebuild standard story collection icons from recovered original artwork."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_legacy_media import pack_pc, repack_serialized
from tools.repair_unityweb_lzma import layout


def asset_id(name):
    return hashlib.md5(name.encode("utf-16le")).hexdigest()


def table(root, name):
    return json.loads((root / (name + ".json")).read_bytes())[name]


def build(blob, template, target, art):
    import UnityPy
    from PIL import Image

    env = UnityPy.load(blob)
    assets = list(env.objects)
    container, = [obj for obj in assets if obj.type.name == "AssetBundle"]
    textures = [obj for obj in assets if obj.type.name == "Texture2D"]
    if len(textures) + 1 != len(assets):
        raise ValueError("unexpected item template objects")
    names, replacements, expected = {}, {}, {}
    for obj in textures:
        record = obj.read_typetree()
        old = record["m_Name"]
        if old != template and not old.startswith(template + "_"):
            raise ValueError("unexpected item name")
        name = target + old[len(template):]
        with Image.open(art[name]) as raw:
            image = raw.convert("RGBA")
        width, height = image.size
        pixels = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
        record.update(m_Name=name, m_Width=width, m_Height=height, m_TextureFormat=4,
                      m_MipMap=False, m_CompleteImageSize=len(pixels))
        record["image data"] = pixels
        replacements[obj.path_id] = obj.save_typetree(record)
        names[old] = name
        expected[name] = (image.size, hashlib.sha256(image.tobytes()).hexdigest())
    tree = container.read_typetree()
    if {name for name, _ in tree["m_Container"]} != names.keys():
        raise ValueError("unexpected item container bindings")
    tree["m_Container"] = [(names[name], ref) for name, ref in tree["m_Container"]]
    replacements[container.path_id] = container.save_typetree(tree)
    sf = container.assets_file
    node = repack_serialized(sf.reader.bytes, sf, replacements)
    offset, _, _ = layout(blob)
    data = pack_pc(blob[:offset], "CustomAssetBundle-" + hashlib.md5(node).hexdigest(), node)
    result = {}
    for name, ptr in UnityPy.load(data).container.items():
        tex = ptr.read()
        if int(ptr.get_obj().platform) != 7 or tex.m_Name != name:
            raise ValueError("readback has an incorrect PC texture binding")
        image = tex.image.convert("RGBA")
        result[name] = (image.size, hashlib.sha256(image.tobytes()).hexdigest())
    if result != expected:
        raise ValueError("readback changed the collected artwork")
    return data, result


def collect_areas(tables):
    areas = {}
    sections = {}
    for row in table(tables, "quest_1_index").values():
        if row.get("enable") is not True or row.get("clientEnable") is not True:
            continue
        quest = f"quest_1_{row['questNo']:04d}"
        if quest not in sections:
            sections[quest] = table(tables, quest)
        chapter = row["chapterNo"]
        for area in range(1, row["areaCount"] + 1):
            # QuestAreaTableAccessor.getShowItems reads the first section of each area.
            section = sections[quest][f"{chapter}_{area}_1"]
            ids = [section[f"item{i}"] for i in range(1, 5)]
            areas[f"{quest}:{chapter}:{area}"] = [item for item in ids if item not in ("", "none")]
    return areas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tables", "bundles", "art", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    areas = collect_areas(args.tables)
    items = {}
    for path in sorted(args.tables.glob("item[0-9][0-9].json")):
        items.update(table(args.tables, path.stem))
    locations = {}
    for area, ids in areas.items():
        for item in set(ids):
            icon = items[item]["iconName"]
            locations.setdefault(icon, {}).setdefault(item, []).append(area)
    art = {}
    for path in args.art.rglob("*.png"):
        icon, _, variant = path.stem.rpartition("_")
        if icon in locations and re.fullmatch(r"[0-9]{2}", variant):
            choices = art.setdefault(icon, {})
            previous = choices.get(path.stem)
            if previous and previous.read_bytes() != path.read_bytes():
                raise ValueError(f"conflicting art sources for {path.stem}")
            choices[path.stem] = path
    templates = {"item01": ("item01_0000659", range(1, 11)), "item08": ("item10_0060009", (1, 2, 91))}
    outputs, proof = {}, []
    for icon, usage in sorted(locations.items()):
        name = asset_id(icon) + ".unity3d"
        row = {"icon": icon, "file": name, "usage": usage}
        proof.append(row)
        if (args.bundles / name).is_file():
            row["status"] = "existing"
            continue
        template = templates.get(icon[:6])
        if template is None:
            row["status"] = "missing template"
            continue
        template_name, variants = template
        choices = art.get(icon, {})
        missing = [f"{icon}_{i:02d}" for i in variants if f"{icon}_{i:02d}" not in choices]
        if missing:
            row.update(status="missing original art", missing=missing)
            continue
        blob = (args.bundles / (asset_id(template_name) + ".unity3d")).read_bytes()
        data, textures = build(blob, template_name, icon, choices)
        outputs[name] = data
        row.update(status="rebuilt", sha256=hashlib.sha256(data).hexdigest(), textures=textures)
    args.out.mkdir(parents=True, exist_ok=False)
    for name, data in outputs.items():
        (args.out / name).write_bytes(data)
    available = {row["icon"] for row in proof if row["status"] in {"existing", "rebuilt"}}
    counts = {"areas": len(areas), "icons": len(proof), "rebuilt": len(outputs),
              "missing": len(proof) - len(available), "available": len(available),
              "coveredAreas": sum(all(items[item]["iconName"] in available for item in ids)
                                  for ids in areas.values())}
    (args.out / "manifest.json").write_text(json.dumps({"counts": counts, "icons": proof}, indent=2) + "\n",
                                             encoding="utf-8")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
