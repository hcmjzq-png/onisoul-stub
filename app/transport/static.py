"""PC WebPlayer and AssetBundle static-file routing."""
from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app import paths

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
    path: Path | None = None
    body: bytes | None = None

    @property
    def size(self) -> int:
        if self.path is not None:
            return self.path.stat().st_size
        return len(self.body or b"")


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
        return StaticResource(
            content_type=_content_type(path),
            cache_control=cache_control or _cache_control(path),
            path=path,
        )

    def _bundle(self, parts: list[str]) -> StaticResource | None:
        # /client/pc/jp/assets/<category>/<name>
        if len(parts) != 6 or parts[:4] != ["client", "pc", "jp", "assets"]:
            return None
        category, name = parts[4], parts[5]
        candidates = (
            (self.bundle_dir, Path(category) / name),
            (self.bundle_dir, Path(category) / f"{category}__{name}"),
            (self.cache_dir, Path(category) / name),
            (self.cache_dir, Path(category) / f"{category}__{name}"),
            (self.cache_dir, Path(f"{category}__{name}")),
            (self.cache_dir, Path(name)),
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
            return None

        if parts == ["crossdomain.xml"]:
            override = self._file(
                self.web_dir, Path("crossdomain.xml"), cache_control=NO_STORE
            )
            if override is not None:
                return override
            return StaticResource(
                content_type="application/xml; charset=utf-8",
                cache_control=NO_STORE,
                body=CROSSDOMAIN_XML,
            )

        if parts[:4] == ["client", "pc", "jp", "assets"]:
            return self._bundle(parts)

        if parts[0] != "client":
            return None
        return self._file(self.web_dir, Path(*parts))
