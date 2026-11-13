"""无守卫读键扫描器：从反编译 C# 抽命名键读取点，与契约表对账。

两段式流水线（dump 可复用，gap 只读 dump，不必重扫 2034 个 .cs）：

    python3 tools/unguarded_reads.py dump --src <il_csharp/app> --out reads.tsv
    python3 tools/unguarded_reads.py gap --dump reads.tsv \
        --contract docs/analysis/api_contract.tsv --out docs/analysis/unguarded_gaps.tsv

dump：所有方法里的 `["命名键"]` 读取点，按 (类,方法,键) 去重；列
`file / class / method / line / key / cast / guarded / snippet`。
`guarded=1` 表示方法体内出现过 `ContainsKey("同一键")`；`cast` 是 `[` 前面
紧邻的强转序列，形如 `(int)((double)`（能看出读的是 `double` 还是 `Hashtable`）。

gap：只取契约表 `call_sites` 里的 `Class.method`，把它们的**无守卫**读取键与
该端点 `response_keys` 的**根段**比较（`a.b` 视为声明了根 `a`），输出「客户端
无守卫读、契约未声明」的候选行：`endpoint / callsite / missing_keys / first_evidence`。
保留键 `succeeded / now / errorReason` 视为已声明。

口径与已知误报（不要当成精确结论）：
* 守卫是**方法级**的：`if (ht.ContainsKey("x"))` 能识别；`isEventOpen("x")`、
  `if (ht != null)`、或守卫写在 helper 里（如 `StatusView.isEventOpen`）看不到。
* 归属是**方法级**的：一个方法里连发多个请求时，读键无法判给哪个响应。
* 只匹配 `call_sites` 里那个方法本身：DTO/构造函数里的读取不计入。
* 读的对象不一定是响应根：形参、请求参数回读、文案常量（`STRATEGY_MSG_*`）
  都会被当成响应键读，属误报。

来源过滤（`gap --filter origin --receivers ... --origins ...`）：候选里 67/104 是这类误报，
它们的共同特征是「读的接收者不是本端点的回包对象」。`--receivers` 给 (调用点,键) 的接收者
取证（`receiver` 是 `["键"]` 前的表达式，`write=W` 表示写侧），`--origins` 给
「这个接收者不是回包」的来源类别；命中即剔除该键，**没被取证覆盖的一律保留**。
不加 `--filter`（默认 `none`）就是过滤前口径，产出 104 行快照；`dump` 段两者共用、数字不变。
"""
import argparse
import collections
import csv
import fnmatch
import io
import os
import re
import sys

METHOD_RE = re.compile(
    r"^(\t+)(?:public|private|protected|internal)\s"
    r"(?:static\s+|virtual\s+|override\s+|new\s+|sealed\s+)*"
    r"[^\n;{}=]{0,120}?\b([A-Za-z_]\w*)\s*\(",
    re.M,
)
KEY_RE = re.compile(r'\["([A-Za-z_][A-Za-z0-9_]*)"\]')
CAST_RE = re.compile(r"\(([A-Za-z_][A-Za-z0-9_]*)\)")
CALLSITE_RE = re.compile(r"^[A-Za-z_]\w*\.[A-Za-z_]\w*$")
RESERVED = {"succeeded", "now", "errorReason"}
RECEIVER_FIELDS = ["callsite", "key", "line", "receiver", "write"]
ORIGIN_FIELDS = ["callsite", "receiver", "origin", "evidence"]
# 读的不是响应回包的来源类别（--filter origin 的 denylist 词表）
ORIGINS = {
    "write",          # 写侧：`ht["k"] = ...`，不是读
    "html_request",   # HTML 表单 / 请求参数回读
    "task_param",     # 任务参数（task.TaskParams）
    "config_table",   # 配置表访问器
    "dialog_result",  # UI 对话框结果哈希
    "local_build",    # 方法内自建的临时表
    "debug_build",    # debug 分支自造的表
    "message_table",  # 消息表（STRATEGY_MSG_* 等）
}
SNIPPET_MAX = 70
BODY_LIMIT = 4000
FIELDS = ["file", "class", "method", "line", "key", "cast", "guarded", "snippet"]
GAP_FIELDS = ["endpoint", "callsite", "missing_keys", "first_evidence"]


def method_body(text, sig_end):
    """从签名结尾找方法体的 `{`，按花括号配平截出 body。"""
    i = text.find("{", sig_end)
    if i < 0 or i - sig_end > 800:
        return "", -1
    depth = 0
    j = i
    while j < len(text) and j - i < BODY_LIMIT:
        ch = text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1], i
        j += 1
    return text[i:i + BODY_LIMIT], i


def casts_before(text, pos, window=60):
    """取 `[` 之前紧邻的强转序列。"""
    casts = CAST_RE.findall(text[max(0, pos - window):pos])
    if not casts:
        return ""
    if len(casts) == 1:
        return "(" + casts[0] + ")"
    return "(" + ")((".join(casts) + ")"


def scan(src):
    rows = []
    files = 0
    for dirpath, _, names in os.walk(src):
        names.sort()
        for name in names:
            if not name.endswith(".cs"):
                continue
            files += 1
            path = os.path.join(dirpath, name)
            text = io.open(path, encoding="utf-8-sig", errors="replace").read()
            rel = os.path.relpath(path, src).replace(os.sep, "/")
            cls = name[:-3]
            for m in METHOD_RE.finditer(text):
                method = m.group(2)
                body, body_at = method_body(text, m.end())
                if not body or body_at < 0:
                    continue
                guards = set(re.findall(r'ContainsKey\("([^"]+)"\)', body))
                for k in KEY_RE.finditer(body):
                    key = k.group(1)
                    pos = body_at + k.start()
                    line = text[:pos].count("\n") + 1
                    snippet = " ".join(body[max(0, k.start() - 40):k.start() + 12].split())
                    rows.append({
                        "file": rel,
                        "class": cls,
                        "method": method,
                        "line": line,
                        "key": key,
                        "cast": casts_before(text, pos),
                        "guarded": "1" if key in guards else "0",
                        "snippet": snippet[:SNIPPET_MAX],
                    })
    return files, rows


def declared_roots(response_keys):
    roots = set()
    for tok in (response_keys or "").split(";"):
        tok = tok.strip().strip("*")
        if not tok:
            continue
        name = tok.split(":")[0].strip().lstrip("*").split(".")[0]
        if name:
            roots.add(name)
    return roots


def contract_sites(path):
    """call_sites -> [(endpoint, declared_root_set)]"""
    out = collections.defaultdict(list)
    for r in csv.DictReader(io.open(path, encoding="utf-8"), delimiter="\t"):
        for tok in (r["call_sites"] or "").split("|"):
            tok = tok.split("#")[0].strip()
            if CALLSITE_RE.match(tok):
                out[tok].append((r["endpoint"], declared_roots(r["response_keys"])))
    return out


def write_tsv(path, header, rows):
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(str(r[h]) for h in header) + "\n")


def cmd_dump(args):
    files, rows = scan(args.src)
    dedup = {}
    for r in rows:
        dedup.setdefault((r["class"], r["method"], r["key"]), r)
    ordered = sorted(dedup.values(), key=lambda r: (r["class"], r["method"], r["key"]))
    write_tsv(args.out, FIELDS, ordered)
    unguarded = sum(1 for r in ordered if r["guarded"] == "0")
    print(".cs 文件 %d，读取点 %d，去重 (类,方法,键) %d，无守卫 %d"
          % (files, len(rows), len(ordered), unguarded))
    print("写出 %s" % args.out)


def load_receivers(path):
    """(callsite, key) -> [(receiver, write)]"""
    occ = collections.defaultdict(list)
    for r in csv.DictReader(io.open(path, encoding="utf-8"), delimiter="\t"):
        occ[(r["callsite"], r["key"])].append((r.get("receiver", ""), r.get("write", "R")))
    return occ


def load_origins(path):
    rows = []
    for r in csv.DictReader(io.open(path, encoding="utf-8"), delimiter="\t"):
        if r["origin"] not in ORIGINS:
            raise SystemExit("origins 表里的 origin 不在词表：%s" % r["origin"])
        rows.append((r["callsite"], r["receiver"], r["origin"]))
    return rows


def origin_of(site, key, receivers, origins):
    """判定该 (调用点, 键) 的读取来源；返回 drop 类别或 None。

    两条机械规则，都只依赖 --receivers 里的 receiver 列与 --origins 表：
    1) 该键的所有出现都是写侧（`...["k"] = `）→ write；
    2) 任一次出现的接收者命中 origins 行（callsite 支持 fnmatch，receiver 为 `*` 表示整站点）。
    没被取证覆盖的 (调用点, 键) 一律保留，宁漏不误杀。
    """
    occ = receivers.get((site, key), [])
    if occ and all(w == "W" for _, w in occ):
        return "write"
    for pat, want, origin in origins:
        if not fnmatch.fnmatchcase(site, pat):
            continue
        if want == "*":
            return origin
        if any(recv == want for recv, _w in occ):
            return origin
    return None


def cmd_gap(args):
    reader = csv.DictReader(io.open(args.dump, encoding="utf-8"), delimiter="\t")
    rows = [r for r in reader]
    sites = contract_sites(args.contract)
    reads = collections.defaultdict(dict)
    for r in rows:
        if r.get("guarded", "0") != "0":
            continue
        site = r["class"] + "." + r["method"]
        if site in sites:
            reads[site].setdefault(r["key"], r)

    receivers = load_receivers(args.receivers) if args.receivers else {}
    origins = load_origins(args.origins) if args.origins else []
    dropped = collections.Counter()
    dropped_keys = 0

    covered = gap = 0
    out_rows = []
    for site, keys in reads.items():
        for ep, roots in sites[site]:
            keep = {}
            for k, r in keys.items():
                if k in roots or k in RESERVED:
                    continue
                why = origin_of(site, k, receivers, origins) if args.filter == "origin" else None
                if why:
                    dropped[why] += 1
                    dropped_keys += 1
                    continue
                keep[k] = r
            if not keep:
                covered += 1
                continue
            gap += 1
            first = keep[sorted(keep)[0]]
            out_rows.append({
                "endpoint": ep,
                "callsite": site,
                "missing_keys": ",".join(sorted(keep)),
                "first_evidence": "%s.cs:%s%s" % (first["class"], first["line"], first["cast"]),
            })
    ordered = sorted(out_rows, key=lambda r: (r["endpoint"], r["callsite"]))
    write_tsv(args.out, GAP_FIELDS, ordered)
    print("dump 读取点 %d，契约调用点 %d，其中有读取的 %d"
          % (len(rows), len(sites), len(reads)))
    if args.filter == "origin":
        print("来源过滤：剔除键 %d（%s）"
              % (dropped_keys, "、".join("%s=%d" % (k, v) for k, v in sorted(dropped.items())) or "-"))
    print("对账：命中声明 %d，候选缺口行 %d（%d 个端点）"
          % (covered, gap, len({r["endpoint"] for r in ordered})))
    print("写出 %s" % args.out)


def main(argv):
    ap = argparse.ArgumentParser(description="无守卫读键扫描器")
    sub = ap.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("dump")
    p.add_argument("--src", required=True, help="il_csharp 的 app 目录")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_dump)
    p = sub.add_parser("gap")
    p.add_argument("--dump", required=True, help="dump 模式产出的 reads.tsv")
    p.add_argument("--contract", required=True, help="docs/analysis/api_contract.tsv")
    p.add_argument("--out", required=True)
    p.add_argument("--filter", choices=["none", "origin"], default="none",
                   help="origin：按 --receivers/--origins 剔除读的不是回包的键")
    p.add_argument("--receivers",
                   help="接收者取证表（callsite/key/line/receiver/write），filter=origin 时必填")
    p.add_argument("--origins",
                   help="非回包来源表（callsite/receiver/origin/evidence），filter=origin 时必填")
    p.set_defaults(func=cmd_gap)
    args = ap.parse_args(argv)
    if args.mode == "gap" and args.filter == "origin" and not (args.receivers and args.origins):
        print("filter=origin 需要同时给 --receivers 与 --origins", file=sys.stderr)
        return 2
    if args.mode == "dump" and not os.path.isdir(args.src):
        print("源目录不存在：%s" % args.src, file=sys.stderr)
        return 2
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
