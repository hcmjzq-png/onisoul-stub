# H 串行验收计划

由汇总对话独占原 Unity 客户端；H 本轮未启动客户端。保持游戏原始尺寸，监控面板与游戏等大对齐。
本机与局域网分别记录，链路均为：客户端→hosts→proxy80→stub。记录服务提交、客户端 DLL/表散列、计划指纹、服务器 UTC 时间和脱敏账号。

## 前提

- 隔离测试账号，绝不修改生产玩家；有完整原包 `LoginBounusMenu`、`LoginBG`、奖品图标及表资源。
- 先审核目标服别/时期的排期、奖励、日界线和断签政策。若使用兼容测试计划，画面和日志必须标为测试，不能冒充原服历史数值。
- 已应用待集成补丁，并有 I 组确认的 CAS 存储。默认无计划不启用。

## 签到

1. 正常登录创建角色，读取 `common/getPlayerParams` 的两处 nextStampDate，确认 `UserStatus.IsNeedLoginStamp` 与服务器日期一致，触发 `common/stampLoginSheet`；记录 `startDate/endDate/stampCount/loginSheet/nextStampDate` 和前后存档 revision。
2. 打开我的资料签到浏览：仅 `common/getLoginStampSheet`，不产生领奖收据、余额或点数变化。
3. 同日重登及重复 stamp：只有首次成功会使客户端 RewardProcessor 加资源。重复 errorReason 应走 GameRestarter，不应显示第二次奖品；记录错误对话框/恢复行为。
4. 丢弃首次成功回包但保留服务器提交，再重登：权威余额与已领格回读一致。验证只出现一次奖励；如果需改客户端交互，另行明确兼容方案。
5. 在日界前后各一次；间隔数秒也应属于两天。再隔一日不登录，检查所审核的 preserve/reset 规则；不可由这次模拟服实验反证原服行为。
6. 最后格领完、活动结束、切换互不重叠的新排期；不可越界播放第 N+1 格，也不可沿用旧领取成功回包。
7. 容量不足、资源缺失、并发冲突分别回归。文件/表加载失败记 `stub has no assets`；无排期、坏引用/状态、未实现规则记 `no stub response`。

## 尚需历史材料确认的判别实验

若取得同版本原服录屏/保存响应：首日+次日定位格序；漏一天后格序区分累计/连续/按日历；维护前后与 00:00/UTC 对照确定时区；完整十四格与 start/end 同时出现才能绑定奖励目录。不能将日服 2012 的零时公告或 PS3 奖杯写成台服日界线。

每日任务需同一个真实事件（例如 daily_mission_52 获得金钱）前后 `getDailyMission/getPoint`，以及奖励/兑换前后的 point、curCount、state、Result；区分到账积分/累计积分、日重置/周期重置、礼包与任务奖池。当前没有可靠历史数据，不能以测试日志虚构计数。

收藏需原 UI 的 seriesId、payableCount、receiveCount、items 和领奖消耗前后（首次/重复、非整套）；武将图鉴需来源与历史等级。迁国需初次/冷却内/目标国上位限制、迁居确认 key 和完整资产前后清单。兑换码须发行目录、期效及账号/全服限额；挂机须权益订单来源。
