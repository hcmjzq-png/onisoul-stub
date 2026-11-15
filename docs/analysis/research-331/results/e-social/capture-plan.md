# E 原客户端串行验收清单

本任务不启动 Unity。由汇总对话独占原客户端，维持原始游戏尺寸；若开监控面板，与游戏等大对齐。
本机与局域网分别记录，按 **客户端 → hosts → proxy80 → stub** 确认请求身份及回包。
只用两个隔离已创建角色；原 avatar、defines/playerLevel、地图和相关网页资源须先可加载。

1. A 发送申请，B 看 receive、接受；重登双方，核对 getFriends 裸映射、count和friendOffer。分别记录失败前乐观计数和失败后恢复。
2. 新申请依次做拒绝/取消；在 A 旧确认窗口打开期间由 B 改关系，查看 updateFriendData.remove。刷新列表/重新打开profile后重新申请，观察本服通知确认策略是否阻塞按钮。此实测只验证兼容性，不证明原服删除原因。
3. 在隔离服可控时钟下测期限前一秒、恰好604800秒；必须同时核对两份存档、remove和badge。原服期限单位/清理时点还需历史原回包，模拟服时钟实验不算原服规则证据。
4. 管理员为A发行一包小量四资源，保留发行ID；B不能查询/领取。A打开原reward页、领取、重发同请求、重登，再以同发行ID重试。核对资源仅增一次、pending为0、通知为0；首响应丢失后做getPlayerParams/重登同步。
5. A资源满容量时领取混合资源包，确认整包保留且不部分发奖；同批另一合法包裹可成功。原服务是否这样处理仍需历史证据。
6. 好友/非好友分别访问默认mapId=-1与指定地图；捕获Data2/visit请求先后、friendInfo/status/isFirst、completecount/acceleratecount和后续助产接口。关系不是访问权限，不能以好友测试成功代替非好友分支。
7. 获取原 `bbs/bbs.html`、`mailbox/mailbox.html`、`mail/mail.html`、`reward/reward.html` 及其脚本的可溯源缓存或玩家录像：BBS预览commit=false/提交、作者与非作者操作；邮件status值/读后标记/收发列表/删除单侧性；inbox实际标题、正文和分页。不使用现有AI仿制页面作原证据。

静态缓存中未出现四页正文不等同线上新增4个404；真正文件加载失败标 `stub has no assets`。
未实现业务、坏状态或未确认权限标 `no stub response`，分别保存请求和状态前后摘要，不保存token/账户凭据。
