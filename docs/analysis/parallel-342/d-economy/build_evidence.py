"""Rebuild scoped evidence metadata; original files are only read, never copied."""
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
sys.path.insert(0, str(ROOT))
from app.minijson import parse_json_document
SOURCE = Path(r"C:\Users\74378\AppData\Local\Temp\onisoul-static-original-20261115")
TABLES = Path(r"D:\onisoul\work\quest-contract-20261115\all-tables")
ASSIGNMENT = Path(r"D:\onisoul\work\parallel-review-342-20261115\D-economy.txt")


def source_ref(name, methods):
    path = SOURCE / name
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    hits = {}
    for method in methods:
        hits[method] = [i for i, line in enumerate(lines, 1)
                        if re.search(r"\b" + re.escape(method) + r"\s*\(", line)
                        and re.match(r"\s*(public|private|protected)", line)]
        assert hits[method], (name, method)
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), methods=hits)


def main():
    endpoints = [s for s in ASSIGNMENT.read_text(encoding="utf-8-sig").splitlines()
                 if re.match(r"^(auction|netCafe|politic)/", s)]
    assert len(endpoints) == 39
    refs = [source_ref(name, methods.split()) for name, methods in {
        "AuctionDataManager.cs": "OnAuctionStatus OnGetAuctionCardsCommon CreateStatus OnGetMySellingCards OnSearchResourceFromAuction OnGetMySellingResources ParseSingleResourceData ParseSingleCardData ParseTaxCardData ParseTaxResourceData GetSortString SortAuctionResourceMap",
        "AuctionResourcePriceDropListBtn.cs": "OnRange1Click OnRange2Click OnRange3Click",
        "AuctionResourceAmountDropListBtn.cs": "OnRange1Click OnRange7Click",
        "AuctionBuyResourcePage.cs": "Search SearchAll",
        "mypageShopBgWindow.cs": "phaseInit phaseBuyMenu phaseBuyItem",
        "ShopItemBgTableAccessor.cs": "IsEnable getCategory getItemIds getCredit",
        "mypageBgSelectWindow.cs": "makeBgList",
        "mypageBgItemSelect.cs": "init",
        "ItemsTableAccessor.cs": "getValue",
        "ShopUpdateNationalPower.cs": "createItemObject setShopList",
        "ShopItemNationalPower.cs": "saleWindowResult",
        "PoliticErrantryEntryWindow.cs": "callErrantry",
        "PoliticFSMErrantryReward.cs": "createRewardAll recieveErrantry",
        "UserStatus.cs": "updateTravel updateErrantry",
        "PoliticFSMWaterTradeEntry.cs": "getFleetInfo getFriendInfo",
        "PoliticWaterTradeWindow.cs": "getTimeCrunchRate getGoldSavingRate getSuccessRate",
        "PoliticWaterTradeProgressStatus.cs": "setup",
        "PoliticFSMWaterTradeReward.cs": "createRewardAll recieveWaterTrade",
        "PoliticMissionProgressList.cs": "updateWaterTradeList sendWaterTrade",
        "KokugiScene.cs": "listupInvokedIds updatePageItems",
        "KokugiDedicateWindow.cs": "doDedicate",
        "onikujiNetCafeExchangeDialog.cs": "onExchangeNPointResult",
        "ErrantryTableAccessor.cs": "setup getResultFileName",
        "WaterBorneTradeTableAccessor.cs": "setup getResultFileName",
    }.items()]
    web = SOURCE / "WebApiClient.cs"
    text = web.read_text(encoding="utf-8-sig")
    signatures = list(re.finditer(r"^\tpublic void (\w+)\([^\n]+", text, re.M))
    wrappers = {}
    for i, signature in enumerate(signatures):
        end = signatures[i + 1].start() if i + 1 < len(signatures) else len(text)
        body = text[signature.start():end]
        for api in re.findall(r'httpCall\("([^"]+)"', body):
            if api in endpoints:
                wrappers.setdefault(api, []).append(dict(method=signature.group(1),
                    line=text[:signature.start()].count("\n") + 1,
                    parameters=sorted(set(re.findall(r'hashtable.Add\("([^"]+)"', body)))))
    assert set(wrappers) == set(endpoints)
    refs.append(dict(path=str(web), sha256=hashlib.sha256(web.read_bytes()).hexdigest(), wrappers=wrappers))
    table_refs = []
    for name in ("shop_item_bg", "national_power_shop_item", "shop_item", "shop_item_country",
                 "building_errantry", "errantry", "building_waterborne_trade", "kokugi", "kokugiLevel"):
        path = TABLES / (name + ".json")
        parsed = parse_json_document(path.read_bytes())
        table = parsed[name]
        table_refs.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                               root=name, rows=len(table), example_fields=sorted(next(iter(table.values())))))
        if name in ("shop_item_bg", "national_power_shop_item"):
            keys = list(table)[:2 if name == "shop_item_bg" else 1]
            target = ROOT / "tests" / "fixtures" / "economy" / (name + ".json")
            target.write_text(json.dumps({name: {key: table[key] for key in keys}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            table_refs[-1]["sample_rows"] = keys
    evidence = dict(baseline="1f287e33123afa452d2f5d2aac2427566d549f73", scope=endpoints,
        original_protocol={"sources": refs, "tables": table_refs,
            "assembly_sha256": "b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e"},
        compatibility_decisions=["ResourceSnapshot/ResourceListing are internal, provider must read one consistent public snapshot",
            "No provider means no stub response; never fake an empty market",
            "Inclusive bounds match adjacent client dropdown ranges; original server boundary captures unavailable",
            "Page size cap 300, stable item_sn tie break, numeric root display slots, decimal string scalars are local compatibility decisions",
            "Expiry is derived from internal expires_at and snapshot observed_at; not a recovered storage schema",
            "No writes, no production registration, no global endpoint count change, no permanent background grant"],
        limitations=["Original-server economics, auction tax constants, listing eligibility, event schedules and retry IDs unavailable",
            "item13.json and item14.json not in the supplied 662-table extraction: does NOT prove missing installed assets",
            "No original-server replay or Unity dynamic verification; read provider not integrated"])
    (OUT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = []
    for api in endpoints:
        name = api.rsplit("/", 1)[-1]
        request = " | ".join(",".join(w["parameters"]) for w in wrappers[api])
        proof = "; ".join("WebApiClient.cs:" + str(w["line"]) + " " + w["method"] for w in wrappers[api])
        shape, callback, tables, persistence, rules, status, next_step = review(api, name)
        rows.append([api, request, shape, proof + "; " + callback, tables, persistence, rules, status, next_step])
    with (OUT / "reviewed-endpoints.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["endpoint", "request", "response_hierarchy", "callback_evidence", "table_evidence", "persistence", "permission_cost_retry", "status", "next_step"])
        writer.writerows(rows)


def review(api, name):
    if api.startswith("auction/"):
        if name in ("auctionResourceBrowse", "auctionResourceSearch"):
            return ("bare <slot>.{item_sn,resource_type,price,num,period,remain_time}",
                "AuctionDataManager.OnSearchResourceFromAuction/ParseSingleResourceData/SortAuctionResourceMap; AuctionResourcePriceDropListBtn; AuctionResourceAmountDropListBtn",
                "No static row establishes active market or taxes", "Read one injected snapshot; no player load/save",
                "Authenticated; no cost; retry reads latest snapshot; integer ranges and sort whitelist",
                "Implemented limited read semantics; unmounted; no live provider", "Integrate transactional read snapshot and bare-map shape; capture boundary/page semantics")
        if "Card" in name and ("Browse" in name or "Search" in name):
            return ("bare <listing>.character + price.<listing> + remain_time.<listing>; status=0 maintenance special case",
                "AuctionDataManager.OnGetAuctionCardsCommon/CreateStatus/createAuctionCharaStatus",
                "character/skill consumers; original search normalization not proven", "Needs shared market view",
                "Authenticated; no charge; decimal string pagination except Faction numeric; name/skill have ID-list overload",
                "Callback traced; not implemented", "Correct shared shape; C supplies trade-eligible card projection; prove search name/skill and tie rules")
        if name == "auctionStatus":
            return ("status (ToString); 0 maintenance", "AuctionDataManager.OnAuctionStatus", "No operating schedule in evidence",
                "Shared operational status needed", "No fee; do not infer open from table existence", "Callback traced; not implemented", "Integrator supplies explicit market availability")
        if name.endswith("Sale"):
            card = "Card" in name
            return ("bare owned slots + params.{" + ("base,grade_mul,level_mul" if card else "base,amount_mul") + "}",
                "AuctionDataManager.OnGetMySelling" + ("Cards/ParseSingleCardData/ParseTaxCardData" if card else "Resources/ParseSingleResourceData/ParseTaxResourceData"),
                "Tax coefficients originate in response; no verified constants", "Owned escrow/listings; expired collection state unknown",
                "Only seller listings; taxes and expiry settlement unknown", "Callback traced; not implemented", "Prove tax values and expiry/collection, implement persisted market query")
        return ("status maintenance guard then delegated callback; success settlement shape not fully verified",
            "AuctionDataManager post/buy/remove callbacks", "No server tax/price/duration constants proven",
            "Shared listing + escrow + buyer/seller saves must commit atomically",
            "Owner-only remove; buy must recheck listing and funds; retries require ledger; C trade eligibility for cards",
            "Partial callback trace; writes NOT implemented", "Trace downstream UI; prove taxes; implement database transaction/ledger before registering")
    if api.startswith("netCafe/"):
        return ("npoint.{prev,current}; yellowSoul.{prev,current}", "onikujiNetCafeExchangeDialog.onExchangeNPointResult",
            "No verified operator campaign/rate", "Npoint and soul balances require one commit",
            "Eligibility and conversion rate unknown; do not invent an event", "Non-ordinary operator feature; not implemented", "Obtain operator entitlement/rate and replay evidence")
    if "/shop/" in api:
        if "Credit" in name:
            return ("Unknown: no call site outside WebApiClient found", "WebApiClient wrapper only; ordinary buyShopItem is a separate existing endpoint",
                "shop_item exists; does not prove this obsolete/alternate entry's semantics", "Unknown",
                "Do not alias to ordinary credit purchases just from name", "Wrapper only; not implemented", "Find runtime caller/capture before assigning response or price rules")
        if "Background" in name:
            return ("shopItems.<shopId> (keys only)" if name.startswith("get") else "optional resources.<kind>.amount",
                "mypageShopBgWindow.phaseInit/phaseBuyMenu/phaseBuyItem; ShopItemBgTableAccessor; mypageBgItemSelect.init",
                "shop_item_bg: 8 rows, 4 enabled, credit=168; itemIds are item13/item14 IDs",
                "Proposal only: one A/D shared ownership store, no second permanent grant",
                "Category near/far; credit cost proven; ownership duration/initial rights and live-sale rules unproven",
                "Catalogue/callback verified; no handler or purchase", "Verify item13/item14 and initial ownership/expiry; agree shared A state before charging")
        return ("shopItems/recommendedItems.<id>.{state,remain}" if name.startswith("get") else "resources.<kind>.amount; errorReason",
            "ShopUpdateNationalPower.createItemObject/setShopList; ShopItemNationalPower.saleWindowResult",
            "national_power_shop_item.goal/limitPerPerson/costTypes/costAmounts; shop_item_country maps national draft",
            "National goal activation + per-player remaining quota and inventory require atomic save",
            "Set purchase uses index=-1; live goal activation/reset period/retry identity unknown",
            "Callback/table verified; not implemented", "Prove goal unlock/reset and persist quota; preserve ordinary shop handler")
    if "/kokugi/" in api:
        shape = {"getStatus": "selfPoint,levelRate,kokugiPoint.<id>", "develop": "usedPoint,point", "addPoint": "Unknown: wrapper only"}[name]
        return (shape, "KokugiScene.listupInvokedIds/updatePageItems; KokugiDedicateWindow.doDedicate (addPoint has no external caller)",
            "kokugi/kokugiLevel; global levelRate is response-derived", "Self points and country shared progress need transaction",
            "Do not accept arbitrary addPoint; source/cost, country multiplier and reset unproven",
            "Wrapper only" if name == "addPoint" else "Callback/table traced; not implemented", "Prove point source and shared-country scope; give A/B effect definitions after verification")
    if "/errantry/" in api:
        shape = {"send3": "optional isActive,dueTime,errantryId,buildingId",
            "getStatus3": "<mapId>.errantry.{isActive,dueTime,errantryId,buildingId}",
            "receive3": "optional catalog; results.<event>.reward.<itemId> (numeric)", "call3": "callback ignores payload; no refund proof"}[name]
        return (shape, "PoliticErrantryEntryWindow; UserStatus.updateTravel/updateErrantry; PoliticFSMErrantryReward.createRewardAll/recieveErrantry",
            "building_errantry/errantry -> dynamic result table (ErrantryTableAccessor.getResultFileName)",
            "Per-map journey start/return/claim record; original save/relogin protocol not captured",
            "Validate owned building/map; cost preview exists; outcome weights/cancel refund/claim retry unknown",
            "Callback/helper traced; lifecycle not implemented", "Resolve dynamic result chain, outcome rules, restart/claim ledger before send")
    shape = {"getFleet": "fleetEffects.{timeCrunch,increaseReward,successRate,successRateForFriend,costSavings}",
        "getFriendTraders": "traders.<id> (entry details pending)",
        "getStatus": "bare <mapId>.{politicDeck,totalIntelligence,trade.<buildingId>}",
        "send": "catalog,tradeId,createdTime,dueTime,deck",
        "sendWithFriends": "catalog,tradeId,createdTime,dueTime,deck",
        "receive": "results.<event>.reward.<itemId>; deck/building updates delegated",
        "call": "delegated cancellation/building update; full shape pending"}[name]
    return (shape, "PoliticFSMWaterTradeEntry/Reward; PoliticWaterTradeWindow; PoliticWaterTradeProgressStatus.setup; PoliticMissionProgressList.updateWaterTradeList",
        "building_waterborne_trade -> dynamic WaterBorneTradeTableAccessor result sheets", "Per-building voyage + fleet/deck reservation + claims; friends may cross accounts",
        "Owned map/building; friend permission required; effects, outcome distribution and cancellation/refund incomplete",
        "Callback/helper traced; not implemented", "Prove fleet effects/outcome/expiry; integrate E friend permissions and atomic multi-player reservations")


if __name__ == "__main__":
    main()
