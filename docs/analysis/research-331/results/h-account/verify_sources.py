"""Rebuild small H evidence samples; read-only access to original materials."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from tools.extract_tables_from_bundle import extract_assets

SOURCE = Path('C:/Users/74378/AppData/Local/Temp/onisoul-static-original-20261115')
CONTAINER = Path('D:/onisoul/work/quest-contract-20261115/tableAssets.bin')
OUT = Path(__file__).parent
FIX = ROOT / 'tests/fixtures/research331/h-account'
SELECTION = {'item11': ['item11_0000101', 'item11_0000201', 'item11_0000301', 'item11_0000401'],
             'item08': ['item08_0102701'],
             'daily_mission': ['daily_mission_52', 'daily_mission_84'],
             'migrate': ['migrate_0001']}
FILES = {
    'WebApiClient.cs': ['671-684', '295-337'],
    'GameRestarter.cs': ['60-92'],
    'ClockTimer.cs': ['23-48', '88-94'],
    'SceneResources.cs': ['114-117'],
    'Politic.cs': ['116-124'],
    'PoliticFSMLogin.cs': ['48-69', '119-129'],
    'PoliticScriptCommand.cs': ['1571-1605'],
    'LoginBounusMenu.cs': ['175-180', '210-216', '270-332'],
    'UserStatus.cs': ['777-788', '1791-1818'],
    'RewardProcessor.cs': ['25-70', '239-245'],
    'DailyMissionScene.cs': ['136-192', '331-403', '560-574'],
    'DailyMissionTableAccessor.cs': ['1-26'],
    'mypageCollectionSeriesParam.cs': ['48-89', '96-117'],
}


def main():
    raw = CONTAINER.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == '20b987a41c5ec8f0b70dfe65bf0383c7acf25cc755f38f5b4d9dbdaa361dc4f7'
    assets = extract_assets(raw, {name + '.json': name for name in SELECTION})
    by_root = {asset.root_key: asset for asset in assets.values()}
    assert set(by_root) == set(SELECTION)
    report = {'base': '8023c3fee8e525040d101fee8bf843b48b3256d3',
              'client_dll_sha256': 'b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e',
              'container': {'path': str(CONTAINER), 'sha256': digest},
              'files': {}, 'tables': {}, 'fixtures': {}}
    FIX.mkdir(parents=True, exist_ok=True)
    for name, keys in SELECTION.items():
        asset = by_root[name]
        rows = json.loads(asset.raw)[name]
        report['tables'][name] = {**asset.evidence(), 'row_count': len(rows),
                                 'fields': sorted({key for row in rows.values() for key in row})}
        sample = {name: {key: rows[key] for key in keys}}
        path = FIX / (name + '.json')
        path.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        report['fixtures'][str(path.relative_to(ROOT))] = {
            'row_ids': keys, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    for name, ranges in FILES.items():
        path = SOURCE / name
        report['files'][name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                 'reviewed_line_ranges': ranges}
    (OUT / 'source-proof.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'source_files': len(FILES), 'tables': {k: v['row_count'] for k, v in report['tables'].items()},
                      'fixture_rows': sum(map(len, SELECTION.values()))}))


if __name__ == '__main__':
    main()
