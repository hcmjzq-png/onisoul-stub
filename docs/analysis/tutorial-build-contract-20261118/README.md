# 新手主城图纸重复与任务 4 田地中断

2026-11-18，基于已合并 #84 的 `f25bc409faa36e014176c1e8ad3c1e6646daf9e4`。
本次修改服务端初始化与任务条件判定，不修改客户端、资源包或现有玩家物品。
目前仅加载到本机测试服；尚未发布云端或取得本次修复后的 Unity 操作验收。

## 主城为什么有两张

旧 `_default_state` 无条件放入 `draft2000002: 1`；任务 1 的原始奖励
`reward01_04_00001_01` 又发 `country_00041_self: 1`。
后者经 `reward99_country.country_00041`、`item04.parameterId` 解析为国家对应城图纸。
`getDrafts` 汇总直接图纸和物品图纸，因而两次发放会叠加。

- 原 `beginning_equipment.common` 和国家行的 `drafts/draftAmounts` 为空；
  三种主城 `draft2000000/1/2.initialAmount` 均为 0。
- country30 的任务奖励是 `item04_0200002 → draft2000002`，与额外赠送合计为 2。
- country01 的原奖励是 `draft2000001`，旧代码还会多发另一个阵营的 `draft2000002`。
- 本机历史抓包：任务 1 关闭后奖励包含 `item04_0200002: 1`，随后 `getDrafts`
  返回城图纸 2 张。任务奖励账本没有重复领取；多出的是初始化赠送。

删除无原表依据的初始赠送，正常任务奖励保留。旧档已有图纸继续保留；
缺少 `drafts` 的旧档也不再默认补发。不批量扣除玩家图纸或拆除建筑。

## 任务 4 为什么中断

本机 2026-11-18 的脱敏请求顺序如下，均 HTTP 200：

| 时间 | 请求 | 结果 |
| --- | --- | --- |
| 00:18:16 | `submitBuildTask`，田地图纸 `draft2000041` | 成功；`status=building`、`remainedClickCount=0`，没有 `errorReason` |
| 00:18:17 | `mission/changeState`，任务 4 `finished` | 拒绝：`mission completion conditions are not satisfied` |
| 00:18:17 | `completeTasks` | 成功；田地转为 `status=none` |

客户端请求已到 stub；不是 hosts/proxy80 断开，也不是 `stub has no assets` 或
`no stub response`。这次有真实业务拒绝，与 #84 的空 `errorReason` 误带不同。

原客户端证据来自相同原始 PC DLL，SHA-256
`b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e`：

- `PoliticMissionConditionOne.cs:174` 的 `totalBuildingCount` 调用
  `UserStatus.getBuildingCount`，任务 4 原表使用该条件，三个目标对应三个田地变体。
- `PoliticBuildingState/StateBuilding.cs:86` 的完成待点击状态在退出时先
  `addBuildingCount`，再进入 `waitCompleteCheck` 排队请求 `completeTask`。
  因而客户端可以先发任务完成，再发建筑完成；本机抓包正是此顺序。
- 任务 2 使用 `categoryGradeCount`，经 `PoliticBuildingList.cs:397` 检查
  `IsBuildComplete`（`PoliticBuilding.cs:211`），需要完成回调后的建筑状态。

兼容修复：`totalBuildingCount` 对服务端已保存且显式 `remainedClickCount=0`
的待确认建筑允许计数，避免依赖两个请求先后。类别条件仍排除施工建筑；
缺失/非法/非零次数和不同建筑类型不通过，不信任客户端上报的任务 work 值。
此判定不改建筑状态，后续 `completeTasks` 仍负责正常完成施工。

## 验收范围

- 隔离 MySQL 8.0.46：673 项通过、0 跳过，临时实例已停止，不使用运行中的玩家库。
- 原始完整表的内存冒烟：自然完成任务 1～4，国家对应主城唯一，田地按捕获顺序结算。
- 本机 80 入口 HTTP 临时账号：country01 与 country30；创建时无城图纸、任务 1
  只发 1 张、消耗后重登不补发；任务 2 完工前仍拒绝完成；任务 4 放置前拒绝，
  放置后先完成任务、再完成建筑均成功；重复领奖无奖励、重登建筑与物品保持一致。
- 临时账号精确清理；测试前后现有玩家 `state_json` 校验一致，无存档迁移。
- 测试夹具补齐原 country01 奖励对应的 `draft2000001/building200_001`，
  冒烟工具消费真实奖励，避免继续使用额外赠送来掩盖问题。

输入散列及脱敏验收摘要见 [source-proof.json](source-proof.json)。
原客户端本次修复后的自然操作，以及后续教学/生产仍待单独验收。
