#!/usr/bin/env python3
"""Import only the 108 client-declared JSON tables into the runtime directory."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import paths  # noqa: E402
from app.tables import MANIFEST_PATH  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate(path: Path, root_key: str) -> str | None:
    try:
        with io.open(path, encoding="utf-8-sig") as handle:
            document = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return f"invalid JSON: {exc}"
    if not isinstance(document, dict) or root_key not in document:
        return f"missing root key: {root_key}"
    if not isinstance(document[root_key], dict):
        return f"root key must contain an object: {root_key}"
    return None


def read_manifest(path: Path) -> list[dict[str, str]]:
    with io.open(path, encoding="utf-8", newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle, delimiter="\t")
            if (row.get("table_file") or "").strip()
        ]


def atomic_manifest(path: Path, records: list[dict[str, Any]]) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    with io.open(temp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {"schema": 1, "tables": records},
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")
    os.replace(temp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="directory containing extracted JSON tables")
    parser.add_argument("--dest", default=str(paths.TABLE_DIR), help="runtime table directory")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH), help="client table manifest TSV")
    parser.add_argument("--check-only", action="store_true", help="validate without copying")
    parser.add_argument("--strict", action="store_true", help="return failure when manifest tables are missing")
    parser.add_argument("--json", action="store_true", help="print a machine-readable report")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    dest = Path(args.dest).resolve()
    manifest = Path(args.manifest).resolve()
    if not source.is_dir():
        parser.error(f"source directory not found: {source}")
    if not manifest.is_file():
        parser.error(f"manifest not found: {manifest}")

    if not args.check_only:
        dest.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for row in read_manifest(manifest):
        name = row["table_file"].strip()
        root_key = (row.get("root_key") or "").strip()
        source_file = source / name
        target_file = dest / name

        if not source_file.is_file():
            records.append(
                {
                    "file": name,
                    "root_key": root_key,
                    "status": "missing",
                }
            )
            continue

        problem = validate(source_file, root_key)
        digest = sha256(source_file)
        record: dict[str, Any] = {
            "file": name,
            "root_key": root_key,
            "bytes": source_file.stat().st_size,
            "sha256": digest,
            "status": "invalid" if problem else ("checked" if args.check_only else "copied"),
        }
        if problem:
            record["error"] = problem
        elif not args.check_only:
            temp = target_file.with_name(f".{target_file.name}.tmp")
            shutil.copy2(source_file, temp)
            os.replace(temp, target_file)
        records.append(record)

    copied = sum(record["status"] in {"copied", "checked"} for record in records)
    missing = sum(record["status"] == "missing" for record in records)
    invalid = sum(record["status"] == "invalid" for record in records)
    report = {
        "manifest": str(manifest),
        "source": str(source),
        "dest": str(dest),
        "manifest_count": len(records),
        "ready": copied,
        "missing": missing,
        "invalid": invalid,
        "records": records,
    }

    if not args.check_only:
        manifest_out = dest / "import-manifest.json"
        atomic_manifest(manifest_out, records)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"[tables] manifest={len(records)} ready={copied} "
            f"missing={missing} invalid={invalid}"
        )
        for record in records:
            if record["status"] in {"missing", "invalid"}:
                detail = record.get("error", "not found")
                print(f"[tables] {record['status']}: {record['file']} ({detail})")

    if invalid:
        return 1
    if args.strict and missing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
