"""Пакет с игровыми сервисами."""

from .repository import DataStore
from .services import GameService

__all__ = ["DataStore", "GameService"]
