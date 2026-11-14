"""Reproduce harvest evidence without executing the client or changing sources."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from app.business.city_production_rules import reward_slot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--container", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    names = ("building", "product", "reward01_politic", "building_level", "defines", "skill")
    tables = {name: json.loads((args.tables / f"{name}.json").read_text("utf-8-sig"))[name] for name in names}
    report = {"scope": "Static catalogue facts, NOT server settlement formulas or probabilities",
              "table_sources": [{"path": str(args.tables / f"{n}.json"), "sha256": sha(args.tables / f"{n}.json"),
                                 "rows": len(tables[n])} for n in names]}
    products, rewards, buildings = (tables[n] for n in ("product", "reward01_politic", "building"))
    missing, unrecognized, repeated, varying_counts, varying_ratios, parser_errors = [], [], [], [], [], []
    exp_items, exp_fields = 0, 0
    slots_histogram: Counter = Counter()
    for key, row in products.items():
        rid = row.get("rewardId", "")
        if not rid.startswith("reward01_"):
            unrecognized.append({"product": key, "rewardId": rid})
            continue
        if rid not in rewards:
            missing.append({"product": key, "rewardId": rid})
            continue
        try:
            slots = [slot for i in range(1, 11) if (slot := reward_slot(rewards[rid], i)) is not None]
        except ValueError as exc:
            parser_errors.append({"product": key, "error": str(exc)})
            continue
        slots_histogram[len(slots)] += 1
        groups = [s.group for s in slots]
        if len(set(groups)) < len(groups):
            repeated.append(key)
        if any(s.count_min != s.count_max for s in slots):
            varying_counts.append(key)
        if any(s.ratio_min != s.ratio_max for s in slots):
            varying_ratios.append(key)
        exp_items += any(s.item_id == "item11_0000501" for s in slots)
        exp_fields += "buildingExp" in row
    report["reward_audit"] = {
        "active_slot_count_histogram_per_product": dict(slots_histogram),
        "missing_references_not_missing_asset_files": missing,
        "non_politic_reward_prefixes": unrecognized, "parse_errors": parser_errors,
        "products_with_repeated_active_group": len(repeated),
        "products_with_variable_count_bounds": len(varying_counts),
        "products_with_variable_ratio_bounds": len(varying_ratios),
        "resolved_products_with_player_exp_item": exp_items,
        "resolved_products_with_buildingExp_field": exp_fields,
        "products_with_gainTypes_or_gainAmounts": sum("gainTypes" in r or "gainAmounts" in r for r in products.values()),
        "note": "Repeated group or fixed ratios do not prove an RNG algorithm; counts are per product, may overlap."}
    report["durability_histogram"] = dict(Counter(str(r["durability"]) for r in buildings.values()))
    report["level_audit"] = {
        "lowercase_intervalRatio_histogram": dict(Counter(str(r.get("intervalRatio")) for r in tables["building_level"].values())),
        "uppercase_IntervalRatio_rows": sum("IntervalRatio" in r for r in tables["building_level"].values()),
        "gainRatio_rows": sum("gainRatio" in r for r in tables["building_level"].values()),
        "nonunit_costRatio_rows": sum(r.get("costRatio") != 1 for r in tables["building_level"].values())}
    source_methods = {
        "RewardTableAccessor.cs": "getReward:52-82",
        "ProductsTableAccessor.cs": "getGain:77-98 (no external textual call found)",
        "PoliticBuildingParameter.cs": "IsInfiniteDurability/IsDead:79-81; set:157-170",
        "DefinesTableAccessor.cs": "getAutoHarvestPoint:77-84; getInfiniteDurability:145-153",
        "PopUpBuildingIcon.cs": "setZzzPopUp:420-463; setProducingPopUp:500-537",
        "PoliticBuildingState/StateAutoProduce.cs": "payout:96-188; onCompliteProducings:401-430; onComplite:475-507",
        "PoliticBuildingState/StateManualProduce.cs": "onComplite:78-85",
        "PoliticGainResourceExp.cs": "getGainResource:15-22",
        "PoliticGainResource.cs": "getGainResource:17-20",
        "PoliticGainResourceCreate.cs": "createPayResourceIcon",
        "PoliticBuilding.cs": "getProductCosts:1872-1885; processDead:549-568; submitProduce:1110-1134",
        "PluginPoliticDataReader.cs": "getProductCosts:220-238",
        "LevelUpTableAccessor.cs": "getCostRatio:53-61; getIntervalRatio:63-71; getGainRatio:73-81",
        "UserStatus.cs": "calcAmount:1735-1741",
        "PoliticFSMAutoHarvest.cs": "noticeResult:83-125",
        "PluginRunner_DoHarvest.cs": "CalcPoliticPoint:81-87",
        "PluginPoliticDataWriter.cs": "OnGetProductings:20-47",
        "PoliticRoadChecker.cs": "Update:34-71",
        "PoliticConnectBase.cs": "addRoad:236-257; searchRoad:355-435",
        "PoliticPeople.cs": "RoadChecker calls:192,298,394",
        "SkillTableAccessor.cs": "getDesc; getCategory; no road multiplier formula",
    }
    report["source_files"] = [{"path": str(args.source / name), "sha256": sha(args.source / name), "methods_or_lines": methods}
                              for name, methods in source_methods.items()]
    # Byte offsets point at the JSON object's opening brace. Keep only small
    # evidence records, never the source container or a complete message table.
    raw = args.container.read_bytes()
    wanted = {"POM_MES_000273_03_001", "POM_MES_000273_03_002", "POM_MES_000273_03_005",
              "POM_MES_000033_01_001", "POM_MES_000089_03_002", "POM_MES_000220_01_001",
              "POM_MES_000006_03_001", "SKILL_MSG_1_11058_01_DESC", "SKILL_MSG_1_11064_01_DESC"}
    texts = []
    for match in re.finditer(rb'\{[^{}\x00]{0,200}"tw"\s*:\s*"(?:[^"\\]|\\.)*"\s*\}', raw):
        try:
            row = json.loads(match.group().decode("utf-8"))
        except (ValueError, UnicodeError):
            continue
        if row.get("id") in wanted:
            texts.append({"offset": match.start(), "byte_length": len(match.group()), **row})
            wanted.remove(row["id"])
    report["localized_evidence"] = {"path": str(args.container), "sha256": hashlib.sha256(raw).hexdigest(),
                                    "texts": texts, "unresolved_ids": sorted(wanted)}
    sample = ROOT / "tests/fixtures/city_production/production-rules.json"
    fixture = json.loads(sample.read_text("utf-8"))
    assert all(tables[n][k] == row for n, data in fixture.items() for k, row in data.items())
    report["fixture"] = {"path": sample.relative_to(ROOT).as_posix(), "sha256": sha(sample),
                         "row_ids": {n: list(data) for n, data in fixture.items()}, "exact_original_rows": True}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"reward_audit": report["reward_audit"], "level_audit": report["level_audit"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
