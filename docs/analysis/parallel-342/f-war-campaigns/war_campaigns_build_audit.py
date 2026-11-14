"""Reproduce the F inventory from read-only original C# and table sources.

Lexical call sites are navigation aids, not proof that an overload is used.
Hand-reviewed response notes below deliberately do not reuse api_contract.tsv.
"""
import csv
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
SOURCE = Path(r"C:\Users\74378\AppData\Local\Temp\onisoul-static-original-20261115")
TABLES = Path(r"D:\onisoul\work\quest-contract-20261115\all-tables")
TASK = Path(r"D:\onisoul\work\parallel-review-342-20261115\F-war-campaigns.txt")
ENDPOINTS = re.findall(r"^(?:strategy|siege|turfWar)/\S+$", TASK.read_text(encoding="utf-8"), re.M)
ENDPOINTS = [value.strip() for value in ENDPOINTS]
assert len(ENDPOINTS) == len(set(ENDPOINTS)) == 47

# Each value: response paths (partial unless explicitly stated), evidence, next work.
NOTES = {
"siege/discharge": ("gainBlackSoul,situation,charge,record,dischargeLogs,selfDeck,costs,rival", "vsSetting_Siege.cs:attack:784-801; PluginRunner_DoBattleSiege.cs:onSiegeDischarge", "核实放出时机/积分/费用，依赖 B 战斗事务"),
"siege/enter": ("callback transitions screen; full payload unknown", "siegeBriefMenu.cs:siegeEnter; PluginRunner_DoBattleSiege.cs:onEnterSiege", "确认报名资格/活动期/重复报名"),
"siege/getBrief": ("day,stage,isEntry,winner.day0..2,attacker.<index>,defender.<index>,role", "siegeBriefMenuDesc.cs:setup", "配对与活动日期未知；init 的国家常量不能作服务端事实"),
"siege/getPairings": ("pairings.<index>.defender.0;pairings.<index>.attacker.0/optional 1 (countryId strings)", "HTMLSiegeMediator.cs:61-118; original app.js:73-80,169-173; web-evidence.json", "限定只读投影已测；缺真实配对生产端及 siege/siege.html 本体，不能称配对算法完成"),
"siege/getSiegeResultLog": ("schedule.open/close;record.rank/globalTotalScore;winner.dayN;role;attacker/defender.<index>", "SiegeResultRenderer.cs:load/convertHtmlParameter/convertVictoryPoint", "补全 HTML 下游与真实已结算日志"),
"siege/getSiegeStatus": ("selfDeck,costs,rival,situation,charge,record,dischargeLogs,siegeBattlePoint", "vsSetting_Siege.cs:getSiegeSituation/setSituation/setCharge", "证明 spots/dailyScores、兵力、敌手及活动轮转"),
"siege/lookSiegeResult": ("same renderer as getSiegeResultLog; not proof of same side effects", "SiegeResultRenderer.cs:load/convertHtmlParameter", "查首次领取与重复查看差异/奖励入账事务"),
"siege/openingBet": ("charge", "vsSetting_Siege.cs:754-763; PluginRunner_DoBattleSiege.cs:159", "原 siege_bet_rate 有表；投入上限、取整及重复请求待证"),
"strategy/getMercenaryEmployInfo": ("kokudaka,maxForceSize,regularSoldier (numeric)", "StrategySelect_army.cs:58-65", "mercenaryPrice=50 是原 defines 行；最大/常备兵公式未证，不按国力猜算"),
"strategy/entryStrategy": ("callback ignores payload then subtracts armyInfo.Cost and changes scene", "StrategySelect.cs:232-238; StrategySelect_army.cs:Cost; WebApiClient.cs:3789-3804", "雇佣菜单费用=count*mercenaryPrice 已证；容量/报名资格/幂等待证；fieldName 不发送"),
"strategy/getStrategyBrief": ("teams.a/b.belongCountries/maxForceSize/rate/point;turn.current/max;openTime;interval", "StrategySelect.cs:97-141; StrategyHUDController.cs:Start", "需要真实周期和队伍快照；不生成固定对手"),
"strategy/getStrategyStatus": ("map,battlefield,cell,self; battlefield.id; self.team", "Strategy.cs:onPreSetup/setupMap; StrategyDataCache.cs:MapData/BattlefieldData/CellData/SelfData", "完整地图/格子消费者链未闭合；缺 strategy_battlefield"),
"strategy/getStrategyCommandInfo": ("consumption,acquire,cellBattleContribution,contributionPercent (partial)", "StrategyCommandSelector.cs:196-210; StrategyMoveableRegionSelector.cs:147; StrategyStrategizeRegionSelector.cs:168", "原表费用并列数组可读取；force/diffMaxForce 的结算单位与贡献公式待证"),
"strategy/isAlive": ("isAlive:boolean at root", "StrategyHUDController.cs:985-989; WebApiClient.cs:4019-4024", "限定实现：读取本账号未过期权威观测；真实战斗写入端仍未接入"),
"strategy/getStrategyCellLogs": ("logs.<index>.position (partial)", "StrategyLogAnalizer.cs:788-793/createData2:875-892", "原日志结构和地图地名依赖，不能以缺字段变空日志"),
"strategy/getStrategyPersonalLogs": ("root.<row>.cell/turn (partial)", "StrategyLogAnalizer.cs:797-802/createPlayerData:894-930", "保留根记录结构；fieldName 为客户端派生，非服务端已证字段"),
"strategy/getStrategyActionLogs2": ("battlefield;logs.<row>.messages.<group>.<row>.detail.position/destPosition (partial)", "StrategyLogAnalizer.cs:806-811/createPlayer2Data2:969", "补全消息变体及原 HTML；不可与旧 ActionLogs 混用"),
"strategy/getStrategyBattleLogs": ("battlefield;logs.<index>.turn/command/battleRule/type/cell/consumeResources/proficiencies/contributionRatios/attacker/defender/roundDetail", "StrategyLogAnalizer.cs:815-820/convPlayerBattleHashFromServer:1905-1964", "与 B 协议对齐；mypageBattleLogUpdateStrategy 的 string force 重载属于 battle/getVsBattleLogs"),
"strategy/getStrategyLogs": ("turn-keyed entries -> flags/field/info/damage/detail (partial)", "StrategyLogManager.cs:Log.setup/analize", "旧日志链需动态确认是否仍可达；debug 值不可用于胜负"),
"strategy/getStrategyPromptReport": ("setupParams receives report; full hierarchy not traced", "StrategyResultWindow2.cs:288-293/setupParams; WebApiClient.cs:getStrategyPromptReport", "请求 position 为字符串；继续追踪 setupParams 与页面消费者"),
"strategy/getStrategyNormRewardInfo": ("strategyBattlePoint;activityReward", "NormRewardScene.cs:25-36", "积分必须来自持久结算，领取进度/阈值另行验证"),
"strategy/getStrategyPairings": ("root.match_01..N.a.0.countryId/rate;b.0/optional 1.countryId/rate;winReward/loseReward=reward IDs", "HTMLStrategyMatchMediator.cs:134-221; original app.js:53-61; web-evidence.json", "winRewardNum/图标是客户端查表转换，仅预览第一槽 countMin；原 iframe 缺失，奖励结算未知"),
"strategy/getStrategyWinLossRecords": ("totalCount;records.<index>.openTime;decisions nested INSIDE records.<index>:match_01..N.a/b.<slot>.countryId/rate,winner", "HTMLStrategyMatchMediator_History.cs:179-248; original app.js:53-61,169-173", "限定完整已保存历史的只读投影已测；真实结算生产端/分页/周期仍待证"),
"strategy/lookStrategyResult": ("callback refresh/transition; full reward contract unknown", "PoliticButton.cs:goStrategySelect", "查一次性领奖/跨重登幂等，与 B/G 结算协作"),
"turfWar/entryWar": ("team:string", "TurfWarBriefCache.cs:379-393", "自动报名在 open 且 team=none 分支；分队算法/持久化未知"),
"turfWar/entryBattlefield": ("payload ignored; local Battlefield changed BEFORE request; callback clears isMovable/adversaries", "TurfWarWorldMap.cs:283-328; TurfWarBriefCache.cs:IsMoveable; WebApiClient.cs:2799-2806", "资格/所属队/战场容量/重试未证；失败过滤不会撤销已改的本地 Battlefield"),
"turfWar/moveBattlefield": ("payload ignored; local Battlefield changed BEFORE request; branch selected by warSituation.isMovable", "TurfWarWorldMap.cs:291-328; TurfWarBriefCache.cs:IsMoveable; WebApiClient.cs:2809-2815", "移动费用/冷却/占领联动未知；动态验证失败恢复与重登对账"),
"turfWar/getSelfSituation": ("unknown; wrapper battlefield argument NOT sent", "WebApiClient.cs:2818-2823", "未找到普通 C# 调用；须查原页面/动态流量"),
"turfWar/getSelfRecord": ("unknown; not battle/getSelfRecord", "WebApiClient.cs:2826-2831", "未找到普通 C# 调用；勿把 decisiveBattleSituation 的 battle/getSelfRecord 混入"),
"turfWar/getTurfWarResultLog": ("schedule.open/close;gainRedSoul;rank;score;defenseScore; nested ranking conversion (partial)", "TurfWarResultRenderer.cs:load/convertHtmlParameter/convertGlobalRanking", "追踪原页面全部字段；日榜和总榜周期交 G"),
"turfWar/receiveTurfWarReward": ("same result renderer as getTurfWarResultLog; not proof of identical mutations", "TurfWarResultRenderer.cs:load/convertHtmlParameter; WebApiClient.cs:1638-1643/2834-2839", "领取幂等/奖励入账/邮箱溢出都待证，不按固定红魂发放"),
}
COMMON_COMMAND = "isAlive,isExecuted,nextOperableTime,operatedTime,proficiency,currentForceSize,aroundEffect;resources.<resource>.amount (shared processor; path-specific fields additional)"
for endpoint in ENDPOINTS:
    if endpoint.startswith("strategy/command/"):
        action = endpoint.rsplit("/", 1)[1]
        shape = COMMON_COMMAND
        detail = "完整状态转换、冷却/费用、并发及重试未证；共享地图需事务"
        if action in ("march", "march2"):
            shape += ";position,base,optional route"
            detail = "缺 strategy_battlefield；march2 使用 seqId，需路径版本/重放/占格规则"
        elif action == "traceroute":
            shape = "reachable:boolean;route.<index>:position string;coolTime:number;seqId:number"
            detail = "position=[x,y]；需路径算法、seqId 生命周期，不能猜地图"
        elif action == "cancelMarch":
            detail = "路径取消是否退资源/取消冷却未证"
        elif action == "attack":
            detail = "command 字符串变体与 B 战斗输入输出对齐；禁止固定胜负"
        NOTES[endpoint] = (shape, "StrategyCommandSelector.cs; StrategyCommandResultProcessor.cs:process/processCommonUpdate; StrategyHUDController.cs", detail)

NOTES["strategy/command/traceroute"] = ("reachable:boolean;route.<index>:position string;coolTime:number;seqId:number", "StrategyMoveableRegionSelector.cs:145-168", "需地图、路径版本/占格规则；回调先改本地 self.route，seqId 传 march2，不能靠构造路径还原算法")
NOTES["strategy/getStrategyPromptReport"] = ("currentCellLog.turn.current/max,occupied,playerCounts/forceSizes/injureds/contributions.a/b;mainlyCells.<index>.position/playerCounts/forceSizes/occupied;topRankers.a/b.<index>.name/score", "StrategyResultWindow2.cs:24-50,150-278", "hash(position/fieldCatalogId/matchId/team/commonEffectId/openHTML)是窗口参数，不能误混入 reportHash；缺真实格子结算和地图")
for api in ("turfWar/getTurfWarResultLog", "turfWar/receiveTurfWarReward"):
    NOTES[api] = ("schedule.open/close;gainRedSoul,rank,score,defenseScore;global.end/daily.<day>.score/rank/defenseScore;battlefield.end.<field>/daily.<day>.<field>.score/rank;bonuses.optional fieldWon/teamWon", "TurfWarResultRenderer.cs:61-195,209-235; BrowserProxy.cs:65-101; original unityProxy.js:103-140", "names/victory/responseId 是桥接派生字段，不预填；原结果 HTML 缺失，奖励及领取幂等未知")

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

sources = {p.name: p.read_text(encoding="utf-8-sig") for p in SOURCE.glob("*.cs")}
web = sources["WebApiClient.cs"]
methods = list(re.finditer(r"\tpublic void (\w+)\(([^\n]*)\)\s*\n\t\{(.*?)\n\t\}", web, re.S))
records, used_files = {}, {"HashAccessFuncs.cs", "HashAccessor.cs", "GameRestarter.cs", "StrategyDataCache.cs", "StrategyBattleFieldTableAccessor.cs", "ComboTableAccessor.cs", "DefinesTableAccessor.cs"}
rows = []
for endpoint in ENDPOINTS:
    wrappers = []
    navigation = []
    for method in methods:
        if f'httpCall("{endpoint}"' not in method[3]:
            continue
        start = web.count("\n", 0, method.start()) + 1
        fields = re.findall(r'hashtable\.Add\("([^\"]+)"', method[3])
        wrappers.append(dict(method=method[1], signature=method[2], line=start, end_line=start+method[0].count("\n"), sent_fields=fields))
        for name, source in sources.items():
            if name == "WebApiClient.cs":
                continue
            for i, line in enumerate(source.splitlines(), 1):
                if re.search(r"\." + re.escape(method[1]) + r"\s*\(", line):
                    navigation.append(dict(file=name, line=i, call=line.strip(), note="lexical navigation only; overload/debug reachability must be checked"))
                    used_files.add(name)
    shape, evidence, next_work = NOTES.get(endpoint, ("unknown", "WebApiClient.cs:wrapper only", "未找到普通 C# 调用；查原页面与动态流量，不能宣称玩法实现"))
    used_files.update(re.findall(r"\b[\w]+\.cs", evidence))
    used_files.add("WebApiClient.cs")
    records[endpoint] = dict(wrappers=wrappers, lexical_navigation=navigation, reviewed_response_paths=shape, reviewed_evidence=evidence, next_work=next_work)
    status = "仅包装器/普通调用未证" if endpoint not in NOTES else "部分消费者已证/规则未证"
    if endpoint in ("strategy/isAlive", "siege/getPairings", "strategy/getStrategyWinLossRecords"):
        status = "限定查询组件可测/未挂载/权威数据生产端未实现"
    group = endpoint.split("/")[0]
    tables = {"strategy": "strategy_command/strategy_terrain/strategy_battlefield_catalogue; strategy_battlefield missing; combo dependency missing", "siege": "siege_bet_rate/siegeBattle_trophy; existence does not prove settlement", "turfWar": "turf_war_battlefield/turf_war_battlefield_catalog/turfWarBattle_trophy; existence does not prove settlement"}[group]
    persistence = "不写档；读取内部 _warCampaigns 权威观测/完整数据集" if status.startswith("限定查询") else "原服务保存不可从客户端证明；本批不新增该入口状态写入"
    rules = "认证本人；拒绝额外选择器；校验归属/有效期/数据结构；重试只读；不计算胜负" if status.startswith("限定查询") else "token 已证；权限/实际费用/幂等仍需权威规则；不凭回调忽略负载判定写入成功"
    rows.append([endpoint, "; ".join(w["method"]+"("+",".join(w["sent_fields"])+")" for w in wrappers), shape, evidence, tables, persistence, rules, status, next_work])

table_proofs = []
for path in sorted(TABLES.glob("*.json")):
    if path.name.startswith(("strategy", "siege", "turf")) or path.name == "defines.json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        table_proofs.append(dict(path=str(path), sha256=digest(path), root_keys=list(data), row_count=sum(len(v) for v in data.values() if isinstance(v, dict))))
proof = dict(baseline="1f287e33123afa452d2f5d2aac2427566d549f73", original_source_root=str(SOURCE),
    assembly_sha256="b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e",
    caveat="Method navigation is not a full callgraph. Debug/default constants are NOT original-server evidence. Response paths marked partial are incomplete.",
    original_sources=[dict(path=str(SOURCE/name), sha256=digest(SOURCE/name)) for name in sorted(used_files) if (SOURCE/name).exists()],
    original_tables=table_proofs, missing_tables=[name for name in ("strategy_battlefield.json", "combo.json") if not (TABLES/name).exists()],
    endpoints=records,
    compatibility_decisions=["_warCampaigns.strategy ownerId/observedAt/validUntil/isAlive is internal storage, not original save format", "No default alive value; expired/missing observation is no stub response", "Existing success/error envelope reused; Unity error flow still needs validation", "Internal cost-array decoder; calculation labels do not prove formulas; no costs deducted", "Mercenary menu quote count*defines.mercenaryPrice is evidenced; negative/fractional/overflow rejection is internal safety policy, not original server error semantics", "No production mounting, event activation, result generation, reward issuance or migration"])
proof["fixture_checks"] = []
proof["compatibility_decisions"].extend([
    "_warCampaigns.queries[api] ownerId/observedAt/validUntil/complete/rows is internal storage; authoritative producers are not implemented",
    "siege/getPairings and strategy/getStrategyWinLossRecords project complete persisted datasets only; absent data is not empty success",
    "History totalCount=len(rows) is a full-dataset supported scope, not recovered original pagination; projections reject malformed rows atomically",
    "Original parent-page bridge verification and missing iframe body scope are recorded separately in web-evidence.json/html-lifecycle.md",
])
for name in ("strategy_command", "defines"):
    fixture = HERE.parents[3] / "tests" / "fixtures" / "war_campaigns" / (name + ".json")
    sample = json.loads(fixture.read_text(encoding="utf-8-sig"))[name]
    original = json.loads((TABLES / (name + ".json")).read_text(encoding="utf-8-sig"))[name]
    assert all(value == original[key] for key, value in sample.items())
    fixture_hash = hashlib.sha256(fixture.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    proof["fixture_checks"].append(dict(file=fixture.relative_to(HERE.parents[3]).as_posix(), sha256_lf=fixture_hash, original_rows=list(sample), equal=True))
(HERE/"evidence.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
with (HERE/"reviewed-endpoints.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
    writer.writerow(["endpoint", "request", "response_hierarchy", "callback_evidence", "table_evidence", "persistence", "permission_cost_retry", "status", "next_work"])
    writer.writerows(rows)
print(f"{len(rows)} endpoints; {len(proof['original_sources'])} source digests; {len(table_proofs)} table digests")
