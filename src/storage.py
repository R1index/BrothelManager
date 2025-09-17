"""Глобальный доступ к игровому сервису."""

from __future__ import annotations

from typing import Optional

from .game import DataStore, GameService
from .models import Girl, Job, Market, Player

_store = DataStore()
_service = GameService(_store)


def get_service() -> GameService:
    return _service


def get_config() -> dict:
    return _service.config


def load_player(user_id: int) -> Optional[Player]:
    return _service.load_player(user_id)


def save_player(player: Player) -> None:
    _service.save_player(player)


def grant_starter_pack(user_id: int) -> Player:
    return _service.grant_starter_pack(user_id)


def roll_gacha(user_id: int, *, times: int = 1):
    return _service.roll_gacha(user_id, times=times)


def generate_market(user_id: int, *, forced_level: Optional[int] = None) -> Market:
    return _service.generate_market(user_id, forced_level=forced_level)


def refresh_market_if_stale(user_id: int, *, max_age_sec: int = 600) -> Market:
    return _service.refresh_market_if_stale(user_id, max_age_sec=max_age_sec)


def load_market(user_id: int) -> Optional[Market]:
    return _service.load_market(user_id)


def save_market(market: Market) -> None:
    _service.save_market(market)


def resolve_job(player: Player, job: Job, girl: Girl):
    return _service.resolve_job(player, job, girl)


def evaluate_job(girl: Girl, job: Job, brothel=None):
    return _service.evaluate_job(girl, job, brothel)


def dismantle_girl(player: Player, uid: str) -> None:
    player.remove_girl(uid)
    save_player(player)


def iter_user_ids():
    return _store.iter_user_ids()


def brothel_leaderboard(limit: int = 10):
    return _service.gather_brothel_top(limit)


def girl_leaderboard(limit: int = 10):
    return _service.gather_girl_top(limit)


__all__ = [
    "get_service",
    "get_config",
    "load_player",
    "save_player",
    "grant_starter_pack",
    "roll_gacha",
    "generate_market",
    "refresh_market_if_stale",
    "load_market",
    "save_market",
    "resolve_job",
    "evaluate_job",
    "dismantle_girl",
    "iter_user_ids",
    "brothel_leaderboard",
    "girl_leaderboard",
]
