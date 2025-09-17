"""Centralised balance configuration for gameplay formulas."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class CostBalance:
    """Parameters that influence stamina and lust consumption."""

    stamina_base: int = 10
    stamina_per_difficulty: int = 4
    stamina_endurance_discount: float = 1.8
    stamina_min: int = 6
    lust_base: int = 8
    lust_per_difficulty: int = 3
    lust_level_discount: float = 1.2
    lust_min: int = 4


@dataclass(frozen=True)
class SuccessBalance:
    """Weights used to compute job success chance."""

    base: float = 0.5
    main_weight: float = 0.09
    sub_weight: float = 0.045
    stamina_midpoint: float = 0.55
    stamina_weight: float = 0.24
    health_midpoint: float = 0.55
    health_weight: float = 0.18
    endurance_weight: float = 0.03
    lust_midpoint: float = 0.6
    lust_weight: float = 0.28
    low_lust_threshold: float = 0.35
    low_lust_penalty: float = 0.38
    difficulty_penalty: float = 0.085
    cap: tuple[float, float] = (0.05, 0.97)


@dataclass(frozen=True)
class RewardBalance:
    """Weights used to compute the payout multiplier and base reward."""

    base_multiplier: float = 1.0
    main_weight: float = 0.06
    sub_weight: float = 0.032
    level_weight: float = 0.024
    endurance_weight: float = 0.045
    stamina_midpoint: float = 0.7
    stamina_weight: float = 0.16
    health_midpoint: float = 0.7
    health_weight: float = 0.12
    lust_midpoint: float = 0.65
    lust_weight: float = 0.3
    high_lust_threshold: float = 0.85
    high_lust_bonus: float = 0.12
    cap: tuple[float, float] = (0.55, 2.1)
    base_main_bonus: int = 12
    base_sub_bonus: int = 9
    base_level_bonus: int = 6


@dataclass(frozen=True)
class InjuryBalance:
    """Weights used to derive injury probability and severity."""

    base: float = 0.1
    difficulty_weight: float = 0.075
    main_weight: float = 0.03
    sub_weight: float = 0.018
    endurance_weight: float = 0.028
    stamina_midpoint: float = 0.6
    stamina_weight: float = 0.11
    health_midpoint: float = 0.65
    health_weight: float = 0.09
    lust_midpoint: float = 0.55
    lust_weight: float = 0.12
    low_lust_threshold: float = 0.3
    low_lust_penalty: float = 0.32
    high_lust_threshold: float = 0.92
    high_lust_penalty: float = 0.34
    cap: tuple[float, float] = (0.04, 0.65)
    injury_min_base: int = 6
    injury_min_difficulty: int = 4
    injury_min_diff_reduction: int = 2
    injury_max_base: int = 18
    injury_max_difficulty: int = 6
    injury_max_diff_reduction: int = 2


@dataclass(frozen=True)
class MarketBalance:
    """Parameters that define the generated job rewards."""

    base_pay: int = 55
    main_step: int = 20
    sub_step: int = 15
    level_step: int = 11
    allure_bonus: int = 16
    comfort_bonus: int = 10
    security_bonus: int = 6
    cleanliness_weight: float = 0.8
    cleanliness_baseline: int = 65
    cleanliness_min_bonus: int = -30
    cleanliness_max_bonus: int = 35
    renown_divisor: int = 5
    min_pay: int = 40
    max_pay: int = 420


@dataclass(frozen=True)
class BalanceProfile:
    """Bundle of all tunable balance parameters."""

    costs: CostBalance = field(default_factory=CostBalance)
    success: SuccessBalance = field(default_factory=SuccessBalance)
    reward: RewardBalance = field(default_factory=RewardBalance)
    injury: InjuryBalance = field(default_factory=InjuryBalance)
    market: MarketBalance = field(default_factory=MarketBalance)


def _coerce_scalar(template: Any, raw: Any) -> Any:
    """Attempt to coerce ``raw`` into the type of ``template``."""

    if isinstance(template, float):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return template
    if isinstance(template, int) and not isinstance(template, bool):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return template
    if isinstance(template, tuple) and len(template) == 2:
        if isinstance(raw, Sequence) and len(raw) == 2:
            first = _coerce_scalar(template[0], raw[0])
            second = _coerce_scalar(template[1], raw[1])
            return (first, second)
        return template
    return raw


def _merge_dataclass(instance: Any, overrides: Mapping[str, Any]) -> Any:
    if not is_dataclass(instance) or not isinstance(overrides, Mapping):
        return instance

    updates: dict[str, Any] = {}
    for field_info in fields(instance):
        name = field_info.name
        if name not in overrides:
            continue
        current_value = getattr(instance, name)
        override_value = overrides[name]
        if is_dataclass(current_value):
            updates[name] = _merge_dataclass(current_value, override_value)
        else:
            updates[name] = _coerce_scalar(current_value, override_value)
    if not updates:
        return instance
    return replace(instance, **updates)


def load_balance_profile(raw: Mapping[str, Any] | None) -> BalanceProfile:
    """Return a :class:`BalanceProfile` with optional overrides applied."""

    profile = BalanceProfile()
    if not isinstance(raw, Mapping):
        return profile
    return _merge_dataclass(profile, raw)

