"""Game services and presentation helpers for the Brothel Manager bot."""

from importlib import import_module
from typing import Any

from .repository import DataStore
from .services import GameService

__all__ = [
    "DataStore",
    "GameService",
    "constants",
    "utils",
    "embeds",
    "views",
]


_LAZY_MODULES = {"constants", "utils", "embeds", "views"}


def __getattr__(name: str) -> Any:
    if name in _LAZY_MODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY_MODULES)
