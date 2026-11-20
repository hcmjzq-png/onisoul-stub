"""Provision the PvE skill deck in a fresh account on the existing local-test instance."""
from __future__ import annotations

import argparse
from copy import deepcopy
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.game_environments import Environments, get_json, validate_health

LOGIN_PATH = "/index.php/gwz/client/login/"
ROSTER = (
    ("chara1_01398_01", ("skill1_08596_01", "skill1_15174_01")),
    ("chara1_01896_01", ("skill1_04053_01",)),
    ("chara1_01850_01", ("skill1_09350_01", "skill1_03750_01")),
    ("chara1_01895_01", ("skill1_02004_01",)),
    ("chara1_01935_01", ("skill1_09309_01", "skill1_03617_01", "skill1_09287_01")),
)


def request(path: str, params: dict | None = None, *, api: bool = False):
    connection = HTTPConnection("127.0.0.1", 80, timeout=15)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    body = None if params is None else urlencode({"params": json.dumps(params)} if api else params)
    try:
        connection.request("GET" if body is None else "POST", path, body, headers)
        response = connection.getresponse()
        return response.status, response.getheader("Location"), response.read()
    finally:
        connection.close()


def call(name: str, token: str, **params) -> dict:
    status, _, raw = request("/api/" + name, {"token": token, **params}, api=True)
    if status != 200:
        raise ValueError(f"{name} returned HTTP {status}")
    result = json.loads(raw)
    if result.get("errorReason"):
        raise ValueError(f"{name}: {result['errorReason']}")
    return result


def login(credentials: dict) -> str:
    status, location, _ = request(LOGIN_PATH, credentials)
    if status != 302 or not location:
        raise ValueError("local sign-in did not redirect to the game")
    return parse_qs(urlsplit(location).query)["token"][0]


def build_cards(service) -> list[dict]:
    characters, skills = service._table("character"), service._table("skill")
    result = []
    for base_id, skill_ids in ROSTER:
        base = characters[base_id]
        slots = {}
        for slot, skill_id in enumerate(skill_ids, 1):
            skill = skills[skill_id]
            if skill["type"] != "battle" or not {0, 7}.intersection(skill["battleType"]):
                raise ValueError(f"{skill_id} cannot run in ordinary raids")
            slots[str(slot)] = {"id": skill_id, "learning": slot * 2,
                                "level": skill["changeLevel"], "exp": 0, "visible": True}
        result.append({"baseId": base_id, "grade": len(skill_ids) * 2, "level": 1, "exp": 0,
                       "combinedPoint": 0, "purchasedVoiceId": "", "voice": base["voice"],
                       "atk": base["atk"], "def": base["def"], "int": base["int"],
                       "atkAdd": 0, "defAdd": 0, "intAdd": 0, "skills": slots})
    return result


def provision(manager: Environments, credentials_path: Path) -> dict:
    for port in (80, 18081):
        validate_health(get_json(port), "local-test", manager.settings["local_instance"])
    if not credentials_path.resolve().is_relative_to(manager.private):
        raise ValueError("store the test credentials under the private profiles directory")
    os.environ.update(manager.local_env())

    from app import state
    from app.business.gameplay import GameplayService

    service = GameplayService()
    cards = build_cards(service)
    account = "pveqa_" + secrets.token_hex(5)
    credentials = {"account": account, "password": secrets.token_urlsafe(18)}
    with credentials_path.open("x", encoding="utf-8") as handle:
        json.dump(credentials, handle)
    status, _, _ = request(LOGIN_PATH + "?page=register", credentials)
    if status != 200:
        raise ValueError(f"local registration returned HTTP {status}")
    token = login(credentials)
    initial = call("auth/gameLogin", token)
    if initial.get("succeeded") or not initial.get("playerId"):
        raise ValueError("expected a newly registered local test account")
    player_id = str(initial["playerId"])
    call("auth/registerName", token, username=account)
    call("auth/createPlayer", token, username=account, countryId="country01",
         navigatorId="navi8000101", colorIndex="color1")

    with state.atomic_players((player_id,)) as players:
        player = players[player_id]
        if player["entity"]["username"] != account or not player["entity"]["created"]:
            raise ValueError("local test account does not match the new save")
        inventory = player["characters"]
        first = max(map(int, inventory), default=0) + 1
        ids = {str(slot): first + slot for slot in range(len(cards))}
        inventory.update({str(first + slot): card for slot, card in enumerate(cards)})
        player["counters"]["characterCount"] = len(inventory)

    original = call("deck/getDecks", token)
    decks = {key: deepcopy(original[key]) for key in
             ("avatar", "quest", "attack", "defense", "politic", "strategy", "siege")}
    decks["quest"]["0"]["ids"] = ids
    call("deck/setDecks", token, decks=decks)
    token = login(credentials)
    if not call("auth/gameLogin", token).get("succeeded"):
        raise ValueError("could not re-enter the test account")
    if call("deck/getDecks", token)["quest"]["0"]["ids"] != ids:
        raise ValueError("the PvE formation did not persist")
    persisted = call("common/getSelectCharacters", token, ids=list(ids.values()))
    for instance, card in zip(ids.values(), cards, strict=True):
        view = persisted[str(instance)]
        if (view["baseId"], view["skills"]) != (card["baseId"], card["skills"]):
            raise ValueError("the PvE card or its skills did not persist")
    return {"cards": len(cards), "skills": sum(len(card["skills"]) for card in cards), "relogin": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-name", default="pve-skill-test.local.json")
    args = parser.parse_args()
    profile = Path(os.environ["LOCALAPPDATA"]) / "OniSoul/environments/profiles.local.json"
    manager = Environments(profile)
    result = provision(manager, manager.private / args.credentials_name)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
