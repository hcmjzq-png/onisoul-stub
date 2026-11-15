"""Apply a historical one-file candidate patch by unique unchanged context.

Line numbers are hints for its original base, not offsets in today's source.
Ambiguous or changed context must fail instead of executing a misplaced patch.
"""
from __future__ import annotations

import re


def apply_context(source: str, patch: str) -> str:
    result = source.splitlines(True)
    hunks = re.split(r"(?m)^@@[^\n]*\n", patch)[1:]
    cursor = 0
    for hunk in hunks:
        old, new = [], []
        for line in hunk.splitlines(True):
            if line == "\n":
                line = " \n"
            if line.startswith((" ", "-")):
                old.append(line[1:])
            if line.startswith((" ", "+")):
                new.append(line[1:])
        matches = [i for i in range(cursor, len(result) - len(old) + 1)
                   if result[i:i + len(old)] == old]
        if len(matches) != 1:
            raise AssertionError(f"candidate patch context has {len(matches)} matches")
        at = matches[0]
        result[at:at + len(old)] = new
        cursor = at + len(new)
    return "".join(result)
