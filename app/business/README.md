# 业务代码索引

本目录包含已接入服务、共享组件和未接入候选。真实接线以
[app/main.py](../main.py) 与 [GameplayService.register](gameplay.py) 为准。
逐接口当前快照见 [endpoints.tsv](../../docs/project-status/endpoints.tsv)，
功能边界和真机状态见 [系统台账](../../docs/project-status/README.md)。

## 正常请求使用的服务

| 系统 | 模块 | 接入范围 |
| --- | --- | --- |
| 登录、角色、新手、建设 | `gameplay.py` | 目前的主要装配和处理器文件，后续按职责拆分 |
| 玩家库存、资料、普通商店 | `player_services.py` | 查询、保护、资料和限定商品交易 |
| 课题与升级 | `progression.py` | 已支持的确定性奖励、等级和任务门槛 |
| 主城建筑 | `city_services.py` | 移动、收纳、部署、限定升级、铺路和产品查询 |
| 建筑出售 | `city_production_services.py` | 只挂载库存建筑出售；背景/开工组件不是已接入生产 |
| 任务 5 田地生产 | `tutorial_production.py` | 已接入无道路/内政编队的 G1 田地免费配方开工；通过 `gameplay.complete_tasks` 结算受限收获 |
| 武将与装备出售 | `card_growth_services.py` | 只挂载两种出售和魂余额；其他成长/仓库代码是候选 |
| 成就 | `account_progress_trophies.py` | 已证实的受限成就处理 |
| 身份兼容与插件日志 | `account_progress_services.py` | Cogid、插件读取/日志的白名单，不开放全部插件入口 |
| 好友与包裹 | `social_services.py`、`social_inbox_services.py` | 7 个好友、2 个四资源包裹入口 |
| 周期通知 | `periodic.py`、`show_off.py` | 好友申请/待领通知、公告与展示字段；演示广播默认关闭 |
| 未参战兼容状态 | `turf_war.py` | 只返回未参战哨兵，不是战争结算 |
| 权限拒绝 | `admin_debug_services.py` | 32 个管理/调试入口禁用政策 |

## 候选与暂未形成完整玩法的代码

| 系统 | 查找位置 | 接入前主要条件 |
| --- | --- | --- |
| 通用生产和支城背景 | `city_production_services.py`、`city_background_services.py`、`city_production_rules.py` | 任务 5 之外的配方、道路规则、所有权与支城来源；受限教程接入不代表通用生产开放 |
| 物语和战斗 | `adventure_services.py`、`adventure_events.py`、`adventure_obstacle_services.py`、`adventure_battles.py` | 步进身份、权威战斗结果、通关与奖励 |
| 武将成长 | `card_growth_services.py`、`card_growth_transactions.py`、`card_growth_ninegrid.py` | 真实操作身份、资格、消耗与结算规则 |
| 经济和交易 | `economy_services.py`、`economy_shop_services.py`、`economy_trade_services.py`、`economy_market_services.py` | 市场/商品来源、共享事务、锁定与交割 |
| 战争 | `war_campaigns_services.py`、`war_campaigns_commands.py`、`war_campaigns_events.py`、`war_campaigns_views.py` | 活动、权威战况、事务适配和结算 |
| 排行 | `rankings_services.py`、`rankings_aggregation.py`、`rankings_periods.py` | 真实得分事件、周期、水位和快照 |
| 签到与账号活动 | `account_progress_daily.py` 和账号服务中的未挂载项 | 已确认活动、日界线、奖励和权益来源 |

一个模块可以同时包含已接入和候选方法，不能仅凭模块名整体判定完成。
研究证据见 [九组汇总](../../docs/analysis/research-331/review/README.md)；历史补丁不能重新套到当前主分支。

## 共享组件

`registry.py` 负责路由，`contract.py` 读取原版契约，`response_shapes.py` 负责回包形态，
`placeholders.py` 负责剩余默认回包及明确拒绝。
`decks.py`、`mission_chain.py`、`mission_validation.py` 提供编队与任务规则组件。

后续接入优先沿现有会话、状态和事务边界实现，在系统台账中更新支持范围和验收。
候选组件的内部结构是本服实现设计，只有原客户端证据支持的字段才能称为原版协议。
