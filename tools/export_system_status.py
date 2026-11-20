"""Export a read-only route inventory; handler counts are not gameplay completion.

Requires the normal server dependencies, but opens no database connection and
dispatches no requests. Output is project metadata, never original wire data.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import functools
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.business import contract
from app.business.admin_debug_services import DISABLED_ENDPOINTS
from app.business.placeholders import BLOCKED_WRITES
from app.main import build_registry

SYSTEMS = {
    "S01": "接入与账号", "S02": "角色与存档", "S03": "新手任务与成长",
    "S04": "主城与建筑", "S05": "生产与收获", "S06": "武将与养成",
    "S07": "商店与交易", "S08": "物语与战斗", "S09": "好友与社区",
    "S10": "战争与领地", "S11": "排行与活动", "S12": "资源与运维",
}
PREFIXES = {
    "auth": "S01", "admin": "S12", "debug": "S12", "auction": "S07",
    "battle": "S08", "quest": "S08", "giganticRaidBoss": "S08",
    "deck": "S06", "navigator": "S06", "community": "S09",
    "friend": "S09", "inbox": "S09", "mailbox": "S09", "invitation": "S09",
    "strategy": "S10", "siege": "S10", "turfWar": "S10", "ranking": "S11",
    "plugin": "S11", "netCafe": "S11", "dailymission": "S03",
    "depletionmission": "S03", "trophy": "S03",
}
COMMON = {
    "dedicate": "S11", "getActionPoints": "S02", "getAnnouncement": "S11",
    "getBriefOfNationalPower": "S11", "getCharacters": "S06", "getEquips": "S06",
    "getEventStatuses": "S11", "getLoginStampSheet": "S11", "getPlayerCogid": "S01",
    "getPlayerEntity": "S02", "getPlayerParams": "S02", "getResources": "S02",
    "getRevisions": "S12", "getSelectCharacters": "S06", "getServerTime": "S01",
    "getShopcredit2": "S07", "getShopsale": "S07", "getTactics": "S06",
    "increasePlayerLevel": "S03", "periodicInquiry": "S01", "recordChat": "S09",
    "solvePlayerLevelCap": "S03", "stampLoginSheet": "S11",
}
POLITIC = {
    "boosterPack": "S06", "building": "S04", "edict": "S03", "errantry": "S08",
    "fixMapProduct": "S05", "kokugi": "S11", "lottery": "S06", "map": "S04",
    "mission": "S03", "shop": "S07", "support_item": "S06", "task": "S04",
    "waterborneTrade": "S07",
}
MYPAGE = {
    "getPlayerProfile": "S02", "setSelfIntroduction": "S02",
    "getLessonStates": "S03", "takeLesson": "S03",
    "getNineGridInfo": "S06", "playNineGridGacha": "S06", "claimReward": "S06",
    **dict.fromkeys(("getArtifactSeries", "getArtifactSeriesReward", "getCharacterCollection",
                     "getCredit2Logs", "getCreditLogs", "getEventcodeLogs", "getJewelSeries",
                     "getJewelSeriesReward", "getMigratePlanCountryStatus", "getMigratePlansStatus",
                     "getPlayerRecords", "migrate", "useEventcode"), "S11"),
}
NOTES = {
    "turfWar/getWarSituation": "未参战哨兵兼容回包；不代表战争实现",
    "common/getEventStatuses": "空活动状态；不生产活动",
    "common/getShopsale": "空促销状态；不代表促销实现",
    "common/getPlayerEntity": "受限消费点仅返回 playerId；不是完整玩家快照",
    "common/getPlayerCogid": "本服会话身份兼容；不是原 COG 平台接入",
    "common/getSelectCharacters": "当前编队选择投影；不代表完整筛选规则",
    "common/getServerTime": "会话确认与信封时间；不是时间玩法",
    "auth/keepAliveContainer": "会话保活确认",
    "deck/getDeckBonus": "编队引用可读；未激活限时/排行加成",
    "politic/lottery/getSouls": "仅读取已存七色魂余额；抽奖未实现",
    "plugin/getPluginData": "已存设置/时长可读；不生产挂机权益",
    "plugin/getPluginLog": "诊断日志；不是战果或奖励账本",
    "plugin/addPluginLog": "诊断日志；不发放奖励",
    "politic/task/completeTasks": "主城全部配方收获、特殊入账、自动续产及有限耐久；抽选/道路/技能叠加有明确兼容策略",
    "politic/task/submitProduceTask": "手动入口按建筑/配方校验；任务 5 的 10 秒田地配方仅可成功收获一次",
    "politic/building/getProductsByBuilding": "配方查询与开工共享门槛；田地、伐木所和炼铁所的 15 分钟基础配方提前开放",
    "politic/shop/buyShopItem": "普通商店整套购买接受客户端 index=-1；图纸可接续施工",
    "politic/building/conflateBuilding": "主城 488 条品级关系；原最大等级/材料资格，新实例重置采用兼容策略",
    "friend/getFriendMap": "已接受双向好友主城投影；-1 默认主城；不含私人库存",
    "friend/getFriendMapData": "已接受双向好友主城投影；-1 默认主城；不含私人库存",
    "friend/getFriendMapData2": "已接受双向好友主城投影；-1 默认主城；不含私人库存",
    "friend/visitFriendMap": "原小姓与奖励菜单字段；不虚构访问赠礼",
    "friend/findFriendsAndSend": "入门 16 好友面板兼容与持久化；当前候选为空",
    "friend/building/getFriendProductsByBuilding": "城主实际建筑配方与等级门槛",
    "friend/task/completeFriendTasks": "同事务给双方完整同额奖励、消耗一轮且续产；分配/日次数属兼容策略",
    "friend/task/accelerateFriendProduceTask": "免费按原表缩短时长；独立日次数属兼容策略",
    "politic/task/submitBulkProduceTasks": "已支持资源配方的一键开工；逐栋扣费、整批提交",
    "politic/task/cancelTasks": "手动/固定生产取消，无退款；自动计时通过收纳停止",
    "politic/task/accelerateProduceTask": "自己生产按原加速表扣朱魂币、更新 dueTime；不提前发奖",
    "politic/support_item/getPotions": "仅查询药品；使用药品另计",
    "politic/support_item/usePotions": "单瓶中回复药或全回复药；同次保存点数和扣瓶结果",
    "debug/debugLogin": "受显式调试密钥限制；不算正常玩家功能",
    "debug/devLogin": "受显式调试密钥限制；不算正常玩家功能",
}


def system_for(api: str) -> str:
    parts = api.split("/")
    if parts[0] == "common":
        return COMMON[parts[1]]
    if parts[0] != "politic":
        return PREFIXES[parts[0]]
    if parts[1] == "mypage":
        return MYPAGE[parts[2]]
    if api == "politic/shop/sellBuildings":
        return "S04"
    if parts[-1] in {"getProductsByBuilding", "getHarvestCounts", "accelerateProduceTask",
                     "submitProduceTask", "submitBulkProduceTasks", "cancelTasks"}:
        return "S05"
    return POLITIC[parts[1]]


def export(output: Path) -> dict:
    registry = build_registry()
    if registry.known() != set(contract.endpoints()):
        raise ValueError("registered routes and original contract differ")
    rows = []
    for api, handler in sorted(registry._handlers.items()):
        module = getattr(handler, "__module__", "")
        if api in DISABLED_ENDPOINTS:
            kind, note = "disabled", "管理/调试入口刻意关闭；不以开放它减少占位数"
        elif module == "app.business.placeholders":
            kind = "explicit_failure" if api in BLOCKED_WRITES else "contract_default"
            note = ("缺少 " + BLOCKED_WRITES[api] if api in BLOCKED_WRITES
                    else "仅契约默认回包；未实现玩法")
        else:
            kind, note = "dedicated_handler", NOTES.get(api, "专用处理器；支持范围和验收见功能台账")
        target = handler.func if isinstance(handler, functools.partial) else handler
        rows.append({"system_id": system_for(api), "endpoint": api, "runtime_kind": kind,
                     "handler_module": target.__module__, "handler_name": target.__name__, "note": note})
    totals = Counter(row["runtime_kind"] for row in rows)
    summary = {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "scope": "route registration only; no API dispatch, DB access or Unity acceptance",
        "registered": len(rows), "runtime_kinds": dict(sorted(totals.items())),
        "legacy_placeholder_total": sum(totals[k] for k in
                                         ("disabled", "explicit_failure", "contract_default")),
        "systems": {key: {"name": name, "registered": sum(r["system_id"] == key for r in rows),
                           "runtime_kinds": dict(sorted(Counter(r["runtime_kind"] for r in rows
                                                                 if r["system_id"] == key).items()))}
                    for key, name in SYSTEMS.items()},
    }
    output.mkdir(parents=True, exist_ok=True)
    with (output / "endpoints.tsv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (output / "routes.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="directory for metadata files")
    args = parser.parse_args()
    print(json.dumps(export(args.output), ensure_ascii=False, indent=2))
