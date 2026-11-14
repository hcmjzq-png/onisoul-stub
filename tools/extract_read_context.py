#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户端读键上下文抽取（数据不入仓，只入仓这个脚本）。

用途：把反编译出来的 .cs 树扫一遍，产出三张 TSV，供
`tools/unguarded_reads.py gap --receivers/--origins` 与裸键定型使用：

  read_context.tsv      class / method / line / key / receiver / cast / write / usage
  key_type_profile.tsv  key / kind / type / count        （cast / accessor / bare / write 计数）
  type_evidence.tsv     key / status / type / kind / evidence / receiver
                        status ∈ single_type / conflict / no_evidence

用法：
  python3 tools/extract_read_context.py --root /path/to/il_csharp/app --out /tmp/ctx

口径与 docs/analysis/unguarded-reads.md 一致：只认 `["字面键名"]`（KEY_RE 同扫描器），
`]` 之后紧跟 `=` 记为写侧；类型证据取 `]` 前的强转与 `]` 之后的访问器调用
（getInt/getLong/getDouble/getFloat/getBool/getString/getHashtable/ToString）。

注意：产物含客户端文件名与行号，按仓库约定**不入仓**，留在本机即可。
"""
import argparse
import collections
import io
import os
import re

METHOD_RE = re.compile(
    r"^\t+(?:public|private|protected|internal)\s"
    r"(?:static\s+|virtual\s+|override\s+|new\s+|sealed\s+)*"
    r"[^\n;{}=]{0,120}?\b([A-Za-z_]\w*)\s*\(",
    re.M,
)
KEY_RE = re.compile(r'\["([A-Za-z_][A-Za-z0-9_]*)"\]')
ACCESSOR_RE = re.compile(
    r"(get(?:Int|Long|Double|Bool|String|Float|Hashtable|Array))\s*\("
)
CAST_RE = re.compile(r"\(([A-Za-z_][A-Za-z0-9_]*)\)")
ACCESSOR_TYPE = {
    "getInt": "int", "getLong": "long", "getDouble": "double", "getFloat": "float",
    "getBool": "bool", "getString": "string", "getHashtable": "Hashtable",
    "getArray": "ArrayList", "ToString": "string",
}


def method_ranges(text):
    """按 `{`/`}` 配对切方法体，返回 [(方法名, body_start, body_end)]。"""
    out = []
    for m in METHOD_RE.finditer(text):
        i = text.find("{", m.end())
        if i < 0:
            continue
        depth, j = 0, i
        while j < len(text):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        out.append((m.group(1), i, j))
    return out


def scan(root):
    rows = []
    files = 0
    for dp, _, fs in os.walk(root):
        for f in sorted(fs):
            if not f.endswith(".cs"):
                continue
            files += 1
            cls = f[:-3]
            try:
                text = io.open(os.path.join(dp, f), encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            for name, b0, b1 in method_ranges(text):
                body = text[b0:b1]
                for km in KEY_RE.finditer(body):
                    key = km.group(1)
                    pos = b0 + km.start()
                    line_no = text.count("\n", 0, pos) + 1
                    ls = text.rfind("\n", 0, pos) + 1
                    le = text.find("\n", pos)
                    line = text[ls:(le if le > 0 else len(text))]
                    head = line[: pos - ls].rstrip()
                    mt = re.findall(r"[A-Za-z_][\w\.]*", head)
                    recv = mt[-1] if mt else ""
                    tail = line[pos - ls + len(km.group(0)):]
                    is_write = bool(re.match(r"\s*=", tail))
                    cast = "".join("(%s)" % x for x in CAST_RE.findall(head[-40:]))
                    rows.append((cls, name, line_no, key, recv, cast,
                                 "W" if is_write else "R", tail.strip()[:40]))
    return files, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="反编译树根目录（含 .cs 文件）")
    ap.add_argument("--out", required=True, help="输出目录")
    a = ap.parse_args()

    files, rows = scan(a.root)
    if not os.path.isdir(a.out):
        os.makedirs(a.out)

    io.open(os.path.join(a.out, "read_context.tsv"), "w",
            encoding="utf-8", newline="\n").write(
        "class\tmethod\tline\tkey\treceiver\tcast\twrite\tusage\n" +
        "".join("%s\t%s\t%d\t%s\t%s\t%s\t%s\t%s\n" % r for r in rows))

    usage = collections.defaultdict(collections.Counter)
    evidence = collections.defaultdict(list)
    for cls, method, line, key, recv, cast, w, tail in rows:
        if w == "W":
            usage[key][("write", "")] += 1
            continue
        tint = cast.strip("()").split(")(")[-1].strip("()") if cast else ""
        acc = next((x for x in ACCESSOR_RE.findall(tail)[:1]), "")
        if ".ToString(" in tail and not acc:
            acc = "ToString"
        if tint:
            usage[key][("cast", tint)] += 1
        elif acc:
            usage[key][("accessor", ACCESSOR_TYPE.get(acc, acc))] += 1
        else:
            usage[key][("bare", "")] += 1
        evidence[key].append((
            "cast" if tint else ("accessor" if acc else "bare"),
            tint or ACCESSOR_TYPE.get(acc, ""),
            "%s.cs:%d" % (cls, line), recv,
        ))

    prof = ["key\tkind\ttype\tcount"]
    for k in sorted(usage):
        for (kind, t), n in sorted(usage[k].items()):
            prof.append("%s\t%s\t%s\t%d" % (k, kind, t, n))
    io.open(os.path.join(a.out, "key_type_profile.tsv"), "w",
            encoding="utf-8", newline="\n").write("\n".join(prof) + "\n")

    evl = ["key\tstatus\ttype\tkind\tevidence\treceiver"]
    stats = collections.Counter()
    for k in sorted(evidence):
        kinds = {e[0] for e in evidence[k]}
        types = {e[1] for e in evidence[k] if e[1]}
        if kinds == {"bare"} or not types:
            st, t = "no_evidence", ""
        elif len(types) == 1:
            st, t = "single_type", list(types)[0]
        else:
            st, t = "conflict", "|".join(sorted(types))
        stats[st] += 1
        best = sorted(evidence[k], key=lambda e: (e[0] == "bare", e[2]))[0]
        evl.append("%s\t%s\t%s\t%s\t%s\t%s" % (k, st, t, best[0], best[2], best[3]))
    io.open(os.path.join(a.out, "type_evidence.tsv"), "w",
            encoding="utf-8", newline="\n").write("\n".join(evl) + "\n")

    print("files=%d reads=%d keys=%d %s" % (files, len(rows), len(evidence), dict(stats)))


if __name__ == "__main__":
    main()
