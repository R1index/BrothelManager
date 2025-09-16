from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Tuple
import time

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

MAIN_SKILLS = ["Human", "Insect", "Beast", "Monster"]
SUB_SKILLS  = ["VAGINAL", "ANAL", "ORAL", "BREAST", "HAND", "FOOT", "TOY"]  # NIPPLE -> BREAST

BROTHEL_FACILITY_NAMES: Tuple[str, ...] = ("comfort", "hygiene", "security", "allure")

RARITY_WEIGHTS = {"R": 70, "SR": 20, "SSR": 9, "UR": 1}
RARITY_COLORS  = {"R": 0x9fa6b2, "SR": 0x60a5fa, "SSR": 0xf59e0b, "UR": 0x8b5cf6}

# Preferences for skills/subskills
PREF_OPEN    = "true"   # open for training
PREF_BLOCKED = "false"  # blocked (girl refuses jobs using it)
PREF_FAV     = "fav"    # accelerated XP gain

# Pregnancy timing
PREGNANCY_TICK_SECONDS = 600      # 10 minutes = 1 point
PREGNANCY_TOTAL_POINTS = 30       # 30 points total

# -----------------------------------------------------------------------------
# Time / stamina
# -----------------------------------------------------------------------------

def now_ts() -> int:
    return int(time.time())

def regen_stamina(
    current: int,
    last_ts: int,
    max_sta: int,
    per_tick: float = 1.0,
    tick_seconds: int = 600,
) -> tuple[int, int]:
    """Regenerate stamina in discrete ticks.

    ``per_tick`` can be fractional to account for endurance-based bonuses. The
    regenerated amount is floored to an integer (fractions are carried by the
    timestamp difference on subsequent calls).
    """
    if current >= max_sta:
        return max_sta, now_ts()
    elapsed = max(0, now_ts() - last_ts)
    ticks = elapsed // tick_seconds
    if ticks <= 0:
        return current, last_ts
    regen_amount = int(ticks * per_tick)
    if regen_amount <= 0:
        return current, last_ts
    new_val = min(max_sta, current + regen_amount)
    new_last = last_ts + int(ticks * tick_seconds)
    return new_val, new_last

# -----------------------------------------------------------------------------
# XP thresholds
# -----------------------------------------------------------------------------

def level_xp_threshold(level: int) -> int:
    """Girl level-up XP requirement (superlinear growth)."""
    return 100 + int(level * 25 + (level ** 1.15))

def skill_xp_threshold(level: int) -> int:
    """Skill level-up XP requirement (slightly superlinear)."""
    return 40 + int(level * 12 + (level ** 1.10))


def stat_xp_threshold(level: int) -> int:
    """XP threshold for secondary stats (vitality/endurance)."""
    return 30 + int(level * 8 + (level ** 1.08))


def facility_xp_threshold(level: int) -> int:
    """XP threshold for brothel facility upgrades."""
    return 80 + int(level * 25 + (level ** 1.05) * 15)

# -----------------------------------------------------------------------------
# Skill helpers (canonical structure: {'level': int, 'xp': int})
# -----------------------------------------------------------------------------

def normalize_skill_map(raw: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """
    Normalize skill dict to {'level': int, 'xp': int}.
    Accepts legacy formats:
      - ints: {"Human": 2, ...}
      - dicts with 'exp': {"Human": {"level": 2, "exp": 10}}
    Missing skills are filled with zeros.
    """
    result: Dict[str, Dict[str, int]] = {}
    for name in MAIN_SKILLS + SUB_SKILLS:
        v = (raw or {}).get(name, 0)
        if isinstance(v, dict):
            lvl = int(v.get("level", 0))
            # migrate 'exp' -> 'xp' if present
            xp  = int(v.get("xp", v.get("exp", 0)))
        else:
            lvl = int(v)
            xp  = 0
        result[name] = {"level": max(0, lvl), "xp": max(0, xp)}
    return result

def add_skill_xp(skmap: Dict[str, Dict[str, int]], name: str, amount: int) -> Tuple[int, int]:
    """Add XP to a single skill, apply level-ups, cap at 9999. Returns (new_level, xp_after)."""
    node = skmap.setdefault(name, {"level": 0, "xp": 0})
    node["xp"] += int(amount)

    while node["level"] < 9999 and node["xp"] >= skill_xp_threshold(node["level"]):
        node["xp"] -= skill_xp_threshold(node["level"])
        node["level"] += 1
        if node["level"] >= 9999:
            node["xp"] = 0
            break

    return node["level"], node["xp"]

def get_level(skmap: Dict[str, Dict[str, int]], name: str) -> int:
    node = skmap.get(name) or {}
    return int(node.get("level", 0))

def get_xp(skmap: Dict[str, Dict[str, int]], name: str) -> int:
    node = skmap.get(name) or {}
    # read canonical 'xp' (legacy 'exp' still supported if loaded raw)
    return int(node.get("xp", node.get("exp", 0)))

def make_bar(current: int, need: int, length: int = 12) -> str:
    """Monospace progress bar."""
    if need <= 0:
        return "■" * length
    filled = min(length, (current * length) // need)
    return "■" * filled + "□" * (length - filled)

# -----------------------------------------------------------------------------
# Preferences helpers
# -----------------------------------------------------------------------------

def normalize_prefs(raw: Dict[str, str], names: list[str]) -> Dict[str, str]:
    """Ensure preference map contains all names with a valid value."""
    out: Dict[str, str] = {}
    for n in names:
        v = str((raw or {}).get(n, PREF_OPEN)).lower()
        if v not in (PREF_OPEN, PREF_BLOCKED, PREF_FAV):
            v = PREF_OPEN
        out[n] = v
    return out

def is_blocked(prefs: Dict[str, str], name: str) -> bool:
    return prefs.get(name, PREF_OPEN) == PREF_BLOCKED

def xp_multiplier_for_pref(prefs: Dict[str, str], name: str) -> float:
    v = prefs.get(name, PREF_OPEN)
    return 1.5 if v == PREF_FAV else 1.0

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------

class Girl(BaseModel):
    uid: str                  # unique per player (e.g. g001#1)
    base_id: str
    name: str
    rarity: str

    # Girl level (separate from skills)
    level: int = 1
    exp: int = 0              # girl's own XP

    image_url: str = ""

    # Vital stats
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
    stamina_last_ts: int = Field(default_factory=now_ts)
    lust_last_ts: int = Field(default_factory=now_ts)

    # Skills (canonical structure)
    skills: Dict[str, Dict[str, int]]    = Field(default_factory=lambda: {k: {"level": 0, "xp": 0} for k in MAIN_SKILLS})
    subskills: Dict[str, Dict[str, int]] = Field(default_factory=lambda: {k: {"level": 0, "xp": 0} for k in SUB_SKILLS})

    # Bio
    breast_size: Optional[str] = None   # e.g. "C"
    body_shape: Optional[str]  = None   # e.g. "slim", "curvy"
    age: Optional[int]         = None
    height_cm: Optional[int]   = None
    weight_kg: Optional[int]   = None
    traits: List[str] = Field(default_factory=list)   # e.g. ["mole", "bald"]

    # Pregnancy
    pregnant: bool = False
    pregnant_since_ts: Optional[int] = None

    # Preferences (training policy)
    prefs_skills: Dict[str, str]    = Field(default_factory=lambda: {k: PREF_OPEN for k in MAIN_SKILLS})
    prefs_subskills: Dict[str, str] = Field(default_factory=lambda: {k: PREF_OPEN for k in SUB_SKILLS})

    def apply_regen(self):
        self.ensure_stat_defaults()
        # stamina regen (endurance affects both cap and per-tick rate)
        self.stamina, self.stamina_last_ts = regen_stamina(
            self.stamina,
            self.stamina_last_ts,
            self.stamina_max,
            per_tick=self.stamina_regen_per_tick(),
        )
        # lust drifts upward while resting
        self.lust, self.lust_last_ts = regen_stamina(
            self.lust,
            self.lust_last_ts,
            self.lust_max,
            per_tick=self.lust_regen_per_tick(),
            tick_seconds=600,
        )
        # pregnancy auto-progress + auto-clear at full term
        if self.pregnant and self.pregnant_since_ts:
            elapsed = max(0, now_ts() - self.pregnant_since_ts)
            points = elapsed // PREGNANCY_TICK_SECONDS
            if points >= PREGNANCY_TOTAL_POINTS:
                self.pregnant = False
                self.pregnant_since_ts = None

    def pregnancy_points(self) -> int:
        """How many pregnancy points (0..30) have elapsed."""
        if not self.pregnant or not self.pregnant_since_ts:
            return 0
        elapsed = max(0, now_ts() - self.pregnant_since_ts)
        return int(min(PREGNANCY_TOTAL_POINTS, elapsed // PREGNANCY_TICK_SECONDS))

    def normalize_skill_structs(self):
        """Normalize legacy data structures for skills/subskills and preferences."""
        self.skills    = normalize_skill_map(self.skills)
        self.subskills = normalize_skill_map(self.subskills)
        self.prefs_skills    = normalize_prefs(self.prefs_skills, MAIN_SKILLS)
        self.prefs_subskills = normalize_prefs(self.prefs_subskills, SUB_SKILLS)
        self.ensure_stat_defaults()

    # ------------------------------------------------------------------
    # Derived stat helpers
    # ------------------------------------------------------------------

    def ensure_stat_defaults(self):
        """Backfill defaults for health/endurance progression."""
        if self.vitality_level <= 0:
            self.vitality_level = 1
        if self.endurance_level <= 0:
            self.endurance_level = 1
        if self.lust_level <= 0:
            self.lust_level = 1
        self.vitality_xp = max(0, int(self.vitality_xp))
        self.endurance_xp = max(0, int(self.endurance_xp))
        self.lust_xp = max(0, int(self.lust_xp))
        if self.health_max <= 0:
            self.health_max = 100
        if self.stamina_max <= 0:
            self.stamina_max = 100
        if self.lust_max <= 0:
            self.lust_max = 80
        if self.health < 0:
            self.health = 0
        if self.stamina < 0:
            self.stamina = 0
        if self.lust < 0:
            self.lust = 0
        self.recalc_limits()
        # Clamp current pools to their caps
        self.health = min(max(0, self.health), self.health_max)
        self.stamina = min(max(0, self.stamina), self.stamina_max)
        self.lust = min(max(0, self.lust), self.lust_max)
        if self.lust_last_ts <= 0:
            self.lust_last_ts = now_ts()

    def recalc_limits(self):
        """Recalculate max health/stamina from progression stats."""
        base_hp = 100 + (self.level - 1) * 6 + (self.vitality_level - 1) * 18
        base_sta = 100 + (self.level - 1) * 4 + (self.endurance_level - 1) * 15
        base_lust = 80 + (self.level - 1) * 5 + (self.lust_level - 1) * 14
        self.health_max = max(60, int(base_hp))
        self.stamina_max = max(60, int(base_sta))
        self.lust_max = max(40, int(base_lust))

    def stamina_regen_per_tick(self) -> float:
        """Stamina regen modifier depending on endurance."""
        return 1.0 + max(0, self.endurance_level - 1) * 0.25

    def lust_regen_per_tick(self) -> float:
        """Natural lust build-up while resting."""
        return 1.6 + max(0, self.lust_level - 1) * 0.35

    def gain_vitality_xp(self, amount: int):
        amount = max(0, int(amount))
        if amount <= 0:
            return
        self.vitality_xp += amount
        while self.vitality_level < 9999 and self.vitality_xp >= stat_xp_threshold(self.vitality_level):
            self.vitality_xp -= stat_xp_threshold(self.vitality_level)
            self.vitality_level += 1
        self.recalc_limits()
        self.health = min(self.health, self.health_max)

    def gain_endurance_xp(self, amount: int):
        amount = max(0, int(amount))
        if amount <= 0:
            return
        self.endurance_xp += amount
        while self.endurance_level < 9999 and self.endurance_xp >= stat_xp_threshold(self.endurance_level):
            self.endurance_xp -= stat_xp_threshold(self.endurance_level)
            self.endurance_level += 1
        self.recalc_limits()
        self.stamina = min(self.stamina, self.stamina_max)

    def gain_lust_xp(self, amount: int):
        amount = max(0, int(amount))
        if amount <= 0:
            return
        self.lust_xp += amount
        while self.lust_level < 9999 and self.lust_xp >= stat_xp_threshold(self.lust_level):
            self.lust_xp -= stat_xp_threshold(self.lust_level)
            self.lust_level += 1
        self.recalc_limits()
        self.lust = min(self.lust, self.lust_max)

class Job(BaseModel):
    # Future: multiple sub-skill demands
    demand_subs: List[Dict[str, int]] | None = None

    job_id: str
    demand_main: str           # one of MAIN_SKILLS
    demand_level: int
    demand_sub: str            # one of SUB_SKILLS
    demand_sub_level: int
    pay: int
    difficulty: int = 1


class BrothelState(BaseModel):
    comfort_level: int = 1
    comfort_xp: int = 0
    hygiene_level: int = 1
    hygiene_xp: int = 0
    security_level: int = 1
    security_xp: int = 0
    allure_level: int = 1
    allure_xp: int = 0

    cleanliness: int = 80
    morale: int = 70
    popularity: int = 15
    rooms: int = 3
    upkeep_pool: int = 0

    last_tick_ts: int = Field(default_factory=now_ts)

    def ensure_bounds(self):
        for name in BROTHEL_FACILITY_NAMES:
            lvl_attr = f"{name}_level"
            xp_attr = f"{name}_xp"
            setattr(self, lvl_attr, max(1, int(getattr(self, lvl_attr, 1))))
            setattr(self, xp_attr, max(0, int(getattr(self, xp_attr, 0))))

        self.cleanliness = min(100, max(0, int(self.cleanliness)))
        self.morale = min(100, max(10, int(self.morale)))
        self.popularity = min(250, max(0, int(self.popularity)))
        self.rooms = max(1, int(self.rooms))
        self.upkeep_pool = min(10000, max(0, int(self.upkeep_pool)))
        if self.last_tick_ts <= 0:
            self.last_tick_ts = now_ts()

    def facility_threshold(self, name: str) -> int:
        return facility_xp_threshold(self.facility_level(name))

    def facility_level(self, name: str) -> int:
        return int(getattr(self, f"{name}_level", 1))

    def facility_xp(self, name: str) -> int:
        return int(getattr(self, f"{name}_xp", 0))

    def facility_progress(self, name: str) -> Tuple[int, int, int]:
        lvl = self.facility_level(name)
        xp = self.facility_xp(name)
        need = facility_xp_threshold(lvl)
        return lvl, xp, need

    def gain_facility_xp(self, name: str, amount: int):
        if name not in BROTHEL_FACILITY_NAMES:
            return
        amount = max(0, int(amount))
        if amount <= 0:
            return
        lvl_attr = f"{name}_level"
        xp_attr = f"{name}_xp"
        lvl = self.facility_level(name)
        xp = self.facility_xp(name) + amount
        need = facility_xp_threshold(lvl)
        while lvl < 9999 and xp >= need:
            xp -= need
            lvl += 1
            need = facility_xp_threshold(lvl)
        setattr(self, lvl_attr, lvl)
        setattr(self, xp_attr, xp)
        self.ensure_bounds()

    def apply_decay(self):
        self.ensure_bounds()
        now = now_ts()
        elapsed = max(0, now - self.last_tick_ts)
        if elapsed < 900:
            return
        ticks = elapsed // 900
        if ticks <= 0:
            return
        decay = int(ticks)
        self.cleanliness = max(0, self.cleanliness - decay)

        morale_shift = 0
        if self.cleanliness < 40:
            morale_shift -= max(1, decay // 2)
        elif self.cleanliness > 85:
            morale_shift += max(1, decay // 3)
        self.morale = min(100, max(10, self.morale + morale_shift))

        if self.cleanliness < 50:
            self.popularity = max(0, self.popularity - max(1, decay // 2))
        else:
            self.popularity = min(250, self.popularity + int(decay // 3))

        remainder = elapsed % 900
        self.last_tick_ts = now - remainder

    def success_bonus(self) -> float:
        boost = 0.015 * max(0, self.comfort_level - 1)
        boost += max(-0.05, (self.morale - 70) / 350)
        boost += min(0.05, self.popularity / 500)
        penalty = max(0.0, (50 - self.cleanliness) / 180)
        total = boost - penalty
        return max(-0.08, min(0.18, total))

    def reward_modifier(self) -> float:
        modifier = 1.0
        modifier += 0.04 * max(0, self.allure_level - 1)
        modifier += min(0.25, self.popularity / 400)
        modifier += (self.cleanliness - 60) / 250
        return max(0.6, min(1.6, modifier))

    def injury_modifier(self) -> float:
        reduction = 0.03 * max(0, self.security_level - 1)
        reduction += max(0.0, (self.cleanliness - 55) / 220)
        reduction += max(0.0, (self.morale - 70) / 300)
        modifier = 1.0 - reduction
        return max(0.55, min(1.05, modifier))

    def lust_modifier(self) -> float:
        modifier = 1.0
        modifier -= 0.02 * max(0, self.comfort_level - 1)
        modifier -= max(0.0, (self.morale - 65) / 320)
        modifier += max(0.0, (40 - self.cleanliness) / 260)
        return max(0.7, min(1.1, modifier))

    def maintain(self, coins: int) -> Dict[str, int]:
        coins = max(0, int(coins))
        if coins <= 0:
            return {"cleanliness": 0, "morale": 0, "pool_used": 0}
        pool_bonus = min(self.upkeep_pool, coins // 2)
        self.upkeep_pool -= pool_bonus
        effective = coins + pool_bonus * 2
        restored = min(100 - self.cleanliness, max(1, effective // 5))
        self.cleanliness += restored
        morale = min(100 - self.morale, max(0, restored // 2))
        self.morale += morale
        self.gain_facility_xp("hygiene", restored * 2)
        self.ensure_bounds()
        return {"cleanliness": restored, "morale": morale, "pool_used": pool_bonus}

    def promote(self, coins: int) -> Dict[str, int]:
        coins = max(0, int(coins))
        if coins <= 0:
            return {"popularity": 0, "morale": 0}
        gained = min(250 - self.popularity, max(1, coins // 6))
        morale = min(100 - self.morale, max(0, coins // 15))
        self.popularity += gained
        self.morale += morale
        self.gain_facility_xp("allure", max(3, coins // 4))
        self.ensure_bounds()
        return {"popularity": gained, "morale": morale}

    def register_job_outcome(self, success: bool, injured: bool, job: "Job", reward: int):
        reward = max(0, int(reward))
        wear = 1 + job.difficulty
        if job.demand_sub == "VAGINAL":
            wear += 1
        self.cleanliness = max(0, self.cleanliness - wear)
        self.upkeep_pool = min(10000, self.upkeep_pool + max(0, reward // 30))

        if success:
            morale_gain = 2 + job.difficulty
            pop_gain = max(1, reward // 90)
            self.morale = min(100, self.morale + morale_gain)
            self.popularity = min(250, self.popularity + pop_gain)
            self.gain_facility_xp("comfort", 6 + job.difficulty * 2)
            self.gain_facility_xp("allure", max(4, reward // 35))
        else:
            morale_loss = 2 + job.difficulty
            self.morale = max(10, self.morale - morale_loss)
            self.popularity = max(0, self.popularity - (1 + job.difficulty))
            self.gain_facility_xp("comfort", 3 + job.difficulty)
            self.gain_facility_xp("allure", max(2, reward // 60))

        hygiene_xp = 4 + max(0, 80 - self.cleanliness) // 5
        self.gain_facility_xp("hygiene", hygiene_xp)

        if injured:
            self.cleanliness = max(0, self.cleanliness - (2 + job.difficulty))
            self.morale = max(10, self.morale - 3)
            self.popularity = max(0, self.popularity - 2)
            self.gain_facility_xp("security", 6 + job.difficulty * 2)
        else:
            self.gain_facility_xp("security", 3 + job.difficulty)

        self.ensure_bounds()

def market_level_from_rep(rep: int) -> int:
    """+1 market level per 100 reputation, starting at 0."""
    if rep < 0:
        rep = 0
    return min(9999, rep // 100)

class Market(BaseModel):
    user_id: int
    jobs: List[Job] = Field(default_factory=list)
    ts: int = Field(default_factory=now_ts)
    level: int = 0

class Player(BaseModel):
    reputation: int = 0
    user_id: int
    currency: int = 0
    girls: List[Girl] = Field(default_factory=list)
    brothel: BrothelState = Field(default_factory=BrothelState)
    created_ts: int = Field(default_factory=now_ts)

    def get_girl(self, uid: str) -> Optional[Girl]:
        return next((g for g in self.girls if g.uid == uid), None)

    def ensure_brothel(self) -> BrothelState:
        if not isinstance(self.brothel, BrothelState):
            data = self.brothel or {}
            if isinstance(data, dict):
                self.brothel = BrothelState(**data)
            else:
                self.brothel = BrothelState()
        self.brothel.ensure_bounds()
        return self.brothel
