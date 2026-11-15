# 首档成就、原表发布与背景边界修正

基线：已合并 PR #49，`fbe51685cf86a9b1c34e0fe34ebbf9c13be60d2c`。
本分支正常注册 402 个接口，其中 71 个专用 handler、331 个占位 handler。
相对基线新增 3 个正式入口，不将背景候选组件算作已完成。

## 已接入的闭环

- `trophy/getTrophyProgress`：只接受 `access=mypage`，只返回 `playerLevel` 首档，使用裸根映射。
- `trophy/completeTrophy`：服务端等级至少 4；原表固定发放金钱 100000、`item08_0102701` × 6。奖励与领取 ledger 同一 CAS 保存。无参数可绕过等级、指定他人或指定奖励。
- `trophy/messageWindowTrophy`：仅确认提醒，可重试，不发奖励。

领取后返回 `level=1,status=lock,window=0`，原 UI 显示首档已领取，后续档不展示领取按钮。
这是有限实现的显示策略，不证明原服后续档机制。请求仅含 category，没有档位或 nonce，
所以首档领取后再次请求明确失败，防止丢包重试意外领取下一档或重放客户端资源增量。
若第一次成功响应丢失，需重新查询玩家资源和成就状态，不能靠重复成功响应补偿。

只支持原 stub 存档：缺失 ledger 视为之前未发放，现有 ledger 保留；异常结构拒绝。
尚未支持原服领取历史导入、其他分类、后续档、随机奖励、角色/装备奖励和溢出转信箱。
超金钱上限或宝石计数溢出时整笔不写入，腾出容量后可重试。

## 七张原表

`server_tables.tsv` 新声明 item08、item13、item14、reward06_trophy、skillRefreshG2/G4/G6。
完整原表不入 Git；来源和原字节 SHA-256 在
[`../parallel-342/review-round2/recovered-tables-source-proof.json`](../parallel-342/review-round2/recovered-tables-source-proof.json)。
本次共 1853 行。不能把新增声明导致的计数变化解释为修好了原先两张缺表或十个资源请求。
仍须区分：缺文件/解析失败是 `stub has no assets`，缺规则或坏引用是 `no stub response`。

```powershell
python tools/publish_verified_tables.py --container D:/onisoul/work/quest-contract-20261115/tableAssets.bin --dest D:/onisoul/work/verified-trophies-20261115/package
```

生成器核对整个解压容器哈希、具名 TextAsset、偏移、长度、文件哈希、根键和行数。
安装已准备的目录（先停服务，单进程操作）：

```sh
python3 tools/publish_verified_tables.py --source /path/to/package --dest /opt/onisoul/assets/pc/tables
```

所有文件及目标冲突检查完成后才开始写；已有同字节文件保持原样，不同字节拒绝覆盖。
import-manifest.json 合并这七项并保留其他项和元数据；写入异常清理本次新建文件。
发布不是多文件数据库事务，维护前仍应备份；掉电中断后重新运行会校验并补齐。
运行身份须与服务的资源文件所有者一致。

## 背景的确定结论

原安装包消费者证明背景功能属于支城 `mapId=1`：

- `mypageCastleTownItem.cs:101-147` 仅 no=1 显示三个按钮，并检查支城启用及任务解锁。
- `mypageBgSelectWindow.cs:135-150` 发送 mapId=1，成功后更新 mapEntry(1)。
- 主城 no=0 隐藏按钮；此前候选组件只接受 mapId=0 是错误实现，现已修正。

A、D 候选组件已统一为 `items` 归属，选择落在 `mapBackgrounds["1"]`，拒绝 mapId=0。
查询不发免费背景、不把旧伪造归属字段自动迁移为权益。
两者都要求来自服务端玩家状态的 `subcity_enabled` 提供者；测试里的 True 只代表测试情景。
当前没有可信的支城解锁与地图持久化生产端，四个入口仍保留未挂载状态，商城不会因此开放扣费。
恢复 item13/item14 也不等于其 parameterId 引用的全部场景资源已验收。

## 验证与部署边界

- 全量 417 项单测通过，含正常注册路径、并发/跨服务 CAS、重登、奖励上限、损坏 ledger、缺表/坏引用分类。
- 发布工具验证整批失败不部分复制、目标冲突拒绝、保存其他 import 记录、写失败回滚和重复执行。
- 从原 tableAssets.bin 重新提取七表成功；完整原表目录运行 `tools/trophy_smoke.py --table-dir ...` 成功，16 次并发领取仅一次成功。
- 背景候选购买→归属→选择跨组件测试通过，主城不被写入；无真实支城提供者时查询/购买/选择失败且不扣费。
- 真机 Unity 画面、原玩家升级到 4 级的完整游玩流程未在本批验收。内存 smoke 只对隔离测试存档设置等级，不改玩家存档。
- 新入口须本 PR 合并并部署后才在线生效；生产部署状态另附执行记录，不将分支数 331 冒充当前线上数。

已执行的生产更新见 [deployed-pr49.json](deployed-pr49.json)：
服务器已部署合并后的 #49（fbe5168），安装七个原表文件并保留原 import 记录。
当前运行代码尚无这七项表声明，因此它们只完成磁盘预置，本 PR 合并部署后才进入默认目录。
线上仍为 334 个占位。服务端 408 项测试中 405 通过、3 项因可选 IL 依赖缺失跳过；
80 端口 HTTP 基线和上一轮 8 接口联调通过。6 个已有玩家 state_json 哈希前后一致，
其存档均无 trophyClaims 字段；原任务补丁保持不变，代理未重启。
回退备份位于 `/var/backups/onisoul/review49-20261115-fbe5168`。
