"""OniSoul Stub 服务端包。

分层：
    transport  HTTP 接入与请求分发
    protocol   请求信封解析、统一响应与错误码
    sessions   账号 / 登录会话（MySQL）
    state      玩家状态存取（MySQL，整行 JSON）
    business   接口业务规则（按 dump / 抓包逐步补齐）
"""
