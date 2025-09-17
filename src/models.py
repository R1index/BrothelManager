"""Доменные модели и вспомогательные функции бота.

Файл реализует базовые структуры данных без зависимости от Discord. Для
управления состоянием используется набор dataclass-объектов, которые умеют
сериализоваться в словари и обратно. Такой подход заметно упрощает хранение
данных и тестирование бизнес-логики.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
import math
import time

# ---------------------------------------------------------------------------
# Константы навыков и предпочтений
# ---------------------------------------------------------------------------

MAIN_SKILLS: List[str] = ["Human", "Insect", "Beast", "Monster"]
SUB_SKILLS: List[str] = [
    "VAGINAL",
    "ANAL",
    "ORAL",
    "BREAST",
    "HAND",
    "FOOT",
    "TOY",
]

BROTHEL_FACILITY_NAMES: Tuple[str, ...] = ("comfort", "hygiene", "security", "allure")

RARITY_WEIGHTS = {"R": 70, "SR": 20, "SSR": 9, "UR": 1}
RARITY_COLORS = {"R": 0x9FA6B2, "SR": 0x60A5FA, "SSR": 0xF59E0B, "UR": 0x8B5CF6}

PROMOTE_COINS_PER_RENOWN = 5

PREF_OPEN = "true"
PREF_BLOCKED = "false"
PREF_FAV = "fav"

PREGNANCY_TICK_SECONDS = 600
PREGNANCY_TOTAL_POINTS = 30


# ---------------------------------------------------------------------------
# Общие утилиты
# ---------------------------------------------------------------------------

def now_ts() -> int:
    """Текущее время в секундах (инт)."""

    return int(time.time())


def regen_resource(
    current: int,
    last_ts: int,
    maximum: int,
    *,
    per_tick: float,
    tick_seconds: int = 600,
) -> Tuple[int, int]:
    """Дискретное восстановление ресурса.

    Функция возвращает пару ``(новое значение, обновлённый timestamp)``.
    ``per_tick`` может быть дробным — остаток переносится между вызовами.
    """

    current = min(current, maximum)
    if current >= maximum:
        return maximum, now_ts()

    elapsed = max(0, now_ts() - last_ts)
    ticks = elapsed // tick_seconds
    if ticks <= 0:
        return current, last_ts

    restored = per_tick * ticks
    new_value = min(maximum, int(current + restored))
    new_ts = last_ts + ticks * tick_seconds
    return new_value, new_ts


# ---------------------------------------------------------------------------
# XP и уровни
# ---------------------------------------------------------------------------

def level_xp_threshold(level: int) -> int:
    return 100 + int(level * 25 + math.pow(level, 1.15))


def skill_xp_threshold(level: int) -> int:
    return 40 + int(level * 12 + math.pow(level, 1.10))


def stat_xp_threshold(level: int) -> int:
    return 30 + int(level * 8 + math.pow(level, 1.08))


def facility_xp_threshold(level: int) -> int:
    return 80 + int(level * 25 + math.pow(level, 1.05) * 15)


def make_bar(current: int, need: int, length: int = 12) -> str:
    if need <= 0:
        return "■" * length
    filled = max(0, min(length, (current * length) // need))
    return "■" * filled + "□" * (length - filled)


# ---------------------------------------------------------------------------
# Навыки и предпочтения
# ---------------------------------------------------------------------------

def normalize_skill_map(raw: Dict[str, Any] | None, *, names: Iterable[str]) -> Dict[str, Dict[str, int]]:
    """Привести карту навыков к каноническому виду ``{"level": int, "xp": int}``."""

    normalized: Dict[str, Dict[str, int]] = {}
    for name in names:
        node = (raw or {}).get(name, 0)
        if isinstance(node, dict):
            level = int(node.get("level", 0))
            xp = int(node.get("xp", node.get("exp", 0)))
        else:
            level = int(node)
            xp = 0
        normalized[name] = {"level": max(0, level), "xp": max(0, xp)}
    return normalized


def add_skill_xp(skills: Dict[str, Dict[str, int]], name: str, amount: float) -> Tuple[int, int]:
    node = skills.setdefault(name, {"level": 0, "xp": 0})
    node["xp"] = max(0, node.get("xp", 0)) + int(amount)
    while node["level"] < 9999 and node["xp"] >= skill_xp_threshold(node["level"]):
        node["xp"] -= skill_xp_threshold(node["level"])
        node["level"] += 1
        if node["level"] >= 9999:
            node["xp"] = 0
    return node["level"], node["xp"]


def get_level(skills: Dict[str, Dict[str, int]], name: str) -> int:
    return int((skills.get(name) or {}).get("level", 0))


def get_xp(skills: Dict[str, Dict[str, int]], name: str) -> int:
    node = skills.get(name) or {}
    return int(node.get("xp", node.get("exp", 0)))


def normalize_prefs(raw: Dict[str, str] | None, names: Iterable[str]) -> Dict[str, str]:
    prefs: Dict[str, str] = {}
    for name in names:
        value = str((raw or {}).get(name, PREF_OPEN)).lower()
        if value not in {PREF_OPEN, PREF_BLOCKED, PREF_FAV}:
            value = PREF_OPEN
        prefs[name] = value
    return prefs


def is_blocked(prefs: Dict[str, str], name: str) -> bool:
    return prefs.get(name, PREF_OPEN) == PREF_BLOCKED


def xp_multiplier_for_pref(prefs: Dict[str, str], name: str) -> float:
    return 1.5 if prefs.get(name, PREF_OPEN) == PREF_FAV else 1.0


# ---------------------------------------------------------------------------
# Дополнительные утилиты прогрессии
# ---------------------------------------------------------------------------

def market_level_from_rep(rep: int) -> int:
    """Определить уровень рынка на основе славы игрока."""

    if rep < 0:
        return 1
    return max(1, min(10, rep // 20 + 1))


# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TrainingAssignment:
    mentor_uid: str
    student_uid: str
    since_ts: int
    focus_type: Optional[str] = None
    focus: Optional[str] = None

    def duration(self) -> int:
        return max(0, now_ts() - self.since_ts)

    def to_dict(self) -> dict:
        return {
            "mentor_uid": self.mentor_uid,
            "student_uid": self.student_uid,
            "since_ts": self.since_ts,
            "focus_type": self.focus_type,
            "focus": self.focus,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrainingAssignment":
        return cls(
            mentor_uid=str(data.get("mentor_uid")),
            student_uid=str(data.get("student_uid")),
            since_ts=int(data.get("since_ts", now_ts())),
            focus_type=data.get("focus_type"),
            focus=data.get("focus"),
        )


@dataclass(slots=True)
class Girl:
    uid: str
    base_id: str
    name: str
    rarity: str
    level: int = 1
    exp: int = 0
    image_url: str = ""
    health: int = 100
    health_max: int = 100
    stamina: int = 100
    stamina_max: int = 100
    lust: int = 80
    lust_max: int = 100
    vitality_level: int = 1
    vitality_xp: int = 0
    endurance_level: int = 1
    endurance_xp: int = 0
    lust_level: int = 1
    lust_xp: int = 0
    stamina_last_ts: int = field(default_factory=now_ts)
    lust_last_ts: int = field(default_factory=now_ts)
    pregnancy_points: int = 0
    pregnant: bool = False
    preferences_main: Dict[str, str] = field(default_factory=dict)
    preferences_sub: Dict[str, str] = field(default_factory=dict)
    skills: Dict[str, Dict[str, int]] = field(default_factory=dict)
    subskills: Dict[str, Dict[str, int]] = field(default_factory=dict)
    mentorship_bonus: float = 0.0
    mentorship_focus_type: Optional[str] = None
    mentorship_focus: Optional[str] = None
    mentorship_mentor_uid: Optional[str] = None

    def __post_init__(self) -> None:
        self.skills = normalize_skill_map(self.skills, names=MAIN_SKILLS)
        self.subskills = normalize_skill_map(self.subskills, names=SUB_SKILLS)
        self.preferences_main = normalize_prefs(self.preferences_main, MAIN_SKILLS)
        self.preferences_sub = normalize_prefs(self.preferences_sub, SUB_SKILLS)
        self.health = max(0, min(self.health, self.health_max))
        self.stamina = max(0, min(self.stamina, self.stamina_max))
        self.lust = max(0, min(self.lust, self.lust_max))

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "base_id": self.base_id,
            "name": self.name,
            "rarity": self.rarity,
            "level": self.level,
            "exp": self.exp,
            "image_url": self.image_url,
            "health": self.health,
            "health_max": self.health_max,
            "stamina": self.stamina,
            "stamina_max": self.stamina_max,
            "lust": self.lust,
            "lust_max": self.lust_max,
            "vitality_level": self.vitality_level,
            "vitality_xp": self.vitality_xp,
            "endurance_level": self.endurance_level,
            "endurance_xp": self.endurance_xp,
            "lust_level": self.lust_level,
            "lust_xp": self.lust_xp,
            "stamina_last_ts": self.stamina_last_ts,
            "lust_last_ts": self.lust_last_ts,
            "pregnancy_points": self.pregnancy_points,
            "pregnant": self.pregnant,
            "preferences_main": self.preferences_main,
            "preferences_sub": self.preferences_sub,
            "skills": self.skills,
            "subskills": self.subskills,
            "mentorship_bonus": self.mentorship_bonus,
            "mentorship_focus_type": self.mentorship_focus_type,
            "mentorship_focus": self.mentorship_focus,
            "mentorship_mentor_uid": self.mentorship_mentor_uid,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Girl":
        return cls(
            uid=str(data.get("uid")),
            base_id=str(data.get("base_id", data.get("id", ""))),
            name=data.get("name", ""),
            rarity=data.get("rarity", "R"),
            level=int(data.get("level", 1)),
            exp=int(data.get("exp", data.get("experience", 0))),
            image_url=data.get("image_url", ""),
            health=int(data.get("health", 100)),
            health_max=int(data.get("health_max", data.get("max_health", 100))),
            stamina=int(data.get("stamina", 100)),
            stamina_max=int(data.get("stamina_max", data.get("max_stamina", 100))),
            lust=int(data.get("lust", 80)),
            lust_max=int(data.get("lust_max", data.get("max_lust", 100))),
            vitality_level=int(data.get("vitality_level", 1)),
            vitality_xp=int(data.get("vitality_xp", 0)),
            endurance_level=int(data.get("endurance_level", 1)),
            endurance_xp=int(data.get("endurance_xp", 0)),
            lust_level=int(data.get("lust_level", 1)),
            lust_xp=int(data.get("lust_xp", 0)),
            stamina_last_ts=int(data.get("stamina_last_ts", now_ts())),
            lust_last_ts=int(data.get("lust_last_ts", now_ts())),
            pregnancy_points=int(data.get("pregnancy_points", 0)),
            pregnant=bool(data.get("pregnant", False)),
            preferences_main=data.get("preferences_main", {}),
            preferences_sub=data.get("preferences_sub", {}),
            skills=data.get("skills") or data.get("base", {}).get("skills", {}),
            subskills=data.get("subskills") or data.get("base", {}).get("subskills", {}),
            mentorship_bonus=float(data.get("mentorship_bonus", 0.0)),
            mentorship_focus_type=data.get("mentorship_focus_type"),
            mentorship_focus=data.get("mentorship_focus"),
            mentorship_mentor_uid=data.get("mentorship_mentor_uid"),
        )

    # ------------------------------------------------------------------
    # Поведение
    # ------------------------------------------------------------------
    def regen_stamina(self) -> None:
        self.stamina, self.stamina_last_ts = regen_resource(
            self.stamina,
            self.stamina_last_ts,
            self.stamina_max,
            per_tick=1.0 + self.endurance_level * 0.25,
        )

    def regen_lust(self) -> None:
        self.lust, self.lust_last_ts = regen_resource(
            self.lust,
            self.lust_last_ts,
            self.lust_max,
            per_tick=1.5 + self.vitality_level * 0.2,
        )

    def consume_stamina(self, amount: int) -> None:
        self.stamina = max(0, self.stamina - int(amount))
        self.stamina_last_ts = now_ts()

    def consume_lust(self, amount: int) -> None:
        self.lust = max(0, self.lust - int(amount))
        self.lust_last_ts = now_ts()

    def gain_exp(self, amount: int) -> None:
        if amount <= 0:
            return
        self.exp += amount
        while self.exp >= level_xp_threshold(self.level):
            self.exp -= level_xp_threshold(self.level)
            self.level += 1

    def gain_stat_xp(self, *, lust: int = 0, endurance: int = 0, vitality: int = 0) -> None:
        if lust:
            self.lust_xp += lust
            while self.lust_xp >= stat_xp_threshold(self.lust_level):
                self.lust_xp -= stat_xp_threshold(self.lust_level)
                self.lust_level += 1
        if endurance:
            self.endurance_xp += endurance
            while self.endurance_xp >= stat_xp_threshold(self.endurance_level):
                self.endurance_xp -= stat_xp_threshold(self.endurance_level)
                self.endurance_level += 1
        if vitality:
            self.vitality_xp += vitality
            while self.vitality_xp >= stat_xp_threshold(self.vitality_level):
                self.vitality_xp -= stat_xp_threshold(self.vitality_level)
                self.vitality_level += 1

    def grant_training_bonus(
        self,
        mentor_uid: str,
        bonus: float,
        focus_type: Optional[str],
        focus_name: Optional[str],
    ) -> None:
        self.mentorship_mentor_uid = mentor_uid
        self.mentorship_bonus = max(0.0, float(bonus))
        self.mentorship_focus_type = focus_type
        self.mentorship_focus = focus_name

    def clear_training_bonus(self) -> None:
        self.mentorship_bonus = 0.0
        self.mentorship_focus_type = None
        self.mentorship_focus = None
        self.mentorship_mentor_uid = None


@dataclass(slots=True)
class Job:
    job_id: str
    demand_main: str
    demand_level: int
    demand_sub: Optional[str]
    demand_sub_level: int
    pay: int
    difficulty: int

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "demand_main": self.demand_main,
            "demand_level": self.demand_level,
            "demand_sub": self.demand_sub,
            "demand_sub_level": self.demand_sub_level,
            "pay": self.pay,
            "difficulty": self.difficulty,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        return cls(
            job_id=str(data.get("job_id", data.get("id", ""))),
            demand_main=data.get("demand_main", "Human"),
            demand_level=int(data.get("demand_level", 0)),
            demand_sub=data.get("demand_sub"),
            demand_sub_level=int(data.get("demand_sub_level", 0)),
            pay=int(data.get("pay", 0)),
            difficulty=int(data.get("difficulty", 1)),
        )


@dataclass(slots=True)
class Market:
    user_id: int
    jobs: List[Job] = field(default_factory=list)
    level: int = 1
    generated_ts: int = field(default_factory=now_ts)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "jobs": [job.to_dict() for job in self.jobs],
            "level": self.level,
            "generated_ts": self.generated_ts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Market":
        return cls(
            user_id=int(data.get("user_id", 0)),
            jobs=[Job.from_dict(item) for item in data.get("jobs", [])],
            level=int(data.get("level", 1)),
            generated_ts=int(data.get("generated_ts", now_ts())),
        )


@dataclass(slots=True)
class BrothelState:
    rooms: int = 3
    renown: int = 15
    morale: int = 75
    cleanliness: int = 80
    comfort_level: int = 1
    hygiene_level: int = 1
    security_level: int = 1
    allure_level: int = 1
    upkeep_pool: int = 0
    last_tick_ts: int = field(default_factory=now_ts)
    decay_buffer: float = 0.0
    training: List[TrainingAssignment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rooms": self.rooms,
            "renown": self.renown,
            "morale": self.morale,
            "cleanliness": self.cleanliness,
            "comfort_level": self.comfort_level,
            "hygiene_level": self.hygiene_level,
            "security_level": self.security_level,
            "allure_level": self.allure_level,
            "upkeep_pool": self.upkeep_pool,
            "last_tick_ts": self.last_tick_ts,
            "decay_buffer": self.decay_buffer,
            "training": [assignment.to_dict() for assignment in self.training],
            "popularity": self.renown,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BrothelState":
        renown = int(data.get("renown", data.get("popularity", 15)))
        return cls(
            rooms=int(data.get("rooms", 3)),
            renown=renown,
            morale=int(data.get("morale", 75)),
            cleanliness=int(data.get("cleanliness", 80)),
            comfort_level=int(data.get("comfort_level", data.get("comfort", 1))),
            hygiene_level=int(data.get("hygiene_level", data.get("hygiene", 1))),
            security_level=int(data.get("security_level", data.get("security", 1))),
            allure_level=int(data.get("allure_level", data.get("allure", 1))),
            upkeep_pool=int(data.get("upkeep_pool", 0)),
            last_tick_ts=int(data.get("last_tick_ts", now_ts())),
            decay_buffer=float(data.get("decay_buffer", 0.0)),
            training=[TrainingAssignment.from_dict(item) for item in data.get("training", [])],
        )

    # ------------------------------------------------------------------
    # Помощники
    # ------------------------------------------------------------------
    def facility_level(self, name: str) -> int:
        mapping = {
            "comfort": self.comfort_level,
            "hygiene": self.hygiene_level,
            "security": self.security_level,
            "allure": self.allure_level,
        }
        return int(mapping.get(name, 0))

    def rooms_free(self, girls_count: int) -> int:
        return max(0, self.rooms - girls_count)

    # ------------------------------------------------------------------
    # Игровая логика
    # ------------------------------------------------------------------
    def promote(self, coins: int) -> Dict[str, int]:
        coins = max(0, int(coins))
        gained = coins // PROMOTE_COINS_PER_RENOWN
        if gained:
            self.renown += gained
        return {"renown": gained}

    def apply_decay(self) -> Dict[str, int]:
        now = now_ts()
        elapsed = max(0, now - self.last_tick_ts)
        ticks = elapsed // 900
        self.last_tick_ts += ticks * 900
        if ticks <= 0:
            return {"cleanliness": 0, "morale": 0, "renown": 0}

        base_loss = 3.2 - self.hygiene_level * 0.25
        raw_loss = base_loss * ticks
        self.decay_buffer += max(0.5, raw_loss)
        loss = int(self.decay_buffer)
        self.decay_buffer -= loss
        before_clean = self.cleanliness
        self.cleanliness = max(0, self.cleanliness - loss)

        morale_loss = 0
        renown_loss = 0
        if self.cleanliness < 45:
            morale_loss = max(0, int((45 - self.cleanliness) * 0.05 * ticks))
        if self.cleanliness < 35:
            renown_loss = max(0, int((35 - self.cleanliness) * 0.03 * ticks))

        self.morale = max(0, self.morale - morale_loss)
        self.renown = max(0, self.renown - renown_loss)
        return {
            "cleanliness": before_clean - self.cleanliness,
            "morale": morale_loss,
            "renown": renown_loss,
        }

    def maintain(self, coins: int) -> Dict[str, int]:
        coins = max(0, int(coins))
        self.upkeep_pool += coins
        effectiveness = 0.15 + self.hygiene_level * 0.05
        restored = int(self.upkeep_pool * effectiveness)
        morale_gain = int(restored * 0.2)
        self.cleanliness = min(100, self.cleanliness + restored)
        self.morale = min(100, self.morale + morale_gain)
        spent = min(self.upkeep_pool, int(restored / max(effectiveness, 0.01)))
        self.upkeep_pool = max(0, self.upkeep_pool - spent)
        return {"cleanliness": restored, "morale": morale_gain}

    def register_job_outcome(
        self,
        *,
        success: bool,
        injured: bool,
        job: Job,
        reward: int,
    ) -> Dict[str, int]:
        base_loss = 6 + job.difficulty * 2
        mitigation = self.hygiene_level * 0.6
        cleanliness_loss = max(3, int(base_loss - mitigation))
        if not success:
            cleanliness_loss = int(cleanliness_loss * 0.7)
        if injured:
            cleanliness_loss += 2
        cleanliness_loss = max(1, cleanliness_loss)
        before = self.cleanliness
        self.cleanliness = max(0, self.cleanliness - cleanliness_loss)

        morale_delta = 0
        if success:
            morale_delta = min(5, int(reward / 80))
            self.morale = min(100, self.morale + morale_delta)
        else:
            morale_delta = -min(5, job.difficulty)
            self.morale = max(0, self.morale + morale_delta)

        return {
            "cleanliness": before - self.cleanliness,
            "morale": morale_delta,
        }

    # ------------------------------------------------------------------
    # Наставничество
    # ------------------------------------------------------------------
    def start_training(
        self,
        *,
        mentor_uid: str,
        student_uid: str,
        focus_type: Optional[str] = None,
        focus: Optional[str] = None,
    ) -> TrainingAssignment:
        assignment = TrainingAssignment(
            mentor_uid=mentor_uid,
            student_uid=student_uid,
            since_ts=now_ts(),
            focus_type=focus_type,
            focus=focus,
        )
        self.training = [a for a in self.training if a.student_uid != student_uid]
        self.training.append(assignment)
        return assignment

    def training_for(self, student_uid: str) -> Optional[TrainingAssignment]:
        for assignment in self.training:
            if assignment.student_uid == student_uid:
                return assignment
        return None

    def stop_training(self, student_uid: str) -> None:
        self.training = [a for a in self.training if a.student_uid != student_uid]


@dataclass(slots=True)
class Player:
    user_id: int
    display_name: str = ""
    currency: int = 0
    renown: int = 15
    girls: List[Girl] = field(default_factory=list)
    brothel: Optional[BrothelState] = None

    def ensure_brothel(self) -> BrothelState:
        if self.brothel is None:
            self.brothel = BrothelState(renown=self.renown)
        else:
            self.brothel.renown = self.renown
        return self.brothel

    def get_girl(self, uid: str) -> Optional[Girl]:
        for girl in self.girls:
            if girl.uid == uid:
                return girl
        return None

    def add_girl(self, girl: Girl) -> None:
        self.girls.append(girl)

    def remove_girl(self, uid: str) -> None:
        self.girls = [girl for girl in self.girls if girl.uid != uid]

    def free_rooms(self) -> int:
        return self.ensure_brothel().rooms_free(len(self.girls))

    def to_dict(self) -> dict:
        brothel = self.ensure_brothel()
        brothel.renown = self.renown
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "currency": self.currency,
            "renown": self.renown,
            "girls": [girl.to_dict() for girl in self.girls],
            "brothel": brothel.to_dict(),
            "reputation": self.renown,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Player":
        renown = int(data.get("renown", data.get("reputation", 15)))
        brothel_payload = data.get("brothel") or {}
        brothel = BrothelState.from_dict(brothel_payload) if brothel_payload else None
        if brothel is not None:
            renown = brothel.renown
        player = cls(
            user_id=int(data.get("user_id", 0)),
            display_name=data.get("display_name", ""),
            currency=int(data.get("currency", 0)),
            renown=renown,
            girls=[Girl.from_dict(item) for item in data.get("girls", [])],
            brothel=brothel,
        )
        return player


__all__ = [
    "MAIN_SKILLS",
    "SUB_SKILLS",
    "BROTHEL_FACILITY_NAMES",
    "RARITY_WEIGHTS",
    "RARITY_COLORS",
    "PROMOTE_COINS_PER_RENOWN",
    "PREF_OPEN",
    "PREF_BLOCKED",
    "PREF_FAV",
    "PREGNANCY_TICK_SECONDS",
    "PREGNANCY_TOTAL_POINTS",
    "now_ts",
    "regen_resource",
    "level_xp_threshold",
    "skill_xp_threshold",
    "stat_xp_threshold",
    "facility_xp_threshold",
    "make_bar",
    "normalize_skill_map",
    "add_skill_xp",
    "get_level",
    "get_xp",
    "normalize_prefs",
    "is_blocked",
    "xp_multiplier_for_pref",
    "market_level_from_rep",
    "TrainingAssignment",
    "Girl",
    "Job",
    "Market",
    "BrothelState",
    "Player",
]
