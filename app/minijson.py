"""Compatibility parser for JSON TextAssets emitted by MiniJSON."""
from __future__ import annotations

import json
from typing import Any


class MiniJsonError(ValueError):
    """The bytes are not a MiniJSON-compatible JSON document."""


def _strip_trailing_commas(text: str) -> str:
    """Remove commas before ``}``/``]`` without touching string literals."""
    output: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue

        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue

        output.append(char)
        index += 1
    return "".join(output)


def parse_json_document(raw: bytes | str) -> Any:
    """Parse one MiniJSON document.

    Standard JSON is accepted first. For client TextAssets, trailing commas are
    removed outside strings and the first complete value is decoded. The latter
    also handles a small number of text files that contain concatenated JSON
    documents.
    """
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise MiniJsonError(f"invalid UTF-8: {exc}") from exc
    else:
        text = raw.lstrip("\ufeff")

    try:
        return json.loads(text)
    except json.JSONDecodeError as strict_error:
        cleaned = _strip_trailing_commas(text)
        start = len(cleaned) - len(cleaned.lstrip())
        try:
            document, _end = json.JSONDecoder().raw_decode(cleaned, start)
            return document
        except json.JSONDecodeError as compatible_error:
            raise MiniJsonError(
                f"MiniJSON parse failed: {compatible_error.msg} "
                f"at line {compatible_error.lineno} column {compatible_error.colno}"
            ) from strict_error
