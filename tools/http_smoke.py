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
        return json.loads(body)

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
        params = api("common/getPlayerParams", {"token": token}, "GET")
        assert params["entity"]["username"] == account and params["characterCount"] > 0
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
        after_reward = api("common/getPlayerParams", {"token": token})["resources"]
        assert change("po_mission_00001", "closed")["reward"] == {}
        assert api("common/getPlayerParams", {"token": token})["resources"] == after_reward
        assert change("po_mission_00002", "accepted")["succeeded"]
        assert change("po_mission_00002", "closed")["succeeded"] is False
        print("[http-smoke] inactive events/shop, owned characters, deck persistence/avatar, mission prerequisites/rewards: OK")
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
        purchase = {"token": token, "shopItemId": "shop0000041", "quantity": 2, "index": 0, "storetable": "shop_item"}
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
