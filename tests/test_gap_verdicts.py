"""104 条候选缺口的逐行判读结论必须与契约表自洽。

`docs/analysis/unguarded_gaps.tsv` 是扫描器的**候选**输出（按「类名.方法名」归属，
同一方法里读任何 hashtable 都会被挂到该方法的端点上）。`unguarded_gaps_verdicts.tsv`
是人工逐条判读后的定论表。本测试把两者的口径差钉死：

- 判读表与候选表逐行一一对应（不多不少，端点 + 调用点唯一）；
- `verdict` 只允许 `real_gap` / `not_response` / `other_endpoint`；
- `real_gap` 行不得填 `real_owner`，`other_endpoint` 行必须填 `real_owner` 且该端点在契约里存在；
- 真缺口补进去的键必须真的在契约的 `response_keys` 里（防止判读了却没落表）。
"""
from __future__ import annotations

import io
import os
import unittest
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAPS = os.path.join(ROOT, "docs", "analysis", "unguarded_gaps.tsv")
VERDICTS = os.path.join(ROOT, "docs", "analysis", "unguarded_gaps_verdicts.tsv")
CONTRACT = os.path.join(ROOT, "docs", "analysis", "api_contract.tsv")

VERDICT_VOCAB = {"real_gap", "not_response", "other_endpoint"}

# 判读为真缺口、本批已补进契约的键
REAL_GAP_KEYS = {
    "debug/dedicate": ["score:double"],
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
    "deck/getDeckBonus": ["id", "bonus:Hashtable"],
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

    def test_verdict_covers_every_gap_row(self) -> None:
        gap_pairs = Counter((r["endpoint"], r["callsite"]) for r in self.gaps)
        ver_pairs = Counter((r["endpoint"], r["callsite"]) for r in self.verdicts)
        self.assertEqual(gap_pairs, ver_pairs, "判读表与候选表行（含重复行）不对应")

    def test_verdict_values_and_owner_shape(self) -> None:
        for row in self.verdicts:
            self.assertIn(row["verdict"], VERDICT_VOCAB, row["endpoint"])
            if row["verdict"] == "real_gap":
                self.assertEqual(row["real_owner"], "", "真缺口不该填归属端点：%s" % row["endpoint"])
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

    def test_verdict_counts(self) -> None:
        counts = {"real_gap": 0, "not_response": 0, "other_endpoint": 0}
        for row in self.verdicts:
            counts[row["verdict"]] += 1
        self.assertEqual(len(self.verdicts), 104)
        self.assertEqual(counts, {"not_response": 67, "other_endpoint": 33, "real_gap": 4})

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
