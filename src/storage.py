"""Compatibility wrappers around the refactored game services."""

from __future__ import annotations

from .game.repository import DataStore
from .game.services import GameService


_DATA_STORE = DataStore()
_SERVICE = GameService(_DATA_STORE)

# Expose directories for legacy callers (e.g. market refresher task)
BASE_DIR = str(_DATA_STORE.base_dir)
DATA_DIR = str(_DATA_STORE.data_dir)
USERS_DIR = str(_DATA_STORE.users_dir)
MARKET_DIR = str(_DATA_STORE.market_dir)
CATALOG = str(_DATA_STORE.catalog_path)


# ---------------------------------------------------------------------------
# Player helpers
# ---------------------------------------------------------------------------

def load_player(uid: int):
    return _SERVICE.load_player(uid)


def save_player(player):
    _SERVICE.save_player(player)


def grant_starter_pack(uid: int):
    return _SERVICE.grant_starter_pack(uid)


def roll_gacha(uid: int, times: int = 1):
    return _SERVICE.roll_gacha(uid, times)


# ---------------------------------------------------------------------------
# Market helpers
# ---------------------------------------------------------------------------

def load_market(uid: int):
    return _SERVICE.load_market(uid)


def save_market(market):
    _SERVICE.save_market(market)


def generate_market(uid: int, jobs_count: int = 5, forced_level: int | None = None):
    return _SERVICE.generate_market(uid, jobs_count=jobs_count, forced_level=forced_level)


def refresh_market_if_stale(uid: int, max_age_sec: int = 300, forced_level: int | None = None):
    return _SERVICE.refresh_market_if_stale(uid, max_age_sec=max_age_sec, forced_level=forced_level)


# ---------------------------------------------------------------------------
# Job resolution / evaluation
# ---------------------------------------------------------------------------

def evaluate_job(girl, job, brothel=None):
    return _SERVICE.evaluate_job(girl, job, brothel)


def resolve_job(player, job, girl):
    return _SERVICE.resolve_job(player, job, girl)


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def dismantle_girl(player, girl_uid: str):
    return _SERVICE.dismantle_girl(player, girl_uid)


def load_catalog():
    return _DATA_STORE.load_catalog()


def iter_user_ids():
    return _SERVICE.iter_user_ids()
