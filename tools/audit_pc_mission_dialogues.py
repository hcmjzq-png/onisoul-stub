"""Audit every PC commission script and stage verified missing bundles."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_mission14_dialogue import Dialogue, TEMPLATE, build, navigator_messages
from tools.build_quest_collection_icons import asset_id, table


# PoliticFSMStartup.defaultFileName_ and PoliticFSMLogin.defaultFileName_.
CITY_SCRIPTS = ("scr2_000001_01", "scr2_000012_01")
PLACEHOLDERS = {"内政委托", "内政委托内文", "内政委托内容"}


def placeholder(text: str) -> bool:
    return "".join(text.split()).strip("「」@") in PLACEHOLDERS


def has_page_marker(text: str) -> bool:
    # EffectiveText.play skips messages without either PC display delimiter.
    return "@" in text or "!" in text


def dialogue_for(row: dict, references: list[dict], messages: dict) -> tuple[Dialogue, int]:
    number = int(row["id"].removeprefix("po_mission_"))
    base = Dialogue(number, 0, row["iconIndex"], icon_file=row["iconFileName"])
    if (row["enterScript"], row["exitScript"]) != (base.script + "_01", base.script + "_03"):
        raise ValueError("unconfirmed message prefix for script pair")

    required_menu = {1, *(i + 1 for i in range(1, 4)
                         if any(r[f"conditionCount{i}"] > 0 for r in references))}
    counts = set()
    blank_menu_rows = set()
    unmarked = 0
    keys = re.compile(rf"POM_MES_{number:06}_(0[123])_(\d{{3}})")
    for filename, texts in messages.items():
        parts: dict[str, dict[int, str]] = defaultdict(dict)
        for key, languages in texts.items():
            if match := keys.fullmatch(key):
                text = languages.get("tw", "").strip()
                if text and not placeholder(text):
                    parts[match[1]][int(match[2])] = text
        menu = parts["02"]
        if required_menu - menu.keys():
            raise ValueError(f"missing substantive mission menu in {filename}")
        # Only condition rows that the original menu hides may use empty labels.
        blank_menu_rows.update(set(range(1, 5)) - menu.keys())
        opening = parts["01"]
        if (opening.keys() != set(range(1, len(opening) + 1))
                or not any(has_page_marker(text) for text in opening.values())):
            raise ValueError(f"missing or noncontiguous opening dialogue in {filename}")
        end = parts["03"]
        titles = [i for i, text in end.items() if not has_page_marker(text.rstrip("!"))
                  and re.search(r"(?:达成|完成)[！!]?$", text)]
        if len(titles) != 1:
            raise ValueError(f"missing or ambiguous reward title in {filename}")
        title = titles[0]
        if end.keys() != set(range(1, title + 1)):
            raise ValueError(f"missing or noncontiguous reward dialogue in {filename}")
        counts.add((len(opening), title))
        unmarked += sum(not has_page_marker(text) for text in opening.values())
        unmarked += sum(not has_page_marker(text) for i, text in end.items() if i < title)
    if len(counts) != 1:
        raise ValueError("navigator variants disagree on opening pages or reward title")
    pages, title = counts.pop()
    return Dialogue(number, title, base.icon_index, pages, base.icon_file, tuple(sorted(blank_menu_rows))), unmarked


def verify_script_bundle(path: Path, scripts: set[str]) -> None:
    import UnityPy
    from xml.etree import ElementTree

    bindings = UnityPy.load(str(path)).container
    pending = sorted(scripts)
    verified = set()
    while pending:
        script = pending.pop()
        if script in verified:
            continue
        for name in (script, script + "_stringtable.json"):
            if name not in bindings:
                raise ValueError(f"missing TextAsset {name}")
            ref = bindings[name]
            obj = ref.get_obj()
            if obj.type.name != "TextAsset" or int(obj.platform) != 7 or ref.read().m_Name != name:
                raise ValueError(f"invalid PC TextAsset binding {name}")
        xml = bytes(bindings[script].read().m_Script).decode("utf-8-sig")
        entry = ElementTree.fromstring(xml).find(script)
        if entry is None:
            raise ValueError(f"missing script entry {script}")
        verified.add(script)
        stem = script.rsplit("_", 1)[0]
        for node in entry.iter("import"):
            dependency = node.attrib["id"]
            if dependency.rsplit("_", 1)[0] == stem:
                pending.append(dependency)


def stage(tables: Path, bundles: Path, sources: list[Path], out: Path | None) -> dict:
    rows = table(tables, "politicMission")
    messages = {name: {key: val for key, val in text.items() if key.startswith("POM_MES_")}
                for name, text in navigator_messages(tables, bundles).items()}
    scripts: dict[str, set[str]] = defaultdict(set)
    references: dict[str, list[dict]] = defaultdict(list)
    missions: dict[str, dict] = {}
    for code, row in rows.items():
        entries = {row["enterScript"], row["exitScript"]} - {"none"}
        stems = sorted({entry.rsplit("_", 1)[0] for entry in entries})
        icon = row["iconFileName"]
        missions[code] = {
            "scripts": stems, "boot": row["bootCheckFunc"], "prerequisites": row["bootCheckData"],
            "icon": icon, "icon_present": icon == "none" or (bundles / "mission" / (asset_id(icon) + ".unity3d")).is_file(),
        }
        for entry in entries:
            scripts[entry.rsplit("_", 1)[0]].add(entry)
        for stem in stems:
            references[stem].append(row)
    for entry in CITY_SCRIPTS:
        scripts[entry.rsplit("_", 1)[0]].add(entry)

    originals: dict[str, list[Path]] = defaultdict(list)
    for source in sources:
        if not source.exists():
            raise FileNotFoundError(source)
        for path in sorted(source.glob("*.unity3d")) if source.is_dir() else [source]:
            if match := re.search(r"([0-9a-f]{32})\.unity3d$", path.name.lower()):
                originals[match[1]].append(path)

    template = (bundles / "scr" / (asset_id(TEMPLATE) + ".unity3d")).read_bytes()
    results = {}
    for stem, entries in sorted(scripts.items()):
        hashed = asset_id(stem)
        filename = hashed + ".unity3d"
        present = bundles / "scr" / filename
        record = results[stem] = {"file": "scr/" + filename}
        blob = None
        if present.is_file():
            try:
                verify_script_bundle(present, entries)
            except Exception as error:
                record.update(status="invalid_installed", reason=str(error))
                continue
            record["status"] = "installed"
        else:
            for candidate in originals.get(hashed, ()):
                try:
                    verify_script_bundle(candidate, entries)
                except Exception:
                    continue
                blob = candidate.read_bytes()
                record["status"] = "original"
                break
            if blob is None:
                row = rows.get("po_mission_" + stem.removeprefix("scr1_")[-5:])
                try:
                    if not stem.startswith("scr1_") or row is None:
                        raise ValueError("no verified original or commission dialogue mapping")
                    dialogue, unmarked = dialogue_for(row, references[stem], messages)
                    if entries != {dialogue.script + "_01", dialogue.script + "_03"}:
                        raise ValueError("additional required script entries")
                except ValueError as error:
                    record.update(status="unresolved", reason=str(error))
                    continue
                blob = build(template, dialogue)
                record.update(status="compatibility", opening_pages=dialogue.enter_pages, reward_title=dialogue.reward_title,
                              unmarked_message_entries=unmarked)
        if blob is not None:
            record["sha256"] = hashlib.sha256(blob).hexdigest()
            if out is not None:
                target = out / "scr" / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(blob)
    return {"navigator_tables": len(messages),
            "counts": dict(Counter(row["status"] for row in results.values())),
            "missions": missions, "scripts": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--bundles", type=Path, required=True)
    parser.add_argument("--source", action="append", type=Path, default=[])
    parser.add_argument("--out", type=Path, help="Empty staging directory for missing bundles")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.out and args.out.exists() and any(args.out.iterdir()):
        parser.error("--out must be empty")
    result = stage(args.tables, args.bundles, args.source, args.out)
    args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
