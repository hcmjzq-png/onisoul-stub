"""候选缺口表的来源过滤口径：过滤后的候选行必须都能在判读台账里找到结论。

两套东西，故意用两套逻辑交叉校验：

* `docs/analysis/verify/gap_receivers.tsv` + `gap_origins.tsv` 是**机械**判定依据
  （每条读取的接收者表达式、以及「这个接收者不是响应回包」的来源类别）；
* `docs/analysis/unguarded_gaps_verdicts.tsv` 是**人工**逐行判读的定论。

`tools/unguarded_reads.py gap --filter origin` 只按前者剔除键，本测试则要求：
过滤后的 `unguarded_gaps.tsv` 里不允许出现任何被判读为 `not_response` 的行，
且每一个被剔除的键都能在机械依据里找到出处（写侧赋值或命中的来源表行）。
"""
from __future__ import annotations

import fnmatch
import io
import os
import unittest
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAPS = os.path.join(ROOT, "docs", "analysis", "unguarded_gaps.tsv")
VERDICTS = os.path.join(ROOT, "docs", "analysis", "unguarded_gaps_verdicts.tsv")
CONTRACT = os.path.join(ROOT, "docs", "analysis", "api_contract.tsv")
RECEIVERS = os.path.join(ROOT, "docs", "analysis", "verify", "gap_receivers.tsv")
ORIGINS = os.path.join(ROOT, "docs", "analysis", "verify", "gap_origins.tsv")

VERDICT_VOCAB = {"real_gap", "not_response", "other_endpoint", "covered_nested"}
FILTER_VOCAB = {"kept", "dropped", "mixed", "nested"}
ORIGIN_VOCAB = {
    "write",
    "html_request",
    "task_param",
    "config_table",
    "dialog_result",
    "local_build",
    "debug_build",
    "message_table",
    "nested_child",
}

# 判读为真缺口、本批已补进契约的键
REAL_GAP_KEYS = {
    "debug/dedicate": ["score:double"],
    "debug/resetDedication": ["score:double"],
    "deck/extendCharacterStore": [
        "possessionLimits:Hashtable",
        "possessionLimits.character:Hashtable",
    ],
    "quest/clearObstacle": ["uses:Hashtable", "uses.category:string"],
    "battle/executeBattle": [
        "executeInfo:Hashtable",
        "executeInfo.step:double",
        "executeInfo.missionPoint:double",
        "eventInfo:Hashtable",
        "eventInfo.obstacleInfo:Hashtable",
        "eventInfo.treasureInfo:Hashtable",
        "rewardInfo:Hashtable",
        "bonusInfo:Hashtable",
    ],
    "politic/support_item/getPotions": [
        "potions:Hashtable",
        "potions.potion0000102:Hashtable",
        "potions.potion0000102.amount:double",
    ],
}

# 判读归给别人、但那批键必须在归属端点里真的声明过
OWNER_KEYS = {
    "deck/getDeckBonus": ["deck.<kind>.<slot>.id", "deck.<kind>.<slot>.bonus:Hashtable"],
    "deck/getDecks": ["inheritPoint:double", "possessionLimits:Hashtable", "skillCoins:double"],
    "deck/getAvatarCharacters": ["baseId:string"],
    "ranking/getRecordOfCountryInBattle": ["countryId", "rank:double"],
    "battle/getRivals2": ["rivals:Hashtable"],
    "friend/getFriendMapData2": ["acceleratecount:double", "completecount:double"],
    "quest/getQuestEncountWorks": ["obstacle:Hashtable"],
    "quest/getQuestBossPunish": ["script:string"],
    "quest/getChapterData": ["clearCount:double"],
    "inbox/getParcels": ["parcels", "totalCount"],
    "common/getPlayerParams": ["actionPoints:Hashtable", "entity:Hashtable", "resources:Hashtable"],
    "battle/executeBattle": ["eventInfo:Hashtable", "eventInfo.eventType:double", "rewardInfo:Hashtable"],
    "strategy/getStrategyStatus": [
        "self:Hashtable",
        "self.team:string",
        "self.route:Hashtable",
        "self.isAlive:bool",
        "cell:Hashtable",
        "cell.attackLogs:Hashtable",
    ],
}

# 判读为「消息表污染」，契约里必须没有
POLLUTION_KEYS = {
    "strategy/getStrategyCommandInfo": [
        "STRATEGY_MSG_COMMAND_CONSCRIPT_INFO0",
        "STRATEGY_MSG_COMMAND_TRAINING_INFO0",
    ],
}


def _tsv(path: str) -> list[dict[str, str]]:
    lines = io.open(path, encoding="utf-8").read().split("\n")
    head = lines[0].split("\t")
    out = []
    for line in lines[1:]:
        if line.strip():
            out.append(dict(zip(head, line.split("\t"))))
    return out


def _keys(row: dict[str, str]) -> list[str]:
    return [k for k in row["response_keys"].split(";") if k.strip()]


class GapVerdictsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gaps = _tsv(GAPS)
        cls.verdicts = _tsv(VERDICTS)
        cls.contract = {row["endpoint"]: row for row in _tsv(CONTRACT)}
        cls.receivers = defaultdict(list)
        for row in _tsv(RECEIVERS):
            cls.receivers[(row["callsite"], row["key"])].append((row["receiver"], row["write"]))
        cls.origins = [(r["callsite"], r["receiver"], r["origin"]) for r in _tsv(ORIGINS)]

    # ---- 判读台账自身 ---------------------------------------------------
    def test_verdict_counts_and_filter_column(self) -> None:
        counts = Counter(r["verdict"] for r in self.verdicts)
        labels = Counter(r["filter"] for r in self.verdicts)
        self.assertEqual(len(self.verdicts), 104)
        self.assertEqual(
            counts,
            Counter({"not_response": 67, "other_endpoint": 33, "real_gap": 2, "covered_nested": 2}),
        )
        self.assertEqual(labels, Counter({"dropped": 67, "kept": 33, "mixed": 2, "nested": 2}))
        for row in self.verdicts:
            self.assertIn(row["filter"], FILTER_VOCAB, row["endpoint"])

    def test_verdict_values_and_owner_shape(self) -> None:
        for row in self.verdicts:
            self.assertIn(row["verdict"], VERDICT_VOCAB, row["endpoint"])
            if row["verdict"] in ("real_gap", "covered_nested"):
                self.assertEqual(row["real_owner"], "", "真缺口/已声明嵌套不该填归属端点：%s" % row["endpoint"])
            elif row["verdict"] == "other_endpoint":
                self.assertNotEqual(row["real_owner"], "", "归属错的行必须给出真端点：%s" % row["endpoint"])
                for owner in row["real_owner"].split(";"):
                    self.assertIn(owner, self.contract, "归属端点不在契约里：%s" % owner)
            else:
                self.assertNotIn(
                    row["real_owner"].strip(),
                    self.contract,
                    "not_response 行把端点写进了 real_owner：%s" % row["endpoint"],
                )

    # ---- 过滤后的候选表 vs 台账 -----------------------------------------
    def test_filtered_gaps_are_the_kept_rows(self) -> None:
        kept = {(r["endpoint"], r["callsite"]) for r in self.verdicts if r["filter"] == "kept"}
        out = {(r["endpoint"], r["callsite"]) for r in self.gaps}
        self.assertEqual(len(self.gaps), 33, "过滤后候选行数变了，记得同步文档")
        self.assertEqual(len({r["endpoint"] for r in self.gaps}), 25)
        self.assertEqual(out, kept, "候选表与台账 kept 行不对应")

    def test_no_not_response_row_survives(self) -> None:
        verdict = {(r["endpoint"], r["callsite"]): r["verdict"] for r in self.verdicts}
        residue = [
            (r["endpoint"], r["callsite"])
            for r in self.gaps
            if verdict[(r["endpoint"], r["callsite"])] == "not_response"
        ]
        self.assertEqual(residue, [], "过滤后仍残留读的不是回包的候选行：%s" % residue)
        for row in self.gaps:
            self.assertIn(
                verdict[(row["endpoint"], row["callsite"])],
                {"real_gap", "other_endpoint"},
                "候选行必须是真缺口或归属错：%s" % row["callsite"],
            )

    def test_label_matches_verdict(self) -> None:
        for row in self.verdicts:
            if row["filter"] == "dropped":
                self.assertEqual(row["verdict"], "not_response", row["endpoint"])
            elif row["filter"] == "kept":
                self.assertIn(row["verdict"], {"real_gap", "other_endpoint"}, row["endpoint"])
            elif row["filter"] == "nested":
                self.assertEqual(row["verdict"], "covered_nested", row["endpoint"])
            else:
                self.assertEqual(row["verdict"], "real_gap", "mixed 只该出现在真缺口行：%s" % row["endpoint"])

    def test_gap_keys_are_subset_of_ledger_keys(self) -> None:
        ledger = {(r["endpoint"], r["callsite"]): set(r["missing_keys"].split(",")) for r in self.verdicts}
        for row in self.gaps:
            keys = set(row["missing_keys"].split(","))
            self.assertTrue(keys, "候选行的 missing_keys 不能为空：%s" % row["callsite"])
            extra = keys - ledger[(row["endpoint"], row["callsite"])]
            self.assertEqual(extra, set(), "过滤只会减键，不会新增：%s" % extra)

    # ---- 被剔除的键必须有机械依据 ---------------------------------------
    def _roots(self, endpoint: str) -> set[str]:
        """契约里该端点已声明的根键（去类型、去可选与动态标记）。"""
        out = set()
        for item in _keys(self.contract[endpoint]):
            head = item.split(":")[0]
            out.add(head.split(".")[0].rstrip("*<>"))
            out.add(head.rstrip("*<>"))
        return out

    def _provenance(self, site: str, key: str) -> str | None:
        occ = self.receivers.get((site, key), [])
        if occ and all(w == "W" for _, w in occ):
            return "write"
        for pat, want, origin in self.origins:
            if not fnmatch.fnmatchcase(site, pat):
                continue
            if want == "*" or any(recv == want for recv, _ in occ):
                return origin
        return None

    def test_dropped_keys_have_mechanical_provenance(self) -> None:
        gaps_keys = {(r["endpoint"], r["callsite"]) for r in self.gaps}
        out_keys = defaultdict(set)
        for row in self.gaps:
            out_keys[(row["endpoint"], row["callsite"])] = set(row["missing_keys"].split(","))
        unexplained = []
        for row in self.verdicts:
            declared = self._roots(row["endpoint"])
            if row["filter"] == "dropped":
                gone = set(row["missing_keys"].split(",")) - declared
            elif row["filter"] in ("mixed", "nested"):
                pair = (row["endpoint"], row["callsite"])
                gone = set(row["missing_keys"].split(",")) - out_keys.get(pair, set()) - declared
            else:
                continue
            for key in gone:
                if self._provenance(row["callsite"], key) is None:
                    unexplained.append((row["callsite"], key))
        self.assertEqual(unexplained, [], "这些键被过滤掉但找不到来源依据：%s" % unexplained)
        self.assertGreater(len(gaps_keys), 0)

    # ---- 取证表自身 ------------------------------------------------------
    def test_provenance_tables_are_well_formed(self) -> None:
        sites = set()
        for row in self.contract.values():
            for item in row["call_sites"].split(";"):
                for one in item.split("|"):
                    one = one.split("#")[0].strip()
                    if one:
                        sites.add(one)
        for row in _tsv(ORIGINS):
            self.assertIn(row["origin"], ORIGIN_VOCAB, "来源类别不在词表：%s" % row["origin"])
            self.assertTrue(row["evidence"].strip(), "来源行必须带证据：%s" % row["callsite"])
        for row in _tsv(ORIGINS):
            pat = row["callsite"]
            if "*" in pat:
                self.assertTrue(
                    any(fnmatch.fnmatchcase(s, pat) for s in sites),
                    "整站点规则没命中任何契约调用点：%s" % pat,
                )
            else:
                self.assertIn(pat, sites, "来源表里的调用点不在契约 call_sites：%s" % pat)
        for row in _tsv(RECEIVERS):
            self.assertIn(row["callsite"], sites, "接收者表的调用点不在契约 call_sites：%s" % row["callsite"])
            self.assertIn(row["write"], {"W", "R"}, "write 列只能是 W/R")
            self.assertTrue(row["receiver"].strip(), "接收者不能为空")
            self.assertTrue(row["line"].isdigit(), "行号必须是数字")

    # ---- 已补进契约的键 ------------------------------------------------
    def test_real_gap_keys_are_declared(self) -> None:
        for ep, keys in REAL_GAP_KEYS.items():
            row = self.contract[ep]
            declared = _keys(row)
            missing = [k for k in keys if k not in declared]
            self.assertEqual(missing, [], "%s 缺键没落表：%s" % (ep, missing))
            self.assertEqual(int(row["key_count"]), len(declared), "%s key_count 与条目数不一致" % ep)

    def test_owner_endpoints_declare_the_keys(self) -> None:
        for ep, keys in OWNER_KEYS.items():
            declared = {k.split(":")[0] for k in _keys(self.contract[ep])}
            missing = [k for k in keys if k.split(":")[0] not in declared]
            self.assertEqual(missing, [], "%s 没声明 %s" % (ep, missing))

    def test_pollution_keys_removed(self) -> None:
        for ep, keys in POLLUTION_KEYS.items():
            declared = _keys(self.contract[ep])
            for key in keys:
                self.assertNotIn(key, declared, "%s 仍挂着消息表污染键 %s" % (ep, key))

    def test_get_potions_has_no_untyped_potions(self) -> None:
        declared = _keys(self.contract["politic/support_item/getPotions"])
        self.assertNotIn(
            "potions*",
            declared,
            "potions 不能留无类型/可选形态，占位会整键跳过（QuestScriptCommand.cs:1609 会读到 null）",
        )


if __name__ == "__main__":
    unittest.main()
