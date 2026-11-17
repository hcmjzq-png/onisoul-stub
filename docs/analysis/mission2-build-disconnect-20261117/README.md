# 本地任务 2 摆放主城联机中断

2026-11-17，范围为本机独立测试服，代码基线 `0643c37`。

## 根因与链路

客户端 → hosts（回环地址）→ gateway:80 → proxy:18082 → stub:18081。
当日 23:09:23 的 `politic/task/submitBuildTask` 请求为
`draft2000002`、`originCoord=[15,15]`，HTTP 200 / 80 ms；
成功回包同时包含 `succeeded:true` 和 `errorReason:""`。
本机 `logs/local-capture/capture-20261117.jsonl:371` 保留该记录。

**bundle 证据**：安装包程序集 SHA-256
`b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e`。
`GameRestarter::isError`（token `0x0600158D`，反编译 `GameRestarter.cs:79-99`）
检查根表是否存在 `errorReason`；除内部忽略值 `hoge` 外，有键即失败，空串同样失败。
`WebApiClient.cs:324` 在调用成功回调前执行该过滤器；
`GameRestarter::onError`（token `0x0600158E`）暂停服务并清空请求队列。
因此此次中断发生在回包过滤阶段，不是成功回调中的字段转换异常。

服务端 `GameplayService._success()` 合并契约占位字段时，把失败分支读取的
`errorReason:string` 默认值也带进了成功回包。主城先保存，客户端随后拒绝回包，
所以未继续发 `completeTasks`。只读核对：该主城仍在 `(15,15)`，
`status=building`、`remainedClickCount=0`，任务 2 为 `A`。

这是**回包兼容缺陷**。此次请求既非 `stub has no assets`（资源缺失），
也非 `no stub response`（接口无实现或可信状态）。

## 修复与验收

- 真实成功响应合并业务数据前，移除契约产生的默认 `errorReason`；失败响应仍保留错误原因。
- 任务 1～4 回归检查普通建造和立即完成均不带该键；非法图纸仍失败且不写存档。
- HTTP 冒烟对每个 `succeeded:true` 回包检查错误键不存在，增加主城摆放、完成与地图回读。
- 修复前任务 2 回归在错误键断言处失败；修复后 677 项隔离 MySQL 回归全部通过，无跳过。
- 本机实际 hosts/两层代理/stub/MySQL 链路通过上述 HTTP 冒烟，临时账号已精确清理；
  运行前后已有玩家整行摘要一致。
- 已将同一修复应用到本机测试服运行工作树，重启本机 stub/proxy；云端服务未改。
- 首轮回包修复后仍须原 UI 复测；后续实测发现重登脚本阻塞，处理和结果见下节。
  已摆放主城保留，无需删档重摆。

本机私有证据位于 `work/mission2-evidence/`（脱敏抓包、原 IL、只读存档摘要、HTTP 结果）
及 `work/local-sql-mission2-20261117/`（完整隔离 SQL 回归）。

## 追加：普通重登的临时操作锁

用户复测主城可见却无法点击。23:21:32 的普通进城请求中，
`scr2_000001`（URL 键 `cc4294d197c943136191cfba8db1a950`）连续五次 404。
这是 **stub has no assets**；与前述成功回包错误独立。

**bundle 证据**：`PoliticFSMStartup.cs:5,56,100-119` 在普通启动时先 lockOperate，
等待 `scr2_000001_01` 完成回调后转 Product，并在状态退出时 unlockOperate。
它是普通进城脚本，不是任务 2，也不能从文件名中的 2 推断任务编号。
`Script/StanderdLibrary.cs:102-115` 一直等待非空资源；
`Loader.cs:331-348` 在下载重试耗尽后直接退出，不通知资源消费者。
因此缺包时上层连错误分支都走不到，临时锁一直保留。
未解锁的灰色功能按钮仍属任务阶段限制，不能拿它们判断点击故障。

未找到可信原脚本。现有同名候选仅含空 XML，未下发。
本次为**客户端兼容修复**：只把 `assets/scr/scr2_000001.unity3d` 的最终下载失败
传给同名脚本等待器，使其退出等待，沿 Interpreter 原有错误分支触发一次完成回调；
由原 FSM 退出临时锁。开始新一轮同名脚本时清除失败标志，原资源存在时仍正常播放。
不伪造原脚本，不修改任务状态或开放位，不跳过新手教学或活动启动脚本。

本机已下发新 app，SHA-256
`593f03e241a9f9f7c3fa9939b3df9eb87f86e50b662093484f71af0027b9ed23`；
程序集为 `0c34100effc18c976850ba66b42660366b0fc2e6cb718abc77204b95b4a512e1`。
主包其他 24 个条目逐字节保持；原 app 已备份。云端未发布这次补丁。
原脚本仍返回 404，兼容恢复不代表资源已找回。

验证：原 DLL 的 C# 回归覆盖最终失败传递、空等待结束、重试清零、五种排除脚本及回调一次性。
完整 IL 解码通过。用户在新主包重新进入后确认可点击，抓包记录：
23:44:17 completeTasks 返回主城 status=none；23:44:18 任务 2 finished；
23:44:26 任务 2 closed 并发奖；23:44:28 任务 3 opened。
没有通过改档完成任务。原生与发布证据在 `work/startup-recovery/`。

## 同类回包审计

契约模板中的空 errorReason 共命中五个入口：submitBuildTask、submitBuildAndComplete、
levelUpBuilding、levelUpBuildings、conflateBuilding。前四个真实处理器共用 `_success`，
本次成功回包修复同时覆盖它们；建筑合成仍未实现，源码改为明确 no stub response，
不再以 succeeded=true 加空错误键冒充成功。这不证明其他玩法已完成全流程验收。
