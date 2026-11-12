"""玩家状态层（MySQL，整行 JSON 存储）。"""
from app.state.player import DEFAULT_PLAYER_ID, load, save

__all__ = ["load", "save", "DEFAULT_PLAYER_ID"]
