"""Reproduce G's source inventory; lexical call references are not proof of rules.
Run from repository root with: python docs/analysis/parallel-342/g-rankings/rankings_review.py
"""
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from app.minijson import parse_json_document

SOURCE = Path(r"C:\Users\74378\AppData\Local\Temp\onisoul-static-original-20261115")
TABLES = Path(r"D:\onisoul\work\quest-contract-20261115\all-tables")
TASK = Path(r"D:\onisoul\work\parallel-review-342-20261115\G-rankings.txt")
OUT = Path(__file__).parent
FIX = ROOT / "tests/fixtures/rankings"
FIX.mkdir(parents=True, exist_ok=True)
endpoints = re.findall(r"^(?:common|ranking)/\w+$", TASK.read_text(encoding="utf-8"), re.M)
assert len(endpoints) == len(set(endpoints)) == 51
sources = {p.name: p.read_text(encoding="utf-8") for p in SOURCE.glob("*.cs")}
web = sources["WebApiClient.cs"]
wrappers = {}
for match in re.finditer(r"public void (\w+)\([^\n]+\)\s*\{(.*?)\n\t\}", web, re.S):
    name, body = match.groups()
    apis = re.findall(r'httpCall\("([^"]+)"', body)
    for api in apis:
        if api in endpoints:
            wrappers.setdefault(api, []).append({"method": name,
                "line": web[:match.start()].count("\n") + 1,
                "request_keys": re.findall(r'hashtable.Add\("([^"]+)"', body),
                "literal_parameters": re.findall(r'hashtable.Add\("([^"]+)", "([^"]+)"\)', body)})

player_shape = "entries;myRecord.{rank,score};rankers.<pageIndex>.{rank,score,username,playerId,country};optional timestamp,nextswitch"
brief_shape = "brief.{score,rank,lastRank,rankingId};optional brief.nextswitch for reward preview;specialized callback extras require verification"
overrides = {
    "common/dedicate": "gainPoint;dedication.{point,limit,rank};myRank.{rank,countryRank};bonus.<index>;optional nationalPower,totalBuildingCount",
    "common/getBriefOfNationalPower": "dedicationRanking.{prev,current};battleRanking.{prev,current};nationalPowerRanking.current;rank(string);change;nationalPower;dedication(number);kokudaka;optional siege result",
    "ranking/getRecordOfCountryInBattle": "won;lost;rank;timestamp;neighboring.<index>.{countryId,rank,won,lost}",
    "ranking/getRankingOfCountriesInBattle": "countries.<index>.{countryId,rank,score};score displayed as percentage;myRecord.rank",
    "ranking/getRankersInNationalPower": "rankers.<index>.{countryId,rank,score};myRecord.rank",
    "ranking/getRankersInStrategyPie": "rankers.<index>.{countryId,rank,score};myRecord.rank",
    "ranking/getRankersOfCountriesInGiganticRaidBoss": "rankers.<index>.{countryId,rank,score};myRecord.rank",
    "ranking/getTopRankersInTurfWar": "rankers (TurfWarBriefCache caches response); downstream row fields require verification",
}
groups = [
    ("Kokudaka", "A: verified city kokudaka; no player-level substitution", "building,building_level"),
    ("NationalRanking", "rankingGroup-selected national metric; weekly/all separate", "ranking,ranking_reward_weekly"),
    ("NationalPower", "country national power aggregate; dedication and settlement rules pending", "national_power_goal,countryRank"),
    ("Dedication", "contribution ledger; costs/bonus/cap/reset pending", "character,building,equip,tactics,defines,countryRank"),
    ("GiganticRaidBoss", "B/F: gigantic boss contribution/max damage/country aggregation differ", "ranking,ranking_reward"),
    ("RaidBoss", "B: boss score; national/daily scopes differ", "ranking,ranking_reward"),
    ("TurfWar", "F: battlefield/team victory points; event calendar unavailable", "ranking,turf_war_battlefield"),
    ("Strategy", "F: battlefield/team/action statistics; Pie is country rows", "ranking,strategy_battlefield"),
    ("Siege", "F: role-specific siege results", "ranking"),
    ("RandomQuest", "B: random quest result metric; no level substitution", "ranking"),
    ("Brawn", "B: brawn result metric; formula pending", "ranking"),
    ("Battle", "B: combat records; country won/lost versus player score", "ranking,vsBattleRankBonus"),
]
evidence_endpoints, rows, used = {}, [], {"WebApiClient.cs", "HTMLRankingMediator.cs", "HashAccessFuncs.cs", "HashAccessor.cs"}
for api in endpoints:
    methods = wrappers[api]
    names = {w["method"] for w in methods}
    refs = []
    call_pattern = re.compile(r"\.(?:" + "|".join(re.escape(n) for n in names) + r")\b")
    for filename, source in sources.items():
        if filename == "WebApiClient.cs":
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            if call_pattern.search(line):
                refs.append(f"{filename}:{lineno}")
                used.add(filename)
    _, metric, tables = next((g for g in groups if g[0] in api),
                            ("Dedication", groups[3][1], groups[3][2]))
    shape = overrides.get(api, brief_shape if "Brief" in api else player_shape)
    if not refs:
        shape = "unconfirmed: wrapper only; no direct caller found in original C#"
    status = "consumer traced; settlement/source pending; not implemented" if refs else "wrapper only; not implemented"
    if "Kokudaka" in api:
        status = "implemented snapshot query only; UNMOUNTED; production source integration pending"
        if "Brief" in api:
            shape = "brief.{rank,score,lastRank};rankingId optional not emitted"
    if api == "common/dedicate":
        status = "cost shape and preview traced; mutation NOT implemented"
    period = "daily" if "Daily" in api else "monthly" if "Monthly" in api else "weekly/all via rankingPeriod" if "NationalRanking" in api else "non-daily; exact reset unknown"
    request = " | ".join(w["method"] + ":" + ",".join(w["request_keys"]) for w in methods)
    helpers = "HTMLRankingMediator.cs:commonOutput/createMyRankHash/send/calcRankRange/convToTurnStr; mypageRankingWindow.cs:makeBriefInfo"
    if api.startswith("common/"):
        helpers = "DedicateOfMaterialsDialog.cs:onDedicateResult/onDedicateSuccessProcedure; MightOfNationDialog.cs:updateInformation/onDedicate; UserStatus.cs:Dedication.update"
    elif "getRecordOfCountry" in api:
        helpers = "CountryRanking.cs:setup/Record"
    if any(ref.startswith("HTMLRewardMediator.cs:") for ref in refs):
        helpers += ";HTMLRewardMediator.cs:requestFromRankingRewardTable/requestFromRankingRewardTableByRankingId/setTimeStamp"
    if not refs:
        helpers = "not confirmed; do not inherit generic response without callback evidence"
    evidence_endpoints[api] = {"wrappers": methods, "direct_call_references": refs,
        "helper_review": helpers, "status": status}
    rows.append([api, request, metric, period, shape, ";".join(refs) or "none", helpers,
                 tables + " (metadata/preview only; not live rankings)",
                 "read-only; provider must persist atomic current/last snapshots" if "Kokudaka" in api else "authoritative ledger/snapshots not implemented",
                 "session country and player; no cost; read retries safe" if "Kokudaka" in api else "auth required; write costs/retry/dedup pending for dedicate; reads must not mutate",
                 status, "integrate verified A source + atomic provider" if "Kokudaka" in api else "obtain authoritative settlement, period and scope evidence before mounting"])

with (OUT / "reviewed-endpoints.tsv").open("w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f, delimiter="\t")
    writer.writerow(["endpoint", "request", "metric_source", "period", "response_hierarchy", "callback_evidence", "helper_evidence", "tables", "persistence", "permissions_cost_retry", "status", "next_step"])
    writer.writerows(rows)

used.update({"DedicateOfMaterialsDialog.cs", "UserStatus.cs", "MightOfNationDialog.cs",
    "CharacterTableAccessor.cs", "BuildingsTableAccessor.cs", "EquipTableAccessor.cs",
    "TacticsTableAccessor.cs", "DefinesTableAccessor.cs", "RankingTableAccessor.cs",
    "RankingRewardTableAccessor.cs", "CountryRankTableAccessor.cs", "NationalPowerGoalTableAccessor.cs"})
used.update(n for n in sources if n.startswith("HTMLRankingMediator"))
source_proofs = [{"path": str(SOURCE / n), "sha256": hashlib.sha256((SOURCE / n).read_bytes()).hexdigest()}
                 for n in sorted(used) if n in sources]
table_proofs = []
samples = {}
for name in ("defines", "ranking", "national_power_goal", "character", "building", "equip", "tactics"):
    p = TABLES / (name + ".json")
    data = parse_json_document(p.read_text(encoding="utf-8"))[name]
    key = "scale_kokudaka_for_dedication" if name == "defines" else next(iter(data))
    samples[name] = {key: data[key]}
    table_proofs.append({"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                         "sample_key": key, "row_count": len(data)})
(FIX / "original-table-samples.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
proof = {"baseline": "1f287e33123afa452d2f5d2aac2427566d549f73", "original_sources": source_proofs,
    "original_tables": table_proofs, "endpoints": evidence_endpoints,
    "protocol_evidence": ["zero-based inclusive pagination; current/last; indexed rankers", "brief and myRecord nesting differ", "common national power uses dedication scalar; dedication mutation returns nested dedication"],
    "server_compatibility_decisions": ["competition ties with playerId ordering not proven original", "100-row request limit", "explicit complete country snapshot provider; never infer scores from level", "missing period fails; proven empty snapshot yields rank=-1; no fake timestamp/reset", "no production registration; no full gameplay completion claim",
        "reject scores that cannot round-trip through float32 and Int32; never clamp or round source scores; support constraint, not original cap",
        "one immutable pair per response; separate requests may observe different publications; no invented revision wire field"],
    "kokudaka_self_review": {
        "list_paths": {"entries": "HTMLRankingMediator.cs:251", "myRecord.rank/score": "HTMLRankingMediator.cs:281-290",
                       "rankers.<pageIndex>.rank/score/username/playerId/country": "HTMLRankingMediator.cs:304-344"},
        "brief_paths": {"brief.rank/score/lastRank": "mypageRankingWindow.cs:787-797",
                        "brief.rank for Around": "HTMLRankingMediator_Kokudaka.cs:43-53"},
        "numeric_conversion": ["mypageRankingWindow.cs:503: getInt after makeBriefInfo.getLong",
                               "HashAccessFuncs.cs:94-118: float.TryParse then (int)",
                               "HTMLRankingMediator.cs:327: list score via getDouble then (long)"],
        "known_client_limit": "Kokudaka historical Around calls a term-less current brief before requesting term=last; cannot change brief semantics or add guessed request fields",
        "concurrency_test_boundary": "two authenticated readers plus concurrent publication, paused after pair capture; proves request-local consistency only, not producer/database transactions"}}
(OUT / "evidence.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {len(rows)} endpoints, {len(source_proofs)} source hashes, {len(table_proofs)} small table samples")
