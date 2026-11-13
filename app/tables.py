"""PC 客户端配置表加载器。

表文件不进入 Git。运行时只接受 ``docs/analysis/table_list.tsv`` 清单中的
108 张表，并按文件 mtime 热加载。每个 JSON 文件都必须以清单声明的 root key
包住表记录，例如 ``{"building": {...}}``。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import paths
from app.minijson import MiniJsonError, parse_json_document

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "docs" / "analysis" / "table_list.tsv"


class TableError(RuntimeError):
    """Base error for table loading failures."""


class UnknownTableError(TableError):
    """The requested table is not declared by the client manifest."""


class MissingTableError(TableError):
    """The requested table is declared but absent from the table directory."""


class InvalidTableError(TableError):
    """The table cannot be parsed or does not contain its declared root key."""


@dataclass(frozen=True)
class TableEntry:
    file: str
    root_key: str
    accessors: tuple[str, ...]


class TableCatalog:
    """Thread-safe, manifest-backed table store with mtime-based hot reload."""

    def __init__(
        self,
        table_dir: str | os.PathLike[str] | None = None,
        manifest_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.table_dir = Path(table_dir or paths.TABLE_DIR).resolve()
        self.manifest_path = Path(manifest_path or MANIFEST_PATH).resolve()
        self._entries = self._read_manifest()
        self._by_root = {entry.root_key: entry for entry in self._entries.values()}
        self._cache: dict[str, tuple[tuple[int, int], Any]] = {}
        self._lock = threading.RLock()

    def _read_manifest(self) -> dict[str, TableEntry]:
        if not self.manifest_path.is_file():
            raise TableError(f"table manifest not found: {self.manifest_path}")

        entries: dict[str, TableEntry] = {}
        with io.open(self.manifest_path, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                name = (row.get("table_file") or "").strip()
                root_key = (row.get("root_key") or "").strip()
                if not name or not root_key:
                    continue
                if Path(name).name != name:
                    raise TableError(f"unsafe table filename in manifest: {name!r}")
                entries[name] = TableEntry(
                    file=name,
                    root_key=root_key,
                    accessors=tuple(
                        item.strip()
                        for item in (row.get("accessor_classes") or "").split(",")
                        if item.strip()
                    ),
                )
        if not entries:
            raise TableError(f"table manifest is empty: {self.manifest_path}")
        return entries

    @property
    def entries(self) -> tuple[TableEntry, ...]:
        return tuple(self._entries.values())

    def resolve(self, name: str) -> TableEntry:
        """Accept either a manifest filename or a JSON root key."""
        entry = self._entries.get(name) or self._by_root.get(name)
        if entry is None:
            raise UnknownTableError(f"unknown table: {name}")
        return entry

    def path_for(self, name: str) -> Path:
        return self.table_dir / self.resolve(name).file

    def load(self, name: str) -> dict[str, Any]:
        """Load one table and return the value stored under its declared root key."""
        entry = self.resolve(name)
        path = self.table_dir / entry.file
        try:
            stat = path.stat()
        except FileNotFoundError as exc:
            raise MissingTableError(f"missing table: {entry.file}") from exc
        except OSError as exc:
            raise TableError(f"cannot stat table {entry.file}: {exc}") from exc

        signature = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._cache.get(entry.file)
            if cached and cached[0] == signature:
                return cached[1]

        try:
            raw = path.read_bytes()
            document = parse_json_document(raw)
        except FileNotFoundError as exc:
            raise MissingTableError(f"missing table: {entry.file}") from exc
        except (OSError, MiniJsonError) as exc:
            raise InvalidTableError(f"invalid table {entry.file}: {exc}") from exc

        if not isinstance(document, dict) or entry.root_key not in document:
            raise InvalidTableError(
                f"{entry.file} does not contain root key {entry.root_key!r}"
            )
        root = document[entry.root_key]
        if not isinstance(root, dict):
            raise InvalidTableError(
                f"{entry.file} root key {entry.root_key!r} must contain an object"
            )

        with self._lock:
            self._cache[entry.file] = (signature, root)
        return root

    def missing(self) -> list[str]:
        return sorted(
            entry.file
            for entry in self._entries.values()
            if not (self.table_dir / entry.file).is_file()
        )

    def check(self) -> list[str]:
        """Return human-readable diagnostics without raising on individual tables."""
        issues: list[str] = []
        expected = self._imported_hashes()
        for entry in self._entries.values():
            try:
                self.load(entry.file)
            except TableError as exc:
                issues.append(str(exc))
                continue
            digest = expected.get(entry.file)
            if digest:
                try:
                    actual = hashlib.sha256(
                        (self.table_dir / entry.file).read_bytes()
                    ).hexdigest()
                except OSError as exc:
                    issues.append(f"cannot read table {entry.file}: {exc}")
                    continue
                if actual != digest:
                    issues.append(
                        f"checksum drift: {entry.file} "
                        f"(expected {digest[:12]}, got {actual[:12]})"
                    )
        return issues

    def _imported_hashes(self) -> dict[str, str]:
        manifest = self.table_dir / "import-manifest.json"
        if not manifest.is_file():
            return {}
        try:
            with io.open(manifest, encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        records = document.get("tables") if isinstance(document, dict) else None
        if not isinstance(records, list):
            return {}
        return {
            str(record["file"]): str(record["sha256"])
            for record in records
            if isinstance(record, dict)
            and record.get("file")
            and record.get("sha256")
            and record.get("status") in {"copied", "checked"}
        }


_DEFAULT_CATALOG: TableCatalog | None = None
_DEFAULT_LOCK = threading.Lock()


def default_catalog() -> TableCatalog:
    global _DEFAULT_CATALOG
    with _DEFAULT_LOCK:
        if _DEFAULT_CATALOG is None:
            _DEFAULT_CATALOG = TableCatalog()
        return _DEFAULT_CATALOG


def reset_default_catalog() -> None:
    """Drop the process-wide catalog, mainly for tests and configuration reloads."""
    global _DEFAULT_CATALOG
    with _DEFAULT_LOCK:
        _DEFAULT_CATALOG = None


def load(name: str) -> dict[str, Any]:
    return default_catalog().load(name)
