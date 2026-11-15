#!/usr/bin/env python3
"""Exercise mounted social/trophy routes with two owned, disposable HTTP accounts.

Run on the server with its ONI_DB_* config. Never prints passwords or tokens.
Only these new accounts receive fixture rewards; exact-account cleanup runs finally.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db, state
from app.business.gameplay import GameplayService
from app.business.social_inbox_services import SocialInboxServices

if not __debug__:
    raise SystemExit("This acceptance tool requires assertions; do not use python -O.")


def run(port: int) -> dict:
    login_path = "/index.php/gwz/client/login/"
    people = [{"account": "r62_" + secrets.token_hex(6), "password": secrets.token_urlsafe(20)}
              for _ in range(2)]
    for person in people:
        person["id"] = "p_" + hashlib.sha1(person["account"].casefold().encode()).hexdigest()[:16]

    def request(method, path, form=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        try:
            conn.request(method, path, form, {"Content-Type": "application/x-www-form-urlencoded"})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def api(name, person, method="POST", **params):
        params["token"] = person["token"]
        form = urlencode({"params": json.dumps(params)})
        status, _, body = request(method, "/api/" + name + ("?" + form if method == "GET" else ""),
                                 None if method == "GET" else form)
        assert status == 200, (name, status)
        return json.loads(body)

    def login(person):
        form = urlencode({"account": person["account"], "password": person["password"]})
        status, headers, _ = request("POST", login_path, form)
        assert status == 302, "test web login failed"
        person["token"] = parse_qs(urlsplit(headers["Location"]).query)["token"][0]

    with db.connection() as con:
        with con.cursor() as cur:
            for p in people:
                for table in ("users", "accounts"):
                    cur.execute(f"SELECT account_key FROM {table} WHERE account_key=%s", (p["account"],))
                    assert cur.fetchone() is None, "test account collision"
                cur.execute("SELECT player_id FROM players WHERE player_id=%s", (p["id"],))
                assert cur.fetchone() is None, "test player collision"
    try:
        for p in people:
            form = urlencode({"account": p["account"], "password": p["password"]})
            assert request("POST", login_path + "?page=register", form)[0] == 200
            login(p)
            initial = api("auth/gameLogin", p)
            assert initial["succeeded"] is False and initial["playerId"] == p["id"]
            before = state.load(p["id"])
            poll = api("common/periodicInquiry", p)
            assert "errorReason" not in poll and "friendOffer" not in poll
            assert poll["gmMessage"] == "" and isinstance(poll["show_off"], dict)
            assert state.load(p["id"]) == before
            assert api("auth/registerName", p, username=p["account"])["succeeded"]
            assert api("auth/createPlayer", p, username=p["account"], countryId="country01",
                       navigatorId="navi8000101", colorIndex="color1")["succeeded"]
        a, b = people
        def friend(name, actor, target, **params):
            return api("friend/" + name, actor, friendPlayerId=target["id"], **params)
        def send():
            assert friend("sendFriendOffer", a, b)["result"]
        send()
        assert not friend("sendFriendOffer", a, b)["result"]
        assert api("friend/getFriends", a, option="send")[b["id"]]["status"] == "send"
        assert friend("getFriendProfile", a, b, forHTML=False)["username"] == b["account"]
        assert api("friend/updateFriendData", b)["count"]["receive"] == 1
        assert api("common/periodicInquiry", b, "GET")["friendOffer"] == 1
        assert friend("feedbackFriendOffer", b, a, reply="excuse")["result"]
        send()
        assert friend("cancelFriendOffer", a, b)["result"]
        assert not friend("cancelFriendOffer", a, b)["result"]
        send()
        assert friend("feedbackFriendOffer", b, a, reply="ok")["result"]
        assert not friend("feedbackFriendOffer", b, a, reply="ok")["result"]
        login(b)
        assert api("friend/getFriends", b, option="ok")[a["id"]]["status"] == "ok"
        assert friend("dissolutionFriend", a, b)["result"]
        assert not friend("dissolutionFriend", a, b)["result"]
        assert api("friend/getFriends", b, option="") == {}
        print("[social-http] fresh-account poll, all seven friend routes, retry and relogin: OK", flush=True)

        inbox = SocialInboxServices(GameplayService())
        with state.atomic_players((b["id"],)) as rows:
            assert rows[b["id"]]["entity"]["username"] == b["account"]
            gold = rows[b["id"]]["resources"]["gold"]["amount"]
            parcel = inbox.stage_parcel(rows[b["id"]], issuance_id="review62-owned-test",
                source={"kind": "administrator", "authority": "review62-http",
                        "reference": "disposable acceptance account only"},
                rewards={"item11_0000101": 7}, created_time=time.time())
        assert api("common/periodicInquiry", b)["inboxParcel"] == 1
        assert parcel in api("inbox/getParcels", b, start=0, end=499)["parcels"]
        assert parcel in api("inbox/resolveParcels", a, responses={parcel: "accept"})["failed"]
        assert api("inbox/resolveParcels", b, responses={parcel: "accept"})["successful"][parcel]["rewards"] == {"item11_0000101": 7}
        assert api("inbox/resolveParcels", b, responses={parcel: "accept"})["successful"][parcel]["rewards"] == {}
        login(b)
        assert api("common/getPlayerParams", b)["resources"]["gold"]["amount"] == gold + 7
        assert api("common/periodicInquiry", b)["inboxParcel"] == 0
        assert not api("admin/inbox/present", b, rewards={"item11_0000101": 999})["succeeded"]
        print("[social-http] trusted test parcel, ownership, single credit, retry/relogin and admin denial: OK", flush=True)

        # PR #50 is deployed with #62; verify its original-table first trophy.
        fixture = state.load(a["id"])
        assert fixture["entity"]["username"] == a["account"]
        fixture["entity"]["level"] = 4
        state.save(fixture, a["id"])
        assert "playerLevel" in api("trophy/getTrophyProgress", a, access="mypage")
        claim = api("trophy/completeTrophy", a, access="mypage", category="playerLevel")
        assert claim["rewards"] == {"item11_0000101": 100000., "item08_0102701": 6.}
        assert "errorReason" in api("trophy/completeTrophy", a, access="mypage", category="playerLevel")
        assert "errorReason" not in api("trophy/messageWindowTrophy", a, access="mypage", category="playerLevel")
        print("[social-http] three first-tier trophy routes and original rewards: OK", flush=True)
        return {"friend_routes": 7, "inbox_routes": 2, "trophy_routes": 3,
                "precreation_poll": "passed", "relogin": "passed", "port": port}
    finally:
        with db.connection() as con:
            with con.cursor() as cur:
                for p in people:
                    cur.execute("SELECT player_id FROM accounts WHERE account_key=%s", (p["account"],))
                    row = cur.fetchone()
                    if row:
                        assert row["player_id"] == p["id"], "refuse unrelated player cleanup"
                    cur.execute("SELECT state_json FROM players WHERE player_id=%s FOR UPDATE", (p["id"],))
                    player = cur.fetchone()
                    if player:
                        assert row is not None, "refuse unmapped player cleanup"
                        document = json.loads(player["state_json"])
                        # Pre-creation players need not have a username yet.
                        if document.get("entity", {}).get("created"):
                            assert document["entity"]["username"] == p["account"], "refuse unrelated player cleanup"
                for p in people:
                    cur.execute("DELETE FROM players WHERE player_id=%s", (p["id"],))
                    for table in ("sessions", "accounts", "users"):
                        cur.execute(f"DELETE FROM {table} WHERE account_key=%s", (p["account"],))
        print("[social-http] both owned disposable accounts cleaned up", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--create-test-accounts", action="store_true", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.port)))
