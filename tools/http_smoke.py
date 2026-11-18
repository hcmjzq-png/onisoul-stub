#!/usr/bin/env python3
"""Exercise HTTP registration/login/create-player using an isolated temporary account.

Requires the target service's ONI_DB_* configuration for exact-account cleanup.
No existing player is modified; tokens/passwords are never printed.
"""
from __future__ import annotations

import argparse
import http.client
import json
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db, state


def run(host: str, port: int) -> None:
    account = "audit_" + secrets.token_hex(8)
    password = secrets.token_urlsafe(18)
    login_path = "/index.php/gwz/client/login/"

    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(host, port, timeout=15)
        try:
            conn.request(method, path, body, headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def api(name, params, method="POST"):
        form = urlencode({"params": json.dumps(params)})
        status, _, body = request(method, "/api/" + name + ("?" + form if method == "GET" else ""),
                                 form if method == "POST" else None,
                                 {"Content-Type": "application/x-www-form-urlencoded"})
        assert status == 200, (name, status)
        result = json.loads(body)
        if result.get("succeeded") is True:
            assert "errorReason" not in result, (name, "success rejected by GameRestarter")
        return result

    # A fresh instance creates the login table on its first normal page load.
    assert request('GET', login_path)[0] == 200
    # Confirm DB access and uniqueness before creating anything through HTTP.
    with db.connection() as con:
        with con.cursor() as cur:
            cur.execute("SELECT account_key FROM users WHERE account_key = %s", (account,))
            assert cur.fetchone() is None
    try:
        form = urlencode({"account": account, "password": password})
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        assert request("POST", login_path + "?page=register", form, headers)[0] == 200
        status, response_headers, _ = request("POST", login_path, form, headers)
        assert status == 302, "web login did not issue a redirect"
        token = parse_qs(urlsplit(response_headers["Location"]).query)["token"][0]
        initial = api("auth/gameLogin", {"token": token})
        assert initial.get("succeeded") is False and initial.get("playerId"), "fresh player detection"
        assert api("auth/registerName", {"token": token, "username": account})["succeeded"]
        assert api("auth/createPlayer", {"token": token, "username": account, "countryId": "country01",
                                        "navigatorId": "navi8000101", "colorIndex": "color1"})["succeeded"]
        assert api("auth/gameLogin", {"token": token})["succeeded"]
        assert api("politic/building/getDrafts", {"token": token}) == {}
        params = api("common/getPlayerParams", {"token": token}, "GET")
        assert params["entity"]["username"] == account and params["characterCount"] > 0
        assert params["resources"]["gold"]["amount"] == 5000
        assert all(params["resources"][key]["amount"] == 0 for key in ("food", "wood", "iron", "credit"))
        assert [params["actionPoints"][key]["point"] for key in ("missionPoint", "politicPoint", "battlePoint")] == [25, 25, 100]
        for name in ("common/getEventStatuses", "common/getShopsale"):
            result = api(name, {"token": token})
            assert result["succeeded"] and set(result) == {"succeeded", "now"}, name
        characters = api("common/getCharacters", {"token": token})
        assert len(characters) == int(params["characterCount"])
        deck = api("deck/getDecks", {"token": token})
        groups = ("avatar", "attack", "defense", "politic", "quest", "strategy", "siege")
        value = {key: deck[key] for key in groups}
        ids = list(characters)
        chosen = ids[-1]
        value["avatar"]["id"] = int(chosen)
        value["attack"]["0"]["ids"] = {"4": int(chosen)}
        assert api("deck/setDecks", {"token": token, "decks": value}) == {}
        reread = api("deck/getDecks", {"token": token})
        assert {key: reread[key] for key in groups} == value
        assert set(api("deck/getAvatarCharacters", {"token": token, "playerIds": []})) == {chosen}
        assert set(api("common/getSelectCharacters", {"token": token, "ids": [int(chosen)]})) == {chosen}
        bad = json.loads(json.dumps(value))
        bad["attack"]["0"]["ids"] = {"0": 2147483647}
        assert api("deck/setDecks", {"token": token, "decks": bad}).get("errorReason")
        assert api("deck/getDecks", {"token": token})["attack"] == value["attack"]
        def change(mission, state):
            return api("politic/mission/changeState", {"token": token,
                "missionIds": [mission], "states": [state]})
        assert change("po_mission_00001", "closed")["succeeded"] is False
        assert change("po_mission_00002", "accepted")["succeeded"] is False
        assert change("po_mission_00001", "accepted")["succeeded"]
        assert change("po_mission_00001", "finished")["succeeded"]
        assert change("po_mission_00001", "closed")["succeeded"]
        assert api("politic/building/getDrafts", {"token": token}) == {"draft2000001": {"amount": 1.0}}
        after_reward = api("common/getPlayerParams", {"token": token})["resources"]
        assert change("po_mission_00001", "closed")["reward"] == {}
        assert api("common/getPlayerParams", {"token": token})["resources"] == after_reward
        assert change("po_mission_00002", "accepted")["succeeded"]
        assert change("po_mission_00002", "closed")["succeeded"] is False
        castle = api("politic/task/submitBuildTask", {"token": token,
            "draftId": "draft2000001", "originCoord": [15, 15]})
        assert castle["succeeded"]
        castle_id = castle["buildingId"]
        assert api("politic/map/getMapData", {"token": token})["buildings"][castle_id] == castle["building"]
        completed = api("politic/task/completeTasks", {"token": token, "buildingIds": [castle_id]})
        assert completed["succeeded"] and completed["buildings"][castle_id]["status"] == "none"
        assert api("politic/map/getMapData", {"token": token})["buildings"][castle_id]["status"] == "none"
        print("[http-smoke] inactive events/shop, owned characters, deck persistence/avatar, mission rewards, castle build/complete/reload: OK")
        assert api("deck/setCharacterProtect", {"token": token, "characterIds": [chosen], "enable": True}) == {}
        assert chosen in api("deck/getProtectedCharacterIds", {"token": token}).values()
        assert api("deck/setCharacterProtect", {"token": token, "characterIds": [2147483647], "enable": True}).get("errorReason")
        assert api("common/getEquips", {"token": token}) == {}
        assert api("common/getTactics", {"token": token}) == {}
        assert api("deck/getCharactersInStore", {"token": token}) == {}
        assert api("deck/getCharacterStoreInfo", {"token": token})["characterCount"] == 0
        assert api("deck/getDeckBonus", {"token": token})["deck"]["attack"]["4"]["id"] == int(chosen)
        habits = {"0": "habit0000101", "1": "none", "2": "none"}
        assert api("politic/mypage/setSelfIntroduction", {"token": token, "message": "audit profile", "habits": habits})["succeeded"]
        assert api("politic/mypage/getPlayerProfile", {"token": token})["selfIntroduction"]["message"] == "audit profile"
        assert api("politic/map/setMapName2", {"token": token, "mapId": 0, "mapName": "AuditTown"}) == {}
        assert api("politic/map/getMapData", {"token": token})["map"]["name"] == "AuditTown"
        assert api("politic/mypage/getLessonStates", {"token": token})["states"]["1"] == "L"
        shop = api("politic/shop/getShopItems", {"token": token, "category": "draft"})
        assert "shop0000041" in shop["shopItems"] and isinstance(shop["recommendedItems"], dict)
        purchase = {"token": token, "shopItemId": "shop0000041", "quantity": 2, "index": -1, "storetable": "shop_item"}
        gold = api("common/getPlayerParams", {"token": token})["resources"]["gold"]["amount"]
        bought = api("politic/shop/buyShopItem", purchase)
        assert bought["succeeded"] and bought["resources"]["gold"]["amount"] == gold - 2000
        assert api("politic/building/getDrafts", {"token": token})["draft2000041"]["amount"] == 2
        # Production tutorial rewards do not grant credit. Fund only this freshly
        # created, exact-account test fixture; never modify an existing player.
        fixture = state.load(initial["playerId"])
        assert fixture["entity"]["username"] == account and fixture["entity"]["created"]
        fixture["resources"]["credit"]["amount"] = 100
        state.save(fixture, initial["playerId"])
        credit = 100
        bought = api("politic/shop/buyShopItem", {**purchase, "shopItemId": "shop0700006", "quantity": 1})
        assert bought["succeeded"] and bought["resources"]["credit"]["amount"] == credit - 21
        assert api("politic/support_item/getPotions", {"token": token})["potions"]["potion0000102"]["amount"] == 1
        assert api("politic/shop/buyShopItem", {**purchase, "quantity": 9999})["succeeded"] is False
        assert api("politic/building/getDrafts", {"token": token})["draft2000041"]["amount"] == 2
        print("[http-smoke] protection, inventory/storage, profile/map, lessons, gold/credit purchases and balances: OK")
        own = {"token": token}
        assert api("common/getPlayerEntity", {**own, "playerId": "another"})["playerId"] == initial["playerId"]
        assert isinstance(api("common/getServerTime", own)["now"], float)
        assert set(api("auth/keepAliveContainer", own)) == {"succeeded", "now"}
        assert api("common/solvePlayerLevelCap", {**own, "cap": 100})["cap"] == 5
        gold = api("common/getPlayerParams", own)["resources"]["gold"]["amount"]
        lesson = {**own, "lessonId": "lesson_00001"}
        assert api("politic/mypage/takeLesson", lesson)["reward"] == {"item11_0000101": 5000}
        assert api("politic/mypage/takeLesson", lesson)["reward"] == {}
        assert api("politic/mypage/getLessonStates", own)["states"]["1"] == "C"
        assert api("common/getPlayerParams", own)["resources"]["gold"]["amount"] == gold + 5000
        assert not api("politic/mypage/takeLesson", {**own, "lessonId": "lesson_00002"})["succeeded"]
        # Only the isolated audit account receives experience for this check.
        fixture = state.load(initial["playerId"])
        assert fixture["entity"]["username"] == account and fixture["entity"]["created"]
        fixture["entity"]["exp"] = 200
        state.save(fixture, initial["playerId"])
        assert api("common/increasePlayerLevel", own)["succeeded"]
        after_level = api("common/getPlayerParams", own)
        assert after_level["entity"]["level"] == 2 and after_level["entity"]["exp"] == 200
        assert after_level["actionPoints"]["missionPoint"]["point"] == 25
        assert after_level["actionPoints"]["missionPoint"]["maxPoint"] == 30
        assert api("common/increasePlayerLevel", own)["succeeded"]
        assert api("common/getPlayerParams", own)["entity"]["level"] == 2
        print("[http-smoke] lesson claim/retry/prerequisites, level gates/cumulative experience, clock/heartbeat/entity: OK")
        # City checks use only this same disposable account.
        built = api("politic/task/submitBuildAndComplete", {**own, "draftId": "draft2000041", "originCoord": [20, 20]})
        assert built["succeeded"]
        field_id = built["buildingId"]
        recipes = api("politic/building/getProductsByBuilding", {**own, "buildingId": int(field_id)})
        assert recipes["succeeded"] and recipes["products"] == {"product060_001_01_01_1_1": {}}
        assert "level" not in recipes and "buildingTypeId" not in recipes
        before_production = state.load(initial["playerId"])
        short_recipe = "product060_023_01_01_1_1"
        for name, args in (
            ("submitProduceTask", {"buildingId": int(field_id), "productId": short_recipe}),
            ("submitBulkProduceTasks", {"buildingIds": [int(field_id)], "productIds": [short_recipe]}),
            ("cancelTasks", {"buildingIds": [int(field_id)]}),
            ("accelerateProduceTask", {"buildingId": int(field_id)}),
        ):
            blocked = api("politic/task/" + name, {**own, **args})
            assert not blocked["succeeded"]
            assert blocked["errorReason"] == blocked["message"]
        assert state.load(initial["playerId"]) == before_production
        print("[http-smoke] recipe query, locked tutorial recipe and inactive task rejection without writes: OK")
        fixture = state.load(initial["playerId"])
        assert fixture["entity"]["username"] == account
        fixture["buildings"][field_id]["exp"] = 120
        fixture["actionPoints"]["politicPoint"]["point"] = 0
        state.save(fixture, initial["playerId"])
        before_roads = api("common/getPlayerParams", own)
        road_params = {**own, "draftId": "draft2000051", "originCoords": [[21, 20], [22, 20]]}
        roads = api("politic/task/submitBulkBuildAndComplete", road_params)
        assert roads["succeeded"] and len(roads["buildings"]) == 2
        assert api("politic/task/submitBulkBuildAndComplete", road_params)["buildings"] == roads["buildings"]
        serial = api("politic/task/submitSerialBuildAndComplete", {**own, "draftId": "draft2000051", "originCoords": [[23, 20]]})
        assert set(serial) == {"0", "autoProducings", "now"}
        after_roads = api("common/getPlayerParams", own)
        assert after_roads["resources"] == before_roads["resources"]
        assert after_roads["actionPoints"]["politicPoint"]["point"] == 0
        assert api("politic/building/putInBuildings", {**own, "buildingIds": [int(field_id)]})["succeeded"]
        deployed = api("politic/building/deployBuilding", {**own, "buildingId": int(field_id), "originCoord": [25, 25]})
        assert deployed["buildingId"] == int(field_id) and deployed["building"]["exp"] == 120
        layout = api("politic/map/getMapData", own)["buildings"]
        relocate = {f"x{int(row['x'])}y{int(row['y'])}": int(key) for key, row in layout.items() if row["deployedMapKey"] == "map001"}
        del relocate["x25y25"]
        relocate["x26y26"] = int(field_id)
        assert api("politic/map/relocateEnded", {**own, "relocatedGrids": relocate})["succeeded"]
        assert api("politic/map/getMapData", own)["occupiedGrids"]["26,26"] == field_id
        fixture = state.load(initial["playerId"])
        assert fixture["entity"]["username"] == account
        fixture["actionPoints"]["politicPoint"]["point"] = 10
        state.save(fixture, initial["playerId"])
        gold = fixture["resources"]["gold"]["amount"]
        first = api("politic/building/levelUpBuilding", {**own, "buildingId": int(field_id)})
        assert first["building"]["level"] == 2 and first["building"]["exp"] == 100
        second = api("politic/building/levelUpBuildingCollectively", {**own, "buildingIds": [field_id], "levelUpTimes": [1]})
        assert second["resultBuildings"][field_id]["level"] == 3
        assert second["totalUsedPoint"] == 1 and second["restResources"]["gold"]["amount"] == gold - 240
        assert not api("politic/building/levelUpBuilding", {**own, "buildingId": int(field_id)})["succeeded"]
        assert api("common/getPlayerParams", own)["actionPoints"]["politicPoint"]["point"] == 8
        print("[http-smoke] zero-PP roads/retry, serial response count, storage/deployment/relocation and paid upgrades: OK")
        assert api("common/getPlayerParams", {}).get("error") == "UNAUTHORIZED"
        debug = api("debug/devLogin", {"username": account})
        assert debug.get("succeeded") is False and not debug.get("token")
        assert request("HEAD", "/client/app.html")[0] == 200
        status, _, body = request("GET", "/api/audit/absent")
        assert status == 404 and b"no stub response" in body
        status, _, body = request("GET", "/client/audit-absent.unity3d")
        assert status == 404 and b"stub has no assets" in body
        print("[http-smoke] web register/login -> name/create -> re-login -> GET params: OK; strict/debug guards: OK")
    finally:
        with db.connection() as con:
            with con.cursor() as cur:
                cur.execute("SELECT player_id FROM accounts WHERE account_key = %s", (account,))
                row = cur.fetchone()
                if row:
                    cur.execute("DELETE FROM players WHERE player_id = %s", (row["player_id"],))
                cur.execute("DELETE FROM sessions WHERE account_key = %s", (account,))
                cur.execute("DELETE FROM accounts WHERE account_key = %s", (account,))
                cur.execute("DELETE FROM users WHERE account_key = %s", (account,))
        print("[http-smoke] temporary audit account cleaned up")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--create-test-account", action="store_true", required=True)
    args = parser.parse_args()
    run(args.host, args.port)
