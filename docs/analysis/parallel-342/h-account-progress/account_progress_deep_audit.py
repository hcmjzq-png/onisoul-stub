"""Reproduce H phase-2 evidence and small fixtures from the fingerprinted container."""
from pathlib import Path
import sys, json, hashlib, re
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from tools.extract_tables_from_bundle import extract_assets, NAME_PATTERN
SRC = Path(r'C:\Users\74378\AppData\Local\Temp\onisoul-static-original-20261115')
SOURCE = Path(r'D:\onisoul\work\quest-contract-20261115\tableAssets.bin')
OUT = Path(__file__).parent
FIX = ROOT / 'tests/fixtures/account_progress/trophies'
FIX.mkdir(exist_ok=True)
b = SOURCE.read_bytes()
sha = hashlib.sha256(b).hexdigest()
assert sha == '20b987a41c5ec8f0b70dfe65bf0383c7acf25cc755f38f5b4d9dbdaa361dc4f7'
names = ['reward06_trophy','reward04_mypage','reward05_etc','item08','item11','mypage_trophy','trophy_setting','playerLevel','daily_mission']
assets = extract_assets(b, {n+'.json': n for n in names})
data = {v.root_key: json.loads(v.raw)[v.root_key] for v in assets.values()}
report = {'container': {'path':str(SOURCE),'sha256':sha}, 'tables':{v.root_key:v.evidence() for v in assets.values()}, 'source_files':{}, 'fixtures':{}, 'original_evidence':[], 'compatibility_decisions':[]}
selection = {'playerLevel':[str(i) for i in range(1,7)], 'mypage_trophy':[k for k in data['mypage_trophy'] if k.startswith('playerLevel_')], 'trophy_setting':['playerLevel'], 'reward06_trophy':['reward06_playerLevel_001','reward06_playerLevel_002'], 'item08':['item08_0102701']}
for name,keys in selection.items():
 p = FIX / (name+'.json')
 p.write_text(json.dumps({name:{k:data[name][k] for k in keys}},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 report['fixtures'][name] = {'keys':keys,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
(FIX/'table_list.tsv').write_text('table_file\troot_key\n'+''.join(n+'.json\t'+n+'\n' for n in selection),encoding='utf-8')
for name in ['RewardTableAccessor.cs','RewardProcessor.cs','mypageTrophyItem.cs','mypageTrophyItemDetail.cs','mypageTrophyReward.cs','mypageTrophyUpdate.cs','TrophyWindow.cs','TrophyTableAccessor.cs','TrophySettingTableAccessor.cs','LoginBounusMenu.cs','PoliticScriptCommand.cs','PoliticFSMLogin.cs','DailyMissionScene.cs','DailyMissionTableAccessor.cs','UserStatus.cs','WebApiClient.cs','HTMLTreasureMediator.cs']:
 p=SRC/name;report['source_files'][name]={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
report['original_evidence'] = [
 {'source':'RewardTableAccessor.cs:111-123','fact':'reward06_ maps to reward06_trophy; display reads 10 slots via getReward'},
 {'source':'mypageTrophyItemDetail.cs:71-101','fact':'detail resolves clearReward through RewardTableAccessor, displays every non-none slot; countMin is displayed'},
 {'source':'mypageTrophyReward.cs:42-60,65-104','fact':'completeTrophy sends category, consumes progress/rewards/characters/equips/toInBox; rewards itemId -> amount; gold updates client resource'},
 {'source':'WebApiClient.cs:2233-2240','fact':'completeTrophy has token/access/category only, no tier/nonce'},
 {'source':'TrophyWindow.cs:82-100,136-148;mypageTrophyItem.cs:74-108','fact':'bare progress root, level/status/window; complete is claimable, accept hides claim button, lock means already received'},
 {'source':'mypage_trophy.playerLevel_001 and reward06_trophy.reward06_playerLevel_001','fact':'threshold4; fixed gold100000+jewel item08_0102701 quantity6; singleton groups A/B each weight100, min=max'},
 {'source':'item08.item08_0102701; playerLevel.4','fact':'enabled jewel item; maxGold400000'},
 {'source':'LoginBounusMenu.cs:270-317;UserStatus.cs:1790-1818;PoliticFSMLogin.cs:119-129','fact':'dates are response-provided, stampCount selects dayN; replaying reward sheet can repeat client display addition'},
 {'source':'DailyMissionScene.cs:104-192,331-403,560-574;daily_mission table','fact':'85 rows contain only id/missionName; runtime response supplies all counts/reward catalogues; Result shape differs by endpoint'}]
# Negative searches are scoped to this verified container, not all possible originals.
candidates=sorted({m.group(2).decode() for m in NAME_PATTERN.finditer(b)})
report['container_search']={'json_name_candidates':len(candidates),'relevant_names':[n for n in candidates if any(k in n.lower() for k in ['daily','stamp','login','depletion'])], 'exact_byte_hits':{term.decode():b.count(term) for term in [b'loginSheet',b'stampCount',b'nextStampDate']}, 'daily_fields':sorted({k for row in data['daily_mission'].values() for k in row})}
# Verify the human-readable player level requirement inside the original container.
needle=b'PLAYRECORD_MSG_00401_DESC'; i=b.find(needle)
report['level_message']={'offset':i,'snippet':b[i:b.find(b'}',i)+1].decode('utf-8')}
report['compatibility_decisions']=[
 'Only mypage/playerLevel first-tier claim; other categories/access rejected; query omits unsupported categories, not fake zeros',
 'At second tier progress is real eligibility but further claims are not implemented; repeats always error rather than advancing category',
 'Unique singleton weighted groups and fixed counts treated as deterministic; inference from original table and display consumers, not original server code',
 'accountProgress.trophyClaims and levelTrophyNoticeSeen are internal; single save/CAS with resource and items mutation',
 'Jewel placed in existing items inventory; C collection consumer must use the same ledger; no collection redemption added',
 'Over-cap resource delivery fails atomically; no invented inbox/drop/clamp behavior',
 'Notification window=1 for qualified unseen first tier, zero after acknowledgement/claim; local first-tier notification policy',
 'No new stamp/daily success responses until schedules, reset rules and server reward catalogue are evidenced']
report['reward_audit']={'rows':len(data['reward06_trophy']), 'player_level_rows':len(selection['mypage_trophy']), 'first_reward':{'gold':100000,'jewel':6}, 'fixed_first_tier':True, 'runtime_tables_not_installed':True}
(OUT/'deep-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print({k:len(v) for k,v in data.items()})
