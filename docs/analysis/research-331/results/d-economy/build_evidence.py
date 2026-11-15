"""Reproduce D's source audit; read originals, write metadata and small samples only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from tools.extract_tables_from_bundle import extract_assets
from app.minijson import parse_json_document

OUT = Path(__file__).resolve().parent
SOURCE = Path('C:/Users/74378/AppData/Local/Temp/onisoul-static-original-20261115')
CONTAINER = Path('D:/onisoul/work/quest-contract-20261115/tableAssets.bin')
EXPECTED = '20b987a41c5ec8f0b70dfe65bf0383c7acf25cc755f38f5b4d9dbdaa361dc4f7'


def main() -> None:
    blob = CONTAINER.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == EXPECTED
    names = sorted(set(n.decode() for n in re.findall(
        rb'(?:errantry|waterborne|reward07|reward12)[a-zA-Z0-9_]*\.json', blob)))
    wanted = names + [n + '.json' for n in ('building_errantry', 'building', 'item11', 'item07', 'defines')]
    assets = extract_assets(blob, {n: n[:-5] for n in wanted})
    assert set(assets) == set(wanted)
    tables = {a.root_key: parse_json_document(a.raw)[a.root_key] for a in assets.values()}
    samples = {
        'errantry': ['errantry_00001', 'errantry_00002'],
        'building_errantry': ['building200_000_01_01_1_1'],
        'building': ['building200_000_01_01_1_1'],
        'errantry_result_0001': ['result_0001', 'result_0011', 'result_0012', 'result_0013', 'result_0015'],
        'reward07_errantry': ['reward07_0002', 'reward07_0007', 'reward07_0008', 'reward07_0009', 'reward07_0010'],
        'item11': ['item11_0000101', 'item11_0000701', 'item11_0001101'],
        'item07': ['item07_0070001'],
        'defines': ['soul_limit'],
    }
    fixtures = ROOT / 'tests/fixtures/research331/d-economy'
    fixtures.mkdir(parents=True, exist_ok=True)
    (fixtures / 'trade_tables.json').write_text(json.dumps(
        {n: {k: tables[n][k] for k in keys} for n, keys in samples.items()},
        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    sources = {}
    for name in ('WebApiClient', 'UserStatus', 'PoliticErrantryEntryWindow',
                 'PoliticFSMErrantryReward', 'PoliticScriptCommand', 'PoliticDeckTableAccessor',
                 'ErrantryTableAccessor', 'ErrantryResultTableAccessor', 'BuildingErrantryTableAccessor',
                 'AuctionDataManager', 'AuctionSellResourcePage', 'AuctionResourceSellSlot',
                 'AuctionResourceSellingTimeDropListBtn', 'AuctionPostToSellBtn', 'SingleAuctionResource',
                 'KokugiScene', 'ShopItemNationalPower', 'DefinesTableAccessor', 'onikujiMaster',
                 'PoliticMissionProgressList', 'PluginPoliticDataManager'):
        p = SOURCE / (name + '.cs')
        sources[p.name] = {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    audits = []
    for name in names:
        a = assets[name]
        row = a.evidence()
        row['previous_export_present'] = (CONTAINER.parent / 'all-tables' / name).is_file()
        if 'result_' in name:
            reward = 'reward07_errantry' if name.startswith('errantry') else 'reward12_waterborne_trade'
            row['missing_reward_references'] = sorted({r['rewardId'] for r in tables[a.root_key].values()
                                                       if r['rewardId'] not in tables[reward]})
        audits.append(row)
    report = {'container': {'path': str(CONTAINER), 'sha256': EXPECTED}, 'sources': sources,
              'recovered': audits, 'sample_rows': samples,
              'sample_sources': [assets[n + '.json'].evidence() for n in samples],
              'standard_trades': list(tables['errantry'].values()),
              'result_selection': 'unsupported: leastIntelligence/intelligenceBias do not prove sampling',
              'waterborne_base': tables['waterborne_trade'],
              'missing_reward_reference_count': sum(len(r.get('missing_reward_references', [])) for r in audits)}
    (OUT / 'source-evidence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUT / 'trade-tables.tsv').write_text('table_file\troot_key\taccessor_classes\n' + ''.join(
        f'{name}\t{name[:-5]}\tD research331 dynamic trade dependency\n' for name in names), encoding='utf-8')
    print(f'audited {len(names)} dynamic/static trade tables; missing reward references: {report["missing_reward_reference_count"]}')


if __name__ == '__main__':
    main()
