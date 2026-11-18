# 提前建造后接任务导致联机中断

2026-11-18，基于本机实际运行的 `fd9affd`。通用任务状态机修复，不按任务编号放行。
本次仅针对本机测试服；不修改玩家存档、资源包、hosts、局域网或云端配置。

## 精炼炉复现

本机抓包路径为客户端 → hosts（回环）→ gateway:80 → proxy80:18082 → stub:18081。
脱敏请求顺序如下，均 HTTP 200：

| 时间 | 请求 | 结果 |
| --- | --- | --- |
| 17:55:39 | 任务 8 `closed` | 成功，奖励含精炼炉图纸 `item04_0200040` |
| 17:55:42 | 任务 9 `opened` | 成功 |
| 17:55:56 | `submitBuildTask`，`draft2000040` | 成功，生成 `building200_040_01_01_1_1` |
| 17:56:00 | `completeTasks` | 成功，精炼炉 `status=none` |
| 17:56:11 | 任务 9 `finished` | 拒绝：`mission completion conditions are not satisfied` |

只读核对当时存档：任务 9 摘要为 O、明细为 opened，精炼炉已完工。
客户端没有发送 accepted。错误来自 stub 的状态转换限制，链路正常、建筑条件已满足。
这次属于业务状态机不兼容，不是 `stub has no assets`，也不是 `no stub response`。

## 原版证据与修改

原始 PC DLL SHA-256：`b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e`。

- `PoliticMissionProgressStatus.cs:305-343`：phaseOpened 检查条件；GoNext 时，
  条件已满足且非手动任务直接 changeStatus(finished)，否则 changeStatus(accepted)。
  两个分支都会 getAcceptUnlocks。提前建造并非异常操作。
- `PoliticMissionProgressList.cs:1199-1245`：发送 RequestStatus；没有为普通任务额外插入 accepted。
- 原 `politicMission`：任务 9 需要任务 8 已关闭，完成任一指定品级精炼炉即可。

服务端统一允许 opened→finished，仍用原有服务端可信条件证明判断完成。
适用于所有已支持条件的任务，不局限于精炼炉；finished 本身不发奖励，closed 仍一次结算。
locked→finished、opened→closed、未达标、前置未满足、未知条件和回退状态继续拒绝。
自接受教学仍需要真实 accepted，不因兼容分支伪造接受记录。

未实现的任务前置、条件和玩法仍保持明确失败；本修复不代表所有后续任务都已实现。
原客户端检查过但服务端未观察到的历史条件，仍不靠客户端 work 值放行。

## 验证范围

新增回归使用原表子集，散列和行清单见 [source-proof.json](source-proof.json)。

- 主城类别、三种田地、粮食、道路、茶屋、植林地、三种精炼炉：opened→finished。
- 实际精炼炉图纸消耗、建造、完工、服务重建、完成、领奖及重登；重复完成不发奖、重复关闭不再结算。
- 未达标、前置未满足、锁定跳完成、直接领奖、自接受/未知条件及混合批次回滚。

隔离 MySQL 8.0.46 全量回归：789 项通过、0 跳过，临时实例已正常关闭。
读取本机任务 9 仍为 opened 的存档，在内存副本中经真实处理器成功转为 finished，奖励为空；
没有写回数据库。无需修改玩家任务状态或补发建筑。

已将修复提交 `807adc7` 加载到本机测试服，build_id 为
`mission-transitions-v1-20261118-807adc7`；80、18082、18081 三层健康信息一致。
固定运行目录包含原本已启用的生产/商店修改，再加入本次状态机修复。

运行中的 80 入口使用临时账号验证：图纸消耗 → 建造 → 完工 → 重登保持 opened →
不发送 accepted 直接 finished → 原表奖励 → 重登 → 重复领奖为空。
同时验证未建造拒绝完成、opened 直接 closed 拒绝，失败时不写存档。
临时账号精确清理；测试前后现有玩家 state_json 散列一致，无存档迁移。
脱敏验收摘要见 [verification.json](verification.json)。

修复后的 Unity 自然操作尚待验收。本次没有发布云端或改动局域网配置。
