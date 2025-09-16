"""Utility helpers used across the bot modules."""

from __future__ import annotations

from typing import Any

from .constants import PREF_ICONS


def choice_value(option: Any, default: str | None = None) -> str | None:
    """Extract the raw value from an app command Choice or return the option itself."""

    if option is None:
        return default
    if hasattr(option, "value"):
        value = option.value
    else:
        value = option
    if value is None:
        return default
    value = str(value)
    return value if value else default


def lust_state_label(ratio: float) -> str:
    """Convert a lust ratio (0.0-1.0) into a qualitative label."""

    if ratio >= 0.9:
        return "Overdrive"
    if ratio >= 0.7:
        return "Heated"
    if ratio >= 0.45:
        return "Aroused"
    if ratio >= 0.25:
        return "Warming up"
    return "Dormant"


def lust_state_icon(ratio: float) -> str:
    """Return an emoji representing the lust ratio."""

    if ratio >= 0.9:
        return "💥"
    if ratio >= 0.7:
        return "🔥"
    if ratio >= 0.45:
        return "❤️"
    if ratio >= 0.25:
        return "✨"
    return "❄️"


def preference_icon(preference: str) -> str:
    """Map a preference flag (true/fav/false) to its emoji."""

    return PREF_ICONS.get(str(preference).lower(), PREF_ICONS["true"])
