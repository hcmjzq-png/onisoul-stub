"""Read-only evidence/47-endpoint/small-fixture audit; no old task or web fetch.

Run at repository root: python docs/analysis/research-331/results/f-war/audit.py
Requires original source/table paths recorded in this result's proof files.
"""
import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    proof = json.loads((HERE / "local-evidence.json").read_text(encoding="utf-8"))
    for row in proof["sources"]:
        assert digest(Path(row["path"])) == row["sha256"], row["path"]
    sources = json.loads((HERE / "table-evidence.json").read_text(encoding="utf-8"))
    for row in sources:
        original, sample = Path(row["path"]), ROOT / row["fixture"]
        assert digest(original) == row["sha256"], original
        assert digest(sample) == row["fixture_sha256"], sample
        full = json.loads(original.read_text(encoding="utf-8-sig"))[row["root"]]
        fixture = json.loads(sample.read_text(encoding="utf-8"))[row["root"]]
        assert fixture == {key: full[key] for key in row["row_ids"]}
    with (HERE / "endpoints.tsv").open(encoding="utf-8", newline="") as stream:
        endpoints = list(csv.DictReader(stream, delimiter="\t"))
    assert len(endpoints) == len({row["endpoint"] for row in endpoints}) == 47
    with (ROOT / "docs/analysis/parallel-342/f-war-campaigns/reviewed-endpoints.tsv").open(
            encoding="utf-8", newline="") as stream:
        old = {row["endpoint"] for row in csv.DictReader(stream, delimiter="\t")}
    assert old == {row["endpoint"] for row in endpoints}
    assert len(proof["new_evidence_endpoints"]) == 11
    print(json.dumps({"original_sources": len(proof["sources"]), "table_files": len(sources),
                      "fixture_rows": sum(len(row["row_ids"]) for row in sources),
                      "endpoints": len(endpoints), "result": "passed"}))


if __name__ == "__main__":
    main()
