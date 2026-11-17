"""Package and add verified castle bundles without replacing existing assets.

The installer uses only Python's standard library and may run on the server.
It checks the whole archive before linking files and rolls back only its own
additions if HTTP verification fails. Original assets and backups are retained.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ENGINE_SHA256 = "0163227eb92c799322ea26ade936216c766d9d44397d095e8dcec34bbdc00fb5"
SHA256 = re.compile(r"[0-9a-f]{64}")
LOGICAL = re.compile(r"building\d{5}")
MAX_BLOB = 8 * 1024 * 1024


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected_model(tribe: str, grade: int) -> str:
    codes = {"human": "002", "oni": "001", "evil": "000"}
    if tribe not in codes or type(grade) is not int or grade not in range(1, 6):
        raise ValueError("invalid tribe/grade")
    return f"building200_{codes[tribe]}_{grade:02}_01_1_1"


def validate_plan(plan: dict) -> None:
    if plan.get("schema") != 1 or plan.get("engine_sha256") != ENGINE_SHA256:
        raise ValueError("publication schema/engine mismatch")
    files = plan.get("files", [])
    if len(files) != 15:
        raise ValueError("fifteen castle records required")
    seen, relative = set(), set()
    for row in files:
        identity = row["tribe"], row["grade"]
        if identity in seen or row["model"] != expected_model(*identity):
            raise ValueError("duplicate or mismatched castle identity")
        seen.add(identity)
        if not LOGICAL.fullmatch(row["logical"]):
            raise ValueError("invalid building group")
        name = hashlib.md5(row["logical"].encode("utf-16le")).hexdigest() + ".unity3d"
        if row["relative"] != "building/" + name or row["relative"] in relative:
            raise ValueError("unsafe or duplicated castle path")
        relative.add(row["relative"])
        if not SHA256.fullmatch(row["sha256"]) or type(row["bytes"]) is not int or not 0 < row["bytes"] <= MAX_BLOB:
            raise ValueError("invalid castle fingerprint/size")
        if row["action"] not in ("add", "preserve"):
            raise ValueError("invalid publication action")
        if row["member"] != ("blobs/" + name if row["action"] == "add" else None):
            raise ValueError("unexpected archive member")
    if sum(r["action"] == "preserve" for r in files) != 1 or not any(
        r["tribe"] == "human" and r["grade"] == 1 and r["action"] == "preserve" for r in files
    ):
        raise ValueError("the existing human grade-1 original must be preserved")


def build_archive(release: Path, archive_path: Path) -> dict:
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    evidence = json.loads((release / "native-results.json").read_text(encoding="utf-8"))
    if evidence["engine_sha256"] != ENGINE_SHA256 or evidence["passed"] != 15 or evidence["expected"] != 15:
        raise ValueError("complete original-engine evidence required")
    verified = {r["name"]: r for r in evidence["results"]}
    if len(verified) != 15 or manifest.get("native_verified_count") != 15:
        raise ValueError("missing/duplicated native result")
    records, blobs = [], {}
    for row in manifest["files"]:
        native = verified[row["building_id"]]
        if not row["native_verified"] or not native["loaded"] or not native["instantiated"]:
            raise ValueError("castle was not natively instantiated")
        if native["output_sha256"] != row["sha256"] or native["components"] != {"Animation": 1, "MeshRenderer": 1, "MeshCollider": 1}:
            raise ValueError("native evidence does not match castle")
        blob = Path(row["bundle"]).read_bytes()
        if sha(blob) != row["sha256"] or not blob.startswith(b"UnityWeb"):
            raise ValueError("verified castle bundle changed")
        name = Path(row["bundle"]).name
        record = {"tribe": row["tribe"], "grade": row["grade"], "model": row["building_id"],
                  "logical": row["logical"], "relative": "building/" + name,
                  "sha256": sha(blob), "bytes": len(blob),
                  "action": "preserve" if row["pc_existing"] else "add",
                  "member": None if row["pc_existing"] else "blobs/" + name}
        records.append(record)
        if record["member"]:
            blobs[record["member"]] = blob
    plan = {"schema": 1, "engine_sha256": ENGINE_SHA256,
            "native_evidence_sha256": sha((release / "native-results.json").read_bytes()), "files": records}
    validate_plan(plan)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "x") as archive:
        for name, data in {"manifest.json": json.dumps(plan, indent=2).encode(), **blobs}.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o644
            archive.addfile(info, io.BytesIO(data))
    return {"files": 15, "additions": len(blobs), "preserved": 1, "archive_sha256": sha(archive_path.read_bytes())}


def read_archive(path: Path) -> tuple[dict, dict[str, bytes]]:
    with tarfile.open(path, "r:") as archive:
        members = archive.getmembers()
        if any(not m.isfile() for m in members) or len({m.name for m in members}) != len(members):
            raise ValueError("non-regular or duplicated archive member")
        manifest = archive.getmember("manifest.json")
        if manifest.size > 128 * 1024:
            raise ValueError("manifest too large")
        plan = json.loads(archive.extractfile(manifest).read())
        validate_plan(plan)
        expected = {"manifest.json", *(r["member"] for r in plan["files"] if r["member"])}
        if {m.name for m in members} != expected:
            raise ValueError("unexpected archive member set")
        blobs = {}
        for row in plan["files"]:
            if not row["member"]:
                continue
            member = archive.getmember(row["member"])
            if member.size != row["bytes"]:
                raise ValueError("archive size mismatch")
            blob = archive.extractfile(member).read(MAX_BLOB + 1)
            if len(blob) != row["bytes"] or sha(blob) != row["sha256"]:
                raise ValueError("archive fingerprint mismatch")
            blobs[row["relative"]] = blob
    return plan, blobs


def verify_http(plan: dict, bases: list[str]) -> list[dict]:
    if not bases:
        raise ValueError("at least one HTTP verification base is required")
    checks = []
    for base in bases:
        for namespace in ("assets", "assets2"):
            for row in plan["files"]:
                url = base.rstrip("/") + "/client/pc/jp/" + namespace + "/" + row["relative"]
                request = urllib.request.Request(url, headers={"Host": "game-onisoul.86joy.com"})
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(request, timeout=15) as response:
                            body = response.read(MAX_BLOB + 1)
                            if response.status != 200 or len(body) != row["bytes"] or sha(body) != row["sha256"]:
                                raise ValueError("HTTP verification failed: " + row["relative"])
                        break
                    except urllib.error.HTTPError:
                        raise
                    except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
                        if attempt == 2:
                            raise RuntimeError("HTTP transport failed: " + url) from error
                        time.sleep(0.2 * (attempt + 1))
                checks.append({"url": url, "sha256": row["sha256"], "bytes": len(body), "status": 200})
    return checks


def install_archive(archive_path: Path, bundle_root: Path, backup_root: Path, http_bases: list[str]) -> dict:
    plan, blobs = read_archive(archive_path)
    root = bundle_root.resolve()
    if not root.is_dir() or not (root / "building").is_dir():
        raise ValueError("an existing PC bundle/building root is required")
    targets = {}
    for row in plan["files"]:
        target = (root / Path(*PurePosixPath(row["relative"]).parts)).resolve()
        target.relative_to(root)
        if target.exists() and (not target.is_file() or sha(target.read_bytes()) != row["sha256"]):
            raise ValueError("existing castle differs; refusing overwrite: " + row["relative"])
        if row["action"] == "preserve" and not target.is_file():
            raise ValueError("existing original castle is missing")
        targets[row["relative"]] = target
    before = {p.relative_to(root).as_posix(): sha(p.read_bytes())
              for p in sorted((root / "building").rglob("*")) if p.is_file()}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    backup = backup_root.resolve() / ("castles15-" + stamp)
    backup.mkdir(parents=True, mode=0o700)
    originals = backup / "originals"
    for relative in before:
        destination = originals / Path(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / Path(*PurePosixPath(relative).parts), destination)
    shutil.copyfile(archive_path, backup / "release.tar")
    (backup / "before.json").write_text(json.dumps(before, indent=2) + "\n", encoding="utf-8")
    stage = Path(tempfile.mkdtemp(prefix=".castle15-", dir=root.parent)).resolve()
    created, kept = [], []
    try:
        for relative, blob in blobs.items():
            (stage / Path(relative).name).write_bytes(blob)
        for row in plan["files"]:
            target = targets[row["relative"]]
            if target.exists():
                if sha(target.read_bytes()) != row["sha256"]:
                    raise ValueError("castle changed during publication")
                kept.append(row["relative"])
                continue
            if row["action"] != "add":
                raise ValueError("cannot create an absent original")
            try:
                os.link(stage / target.name, target)
            except FileExistsError:
                if not target.is_file() or sha(target.read_bytes()) != row["sha256"]:
                    raise ValueError("castle appeared with different content")
                kept.append(row["relative"])
            else:
                created.append(row["relative"])
        checks = verify_http(plan, http_bases)
        for relative, fingerprint in before.items():
            if sha((root / Path(*PurePosixPath(relative).parts)).read_bytes()) != fingerprint:
                raise RuntimeError("pre-existing building changed")
        result = {"created": created, "kept": kept, "verified_castles": len(plan["files"]),
                  "http_checks": checks, "existing_building_files_preserved": len(before),
                  "backup": str(backup), "status": "complete"}
        (backup / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    except Exception:
        # Remove only additions whose exact digest still matches this release.
        expected = {r["relative"]: r["sha256"] for r in plan["files"]}
        for relative in reversed(created):
            target = targets[relative]
            if target.is_file() and sha(target.read_bytes()) == expected[relative]:
                target.unlink()
        raise
    finally:
        # Flat, known staging files only; no recursive deletion of computed paths.
        if stage.parent != root.parent or not stage.name.startswith(".castle15-"):
            raise RuntimeError("invalid staging cleanup path")
        for path in stage.iterdir():
            if not path.is_file() or path.is_symlink():
                raise RuntimeError("unexpected staging entry")
            path.unlink()
        stage.rmdir()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--release", type=Path, required=True)
    build.add_argument("--archive", type=Path, required=True)
    install = commands.add_parser("install")
    install.add_argument("--archive", type=Path, required=True)
    install.add_argument("--bundle-root", type=Path, required=True)
    install.add_argument("--backup-root", type=Path, required=True)
    install.add_argument("--http-base", action="append", required=True)
    install.add_argument("--result", type=Path)
    args = ap.parse_args()
    if args.command == "build":
        print(json.dumps(build_archive(args.release, args.archive)))
    else:
        result = install_archive(args.archive, args.bundle_root, args.backup_root, args.http_base)
        if args.result:
            args.result.parent.mkdir(parents=True, exist_ok=True)
            args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k:v for k,v in result.items() if k != "http_checks"} | {"http_checks_passed":len(result["http_checks"])}))


if __name__ == "__main__":
    main()
