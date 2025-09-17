"""Фасад для доступа к игровому сервису из когов."""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from .game import DataStore, GameService
from .models import Girl, Job, Market, Player

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
    "iter_user_ids",
    "brothel_leaderboard",
    "girl_leaderboard",
]

_STORE = DataStore()
_SERVICE = GameService(_STORE)


def get_service() -> GameService:
    return _SERVICE


def get_config() -> dict:
    return _SERVICE.config


def load_player(uid: int) -> Optional[Player]:
    return _SERVICE.load_player(uid)


def save_player(player: Player) -> None:
    _SERVICE.save_player(player)


def grant_starter_pack(uid: int) -> Player:
    return _SERVICE.grant_starter_pack(uid)


def roll_gacha(uid: int, times: int = 1) -> Tuple[list[Girl], int]:
    return _SERVICE.roll_gacha(uid, times)


def generate_market(uid: int, forced_level: int | None = None) -> Market:
    return _SERVICE.generate_market(uid, forced_level)


def load_market(uid: int) -> Optional[Market]:
    return _SERVICE.load_market(uid)


def save_market(market: Market) -> None:
    _SERVICE.save_market(market)


def refresh_market_if_stale(uid: int, max_age_sec: int = 0) -> Market:
    return _SERVICE.refresh_market_if_stale(uid, max_age_sec)


def resolve_job(player: Player, job: Job, girl: Girl) -> dict:
    return _SERVICE.resolve_job(player, job, girl)


def evaluate_job(girl: Girl, job: Job, brothel: Optional[object] = None) -> dict:
    return _SERVICE.evaluate_job(girl, job, brothel)  # type: ignore[arg-type]


def iter_user_ids() -> Iterable[int]:
    return _STORE.iter_user_ids()


def brothel_leaderboard(limit: int = 10) -> list[dict]:
    return _SERVICE.gather_brothel_top(limit)


def girl_leaderboard(limit: int = 10) -> list[dict]:
    return _SERVICE.gather_girl_top(limit)

