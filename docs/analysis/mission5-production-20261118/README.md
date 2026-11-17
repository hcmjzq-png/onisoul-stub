# 任务 5：本地田地开工、计时与收获

## 原因与旧实现去向

本机抓包在 2026-11-18 00:41:04 记录到 `submitProduceTask` 返回 HTTP 200，
业务却为 `succeeded=false` / `errorReason=no stub response`，原因为生产结算未接入。
原 `GameRestarter.isError` 会据此终止队列并显示联机中断。这是业务缺口。

旧工作目录中存在《新号进入城下町到任务7问题与解决记录.md》（2026-11-14），
其中任务 5 标为“恢复版已验证，待迁移”；该文档未跟踪、未进入新仓库。
GitHub PR #53 同样注明只有开工候选、收获未挂载，不能据此宣称本仓库任务 1～7 已验收。
旧 `server/business.py:1845,1884` 的生产响应结构可复用，但其随机发奖/自动续产是旧模拟策略，
且把粮食等放入 items；本次没有把它作为原版经济公式或照搬旧库存写法。

## 本次范围与兼容规则

正常注册挂载 `politic/task/submitProduceTask` 的受限实现，与已有 `completeTasks` 共同完成：

- 前置：任务 4 closed、任务 5 已接受；G1 田地 `building200_041_01_01_1_1`，
  原免费配方 `product060_023_01_01_1_1`。归属、地图、完成状态、配方、等级、耐久和点数校验继续使用原候选检查。
- 开工：原表周期 10 秒、金币成本 0、消耗 1 PP；保存 productId/createdTime/dueTime，重登恢复同一计时。
- 到期：仅到期不发奖；收获前验证 dueTime，提前请求失败且不改状态。
- 收获：扣 1 PP；奖励写入实际 food 余额及 entity.exp，建筑 exp、空闲状态、任务删除在同一 CAS 存档中提交。
  回包按原消费者提供 producings.<id>.reward/building/collaborator、buildings、autoProducings、characters、equips。
- 任务 5：按原 `resourceCount → UserStatus.getResourceValue` 读取服务端粮食余额；finished/closed 与原奖励记录联动，重登保持、重复领奖不增发。

**兼容规则，尚非原服结算公式**：仅对这一配方采用原客户端菜单的 grade/level 插值作为实际产量，
原表的玩家经验和 product.buildingExp 作为经验增量。Lv1 为粮食 13、玩家经验 2、建筑经验 10。
没有恢复随机分布。任务 5 领奖继续使用其原表奖励（包含粮食 300、金币 2000、经验 50）。

道路邻接、倍率与技能影响仍无可靠完整公式，因此本受限模式拒绝地图已放道路或非空内政编队的情景，
不默默漏算加成。其他配方、G2/G3、有限耐久、自动续产、批量、取消、加速和好友助产未开放。
这是任务 5 的小闭环，不代表整个生产系统完成。

内部 `tutorialFieldProductionV1` 保存任务代次、奖励快照和建筑等级；不投影到原响应。
同一已保存生产任务最多结算一次；重复 completeTasks 返回空增量，失败批次不保存任何修改。
原请求只有 buildingIds，没有操作 nonce，无法辨别新一轮到期后才送达的旧请求；不声称恢复跨代次迟到请求的原服语义。

## 证据与验证口径

- 原表抽样：`tests/fixtures/tutorial-production.json`，逐行内容与本地原表一致；来源散列见 source-proof.json。
- 原回调：StateManualProduce.waitProduce/onComplite、StateAutoProduce.onCompliteProducings、PoliticBuildingParameter.updateTask/updateProduce。
- 原时钟：PoliticProduceTimer.play 按 dueTime-ClockTimer.Sec 计时。
- 原扣点：PoliticBuilding.submitProduce/onClick 分别对开工和单体收获扣 1 PP。
- 自动回归覆盖完整闭环、提前收获、重建服务、并发重复、上限/点数不足、冲突回滚、混合批次及缺表分类。
- 隔离 MySQL 用实际 HTTP 验证保存、重启、收获、任务领奖和重登。

本次仅部署本机测试服；不部署云端。Unity 游戏内操作由用户验收，尚未把自动回归写成真机验收通过。

2026-11-18 本机验证结果：完整隔离 MySQL 8.0.46 回归 **689 项全部通过、0 跳过**；
测试实例已关闭。通过本地 80 入口新建临时账号，正常完成任务 1～4 后接受任务 5，
真实等待 10 秒周期并收获：粮食 0→13、玩家经验 +2、建筑经验 +10、开工/收获共扣 2 PP。
任务 5 领奖后粮食 313，重复收获/领奖无增量，重新登录后任务状态 C、生产表为空。
临时账号已精确清理；部署前后现有玩家原始存档相同，没有改档跳任务。
摘要见 validation.json；完整抓包、源代码备份和私有运行报告只保留在本机。
