"""Вспомогательные функции."""

from __future__ import annotations

from typing import Any, Iterable, Optional


def choice_value(choice: Any, default: Optional[str] = None) -> Optional[str]:
    """Безопасно извлечь значение из ``discord.app_commands.Choice``."""

    if choice is None:
        return default
    value = getattr(choice, "value", None)
    if value in (None, ""):
        return default
    return str(value)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def weighted_pick(options: Iterable[tuple[Any, float]]):
    total = sum(weight for _, weight in options)
    if total <= 0:
        raise ValueError("Total weight must be positive")
    import random

    pivot = random.random() * total
    cumulative = 0.0
    for item, weight in options:
        cumulative += weight
        if cumulative >= pivot:
            return item
    return list(options)[-1][0]


__all__ = ["choice_value", "clamp", "weighted_pick"]
