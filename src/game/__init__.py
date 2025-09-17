"""Пакет игровых сервисов.

Объединяет репозиторий данных и игровую логику для удобства импорта.
"""
from .repository import DataStore
from .services import GameService

__all__ = ["DataStore", "GameService"]
