# G 串行客户端验收计划

由总集成独占一个原始 Unity3.5.7 客户端执行；本组不启动客户端、不部署。
本机与局域网分别记录客户端→hosts→proxy80→stub 链路；保持游戏原尺寸，监控面板与游戏等大对齐。
只使用隔离新服/测试账号及完整原表，不能在生产玩家上验证回滚或切期。

1. 无内政武将主城：建原田地、升级、入库、再部署。捕获城市写响应 kokudaka、原请求 buildingId/level、
   玩家存档、账本 operationId/sequence/source；核对 10、13、0、13 与显示一致。加入武将/支城应明确拒绝，
   不静默掉建筑后产生错误榜单。这只能验本服兼容性，不能反证原服公式。
2. 同国双账号、异国一账号：捕获 getRankersInKokudaka 和 getBriefOfKokudaka；检查页内键、页外本人、同分、
   0 分已参与与未参与。由服务端显式切期，验证 current/last 不混用；连续请求可跨期应记录为协议限制。
3. 仅当 I 的可信重试身份和 common 对话框前置状态完成后，金币 1000/2000、上限边界、余额不足、同额新操作、
   同操作重发/丢回包。捕获 article、gainPoint、dedication、myRank、bonus、余额、每国累计和账本收据。
   原回调会扣金并增 gainPoint，因此成功只可回调一次；重试失败后重登权威回读验证。
4. 显式不同普通/月期计划：capture getRankersInDedication/getMonthlyRankersInDedication 的 current/last；
   月期累计可跨两个普通期，不能把两榜绑成一张缓存。检查上期缺失 errorReason 与已知空榜不同。
5. D 商店：锁住同一国力/period，上下阈值、跨期购买；捕获 state/remain 及真实金币事件。
   F 开战争后限定 provider 应关闭，不继续把献纳总和称为完整国力。

外部待证实验：找到可读取的台服同期维护公告、原服务端封榜抓包/历史存档、同分不同提交时刻的实际排名、
物品献纳倍率和国力城战前后变化；区分提交早晚/ID 排序、当前值/最高值、月初/最后维护等假设。
仅模拟服录屏/回包无法确认这些原服规则。404 文件单记 stub has no assets；业务失败单记 no stub response。
