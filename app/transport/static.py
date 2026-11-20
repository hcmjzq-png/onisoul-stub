"""PC WebPlayer and AssetBundle static-file routing."""
from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app import paths, environment

CROSSDOMAIN_XML = (
    b'<?xml version="1.0"?>\n'
    b"<cross-domain-policy>\n"
    b'  <allow-access-from domain="*"/>\n'
    b"</cross-domain-policy>\n"
)

NO_STORE = "no-store, no-cache, must-revalidate"
ASSET_CACHE = "public, max-age=600"


class StaticPathError(ValueError):
    """The request path is malformed or escapes a configured asset root."""


@dataclass(frozen=True)
class StaticResource:
    content_type: str
    cache_control: str
    length: int
    last_modified: float | None = None
    path: Path | None = None
    body: bytes | None = None

    @property
    def size(self) -> int:
        return self.length


def _content_type(path: Path) -> str:
    if path.suffix.lower() in {".unity3d", ".unity"}:
        return "application/octet-stream"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _cache_control(path: Path) -> str:
    if path.name.lower() in {"app.html", "app.unity3d", "crossdomain.xml"}:
        return NO_STORE
    if path.suffix.lower() in {".html", ".htm", ".js", ".css"}:
        return NO_STORE
    return ASSET_CACHE


def _safe_parts(url_path: str) -> list[str]:
    if "\x00" in url_path or "\\" in url_path:
        raise StaticPathError("invalid path separator")
    decoded = unquote(url_path)
    if "\x00" in decoded or "\\" in decoded:
        raise StaticPathError("invalid path separator")
    parts = [part for part in decoded.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise StaticPathError("path traversal is not allowed")
    return parts


class StaticFiles:
    def __init__(
        self,
        web_dir: str | os.PathLike[str] | None = None,
        bundle_dir: str | os.PathLike[str] | None = None,
        cache_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self.web_dir = Path(web_dir or paths.PC_WEB_DIR).resolve()
        self.bundle_dir = Path(bundle_dir or paths.PC_BUNDLE_DIR).resolve()
        self.cache_dir = Path(cache_dir or paths.PC_CACHE_DIR).resolve()

    @staticmethod
    def _under(root: Path, relative: Path) -> Path | None:
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise StaticPathError("path escapes configured asset root") from exc
        return candidate if candidate.is_file() else None

    def _file(
        self,
        root: Path,
        relative: Path,
        *,
        cache_control: str | None = None,
    ) -> StaticResource | None:
        path = self._under(root, relative)
        if path is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        if path.name == 'app.html' and environment.identity():
            body = environment.mark_html(path.read_bytes())
            return StaticResource(content_type='text/html; charset=utf-8',
                cache_control=NO_STORE, length=len(body), body=body)
        return StaticResource(
            content_type=_content_type(path),
            cache_control=cache_control or _cache_control(path),
            length=stat.st_size,
            last_modified=stat.st_mtime,
            path=path,
        )

    def _bundle(self, parts: list[str]) -> StaticResource | None:
        if len(parts) < 5 or parts[:3] != ["client", "pc", "jp"]:
            return None
        if parts[3] not in {"assets", "assets2"}:
            return None
        tail = Path(*parts[4:])
        category = tail.parts[0] if len(tail.parts) > 2 else tail.parent.name
        name = tail.name
        candidates = [
            (self.bundle_dir, tail),
            (self.cache_dir, tail),
            (self.cache_dir, Path(name)),
        ]
        if category and category != ".":
            candidates.extend(
                [
                    (self.bundle_dir, tail.parent / f"{category}__{name}"),
                    (self.cache_dir, tail.parent / f"{category}__{name}"),
                    (self.cache_dir, Path(f"{category}__{name}")),
                ]
            )
        for root, relative in candidates:
            resource = self._file(root, relative, cache_control=ASSET_CACHE)
            if resource is not None:
                return resource
        return None

    def resolve(self, target: str) -> StaticResource | None:
        """Resolve a GET target to a configured file.

        Returns ``None`` for a valid URL with no local file. Malformed or
        traversal-like paths raise ``StaticPathError`` so the HTTP layer can
        distinguish a bad request from a missing asset.
        """
        path = urlsplit(target).path
        parts = _safe_parts(path)
        if not parts:
            return self._file(self.web_dir, Path("client") / "app.html", cache_control=NO_STORE)

        if parts == ["crossdomain.xml"]:
            override = self._file(
                self.web_dir, Path("crossdomain.xml"), cache_control=NO_STORE
            )
            if override is not None:
                return override
            return StaticResource(
                content_type="application/xml; charset=utf-8",
                cache_control=NO_STORE,
                length=len(CROSSDOMAIN_XML),
                body=CROSSDOMAIN_XML,
            )

        if parts == ["app.html"]:
            return self._file(
                self.web_dir,
                Path("client") / "app.html",
                cache_control=NO_STORE,
            )

        if parts[:3] == ["client", "pc", "jp"]:
            resource = self._bundle(parts)
            if resource is not None or (len(parts) > 3 and parts[3] in {"assets", "assets2"}):
                return resource

        if parts[0] == "client":
            resource = self._file(self.web_dir, Path(*parts))
            if resource is None and parts == ["client", "inbox", "inbox_mid.html"]:
                # InboxReader uses this URL for every layout except Low.
                return self._file(self.web_dir, Path("client", "inbox", "inbox.html"))
            if resource is not None or not parts[-1].lower().endswith((".unity3d", ".unity")):
                return resource

        if parts[-1].lower().endswith((".unity3d", ".unity")):
            name = Path(parts[-1])
            for root in (self.bundle_dir, self.cache_dir, self.web_dir / "client"):
                resource = self._file(root, name, cache_control=ASSET_CACHE)
                if resource is not None:
                    return resource
        return None
