#!/usr/bin/env python3
"""Prepare/install the seven pinned original TextAssets. Stop the service first.

Validates every file before writing, refuses conflicting destination bytes, and
preserves unrelated import records. This is an offline single-writer operation;
it does not restart services or claim that any business endpoint is deployed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.minijson import parse_json_document  # noqa: E402
from app.tables import TableCatalog  # noqa: E402
from tools.extract_tables_from_bundle import extract_assets  # noqa: E402

PROOF = ROOT / "docs/analysis/parallel-342/review-round2/recovered-tables-source-proof.json"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate_payloads(payloads: dict[str, bytes], proof: dict) -> list[dict]:
    records = []
    expected = {row["name"] + ".json" for row in proof["tables"]}
    if set(payloads) != expected or len(expected) != len(proof["tables"]):
        raise ValueError("verified table set mismatch")
    for row in proof["tables"]:
        name = row["name"] + ".json"
        if Path(name).name != name:
            raise ValueError("unsafe table filename")
        raw = payloads[name]
        if len(raw) != row["length"] or sha256(raw) != row["sha256"]:
            raise ValueError(f"original byte/hash mismatch: {name}")
        document = parse_json_document(raw)
        if (not isinstance(document, dict) or set(document) != {row["name"]}
                or not isinstance(document[row["name"]], dict)
                or len(document[row["name"]]) != row["rows"]):
            raise ValueError(f"original root/row count mismatch: {name}")
        records.append({"file": name, "root_key": row["name"], "bytes": len(raw),
                        "sha256": row["sha256"], "rows": row["rows"],
                        "source_container_sha256": proof["container_sha256"],
                        "script_offset": row["offset"], "status": "copied"})
    return records


def from_container(container: bytes, proof: dict) -> dict[str, bytes]:
    if sha256(container) != proof["container_sha256"]:
        raise ValueError("original container hash mismatch")
    assets = extract_assets(container, {row["name"] + ".json": row["name"] for row in proof["tables"]})
    for row in proof["tables"]:
        asset = assets.get(row["name"] + ".json")
        if asset is None or asset.script_offset != row["offset"]:
            raise ValueError(f"named TextAsset/offset mismatch: {row['name']}")
    payloads = {name: asset.raw for name, asset in assets.items()}
    validate_payloads(payloads, proof)
    return payloads


def atomic_write(path: Path, raw: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install(payloads: dict[str, bytes], dest: Path, proof: dict) -> dict[str, Any]:
    records = validate_payloads(payloads, proof)
    dest = dest.resolve()
    manifest = dest / "import-manifest.json"
    if manifest.is_symlink():
        raise ValueError("import manifest must not be a symlink")
    old_manifest = manifest.read_bytes() if manifest.exists() else None
    document = json.loads(old_manifest) if old_manifest is not None else {"schema": 1, "tables": []}
    if (not isinstance(document, dict) or document.get("schema") != 1
            or not isinstance(document.get("tables"), list)):
        raise ValueError("invalid existing import manifest")
    previous = document["tables"]
    if any(not isinstance(row, dict) or not isinstance(row.get("file"), str) for row in previous):
        raise ValueError("invalid existing import records")
    if len({row["file"] for row in previous}) != len(previous):
        raise ValueError("duplicate existing import records")
    absent = []
    for name, raw in payloads.items():
        target = dest / name
        if target.is_symlink():
            raise ValueError(f"destination must not be a symlink: {name}")
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError(f"conflicting destination; back up and review: {name}")
        else:
            absent.append(name)
    # Replace only these seven records; preserve metadata and all other entries.
    replacements = {row["file"]: row for row in records}
    document["tables"] = [replacements.pop(row["file"], row) for row in previous]
    document["tables"].extend(replacements.values())
    encoded = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    dest.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for name in absent:
            atomic_write(dest / name, payloads[name])
            created.append(name)
        if encoded != old_manifest:
            atomic_write(manifest, encoded)
    except BaseException:
        # Existing files were never overwritten. A failed atomic manifest replace
        # leaves the old manifest intact; remove only files created in this run.
        for name in created:
            (dest / name).unlink()
        raise
    return {"verified": len(records), "created": len(created),
            "already_present": len(records) - len(created), "records": records}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--container", type=Path, help="original decompressed tableAssets.bin")
    source.add_argument("--source", type=Path, help="previously prepared seven-file directory")
    parser.add_argument("--dest", required=True, type=Path)
    args = parser.parse_args(argv)
    proof = json.loads(PROOF.read_text(encoding="utf-8"))
    catalog = TableCatalog(args.dest)
    for row in proof["tables"]:
        if catalog.resolve(row["name"]).file != row["name"] + ".json":
            raise ValueError("runtime table declaration mismatch")
    payloads = (from_container(args.container.read_bytes(), proof) if args.container else
                {row["name"] + ".json": (args.source / (row["name"] + ".json")).read_bytes()
                 for row in proof["tables"]})
    result = install(payloads, args.dest, proof)
    # Verify the runtime catalog can actually load every published root.
    for row in proof["tables"]:
        if len(catalog.load(row["name"])) != row["rows"]:
            raise ValueError("runtime row count mismatch")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
