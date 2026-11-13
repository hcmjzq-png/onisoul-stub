"""契约数据访问层：直接读 `docs/analysis/*.tsv`，不落中间产物。

三份输入都是客户端反编译源码的静态抽取结论（`docs/analysis/README.md` 有口径）：
    api_contract.tsv       402 个端点：发送方法 / 请求参数 / 响应键与类型
    api_call_graph.tsv     416 条端点→端点调用边
    behavior_contract.tsv  场景切换 / 键守卫

只读不改，进程内缓存一次。这样文档就是唯一事实来源，改表即改行为，不会出现
「生成的 JSON 与文档漂移」。运行时开销是解析 3 个几百行 TSV，可忽略。
"""
from __future__ import annotations

import csv
import io
from functools import lru_cache
from pathlib import Path
from typing import Any

DOCS = Path(__file__).resolve().parents[2] / "docs" / "analysis"

TYPED = {"int", "long", "double", "bool", "string", "Hashtable"}


def _rows(name: str) -> list[dict[str, str]]:
    with io.open(DOCS / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _parse_response(raw: str) -> list[dict[str, Any]]:
    """`key:type` 以 `;` 分隔；`*` 结尾是可选项标记；含 `<`/`>` 的是动态键。"""
    out: list[dict[str, Any]] = []
    for item in [x.strip() for x in (raw or "").split(";") if x.strip()]:
        optional = item.endswith("*")
        if optional:
            item = item[:-1]
        key, sep, typ = item.rpartition(":")
        if not sep:
            key, typ = item, ""
        typ = typ.strip()
        out.append({"key": key.strip(), "type": typ if typ in TYPED else "", "optional": optional})
    return out


@lru_cache(maxsize=1)
def data() -> dict[str, Any]:
    endpoints: dict[str, dict[str, Any]] = {}
    for row in _rows("api_contract.tsv"):
        path = (row.get("endpoint") or "").strip()
        if not path:
            continue
        endpoints[path] = {
            "api_methods": [x for x in (row.get("api_methods") or "").split("|") if x],
            "request_params": [
                x.strip() for x in (row.get("request_params") or "").split(",") if x.strip()
            ],
            "response": _parse_response(row.get("response_keys", "")),
            "triggers_scene": [],
            "guards": [],
        }

    for row in _rows("behavior_contract.tsv"):
        path = (row.get("endpoint") or "").strip()
        if path not in endpoints:
            continue
        endpoints[path]["triggers_scene"] = [
            x for x in (row.get("scene_ops") or "").split(";") if x and x != "-"
        ]
        endpoints[path]["guards"] = [
            x for x in (row.get("guarded_keys") or "").split(";") if x and x != "-"
        ]

    edges: list[list[str]] = []
    for row in _rows("api_call_graph.tsv"):
        a = (row.get("from_endpoint") or "").strip()
        b = (row.get("to_endpoint") or "").strip()
        if a and b:
            edges.append([a, b, (row.get("via_method") or "").strip()])

    scenes: dict[str, list[str]] = {}
    for path, info in endpoints.items():
        for scene in info["triggers_scene"]:
            scenes.setdefault(scene, []).append(path)

    batches: list[dict[str, Any]] = []
    for scene, triggers in sorted(scenes.items()):
        batches.append({
            "name": f"scene:{scene}",
            "kind": "scene",
            "endpoints": sorted({t for t in triggers} | {b for t in triggers for a, b, _ in edges if a == t}),
        })
    for path in sorted(endpoints):
        out = sorted({b for a, b, _ in edges if a == path})
        if out:
            batches.append({
                "name": f"fanout:{path}",
                "kind": "fanout",
                "endpoints": sorted({path} | set(out)),
            })

    return {"endpoints": endpoints, "edges": edges, "scenes": scenes, "batches": batches}


def endpoints() -> dict[str, dict[str, Any]]:
    return data()["endpoints"]


def has(api: str) -> bool:
    return api in data()["endpoints"]


def response(api: str) -> list[dict[str, Any]]:
    item = data()["endpoints"].get(api)
    return item["response"] if item else []


def edges() -> list[list[str]]:
    return data()["edges"]


def out_edges(api: str) -> list[str]:
    return sorted({b for a, b, _ in data()["edges"] if a == api})


def in_edges(api: str) -> list[str]:
    return sorted({a for a, b, _ in data()["edges"] if b == api})


def batches() -> list[dict[str, Any]]:
    return data()["batches"]


def scenes() -> dict[str, list[str]]:
    return data()["scenes"]
