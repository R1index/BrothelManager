"""Утилиты поиска ассетов для девушек.

Модуль предоставляет простой интерфейс для выбора изображений профиля и
действий. Каталог с ассетами можно переопределить через
:func:`set_assets_dir` — это используется сервисом при чтении конфигурации.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

__all__ = [
    "set_assets_dir",
    "get_assets_dir",
    "profile_image_path",
    "action_image_path",
    "pregnant_profile_image_path",
]


@dataclass(slots=True)
class _AssetLookup:
    """Контейнер с данными для поиска файлов."""

    base_dir: Path

    def resolve(self, name: str, patterns: Iterable[str]) -> Optional[Path]:
        """Вернуть первый существующий файл из ``patterns`` для указанного ``name``."""

        stem = _slugify(name)
        for pattern in patterns:
            candidate = self.base_dir / pattern.format(name=stem)
            if candidate.exists():
                return candidate
        return None


_assets_lookup: Optional[_AssetLookup] = None


def set_assets_dir(path: Optional[Path | str]) -> None:
    """Настроить базовую директорию ассетов.

    ``None`` сбрасывает директорию в значение по умолчанию (``assets/girls``
    относительно корня проекта). Указывать можно как ``Path``, так и строку.
    """

    global _assets_lookup

    if path is None:
        base = Path.cwd() / "assets" / "girls"
    else:
        base = Path(path)
    _assets_lookup = _AssetLookup(base_dir=base)


def get_assets_dir() -> Optional[Path]:
    """Вернуть активный каталог ассетов (или ``None``, если не сконфигурирован)."""

    return _assets_lookup.base_dir if _assets_lookup else None


def profile_image_path(name: str) -> str:
    """Найти изображение профиля девушки."""

    path = _find(name, ("{name}/{name}_profile.png", "{name}/{name}.png"))
    return str(path) if path else ""


def action_image_path(name: str) -> str:
    """Найти изображение действия (используется в результатах заданий)."""

    path = _find(name, ("{name}/{name}_action.png", "{name}/{name}_work.png"))
    return str(path) if path else ""


def pregnant_profile_image_path(name: str) -> str:
    """Вернуть альтернативный портрет для беременной версии персонажа."""

    path = _find(name, ("{name}/{name}_pregnant.png",))
    return str(path) if path else ""


def _find(name: str, patterns: Iterable[str]) -> Optional[Path]:
    lookup = _assets_lookup
    if not lookup:
        return None
    return lookup.resolve(name, patterns)


def _slugify(name: str) -> str:
    return "".join(ch for ch in name.lower().replace(" ", "_") if ch.isalnum() or ch in {"_", "-"})


# Инициализируем директорию по умолчанию при импортировании модуля.
set_assets_dir(None)
