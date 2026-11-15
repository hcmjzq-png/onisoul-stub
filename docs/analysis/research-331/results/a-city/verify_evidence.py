"""Read-only verification of A's original-file hashes, rows and embedded text."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


def main() -> None:
    folder = Path(__file__).resolve().parent
    root = next(parent for parent in folder.parents if (parent / "app/business").is_dir())
    proof = json.loads((folder / "source-proof.json").read_text("utf8"))
    fixture_path = root / proof["fixture"]["path"]
    # Git normalizes the authored sample; external original hashes stay raw.
    fixture_bytes = fixture_path.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(fixture_bytes).hexdigest() == proof["fixture"]["sha256"]
    fixture = json.loads(fixture_bytes)
    rows = 0
    for source in proof["table_sources"]:
        raw = Path(source["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source["sha256"], source["path"]
        table = json.loads(raw)[source["table"]]
        for key in source["rows"]:
            assert fixture[source["table"]][key] == table[key], key
            rows += 1
    for source in proof["source_files"]:
        raw = Path(source["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source["sha256"], source["path"]
        for first, last in source["lines"]:
            assert 1 <= first <= last <= len(raw.splitlines())
    container = Path(proof["container"]["path"]).read_bytes()
    assert hashlib.sha256(container).hexdigest() == proof["container"]["sha256"]
    for entry in proof["embedded_text"]:
        raw = container[entry["offset"]:entry["offset"] + entry["length"]]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"], entry["id"]
        value = json.loads(raw)
        assert (value["id"], value["tw"]) == (entry["id"], entry["text"])
    with (folder / "endpoints.tsv").open(encoding="utf8") as stream:
        endpoints = [row["endpoint"] for row in csv.DictReader(stream, delimiter="\t")]
    assert len(endpoints) == len(set(endpoints)) == 29
    print(f"Verified {rows} original rows, {len(proof['source_files'])} source files, "
          f"{len(proof['embedded_text'])} embedded texts and {len(endpoints)} endpoint rows.")


if __name__ == "__main__":
    main()
