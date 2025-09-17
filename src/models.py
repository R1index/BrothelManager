"""Доменные модели и базовые формулы проекта BrothelManager.

Файл реализует чистые dataclass-модели без внешних зависимостей. Они
воспроизводят ключевую механику оригинального проекта, но написаны с
учётом предсказуемости и простоты тестирования. Большинство методов
возвращают словари с изменениями, что позволяет выстраивать высокоуровневые
ответы в когах без повторных вычислений.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Tuple
import math
import time

# ---------------------------------------------------------------------------
# Константы и служебные функции
# ---------------------------------------------------------------------------

MAIN_SKILLS: Tuple[str, ...] = ("Human", "Beast", "Monster", "Insect")
SUB_SKILLS: Tuple[str, ...] = (
    "VAGINAL",
    "ANAL",
    "ORAL",
    "GROUP",
    "BREAST",
    "HAND",
    "FOOT",
    "TOY",
)

PROMOTE_COINS_PER_RENOWN = 5

# Формулы роста подобраны так, чтобы демонстрировать в тестах
# сублинейное увеличение стоимости и при этом оставаться простыми.

def now_ts() -> int:
    return int(time.time())


def skill_xp_threshold(level: int) -> int:
    return 40 + int(level * 12 + level ** 1.1)


def facility_xp_threshold(level: int) -> int:
    return 80 + int(level * 25 + level ** 1.05 * 15)


def make_bar(current: int, need: int, length: int = 12) -> str:
    if need <= 0:
        return "■" * length
    filled = min(length, max(0, current) * length // max(1, need))
    return "■" * filled + "□" * (length - filled)


def _ensure_skill_map(names: Iterable[str], raw: Optional[dict]) -> dict:
    data: dict = {}
    raw = raw or {}
    for name in names:
        node = raw.get(name) or {}
        if isinstance(node, int):
            lvl, xp = int(node), 0
        else:
            lvl = int(node.get("level", 0))
            xp = int(node.get("xp", node.get("exp", 0)))
        data[name] = {"level": max(0, lvl), "xp": max(0, xp)}
    return data


def _add_skill_xp(skills: dict, name: str, amount: float) -> Tuple[int, int]:
    node = skills.setdefault(name, {"level": 0, "xp": 0})
    node["xp"] += int(round(amount))
    while node["xp"] >= skill_xp_threshold(node["level"]):
        node["xp"] -= skill_xp_threshold(node["level"])
        node["level"] += 1
    return node["level"], node["xp"]


# ---------------------------------------------------------------------------
# Модели девушек
# ---------------------------------------------------------------------------

@dataclass
class Girl:
    uid: str
    base_id: str
    name: str
    rarity: str

    level: int = 1
    exp: int = 0
    health: int = 100
    health_max: int = 100
    stamina: int = 100
    stamina_max: int = 100
    lust: int = 80
    lust_max: int = 100
    stamina_last_ts: int = field(default_factory=now_ts)
    lust_last_ts: int = field(default_factory=now_ts)
    vitality_level: int = 1
    vitality_xp: int = 0
    endurance_level: int = 1
    endurance_xp: int = 0
    lust_level: int = 1
    lust_xp: int = 0

    skills: dict = field(default_factory=dict)
    subskills: dict = field(default_factory=dict)

    mentorship_bonus: float = 0.0
    mentorship_focus_type: Optional[str] = None
    mentorship_focus: Optional[str] = None
    mentorship_source: Optional[str] = None

    def __post_init__(self) -> None:
        self.skills = _ensure_skill_map(MAIN_SKILLS, self.skills)
        self.subskills = _ensure_skill_map(SUB_SKILLS, self.subskills)
        self.health = int(self.health)
        self.health_max = int(self.health_max)
        self.stamina = int(self.stamina)
        self.stamina_max = int(self.stamina_max)
        self.lust = int(self.lust)
        self.lust_max = int(self.lust_max)

    # ------------------------- XP и тренировки -------------------------
    def add_main_xp(self, name: str, amount: float) -> Tuple[int, int]:
        return _add_skill_xp(self.skills, name, amount)

    def add_sub_xp(self, name: str, amount: float) -> Tuple[int, int]:
        return _add_skill_xp(self.subskills, name, amount)

    def grant_training_bonus(
        self,
        source: str,
        bonus: float,
        focus_type: Optional[str],
        focus: Optional[str],
    ) -> None:
        self.mentorship_source = source
        self.mentorship_bonus = max(0.0, float(bonus))
        self.mentorship_focus_type = focus_type
        self.mentorship_focus = focus

    def clear_training_bonus(self) -> None:
        self.mentorship_source = None
        self.mentorship_bonus = 0.0
        self.mentorship_focus_type = None
        self.mentorship_focus = None

    # ------------------------- Утилиты -------------------------
    def get_skill_level(self, name: str) -> int:
        return int(self.skills.get(name, {}).get("level", 0))

    def get_subskill_level(self, name: str) -> int:
        return int(self.subskills.get(name, {}).get("level", 0))


# ---------------------------------------------------------------------------
# Тренировки и состояние борделя
# ---------------------------------------------------------------------------

@dataclass
class TrainingAssignment:
    mentor_uid: str
    student_uid: str
    since_ts: int
    focus_type: Optional[str]
    focus: Optional[str]


@dataclass
class BrothelState:
    rooms: int = 3
    renown: int = 15
    morale: float = 70.0
    cleanliness: float = 85.0
    comfort_level: int = 1
    hygiene_level: int = 1
    security_level: int = 1
    allure_level: int = 1
    upkeep_pool: int = 0
    last_tick_ts: int = field(default_factory=now_ts)
    _decay_residual: float = field(default=0.0, init=False, repr=False)
    training: List[TrainingAssignment] = field(default_factory=list)

    def facility_level(self, name: str) -> int:
        return int(
            {
                "comfort": self.comfort_level,
                "hygiene": self.hygiene_level,
                "security": self.security_level,
                "allure": self.allure_level,
            }.get(name, 0)
        )

    # ------------------------- Экономика -------------------------
    def promote(self, coins: int) -> dict:
        gained = max(0, coins) // PROMOTE_COINS_PER_RENOWN
        if gained:
            self.renown += gained
        return {"renown": gained}

    def maintain(self, coins: int) -> dict:
        coins = max(0, coins)
        self.upkeep_pool += coins
        effective = self.upkeep_pool * (0.04 + self.hygiene_level * 0.015)
        clean_before = self.cleanliness
        morale_before = self.morale
        cleanliness_gain = min(100.0 - self.cleanliness, effective)
        morale_gain = min(100.0 - self.morale, cleanliness_gain * (0.35 + self.hygiene_level * 0.02))
        self.cleanliness += cleanliness_gain
        self.morale += morale_gain
        # удерживаем часть средств как остаток для будущих процедур
        self.upkeep_pool = int(self.upkeep_pool * 0.25)
        return {
            "cleanliness": cleanliness_gain,
            "morale": morale_gain,
            "cleanliness_before": clean_before,
            "morale_before": morale_before,
        }

    def register_job_outcome(self, success: bool, injured: bool, job: "Job", reward: int) -> dict:
        hygiene_mod = max(0.25, 1.0 - self.hygiene_level * 0.08)
        base_loss = 4.0 + job.difficulty * 2.5
        if injured:
            base_loss += 4.0
        if not success:
            base_loss *= 1.4
        cleanliness_loss = base_loss * hygiene_mod
        clean_before = self.cleanliness
        morale_before = self.morale
        self.cleanliness = max(0.0, self.cleanliness - cleanliness_loss)
        morale_delta = reward / 200 if success else -2.0
        morale_delta += -cleanliness_loss * 0.05
        self.morale = max(0.0, min(100.0, self.morale + morale_delta))
        return {
            "cleanliness": -cleanliness_loss,
            "morale": self.morale - morale_before,
            "cleanliness_before": clean_before,
            "morale_before": morale_before,
        }

    # ------------------------- Деградация -------------------------
    def apply_decay(self) -> None:
        now = now_ts()
        elapsed = max(0, now - self.last_tick_ts)
        ticks = elapsed / 900
        ticks += self._decay_residual
        whole = int(ticks)
        self._decay_residual = ticks - whole
        if whole <= 0:
            return
        hygiene_mod = max(0.25, 1.0 - self.hygiene_level * 0.08)
        cleanliness_loss = whole * 2.2 * hygiene_mod
        self.cleanliness = max(0.0, self.cleanliness - cleanliness_loss)
        morale_loss = whole * max(0.0, (50 - self.cleanliness) * 0.02) * (0.6 + hygiene_mod)
        self.morale = max(0.0, self.morale - morale_loss)
        renown_loss = whole * max(0.0, (40 - self.cleanliness) * 0.01) * (0.8 + hygiene_mod * 0.5)
        if renown_loss:
            self.renown = max(0, int(round(self.renown - renown_loss)))
        self.last_tick_ts = now - int(self._decay_residual * 900)

    # ------------------------- Тренировки -------------------------
    def start_training(
        self,
        mentor_uid: str,
        student_uid: str,
        *,
        focus_type: Optional[str],
        focus: Optional[str],
    ) -> TrainingAssignment:
        assignment = TrainingAssignment(
            mentor_uid=mentor_uid,
            student_uid=student_uid,
            since_ts=now_ts(),
            focus_type=focus_type,
            focus=focus,
        )
        self.training.append(assignment)
        return assignment

    def stop_training(self, student_uid: str) -> None:
        self.training = [t for t in self.training if t.student_uid != student_uid]

    def training_for(self, student_uid: Optional[str]) -> Optional[TrainingAssignment]:
        if student_uid is None:
            return None
        for t in self.training:
            if t.student_uid == student_uid:
                return t
        return None


# ---------------------------------------------------------------------------
# Игрок и рынок
# ---------------------------------------------------------------------------

@dataclass
class Player:
    user_id: int
    currency: int = 0
    renown: int = 15
    girls: List[Girl] = field(default_factory=list)
    brothel: Optional[BrothelState] = None

    def ensure_brothel(self) -> BrothelState:
        if self.brothel is None:
            self.brothel = BrothelState(renown=self.renown)
        else:
            self.renown = int(self.brothel.renown)
        return self.brothel

    def get_girl(self, uid: str) -> Optional[Girl]:
        for girl in self.girls:
            if girl.uid == uid:
                return girl
        return None

    def add_girl(self, girl: Girl) -> None:
        if self.get_girl(girl.uid) is None:
            self.girls.append(girl)

    @property
    def rooms_used(self) -> int:
        return len(self.girls)

    @property
    def rooms_available(self) -> int:
        brothel = self.ensure_brothel()
        return max(0, brothel.rooms - len(self.girls))


@dataclass
class Job:
    job_id: str
    demand_main: str
    demand_level: int
    demand_sub: str
    demand_sub_level: int
    pay: int
    difficulty: int


@dataclass
class Market:
    user_id: int
    jobs: List[Job]
    level: int = 1
    expires_ts: int = field(default_factory=lambda: now_ts() + 3 * 3600)


__all__ = [
    "BrothelState",
    "Girl",
    "Job",
    "Market",
    "Player",
    "TrainingAssignment",
    "PROMOTE_COINS_PER_RENOWN",
    "facility_xp_threshold",
    "make_bar",
    "now_ts",
    "skill_xp_threshold",
]
