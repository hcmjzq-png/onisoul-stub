# H：玩家资料、活动进度与收藏

基线 `1f287e33123afa452d2f5d2aac2427566d549f73`；独立分支 `parallel/342-h-account-progress-20261115`。
37 个入口逐项记录于 [reviewed-endpoints.tsv](reviewed-endpoints.tsv)。新增 6 个**限定范围**处理器，尚未生产挂载；其余 31 项没有宣称完成，不改变全局占位数量。

## 可集成代码

`app/business/account_progress_services.py` 继承 PlayerServices，沿用玩家锁和保存机制。测试显式注册：

```python
AccountProgressServices(service, revisions=verified_manifest).register(registry)
```

| 入口 | 支持范围 | 限制 |
| --- | --- | --- |
| common/getRevisions | 登录前读取部署注入的 server/unity/table/root | 没有配置明确失败；不写死版本号 |
| common/getPlayerCogid | 返回认证会话自身 playerId | 本服身份映射，不是原 COG 账户绑定 |
| plugin/getPluginData | 读取持久设置和可信时长 | 缺状态不赠时长 |
| plugin/setPluginData | 有效时长内保存三类扁平标量设置，整表替换幂等 | 不执行自动任务；只校验存储结构/大小，不声称验证每个游戏参数 |
| plugin/getPluginLog | 读取本账号诊断日志 | 不能当玩法进度或原服规则证据 |
| plugin/addPluginLog | 校验后追加诊断日志，服务器时间，保留最近200条 | 无 nonce 重试会追加；reward 字段永不发奖 |

确认回包沿用现有信封是兼容决策；设置/追加日志的原调用没有响应消费者。
内部 `accountProgress` 存档命名空间、保留策略、尺寸限制、空设置/零时长都与原协议证据分开列在 [evidence.json](evidence.json)。
设置功能需要已存在的可信时长；本分支不提供购买或免费授时入口。

## 关键发现与仍未知内容

- `getActionPoints/getResources/getAnnouncement/getShopcredit2` 全树只找到请求包装器，不能从其他接口嵌套字段猜独立响应。`getCredit2Logs` 同样没有找到业务调用者。
- `getRevisions` 先于登录，不能统一套角色认证；Configs.GetUserInfo 只读取 `getPlayerCogid.playerId`。
- 印章菜单直接解析 `startDate/endDate`，按 `stampCount` 选 `loginSheet.dayN`；UserStatus.addLoginBounus 会把物品交给 RewardProcessor。没有排期、日界线和奖励目录，不能填假日期/空成功。
- `daily_mission` 85 行仅给任务标识/名称，消费者需要的门槛、积分、奖励/兑换目录来自回包。这个表不足以恢复每日业务，属于 no stub response，不是假称缺少资源文件。
- 消耗任务查询读取 `Result.mission/reward/point`；抽奖读取 `Result` 的键作为 rewardList 下标，值未消费。奖池顺序/概率/重试结算仍未知。
- 原表有 artifactSeries 470 行、jewelSeries 261 行；消费者读 `payableCount/receiveCount/items`，并用原表 rewardFirst/reward。证明系统存在，**不证明旧服务收藏库存或奖励逻辑可信**。客户端显示会把 payableCount 折算回物品数，不能直接当当前库存。
- `getCharacterCollection` 是压缩武将编号→grade 的裸根映射；历史收藏不等于当前武将库存。
- `getTrophyProgress(access=mypage)` 也遍历裸根表。现有 response_shapes 的标量根证据有误；其他 access 包括 raidBoss/giganticRaidBoss/动态活动，待分支审阅。completeTrophy 的 `toInBox` 大小写与收藏 `toInbox` 不同。
- `claimReward` 是九宫格，参数实际叫 `reward`（数字字符串），交 C 对接；不按路径名字误认普通资料领奖。
- plugin_time 有三档 credit/expiration/enable；未证明付费余额优先级、有效时长叠加与订单幂等，未实现购买。
- migrate 有 interval/credit/upperRankAllowable；城市/国家/卡牌保留和重置语义未证，不能用 createPlayer 复用初始赠送。兑换码目录与全局限额也未知。

## 来源与复现

原反编译：`C:\Users\74378\AppData\Local\Temp\onisoul-static-original-20261115`；只读原表：`D:\onisoul\work\quest-contract-20261115\all-tables`。
沿用基线 source-proof 中 DLL SHA-256 `b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e`；本批逐文件 SHA-256、请求方法/行号、辅助读字段方法和原表散列另存 evidence.json。
七份单行原表样本位于 `tests/fixtures/account_progress/`，仅用于审阅规则依据；业务没有加载这些样本来假冒完整目录。
`plugin-setting.json` 是 PluginTaskManager.CreateSampleTask 的 potion 参数小样本（81—92行），仅用于存储往返测试，不是默认发放或推荐配置。
`account_progress_audit.py` 可在本机原源仍存在时重建 TSV、证据和原表小样本；不要把原客户端/全表上传。

## 验证与集成

在 H 工作树运行：

```powershell
python -m unittest tests.test_account_progress_services -q
python -m unittest discover -s tests -q
```

新增12项通过；完整238项通过，无跳过。覆盖认证/跨账号、设置替换与重试/过期、重登、输入失败无写入、日志不发奖、并发/保留上限、保存 revision 冲突回滚及重试、未自动生产挂载。
完整回归的基线文件有 ResourceWarning，未导致失败；没有缺可选依赖。
没有执行服务器部署、hosts/proxy80/config.ini 修改或共享客户端操作，没有做 Unity 真机验收。
精确挂载点、公共响应形态修正、A/C/G/D 依赖和最小动态步骤见 [integration-notes.txt](integration-notes.txt)。
