from pathlib import Path
import re,json,hashlib,csv
ROOT=Path(__file__).resolve().parents[4]
SRC=Path(r'C:\Users\74378\AppData\Local\Temp\onisoul-static-original-20261115')
TABLE=Path(r'D:\onisoul\work\quest-contract-20261115\all-tables')
OUT=Path(__file__).parent
FIX=ROOT/'tests/fixtures/account_progress'
# Explicit review annotations; wrapper evidence is extracted independently below.
rows=[]
def add(ep,shape,proof,tables='',rule='',status='待证规则',persist='尚未实现',next='原服回包及前后状态验证'):
 rows.append(dict(endpoint=ep,response=shape,callback=proof,tables=tables,persistence=persist,rules=rule,status=status,next=next))
for ep in ['getActionPoints','getResources','getAnnouncement','getShopcredit2']:
 add('common/'+ep,'未知；不能从 getPlayerParams 类推','WebApiClient.cs 请求包装器；全树未找到业务调用者',rule='仅 token；无独立接口层级证据',status='只有包装器证据',next='捕获原版调用与回包，核对恢复计时/公告/余额语义')
add('common/getRevisions','root.server/unity/table/root: number','TableLoad.cs:_setup',rule='登录前公开；仅注入部署 manifest；不猜版本号',status='已实现限定查询，未挂载',persist='无',next='总集成注入与现有资源 URL 一致的四项 revision')
add('common/getPlayerCogid','root.playerId','Configs.cs:GetUserInfo',rule='认证 session 自身 ID；参数不能替换目标；COG 外部绑定未恢复',status='已实现本服身份映射，未挂载',persist='无',next='验证 Configs 后续平台跳转；不宣称原 COG 账户')
for ep in ['getLoginStampSheet','stampLoginSheet']:
 add('common/'+ep,'root.startDate/endDate/stampCount/loginSheet.dayN.{itemId,amount,anniversary}','mypageLoginStampDialog.cs:processMenu;PoliticFSMLogin.cs:login;LoginBounusMenu.cs:setup;UserStatus.cs:addLoginBounus',rule='日期格式 yyyy-MM-ddTH:mm:ss+0000；日界线/断签/重复领取/奖励归属未证',next='需活动排期与奖励配置；同日重复及跨日/重登对照；C 奖励原子入库')
add('dailymission/getDailyMission','裸根分组 -> point/mission/reward/exchange/item；mission.<id>.curCount/totalCount/getPoint','DailyMissionScene.cs:Start','daily_mission','组键名称未证；reward/exchange.<index>.itemId/amount/state/point；item.<index>.itemId/amount/getPoint',next='恢复计数事件、日界线和服务端奖励目录；不能用空表假完成')
add('dailymission/getPoint','root.Result: integer','DailyMissionScene.cs:refreshActivePt','daily_mission','积分来源和每日重置未证',next='与每日任务统一积分存档；不凭空初始化为已实现')
add('dailymission/exchangeDailyMissionItem','root.Result.<rewardIndex>: remainingPoint','DailyMissionScene.cs:delegateRewardBtn (exchange branch)','daily_mission','rewardIndex；费用/目录/次数/重复领奖未证',next='C 奖励入库；资格扣费领取记录同事务')
add('dailymission/getDailyMissionReward','root.Result: claimedIndex','DailyMissionScene.cs:delegateRewardBtn (reward branch)','daily_mission','rewardIndex；领取资格必须服务端计数；未建立幂等账本',next='跨日归档键+领奖账本+奖励同事务，不由客户端状态判完成')
add('depletionmission/getDepletionMission','root.Result.{mission,reward,point}','DailyMissionTab.cs:OnDrawSystemCallBack;DrawSystem.cs:onGetServerData/ParseMission/ParseReward',rule='mission 行 curCount/totalCount/getPoint；reward 行 itemId/contents/amount；配置与重置规则未知')
add('depletionmission/exchangeDepletionPoint','root.Result: integer','DrawSystem.cs:onExchanged',rule='missionId；消耗计数来源及兑奖重试条件未证')
add('depletionmission/drawDepletionItem','root.Result.<rewardList index>: value未消费','DrawLotter.cs:OnDrawCallback',rule='抽奖概率、扣点和奖励入库原子性未证；不得使用均匀随机',next='取得抽奖配置/历史回包；C 奖励事务')
add('plugin/getPluginData','root.pluginData；root.pluginTime.pluginTime','PluginTaskManager.cs:OnGetServerData;PluginPoliticSetting.cs:SyncTaskDataToUI;PluginBattleSetting.cs:SyncTaskDataToUI',rule='自身保存设置；缺状态={}，到期=0 为本服策略；不赠时长',status='已实现限定存储读取，非普通玩法，未挂载',persist='accountProgress.pluginSetting/pluginExpiresAt（内部）',next='集成可信付费时长来源；原 Unity 验证')
add('plugin/setPluginData','确认信封；原调用 responder=null','PluginTaskManager.cs:SendPluginData;WebApiClient.cs:setPluginData',rule='pluginSetting；有效时长才保存；整表替换幂等；大小/标量验证是本服策略；不执行配置',status='已实现限定设置存储，非普通玩法，未挂载',persist='accountProgress.pluginSetting（内部），玩家锁+现有 save',next='任务参数合法性由各业务处理器校验；不表示自动任务实现')
add('plugin/getPluginLog','root.logdatas.<numericString>.{action,reward,time}','PluginLogManager.cs:requestLogData/ParseLogData',rule='诊断数据非玩法证据；time Unix 秒，key 可 long.Parse',status='已实现限定诊断读取，非普通玩法，未挂载',persist='accountProgress.pluginLogs（内部）',next='Unity 日志列表验证')
add('plugin/addPluginLog','确认信封；原调用 responder=null','PluginLogManager.cs:SendLog;WebApiClient.cs:addPluginLog',rule='logdata.action/reward；忽略传入 time；只记日志不发奖；无 nonce 重试追加；保留最近200条为本服策略',status='已实现限定诊断追加，非普通玩法，未挂载',persist='accountProgress.pluginLogs/pluginLogSequence（内部），玩家锁+现有 save',next='日志不可作为成就/资源依据')
add('plugin/buyPluginTime','root.creditExpireAt.pluginTime','PluginTaskManager.cs:buyTime','plugin_time','pluginId；表有 credit/expiration/enable，但 credit2 优先级/叠加/重试订单语义未证',next='核实付费资产与订单重试；不能用 max(now,end)+expiration 猜原规则')
add('politic/mypage/claimReward','root.result/rewards/toInbox/resources','NineGridDataManager.cs:OnClaimReward;NineGridDataParser.cs:ParseNineGridClaimRewardData',rule='reward（数字字符串）；实为九宫格，依赖 C；领取条件与随机结果需一笔事务',next='交 C 对接九宫格持久进度；H 不重复实现')
for kind in ['Artifact','Jewel']:
 table=kind.lower()+'Series'
 add('politic/mypage/get'+kind+'Series','root.page/pageMax/series.<id>.{payableCount,receiveCount,items}','mypageCollection'+kind+'.cs:load/setSeries;mypageCollectionSeriesParam.cs:setup',table,'category/page/seriesMax；原表与消费者证实收藏非虚构，但旧服务库存/分页/完成数不能沿用',next='核对分类和分页起点；C 提供真实物品获得/消耗记录')
 add('politic/mypage/get'+kind+'SeriesReward','root.series/reward/toInbox','mypageCollectionWork.cs:execReward;RewardProcessor.cs:processAll',table,'seriesId；rewardFirst/reward 仅目录，首次与重复资格/消耗顺序需服务端账本',next='C 原子扣收藏物+发奖+receiveCount；重复请求不重复发放')
add('politic/mypage/getCharacterCollection','裸根 <压缩武将编号>: grade','mypageLibrary.cs:initUseList','character','历史解锁不能等同当前库存；编号补零再拼 chara1_；含 succeeded/now 会解析失败',next='C 发卡/升阶建立历史收藏；旧存档迁移必须有来源')
add('politic/mypage/getCreditLogs','root.logs.<key>.{access,reason,quantity,creditAmount?,createdTime}','mypageRecord.cs:mypageRecordKoban.init/getKobanLogs',rule='start/end；查询范围/排序/账本来源未证',next='D 消费账本与 G 记录边界对齐，不返回伪造历史')
add('politic/mypage/getCredit2Logs','未知；不能自动等同 getCreditLogs','WebApiClient.cs:getCredit2Logs',rule='start/end；全树未找到业务调用者',status='只有包装器证据')
add('politic/mypage/getEventcodeLogs','root.logs.<key>.eventcode/name/createdTime','mypageSerialCode.cs:mypageSerialCodeRecord.init/getSerialCodeRecordLogs',rule='start/end；须真实兑换账本',next='与兑换共用唯一记录；原版日志排序/日期验证')
add('politic/mypage/useEventcode','root.error/name/itemIds','mypageSerialCodeWindow.cs:resultSerialCode',rule='eventcode；代码目录/有效期/账号或全局次数未知',next='取得授权兑换配置；全局限额需跨账号 DB 事务，单玩家锁不足')
add('politic/mypage/getPlayerRecords','root.vsBattle/quest/collection/battle/errantry','mypageRecordUpdate.cs:update/updateVsBattle/updateQuest/updateBattle/updateCollection/updateErrantry',rule='统计需真实事件累计，不能用日志或当前库存反推胜负/历史',next='G 给记录来源；A/B/C 给事件；统一计数迁移')
add('politic/mypage/getMigratePlansStatus','root.migratableTime/migratePlans','mypageEmigrateUpdate.cs:setEmigrate;mypageEmigrateObject.cs:setUp','migrate','冷却、资格、国家限制未证',next='A 地图、C 卡牌、G 国势共同确认迁居预检')
add('politic/mypage/getMigratePlanCountryStatus','root.migratePlan/countries/selfCountry.{country,rank}','mypageEmigrateUpdate.cs:onEmigrate;MigrateCache.cs:setUpMigrateData','migrate','请求 migratePlan；国家开放与 rank 不猜',next='G 国家排名+目标国家限制；不伪造 rank')
add('politic/mypage/migrate','回调不读负载，转场重载','MigrateComfirmation.cs:迁居调用;WebApiClient.cs:migrate','migrate','countryId/navigatorId/colorIndex/migratePlan/migrateKey；重置/保留/费用/幂等键未知',next='A/C 定义完整保留清单；预检后单次原子保存，禁止复用创建角色发初始资源')
add('trophy/getTrophyProgress','mypage: 裸根 <category>.level/status/window；其他 access 另审','TrophyWindow.cs:init;mypageTrophyUpdate.cs:init;WebApiClient.cs:getTrophyProgress','trophy_setting,mypage_trophy','原 wrapper 还含其他 access，不能统一塞信封；完成条件/计数来源未恢复',next='总集成纠正 shape 错误；按 access 分支审阅')
add('trophy/completeTrophy','mypage: root.progress/rewards/characters/equips/toInBox','mypageTrophyReward.cs:回调','trophy_setting,mypage_trophy','access/category；toInBox 大小写不同于收藏；客户端进度不可信',next='逐类别条件+领奖账本+C 奖励事务；其余 access 不猜')
add('trophy/messageWindowTrophy','回调未读取负载','WebApiClient.cs:message_window_trophy;TrophyWindow.cs:init','trophy_setting','access/category；通知确认与领取分离，window 如何前进未证',next='同类别多等级提示/重登对照，禁止标记为领奖')
# Phase 2 supersedes the initial wrapper-only trophy assessment.
for row in rows:
 if row['endpoint'].startswith('trophy/'):
  row['status']='已实现 mypage/playerLevel 首档限定范围，未挂载'
  row['tables']='trophy_setting,mypage_trophy,reward06_trophy,item08,playerLevel；后两奖励依赖由原容器验证提取'
  row['persistence']='accountProgress.trophyClaims/levelTrophyNoticeSeen（内部）；资产与领取账本单次 save/CAS'
  row['rules']='只支持 mypage；level取服务端；领奖仅 playerLevel_001；再次请求明确失败不推进第二档；超容量原子拒绝'
  row['next']='剩余类别/档位、溢出入箱、原客户端动态验证；见 deep-review.json'
  if row['endpoint']=='trophy/getTrophyProgress':
   row['response']='裸根 playerLevel.{level,status,window}；领取后如实显示第二档资格；仅首档支持领奖'
  if row['endpoint']=='trophy/messageWindowTrophy':
   row['rules']='仅确认已展示资格的首档通知；不发奖；重复确认幂等；window=0 的通知策略为本服兼容决策'
  row['callback']+=';mypageTrophyItem.cs:update;RewardTableAccessor.cs:getReward;mypageTrophyItemDetail.cs:update'
 if row['endpoint'] in ('common/getLoginStampSheet','common/stampLoginSheet'):
  row['next']='原容器无 loginSheet/stampCount/nextStampDate 字节命中；需排期/日界线/断签/重试回包，不能编造，详见 deep-review.json'
 if row['endpoint'].startswith('dailymission/'):
  row['next']='原表85行仅 id/missionName，完整容器复查未找到对应奖励目录；需服务端目录、重置规则、计数事件来源'
assert len(rows)==37
web=(SRC/'WebApiClient.cs').read_text(encoding='utf-8-sig')
methods=list(re.finditer(r'\tpublic void (\w+)\([^\n]*\)',web))
evidence={'baseline':'1f287e33123afa452d2f5d2aac2427566d549f73','source_root':str(SRC),'table_root':str(TABLE),'original_protocol':{},'sources':{},'tables':{},'compatibility_decisions':['accountProgress is internal storage, not a protocol field','revision values must be explicitly injected by deployment','COG playerId uses authenticated stub identity, not an external COG binding','empty settings/logs and expiry zero are local no-grant defaults','settings replace atomically, flat scalar section transport; task semantics remain elsewhere','plugin entitlement check follows client SendPluginData time gate; no purchase implementation','log sequence, 200-row retention and length bounds are local policy; time is server Unix seconds','diagnostic log retries append (no request nonce); reward field never changes inventory','no source establishes server reward probability, activity calendar, or migration reset policy']}
files={'WebApiClient.cs','HashAccessor.cs','GameRestarter.cs','PluginTaskDataConverter.cs','PluginUIManager.cs','JewelSeriesTableAccessor.cs','ArtifactSeriesTableAccessor.cs','DailyMissionTableAccessor.cs','TrophySettingTableAccessor.cs','TrophyTableAccessor.cs'}
for row in rows:
 wrappers=[]
 for i,m in enumerate(methods):
  chunk=web[m.start():methods[i+1].start() if i+1<len(methods) else len(web)]
  if '"'+row['endpoint']+'"' in chunk:
   wrappers.append({'method':m.group(1),'line':web.count('\n',0,m.start())+1,'request_fields':re.findall(r'\.Add\("([^"\n]+)"',chunk)})
 row['request']='; '.join(w['method']+':'+','.join(w['request_fields']) for w in wrappers)
 evidence['original_protocol'][row['endpoint']]={'wrappers':wrappers,'response':row['response'],'callback':row['callback'],'status':row['status']}
 files.update(re.findall(r'([A-Za-z0-9_]+\.cs)',row['callback']))
for name in sorted(files):
 p=SRC/name
 if not p.exists(): raise RuntimeError(name)
 text=p.read_text(encoding='utf-8-sig')
 evidence['sources'][name]={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'method_lines':[{'line':i,'declaration':line.strip()} for i,line in enumerate(text.splitlines(),1) if re.search(r'^\s*(?:public|private|protected) .*\(',line) and any(word in line for word in re.findall(r'[A-Za-z_][A-Za-z_0-9]*', ' '.join(r['callback'] for r in rows if name in r['callback'])) if word not in ('cs', name[:-3]))]}
for name in ['daily_mission','artifactSeries','jewelSeries','trophy_setting','mypage_trophy','plugin_time','migrate']:
 p=TABLE/(name+'.json'); data=json.loads(p.read_text(encoding='utf-8-sig'))[name]
 key=next(iter(data)); sample={name:{key:data[key]}}
 dest=FIX/(name+'-sample.json');dest.write_text(json.dumps(sample,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 evidence['tables'][name]={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'rows':len(data),'sample_key':key,'sample_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}
evidence['phase2']={'report':'deep-review.json','source':'fingerprinted original tableAssets.bin','scope':'mypage/playerLevel first tier only; three additional limited handlers, not mounted'}
evidence['setting_fixture']={'path':'tests/fixtures/account_progress/plugin-setting.json','sha256':hashlib.sha256((FIX/'plugin-setting.json').read_bytes()).hexdigest(),'source':'PluginTaskManager.cs:CreateSampleTask:81-92','purpose':'storage round-trip only; not default configuration'}
(OUT/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with (OUT/'reviewed-endpoints.tsv').open('w',encoding='utf-8',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=['endpoint','request','response','callback','tables','persistence','rules','status','next'],delimiter='\t');writer.writeheader();writer.writerows(sorted(rows,key=lambda r:r['endpoint']))
print(json.dumps({k:v['rows'] for k,v in evidence['tables'].items()}))
