"""嵌套占位与精确响应体的回归测试（任务 #7 第一批）。"""
from __future__ import annotations

import unittest

from app.business import contract, placeholders, response_shapes


class NestedPlaceholderTest(unittest.TestCase):
    def test_dotted_keys_become_nested_dicts(self) -> None:
        payload = placeholders.payload("turfWar/receiveTurfWarReward")
        self.assertIsInstance(payload["schedule"], dict)
        # TurfWarResultRenderer.cs:67-68 直接拆箱这两个秒数
        self.assertEqual(payload["schedule"]["open"], 0.0)
        self.assertEqual(payload["schedule"]["close"], 0.0)
        self.assertEqual(payload["global"]["end"]["score"], 0.0)
        self.assertIsInstance(payload["global"]["daily"], dict)
        self.assertIsInstance(payload["battlefield"]["end"], dict)
        self.assertIsInstance(payload["bonuses"], dict)

    def test_res_add_keys_are_not_prebuilt(self) -> None:
        # convertBonus: `res.Add("victory", false)` / convertHtmlParameter:
        # `res.Add("names", value)`：键已存在会抛 ArgumentException，不能预置。
        payload = placeholders.payload("turfWar/receiveTurfWarReward")
        self.assertNotIn("victory", payload)
        self.assertNotIn("names", payload)

    def test_friend_map_data_three_levels(self) -> None:
        payload = placeholders.payload("friend/getFriendMapData2")
        # Politic.cs:318 起：completecount / acceleratecount 无守卫拆箱
        self.assertEqual(payload["completecount"], 0.0)
        self.assertEqual(payload["acceleratecount"], 0.0)
        # ((Hashtable)result)["friendInfo"]["turfWar"]["team"] 三级取值
        self.assertEqual(payload["friendInfo"]["turfWar"]["team"], "")

    def test_event_status_submaps(self) -> None:
        """StatusView.cs:488-520 用 isEventOpen(ContainsKey) 选子表，子表一存在就进各自 setup，
        四个 setup 都无守卫拆箱（`(long)(double)table["closeTime"]`），缺键即 NRE。"""
        payload = placeholders.payload("common/getEventStatuses")
        for name in ("turfWar", "strategy", "siege", "giganticRaidBoss"):
            self.assertIsInstance(payload[name], dict)
        # TurfWarBriefCache.cs:353-354 + getTime:454-469
        self.assertEqual(payload["turfWar"]["status"], "")
        self.assertEqual(payload["turfWar"]["closeWarTime"], 0.0)
        self.assertEqual(payload["turfWar"]["resultCloseTime"], 0.0)
        # StrategyDataCache.cs:196-198 + getTime:168-178
        self.assertIs(payload["strategy"]["isEntry"], False)
        self.assertEqual(payload["strategy"]["endTime"], 0.0)
        # SiegeBriefDataCache.cs:164-167 + getTime:173-183
        self.assertEqual(payload["siege"]["advantage"], "")
        self.assertEqual(payload["siege"]["resultCloseTime"], 0.0)
        # GiganticRaidBossDataCache.cs:111-116 + getTime:82-92
        self.assertIs(payload["giganticRaidBoss"]["isEntry"], False)
        self.assertEqual(payload["giganticRaidBoss"]["closeTime"], 0.0)

    def test_raid_and_siege_schedule_shapes(self) -> None:
        raid = placeholders.payload("giganticRaidBoss/getGiganticRaidBossEventResult")
        # GiganticRaidBossResultRenderer.cs:25-26 用的是 open / end
        self.assertEqual(raid["schedule"]["open"], 0.0)
        self.assertEqual(raid["schedule"]["end"], 0.0)
        siege = placeholders.payload("siege/getSiegeResultLog")
        self.assertEqual(siege["schedule"]["close"], 0.0)


class BareMapBodyTest(unittest.TestCase):
    def test_set_map_name_returns_empty_map(self) -> None:
        body = response_shapes.success(
            "politic/map/setMapName2", placeholders.payload("politic/map/setMapName2")
        )
        # UserStatus.cs:1401 数 Keys.Count：必须为 0，任何键（含 now）都会判失败
        self.assertEqual(body, {})
        self.assertEqual(
            response_shapes.shape_for("politic/map/setMapName2"),
            response_shapes.ResponseShape.BARE_MAP,
        )

    def test_other_endpoints_keep_envelope(self) -> None:
        body = response_shapes.success("common/getPlayerParams", {"entity": {}})
        self.assertIn("now", body)
        self.assertIn("succeeded", body)


class ContractDottedKeysTest(unittest.TestCase):
    def test_dotted_keys_are_declared(self) -> None:
        keys = {f["key"] for f in contract.response("turfWar/receiveTurfWarReward")}
        self.assertIn("schedule.open", keys)
        self.assertIn("global.end.rank", keys)

class ResultRendererKeyTest(unittest.TestCase):
    """同族结果渲染器：不预置 Add 的键，其余无守卫读取都要有占位。"""

    RES_ADD_KEYS = {
        "giganticRaidBoss/getGiganticRaidBossEventResult": [
            "bonus",
            "names",
            "attackerRank",
            "contributionRank",
            "chainCounts",
            "chainPlayers",
        ],
        # TurfWarResultRenderer.convertBonus 里 res.Add("victory")，convertHtmlParameter 里
        # res.Add("names")；SiegeResultRenderer 只做赋值不做 Add。
        "turfWar/receiveTurfWarReward": ["victory", "names"],
    }

    def test_no_predeclared_add_keys(self) -> None:
        for api, keys in self.RES_ADD_KEYS.items():
            payload = placeholders.payload(api)
            for key in keys:
                with self.subTest(api=api, key=key):
                    self.assertNotIn(key, payload)

    def test_gigantic_raid_boss_unguarded_keys(self) -> None:
        payload = placeholders.payload("giganticRaidBoss/getGiganticRaidBossEventResult")
        # country 为空串仍会走表查询，但绝不能是 null（Hashtable 不允许 null 键）
        self.assertIsInstance(payload["country"], str)
        self.assertIsInstance(payload["punishPoint"], str)
        for box in ("damage", "contribute"):
            self.assertIsInstance(payload[box]["top"]["name"], str)
            self.assertEqual(payload[box]["top"]["rank"], 0.0)
            self.assertEqual(payload[box]["top"]["value"], 0.0)
            self.assertEqual(payload[box]["self"]["rank"], 0.0)

    def test_siege_unguarded_keys(self) -> None:
        payload = placeholders.payload("siege/getSiegeResultLog")
        self.assertIsInstance(payload["attacker"], dict)
        self.assertIsInstance(payload["defender"], dict)
        self.assertEqual(payload["record"]["rank"], 0.0)
        self.assertIsInstance(payload["record"]["globalTotalScore"], str)
        self.assertIsInstance(payload["winner"], dict)

    def test_event_statuses_root_has_only_submaps(self) -> None:
        """根上只有四个事件子表。

        6 个调用点全部只读子表（StatusView.cs:490/500/510/520、giganticRaidBossScene.cs:66、
        Strategy.cs:75、StrategySelect.cs:55、PluginRunner_DoBattleSiege.cs:266-271）；
        曾经混进根上的 chain/phase/punishPoint/monsterId/attackList/needPoint/endTime 其实读的是
        giganticRaidBoss/getGiganticRaidBossInformation（giganticRaidBossScene.cs:120-130），
        a/b/current/max 读的是 strategy/getStrategyBrief（StrategySelect.cs:102-110）。
        """
        payload = placeholders.payload("common/getEventStatuses")
        self.assertEqual(sorted(payload), ["giganticRaidBoss", "siege", "strategy", "turfWar"])

    def test_gigantic_raid_boss_information_reads(self) -> None:
        # giganticRaidBossStatus.cs:22-27 needPoint 里按下标取 3 档难度
        # :35-36 hp / damage；giganticRaidBossScene.cs:132-133 giganticRaidBossPoint.status
        payload = placeholders.payload("giganticRaidBoss/getGiganticRaidBossInformation")
        self.assertEqual(payload["needPoint"], {"0": 0, "1": 0, "2": 0})
        self.assertEqual(payload["giganticRaidBossPoint"]["status"], "")
        self.assertIsInstance(payload["hp"], int)
        self.assertIsInstance(payload["damage"], int)

if __name__ == "__main__":
    unittest.main()
