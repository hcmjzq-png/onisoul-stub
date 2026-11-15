"""Read-only proof audit and optional isolated smoke against complete original tables."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT))


def audit() -> None:
    records = json.loads((HERE / "source-proof.json").read_text(encoding="utf-8"))
    for record in records:
        assert hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest() == record["sha256"], record
    fixtures = json.loads((HERE / "fixture-proof.json").read_text(encoding="utf-8"))
    for record in fixtures:
        source = Path(record["source"]).read_bytes()
        fixture = (ROOT / record["fixture"]).read_bytes()
        assert hashlib.sha256(source).hexdigest() == record["sha256"]
        assert hashlib.sha256(fixture).hexdigest() == record["fixture_sha256"]
        actual, sample = json.loads(source), json.loads(fixture)
        name = next(iter(sample))
        assert sample[name] == {key: actual[name][key] for key in record["rows"]}
    with (HERE / "endpoints.tsv").open(encoding="utf-8", newline="") as handle:
        endpoints = [record["api"] for record in csv.DictReader(handle, delimiter="\t")]
    assert len(endpoints) == len(set(endpoints)) == 30
    assert "politic/mypage/claimReward" in endpoints
    assert not {"deck/sellCharacters", "deck/sellEquips", "politic/lottery/getSouls"} & set(endpoints)
    print(json.dumps({"source_files_verified": len(records), "fixtures_verified": len(fixtures),
                      "endpoint_rows": len(endpoints)}))


def smoke(table_dir: str) -> None:
    from app.business.card_growth_services import CardGrowthServices
    from app.business.card_growth_transactions import OperationContext, request_digest
    from app.business.gameplay import GameplayService
    from app.business.registry import Registry
    from app.main import build_registry
    from app.tables import TableCatalog
    from tools.gameplay_smoke import MemorySessions, MemoryState

    states, sessions = MemoryState(), MemorySessions()
    catalog = TableCatalog(table_dir)
    service = GameplayService(catalog=catalog, load_state=states.load, save_state=states.save,
                              session_store=sessions)
    registry = service.register(Registry()).register_contract_defaults()
    normal_registry = build_registry()  # registration only; no DB/session/HTTP operations
    normal = {"entries": len(normal_registry._handlers), "placeholders": sum(
        handler.__module__ == "app.business.placeholders" for handler in normal_registry._handlers.values())}
    session, _ = service._issue_login("isolated-c-original-tables")
    result = service.create_player(dict(username="C proof", countryId="country01",
                                       navigatorId="navi8000101", colorIndex="color1"), session)
    assert result["succeeded"], result
    player = states.load(session["playerId"])
    # Explicit fixture-only saved inventory and credit; never a production grant.
    avatar_id = str(int(player["decks"]["avatar"]["id"]))
    target_id = next(key for key in player["characters"] if key != avatar_id)
    original = copy.deepcopy(player["characters"][target_id])
    for kind in ("attack", "defense", "politic", "quest", "strategy", "siege"):
        for deck in player["decks"][kind].values():
            deck["ids"] = {slot: value for slot, value in deck["ids"].items()
                           if value == "empty" or str(int(value)) != target_id}
    player["items"]["item07_0040016"] = 5
    player["resources"]["credit"]["amount"] = 150
    states.save(player, session["playerId"])
    status, bought = registry.dispatch("politic/shop/buyShopItem", dict(
        shopItemId="shop0700013", index=0, quantity=1, storetable="shop_item"), session)
    assert status == 200 and bought["succeeded"] and bought["resources"]["credit"]["amount"] == 0
    context = None
    CardGrowthServices(service).register_mutations(registry, operation_context=lambda: context)
    for api, params, oid in (
        ("politic/support_item/useDopingItem", dict(characterId=target_id, potionId="potion0000416", count=5), "use"),
        ("politic/support_item/useDopingRemoveItem", dict(characterId=target_id, potionId="potion0000201"), "remove"),
    ):
        context = OperationContext(session["playerId"], api, oid, request_digest(api, params))
        status, payload = registry.dispatch(api, params, session)
        assert status == 200 and payload["succeeded"], payload
        committed = states.load(session["playerId"])
        _, repeated = registry.dispatch(api, params, session)
        assert "errorReason" in repeated and states.load(session["playerId"]) == committed
    assert states.load(session["playerId"])["characters"][target_id] == original
    reloaded = GameplayService(catalog=catalog, load_state=states.load, save_state=states.save,
                               session_store=sessions).register(Registry()).register_contract_defaults()
    _, characters = reloaded.dispatch("common/getCharacters", {}, session)
    assert characters[target_id] == original
    _, potions = reloaded.dispatch("politic/support_item/getPotions", {}, session)
    # Existing getPotions omits zero inventory (apart from its full-auto entry).
    assert "potion0000201" not in potions["potions"]
    assert potions["potions"]["potion0000404"]["amount"] == 1
    print(json.dumps({"complete_original_table_smoke": "passed", "normal_registry": normal,
                      "new_public_registrations": 0, "unity_runs": 0, "database": "isolated memory only"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-dir")
    args = parser.parse_args()
    audit()
    if args.table_dir:
        smoke(args.table_dir)
