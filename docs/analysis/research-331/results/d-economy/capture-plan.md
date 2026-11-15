# D 串行验收计划（由总集成操作客户端）

本组没有启动共享 Unity、改 hosts/proxy80/config.ini，也没有部署或写生产玩家。
本机与局域网分别沿 **客户端 → hosts → proxy80 → stub** 确认地址和日志；本组不改配置。
错误分别记录：缺文件/加载失败 `stub has no assets`；规则、状态或表引用不完整 `no stub response`。
UI 保持游戏原尺寸，监控面板等大对齐。

## 旅交易

前提：隔离账号，主城原城建筑、真实内政编队、至少 10 PP/2000 gold，能取得权威结果选择依据。
未接 planner 时测试应明确失败且零扣费，不能以临时固定结果代替成功验收。

1. 开主城菜单；捕获 `getStatus3` 的 map、politicDeck、totalIntelligence、各槽 int/intAdd、技能效果。
2. 发街道 `send3`，核对请求 mapId/buildingId/errantryId 与返回 dueTime/buildingId 数值类型；
   同时核对存档只扣一次 10 PP/2000 gold，不回放成功让客户端重复减费。
3. 中途登出再登录，状态与 dueTime 保持；到期前 receive3 失败，到期后只领取一次。
   捕获 catalog、errantryId、每个 results 槽的 resultId/reward、紫魂与技宝珠持有量、errantryTimes。
4. 用同一部队重复原服录屏/历史抓包样本（若可得），比较单卡智略、bias 和结果阈值，
   区分“全部合资格行均匀抽样”“阈值定位”“随机偏移后定位”；几次成功不能证明概率。
5. 取消只在有真实原服资料时核实退款和次数；不要在本服伪造取消成功。
   有国政额外奖励/容量满时另抓实际奖励和收件箱，不能从表的 ratioMax 直接造奖励。

## 拍卖

前提：两个隔离账号已有可信 credit 余额及资源，I 原子适配器、明确费率/门槛配置、稳定请求身份。
支付入账不在 D；不得为了测试充值生产账号。

1. 捕获 ResourceSale/CardSale 的 params 税系数及 prefab 上架槽数量/levelLimit。
2. 以已知数量分别选择 8/12/24 小时，核对金钱扣费、挂牌 ID、槽位、资源托管；600 秒是否 UI 可达。
3. 另一账号搜索并购买，核对 result/resources、卖家收款渠道与实际净额、双方邮箱满时行为。
4. 同时买/撤回及超时重试，仅一次成功；I 故障注入最后一次写失败时所有账户/市场/收据回滚。
5. 到期前和到期瞬间购买边界、过期仍占卖家槽、领取后库存恢复；历史公告不是税率证明。
6. 武将 G1/G2、保护/编队/仓库/锁卡/角色等级边界独立测试，不能把资源组件当武将完成。

## 国家商城 / 国技

G 提供真实 country/period/power 记录及周期切换操作，再验证门槛前后、限购一次、换国不重置、
跨周期并发一致性。国技抓 selfPoint/levelRate/kokugiPoint、develop usedPoint/point 及献纳源事务。
未知周期不默认开放，未知倍率不置 1，后台 addPoint 不开放给普通请求。
