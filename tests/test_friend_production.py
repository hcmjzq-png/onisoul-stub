"""Atomic visitor/owner production, quotas, permissions and friend-only buildings."""
import copy
from concurrent.futures import ThreadPoolExecutor

from app.business.friend_production import FriendProduction
from app.business.social_services import SocialServices
from tests.test_production_completion import CompletionCase, CASES
from tests.test_social_services import AtomicMemory


class FriendProductionTest(CompletionCase):
    def setUp(self):
        super().setUp()
        self.place("building200_032_01_01_1_1", player_level=1)
        old = self.states
        self.states = AtomicMemory()
        self.states.rows = copy.deepcopy(old.rows)
        self.mount()
        self.actor = self.session
        self.owner, _ = self.service._issue_login("production-owner-isolated")
        result = self.service.create_player({"username": "production-owner-isolated", "countryId": "country01",
            "navigatorId": "navi8000101", "colorIndex": "color1"}, self.owner)
        self.assertTrue(result["succeeded"], result)
        for session, target in ((self.actor, self.owner), (self.owner, self.actor)):
            player = self.states.load(session["playerId"])
            player["friends"] = {target["playerId"]: {}}
            player["actionPoints"]["politicPoint"].update(point=25, confirmTime=0.0)
            for kind in ("gold", "wood", "food", "iron", "credit"):
                player["resources"][kind]["amount"] = 0
            self.states.save(player, session["playerId"])
        self.register_friend()
        self.set_owner("building200_032_01_01_1_1")

    def register_friend(self):
        self.social = SocialServices(self.service, atomic_players=self.states.transaction, clock=lambda: self.now)
        self.friend = FriendProduction(self.service, self.social)
        self.friend.register(self.registry)

    def set_owner(self, bid):
        player = self.states.load(self.owner["playerId"])
        player["buildings"] = {"1": {"instanceId": 1, "buildingTypeId": bid, "level": 1, "exp": 0,
            "status": "none", "durability": self.tables["building"][bid]["durability"],
            "deployedMapKey": "map001", "x": 10, "y": 10, "remainedClickCount": 0}}
        player["occupiedGrids"] = {"10,10": "1"}
        player["produce"] = {}
        player["automaticResourceProductionV1"] = {}
        player["counters"].update(nextBuildingId=2, buildingCount=1)
        self.states.save(player, self.owner["playerId"])
        mapped = self.f("getFriendMapData2", mapId=-1)
        self.assertTrue(mapped["succeeded"], mapped)
        return mapped

    def f(self, name, **params):
        params.setdefault("friendPlayerId", self.owner["playerId"])
        status, result = self.registry.dispatch("friend/" + name, params, self.actor)
        self.assertEqual(status, 200, result)
        return result

    def test_visit_projects_owner_map_and_counts_without_exposing_private_inventory(self):
        mapped = self.f("getFriendMapData2", mapId=0)
        self.assertEqual((mapped["completecount"], mapped["acceleratecount"]), (5, 5))
        self.assertIn("1", mapped["tasks"]["producings"])
        self.assertNotIn("resources", mapped)
        self.assertNotIn("items", mapped)
        visit = self.f("visitFriendMap")
        self.assertEqual(visit["navigator"]["id"], "navi8000101")
        # resetFriendMap forwards the visit response to the reward menu.
        self.assertIs(visit["isFirst"], False)
        self.assertEqual(visit["reward"], {})
        self.assertEqual(visit["toInbox"], {})
        products = self.f("building/getFriendProductsByBuilding", buildingId=1)
        self.assertIn("building200_032_01_01_1_1", products["products"])
        before = copy.deepcopy(self.states.rows)
        self.assertFalse(self.f("getFriendMapData2", friendPlayerId=self.actor["playerId"], mapId=0)["succeeded"])
        self.assertFalse(self.f("getFriendMapData2", mapId=1)["succeeded"])
        self.assertEqual(self.states.rows, before)

    def test_help_harvest_credits_both_players_once_and_costs_no_points(self):
        self.assertEqual(self.f("task/completeFriendTasks", mapId=0, buildingId="1")["errno"], 1)
        self.now += 7200
        result = self.f("task/completeFriendTasks", mapId=0, buildingId="1")
        self.assertTrue(result["succeeded"], result)
        self.assertNotIn("errno", result)
        self.assertEqual(result["completecount"], 4)
        for session in (self.actor, self.owner):
            player = self.states.load(session["playerId"])
            self.assertEqual(player["resources"]["food"]["amount"], 1000)
            self.assertEqual(player["actionPoints"]["politicPoint"]["point"], 25)
        before = copy.deepcopy(self.states.rows)
        self.assertEqual(self.f("task/completeFriendTasks", mapId=0, buildingId="1")["errno"], 1)
        self.assertEqual(self.states.rows, before)
        self.mount()
        self.register_friend()
        self.assertEqual(self.f("getFriendMapData2", mapId=0)["completecount"], 4)

    def test_daily_help_and_acceleration_quotas_are_persisted_and_reset(self):
        for remaining in range(4, -1, -1):
            result = self.f("task/accelerateFriendProduceTask", mapId=0, buildingId=1.0, id="produce_accel_0001")
            self.assertTrue(result["succeeded"], result)
            self.assertEqual(result["acceleratecount"], remaining)
        self.assertEqual(self.f("task/accelerateFriendProduceTask", mapId=0, buildingId=1, id="produce_accel_0001")["errno"], 1)
        for session in (self.actor, self.owner):
            self.assertEqual(self.states.load(session["playerId"])["resources"]["credit"]["amount"], 0)
        for remaining in range(4, -1, -1):
            self.now = self.states.load(self.owner["playerId"])["produce"]["1"]["dueTime"]
            result = self.f("task/completeFriendTasks", mapId=0, buildingId=1)
            self.assertEqual(result["completecount"], remaining)
        self.now = self.states.load(self.owner["playerId"])["produce"]["1"]["dueTime"]
        self.assertEqual(self.f("task/completeFriendTasks", mapId=0, buildingId=1)["errno"], 1)
        self.now += 86400
        counts = self.f("getFriendMapData2", mapId=0)
        self.assertEqual((counts["completecount"], counts["acceleratecount"]), (5, 5))

    def test_visitor_capacity_or_commit_conflict_rolls_back_owner_and_visitor(self):
        self.now += 7200
        actor = self.states.load(self.actor["playerId"])
        actor["resources"]["food"]["amount"] = actor["resources"]["food"]["maxAmount"]
        self.states.save(actor, self.actor["playerId"])
        before = copy.deepcopy(self.states.rows)
        self.assertFalse(self.f("task/completeFriendTasks", mapId=0, buildingId=1)["succeeded"])
        self.assertEqual(self.states.rows, before)
        actor["resources"]["food"]["amount"] = 0
        self.states.save(actor, self.actor["playerId"])
        before = copy.deepcopy(self.states.rows)
        self.states.fail_commit = True
        self.assertFalse(self.f("task/completeFriendTasks", mapId=0, buildingId=1)["succeeded"])
        self.assertEqual(self.states.rows, before)
        self.states.fail_commit = False
        self.assertTrue(self.f("task/completeFriendTasks", mapId=0, buildingId=1)["succeeded"])

    def test_simultaneous_helpers_cannot_consume_or_credit_one_cycle_twice(self):
        self.now += 7200
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.f("task/completeFriendTasks", mapId=0, buildingId=1), range(8)))
        self.assertEqual(sum("producings" in result for result in results), 1)
        self.assertEqual(self.states.load(self.actor["playerId"])["resources"]["food"]["amount"], 1000)
        self.assertEqual(self.states.load(self.owner["playerId"])["buildings"]["1"]["exp"], 100)

    def test_friend_only_building_rejects_owner_but_visitor_can_harvest_and_renew(self):
        self.set_owner(CASES["friend"])
        status, rejected = self.registry.dispatch("politic/task/completeTasks", {"buildingIds": [1]}, self.owner)
        self.assertEqual(status, 200)
        self.assertFalse(rejected["succeeded"])
        self.now += 3600
        result = self.f("task/completeFriendTasks", mapId=0, buildingId=1)
        self.assertTrue(result["succeeded"], result)
        self.assertNotIn("errno", result)
        self.assertIn("1", result["autoProducings"])
        self.assertEqual(self.states.load(self.actor["playerId"])["resources"]["gold"]["amount"], 18000)

    def test_all_five_original_friend_grades_settle_and_renew(self):
        for bid, row in self.tables["building"].items():
            if row.get("produceType") != "friend":
                continue
            with self.subTest(building=bid):
                # Each grade is an independent visitor/owner pair, so a high
                # reward cannot overflow a preceding grade's resource stock.
                for session in (self.actor, self.owner):
                    player = self.states.load(session["playerId"])
                    player["entity"]["level"] = 100
                    for resource in ("gold", "wood", "food", "iron"):
                        player["resources"][resource]["amount"] = 0
                    player.pop("friendProductionV1", None)
                    self.states.save(player, session["playerId"])
                self.set_owner(bid)
                self.now = self.states.load(self.owner["playerId"])["produce"]["1"]["dueTime"]
                result = self.f("task/completeFriendTasks", mapId=0, buildingId=1)
                self.assertTrue(result["succeeded"], result)
                self.assertNotIn("errno", result)
                self.assertIn("1", result["autoProducings"])
                for resource in ("gold", "wood", "food", "iron"):
                    self.assertEqual(self.states.load(self.actor["playerId"])["resources"][resource],
                                     self.states.load(self.owner["playerId"])["resources"][resource])

    def test_nonfriend_or_foreign_building_request_cannot_mutate_either_account(self):
        before = copy.deepcopy(self.states.rows)
        self.assertEqual(self.f("task/completeFriendTasks", mapId=0, buildingId=999)["errno"], 2)
        self.assertEqual(self.states.rows, before)
        owner = self.states.load(self.owner["playerId"])
        owner["friends"] = {}
        self.states.save(owner, self.owner["playerId"])
        before = copy.deepcopy(self.states.rows)
        self.assertFalse(self.f("task/completeFriendTasks", mapId=0, buildingId=1)["succeeded"])
        self.assertEqual(self.states.rows, before)
