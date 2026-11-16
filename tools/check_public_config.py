"""Reject public host literals and credential artifacts in tracked/staged files.

Never prints the matched value. This checks current content, not Git history.
Loopback/private/example address ranges remain usable for protocol examples.
"""
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
SECRET = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----|"
                    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})|"
                    r"(?m:^ssh-(?:rsa|ed25519) [A-Za-z0-9+/=]{64,})")
PRIVATE_FILE = re.compile(r"(?:\.local\.(?:json|ps1|toml)|\.(?:pem|key|env|sql\.gz))$|(?:^|/)\.env$")


def inspect(name: str, raw: bytes) -> list[tuple[int, str]]:
    if PRIVATE_FILE.search(name):
        return [(1, "private configuration or credential artifact is tracked")]
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return []
    findings = []
    for match in SECRET.finditer(content):
        findings.append((content.count("\n", 0, match.start()) + 1, "credential material"))
    for match in IPV4.finditer(content):
        try:
            address = ipaddress.IPv4Address(match.group())
        except ipaddress.AddressValueError:
            continue
        if address.is_global:
            findings.append((content.count("\n", 0, match.start()) + 1, "public IPv4 literal; use private configuration"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="check added/changed index content only")
    args = parser.parse_args()
    command = (["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
               if args.staged else ["git", "ls-files", "-z"])
    names = subprocess.check_output(command, cwd=ROOT).decode("utf-8").split("\0")
    failures = 0
    checked = 0
    for name in filter(None, names):
        if args.staged:
            raw = subprocess.check_output(["git", "show", ":" + name], cwd=ROOT)
        else:
            path = ROOT / name
            if not path.is_file():
                continue
            raw = path.read_bytes()
        checked += 1
        for line, reason in inspect(name, raw):
            print(f"{name}:{line}: {reason}")
            failures += 1
    print(f"public-config: checked={checked} findings={failures}; Git history not scanned")
    return int(failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
