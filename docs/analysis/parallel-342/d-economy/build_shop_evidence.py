"""Read original verified container; emit only metadata and small test samples."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
sys.path.insert(0, str(ROOT))
from app.minijson import parse_json_document
from app.business.economy_shop_services import EconomyShopServices
from tools.extract_tables_from_bundle import extract_assets

TABLES = Path(r"D:\onisoul\work\quest-contract-20261115\all-tables")
SOURCE = Path(r"C:\Users\74378\AppData\Local\Temp\onisoul-static-original-20261115")
CONTAINER = TABLES.parent / "tableAssets.bin"


def main():
    blob = CONTAINER.read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    assert sha == "20b987a41c5ec8f0b70dfe65bf0383c7acf25cc755f38f5b4d9dbdaa361dc4f7"
    assets = extract_assets(blob, {name + ".json": name for name in ("item13", "item14")})
    assert len(assets) == 2
    tables, refs = {}, []
    for name in ("shop_item_bg", "national_power_shop_item", "national_power_goal", "shop_item_country", "item04", "draft", "building"):
        path = TABLES / (name + ".json")
        tables[name] = parse_json_document(path.read_bytes())[name]
        refs.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    for asset in assets.values():
        tables[asset.root_key] = parse_json_document(asset.raw)[asset.root_key]
    sample = {"shop_item_bg": list(tables["shop_item_bg"]),  # 8 tiny rows including disabled
              "item13": ["item13_0000004", "item13_0000005"],
              "item14": ["item14_1000048", "item14_1000049"],
              "national_power_shop_item": ["np_shop0000001", "np_shop0000005", "np_shop0000009"],
              "national_power_goal": ["3"], "shop_item_country": ["countryshop_00003"]}
    sample["item04"] = sorted(set(tables["shop_item_country"]["countryshop_00003"][c] for c in ("country01", "country02")) | {"item04_0200651", "item04_0200648"})
    sample["draft"] = [tables["item04"][i]["parameterId"] for i in sample["item04"]]
    sample["building"] = [tables["draft"][d]["buildType"] for d in sample["draft"]]
    destination = ROOT / "tests/fixtures/economy/shop_tables"
    destination.mkdir(exist_ok=True)
    for name, keys in sample.items():
        (destination / (name + ".json")).write_text(json.dumps({name: {key: tables[name][key] for key in keys}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = []
    service = EconomyShopServices(SimpleNamespace(catalog=SimpleNamespace(load=lambda name: tables[name])))
    countries = sorted(k for k in tables["shop_item_country"]["countryshop_00003"] if k.startswith("country"))
    for code, row in tables["national_power_shop_item"].items():
        goals = [(key, g["nationalPower"]) for key, g in tables["national_power_goal"].items() if row["goal"] in g["incentives"]]
        audit.append(dict(id=code, goal=row["goal"], thresholds=goals, limit=row["limitPerPerson"],
                          supported_row=EconomyShopServices.national_supported(row)))
        if audit[-1]["supported_row"]:
            failures = {}
            for country in countries:
                try:
                    service.national_goods({"entity": {"country": country}}, row)
                except (ValueError, KeyError) as exc:
                    failures[country] = str(exc)
            audit[-1]["reference_failures"] = failures
    refs_cs = []
    anchors = {
        "MightOfNationAchievement.cs": ["getPower(key) <= power"],
        "NationalPowerShopTableAccessor.cs": ["getCosts(", "getItemIds("],
        "ShopItemNationalPower.cs": ["index = -1", "addDraft(winResult.num", "Amount >= 99", "setRemain("],
        "ShopUpdateNationalPower.cs": ['getString("state")', 'getInt("remain")', 'getCosts(shopItemId)'],
        "mypageShopBgWindow.cs": ['getBackgroundItems(', 'getCredit(requestItemCode_)', 'Remove(requestItemCode_)'],
        "ItemsTableAccessor.cs": ['i < 16', 'key.Substring(0, 6)'],
        "PoliticBgModel.cs": ['getParameterId', 'item13_0000001'],
        "AuctionSellPostCard.cs": ['TaxCard_.BaseTax'],
        "AuctionPostToSellBtn.cs": ['TaxCard_.BaseTax'],
        "AuctionSellResourcePage.cs": ['TaxResource_.BaseTax'],
        "AuctionTaxCard.cs": ['public float'], "AuctionTaxResource.cs": ['public float'],
        "PluginRunner_DoTrade.cs": ['getCostTypes', 'getCostAmounts'],
        "WaterBorneTradeTableAccessor.cs": ['getResultFileName(', 'index == 4', '["friendResult"]'],
        "KokugiScene.cs": ['public static int toLevel', 'public static long toPoint', 'num += (long)'],
    }
    for name, needles in anchors.items():
        path = SOURCE / name
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        refs_cs.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            anchors={needle: [i for i, s in enumerate(lines, 1) if needle in s] for needle in needles}))
    report = dict(container=dict(path=str(CONTAINER), sha256=sha), recovered=[a.evidence() for a in assets.values()],
                  sources=refs_cs, tables=refs, sample_rows=sample, national_row_audit=audit,
                  supported_national_rows=sum(a["supported_row"] for a in audit), countries_checked=countries,
                  decisions=["Static background sale opt-in; existing items count is single ownership source; no automatic initial grant or expiry inference",
                             "Country power threshold is client/table-supported; live country score and global period must come from authoritative context held through save",
                             "Only quota-one national draft sets; wider quotas need retry identity; repeat national purchase errors to avoid client addDraft twice",
                             "All new state keys and policy switches are internal compatibility choices, not original protocol"])
    (OUT / "shop-evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("recovered item13/item14; national supported rows", report["supported_national_rows"], "/", len(audit))


if __name__ == "__main__":
    main()
