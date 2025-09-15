from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Tuple, Any
import time

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

MAIN_SKILLS = ["Human", "Insect", "Beast", "Monster"]
SUB_SKILLS  = ["VAGINAL", "ANAL", "ORAL", "BREAST"]  # NIPPLE -> BREAST

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

def regen_stamina(current: int, last_ts: int, max_sta: int, per_tick: int = 1, tick_seconds: int = 600) -> tuple[int, int]:
    """Regenerate stamina: +1 per 10 minutes (600s). Returns (new_stamina, new_last_ts)."""
    if current >= max_sta:
        return max_sta, now_ts()
    elapsed = max(0, now_ts() - last_ts)
    ticks = elapsed // tick_seconds
    if ticks <= 0:
        return current, last_ts
    new_val = min(max_sta, current + int(ticks * per_tick))
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

    # Stamina
    stamina: int = 100
    stamina_max: int = 100
    stamina_last_ts: int = Field(default_factory=now_ts)

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
        # stamina regen
        self.stamina, self.stamina_last_ts = regen_stamina(self.stamina, self.stamina_last_ts, self.stamina_max)
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
    created_ts: int = Field(default_factory=now_ts)

    def get_girl(self, uid: str) -> Optional[Girl]:
        return next((g for g in self.girls if g.uid == uid), None)
