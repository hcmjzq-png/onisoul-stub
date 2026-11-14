#!/usr/bin/env python3
"""Report actual dispatch coverage; a dedicated handler is not full game restoration."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.main import build_registry
from app.business.placeholders import BLOCKED_WRITES

NEXT = {
    "debug": "开发/调试命令；先确认需要与授权边界，不能开放任意改档",
    "admin": "管理发奖；需权限与幂等规则，不能从接口名生成赠送",
    "ranking": "用户警示的争议功能；需原始统计口径、周期、结算与查询协议",
    "quest": "动态表来源已核实（quest-contract-20261115）；待建立进度/事件/战斗/领取共享状态及验证服务端规则",
    "battle": "缺少完整战斗运算、事件记录与结算一致性；先追踪原始战斗消费者",
    "deck": "扩仓/合成/出售/强化等写操作；需各自费用、材料与装备/锁定规则",
    "politic": "逐条追踪城市操作、建筑与任务状态；奖励表和解锁条件需核验",
    "common": "核验调用与字段归属，再接玩家真实状态；不能按名称猜回包",
    "inbox": "用户警示的争议功能；核验原网页/Unity 桥接与邮件领取事务",
    "mailbox": "用户警示的争议功能；核验原网页/Unity 桥接、读写与附件事务",
    "strategy": "用户警示的争议功能；补原资源/地形表及国战时序、结算证据",
    "siege": "用户警示的争议功能；补原攻城报名、编队、战斗与结算证据",
    "turfWar": "活动规则、报名状态和战斗结算需要原始证据",
    "giganticRaidBoss": "活动排期、参战、战斗与奖励需要原始证据",
}


def report(out: Path) -> dict:
    registry = build_registry()
    source = ROOT / "docs/analysis/static-review-20261115/endpoints.tsv"
    with source.open(encoding="utf-8", newline="") as handle:
        evidence = {row["endpoint"]: row for row in csv.DictReader(handle, delimiter="\t")}
    remaining = sorted(api for api, handler in registry._handlers.items()
                       if handler.__module__ == "app.business.placeholders")
    rows = []
    for api in remaining:
        group = api.split("/")[0]
        rows.append({"endpoint": api, "module": group, "status": "contract_placeholder",
                     "direct_il_refs": evidence.get(api, {}).get("direct_il_refs", "unknown"),
                     "next_work": ("已阻止空成功回包；待核实 " + BLOCKED_WRITES[api] + "，见 production-contract-20261115/README.md") if api in BLOCKED_WRITES else NEXT.get(group, "追踪原始请求/响应与持久化规则，再实现并联调"),
                     "evidence_index": "static-review-20261115/endpoints.tsv"})
    out.mkdir(parents=True, exist_ok=True)
    with (out / "remaining-endpoints.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["endpoint", "module", "status", "direct_il_refs", "next_work", "evidence_index"], delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    summary = {"registered": len(registry.known()), "dedicated_handlers": len(registry.known()) - len(remaining),
               "remaining_placeholders": len(remaining), "remaining_by_module": dict(sorted(Counter(row["module"] for row in rows).items())),
               "scope": "dispatch coverage only; not all dedicated handlers are complete gameplay; zero IL refs do not prove unused; next_work is a work queue, not proof that required evidence is absent"}
    (out / "endpoint-progress.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/analysis/player-loop-20261115")
    print(json.dumps(report(parser.parse_args().out), ensure_ascii=False))
