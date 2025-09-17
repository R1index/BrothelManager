"""Утилиты поиска локальных ассетов.

Модуль хранит глобальную настройку каталога с ассетами и предоставляет
несколько функций для поиска изображений профиля/действий. Логика сведена
к простому перебору распространённых имён файлов, чтобы обеспечить
детерминированное и быстрое поведение в тестах и при запуске бота.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

__all__ = [
    "set_assets_dir",
    "get_assets_dir",
    "profile_image_path",
    "action_image_path",
    "pregnant_profile_image_path",
]

_DEFAULT_SUBDIR = Path("assets") / "girls"
_ASSETS_DIR: Optional[Path] = None


def _resolve_base_dir() -> Path:
    """Определяет каталог ассетов с учётом переопределений."""

    global _ASSETS_DIR
    if _ASSETS_DIR is not None:
        return _ASSETS_DIR

    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / _DEFAULT_SUBDIR


def set_assets_dir(path: Optional[Path | str]) -> None:
    """Устанавливает новый базовый каталог для ассетов.

    ``None`` сбрасывает переопределение и возвращает использование значения
    по умолчанию, что удобно для тестов.
    """

    global _ASSETS_DIR
    if path is None:
        _ASSETS_DIR = None
    else:
        _ASSETS_DIR = Path(path)


def get_assets_dir() -> Path:
    """Возвращает каталог ассетов с учётом переопределений."""

    base = _resolve_base_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _slugify(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")


def _candidate_names(slug: str, kind: str) -> Iterable[str]:
    yield f"{slug}_{kind}.png"
    yield f"{slug}_{kind}.jpg"
    yield f"{slug}_{kind}.jpeg"
    yield f"{slug}_{kind}.webp"
    if kind != "profile":
        yield from _candidate_names(slug, "profile")
    yield f"{slug}.png"
    yield f"{slug}.jpg"
    yield f"{slug}.jpeg"
    yield f"{slug}.webp"
    yield f"{kind}.png"
    yield f"{kind}.jpg"


def _find_asset(name: str, kind: str) -> str:
    base = get_assets_dir()
    slug = _slugify(name or "") or "unknown"
    folder = base / slug
    if folder.is_dir():
        for candidate in _candidate_names(slug, kind):
            path = folder / candidate
            if path.is_file():
                return str(path)
    return ""


def profile_image_path(name: str) -> str:
    return _find_asset(name, "profile")


def action_image_path(name: str) -> str:
    return _find_asset(name, "action")


def pregnant_profile_image_path(name: str) -> str:
    return _find_asset(name, "pregnant")
