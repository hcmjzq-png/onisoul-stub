"""Read-only original-source audit; emits hashes and tiny samples, never full tables."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from tools.extract_tables_from_bundle import extract_assets  # noqa: E402

CONTAINER_SHA = "20b987a41c5ec8f0b70dfe65bf0383c7acf25cc755f38f5b4d9dbdaa361dc4f7"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", type=Path, default=Path(r"D:\onisoul\work\quest-contract-20261115\tableAssets.bin"))
    parser.add_argument("--source", type=Path, default=Path(r"C:\Users\74378\AppData\Local\Temp\onisoul-static-original-20261115"))
    parser.add_argument("--tables", type=Path, default=Path(r"D:\onisoul\work\quest-contract-20261115\all-tables"))
    parser.add_argument("--write", action="store_true", help="Write C-group proof and selected sample rows only")
    args = parser.parse_args()
    blob = args.container.read_bytes()
    if hashlib.sha256(blob).hexdigest() != CONTAINER_SHA:
        raise ValueError("original table container fingerprint mismatch")
    declared = {f"skillRefreshG{g}.json": f"skillRefreshG{g}" for g in (2, 4, 6)}
    declared.update({"skill_slot_payment.json": "skill_slot_payment", "deckMessage.json": "message"})
    assets = extract_assets(blob, declared)
    if set(assets) != set(declared):
        raise ValueError(f"validated TextAssets missing: {set(declared) - set(assets)}")
    skills = json.loads((args.tables / "skill.json").read_text(encoding="utf-8-sig"))["skill"]
    result = {"container": str(args.container), "container_sha256": CONTAINER_SHA,
              "tables": [], "sources": [], "negative_searches": []}
    result["negative_searches"].append({"source": str(args.container),
        "term": "DECK_MSG_CONFIRM_ABSORB_CARDS",
        "exact_utf8_occurrences": blob.count(b"DECK_MSG_CONFIRM_ABSORB_CARDS"),
        "limit": "Exact bytes in this container only; not all client resource files."})
    fixtures = ROOT / "tests/fixtures/card_growth"
    for name, asset in sorted(assets.items()):
        rows = json.loads(asset.raw)[asset.root_key]
        proof = asset.evidence()
        if name.startswith("skillRefresh"):
            histogram = Counter((row["rate"], row["rate_credit"]) for row in rows.values())
            proof["rate_pairs"] = [{"rate": a, "rate_credit": b, "count": n}
                                   for (a, b), n in sorted(histogram.items())]
            proof["rate_sum"] = sum(row["rate"] for row in rows.values())
            proof["rate_credit_sum"] = sum(row["rate_credit"] for row in rows.values())
            proof["unresolved_skill_ids"] = sorted(set(rows) - set(skills))
            proof["exported_file_present"] = (args.tables / name).exists()
            # One original row per distinct pair, not a made-up uniform pool.
            sample = {}
            for pair in sorted(histogram):
                key = next(k for k, row in rows.items() if (row["rate"], row["rate_credit"]) == pair)
                sample[key] = rows[key]
        elif name == "deckMessage.json":
            terms = ("DECK_MSG_CONFIRM_ABSORB_CARDS", "skillCoins", "REFRESH", "技能币")
            result["negative_searches"].append({"source": name,
                "terms": {term: sum(term in k + str(v) for k, v in rows.items()) for term in terms},
                "limit": "Only this verified message TextAsset; not proof that no other resource contains a rate."})
            result["tables"].append(proof)
            continue
        else:
            # Two of six fee rows; the report lists all six scalar fee entries.
            proof["fees"] = {k: {"category": v["category"], "amount": v["amount"]} for k, v in rows.items()}
            sample = {k: rows[k] for k in ("slot_0001_1", "slot_0002_1")}
        proof["sample_rows"] = list(sample)
        content = json.dumps({asset.root_key: sample}, ensure_ascii=False, indent=2) + "\n"
        proof["sample_sha256"] = hashlib.sha256(content.encode()).hexdigest()
        proof["sample_path"] = str((fixtures / name).relative_to(ROOT)).replace("\\", "/")
        result["tables"].append(proof)
        if args.write:
            (fixtures / name).write_text(content, encoding="utf-8")
        elif (fixtures / name).read_text(encoding="utf-8") != content:
            raise ValueError(f"fixture differs from original selected rows: {name}")
    refs = {
        "WebApiClient.cs": ["sendRequest:190-217", "_httpCall:247-273", "sellTactics:1305-1311", "setSkillcoins/setSkillSlot:4554-4570"],
        "RpcQueue.cs": ["reliable/predicable:107-121"],
        "DeckSaleTacticsObj.cs": ["SumLongPrice:57-66", "setText:86-106"],
        "DeckSale_Tactics.cs": ["postCallback:124-150", "sale:307-368"],
        "TacticsTableAccessor.cs": ["getSalePrice:181-188"],
        "TacticsStatus.cs": ["constructor:29-37"],
        "DeckConflate_SkillRefresh.cs": ["postCallBack:105-171", "conflateFablicConnection:215-274", "sendRefreshRequest/transformPaymentId/checkPayment:512-604"],
        "SkillRefreshPaymentTableAccessor.cs": ["getCategory/getAmount:17-35"],
        "CharacterConflatePreview_Character.cs": ["refreshBtnStatus:202-215"],
        "DeckScene.cs": ["getDecks callback:244-253"],
    }
    for filename, methods in refs.items():
        path = args.source / filename
        result["sources"].append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "methods_lines": methods})
    path = args.tables / "tactics.json"
    original = json.loads(path.read_text(encoding="utf-8-sig"))["tactics"]
    sample = fixtures / "tactics.json"
    small = json.loads(sample.read_text(encoding="utf-8"))["tactics"]
    if not all(original[k] == v for k, v in small.items()):
        raise ValueError("tactic fixture differs from original")
    result["tactics"] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "rows": len(original), "sample_rows": list(small), "sample_sha256": hashlib.sha256(sample.read_bytes()).hexdigest()}
    result["protocol_vs_policy"] = {
        "proven": "Tactic prices and quantities; response contains sold quantities. Six refresh fees and tier button mapping. Nonuniform candidate table values.",
        "unknown": "Coin conversion rate; refresh sampling/replacement/learning rules; client request identity for retry deduplication.",
        "service_policy": "Trusted integration-only operation_id, player-local durable receipt, cap 1024 without eviction, reject all deck references and gold overflow. No new wire field or HTTP handler."}
    if args.write:
        Path(__file__).with_name("followup-evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verified_container": CONTAINER_SHA, "tables": len(result["tables"]),
                      "source_files": len(result["sources"]), "write": args.write}))


if __name__ == "__main__":
    main()
