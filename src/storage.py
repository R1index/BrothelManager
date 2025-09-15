from __future__ import annotations

import json
import os
import random
import time
from typing import Optional, Tuple, Dict, Any, List

from .models import (
    Player, Girl, Market, Job,
    MAIN_SKILLS, SUB_SKILLS,
    normalize_skill_map, normalize_prefs,
    get_level, add_skill_xp, level_xp_threshold,
    market_level_from_rep, PREF_BLOCKED, PREF_FAV,
)

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

BASE_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR   = os.path.join(BASE_DIR, "data")
USERS_DIR  = os.path.join(DATA_DIR, "users")
MARKET_DIR = os.path.join(DATA_DIR, "markets")
CATALOG    = os.path.join(DATA_DIR, "girls_catalog.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(USERS_DIR, exist_ok=True)
os.makedirs(MARKET_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# JSON helpers
# -----------------------------------------------------------------------------

def _read_json(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# -----------------------------------------------------------------------------
# Catalog
# -----------------------------------------------------------------------------

def load_catalog() -> dict:
    data = _read_json(CATALOG)
    if not data:
        raise FileNotFoundError(f"Catalog not found: {CATALOG}")
    return data

# -----------------------------------------------------------------------------
# Player I/O + migration
# -----------------------------------------------------------------------------

def _user_path(uid: int) -> str:
    return os.path.join(USERS_DIR, f"{uid}.json")

def save_player(pl: Player):
    _write_json(_user_path(pl.user_id), json.loads(pl.model_dump_json()))

def load_player(uid: int) -> Optional[Player]:
    raw = _read_json(_user_path(uid))
    if not raw:
        return None

    # --- migration of legacy skills structure (ints -> {'level','xp'}) ---
    girls = raw.get("girls", [])
    for g in girls:
        # normalize skills/subskills (always) to ensure new entries exist
        skills_raw = g.get("skills") or {}
        if not isinstance(skills_raw, dict):
            skills_raw = {}
        g["skills"] = normalize_skill_map(skills_raw)

        subskills_raw = g.get("subskills") or {}
        if not isinstance(subskills_raw, dict):
            subskills_raw = {}
        g["subskills"] = normalize_skill_map(subskills_raw)

        # normalize preferences maps if present
        g["prefs_skills"]    = normalize_prefs(g.get("prefs_skills", {}), MAIN_SKILLS)
        g["prefs_subskills"] = normalize_prefs(g.get("prefs_subskills", {}), SUB_SKILLS)

    return Player(**raw)

# -----------------------------------------------------------------------------
# Starter pack / gacha
# -----------------------------------------------------------------------------

def _alloc_girl_uid(base_id: str, uid: int, counter: int) -> str:
    # simple uid: <base_id>#<counter>
    return f"{base_id}#{counter}"

def _make_girl_from_catalog_entry(base: dict, counter: int) -> Girl:
    """
    Build Girl from a catalog entry.
    Catalog entry format expected:
    {
      "id": "g003", "name": "Lyra", "rarity": "SSR", "image_url": "...",
      "bio": {...}, "prefs": {"skills": {...}, "subskills": {...}},
      "base": {"level": 1, "skills": {...}, "subskills": {...}}
    }
    """
    base_id   = base["id"]
    name      = base["name"]
    rarity    = base["rarity"]
    image_url = base.get("image_url", "")

    # base stats
    base_level    = int(base.get("base", {}).get("level", 1))
    base_skills   = normalize_skill_map(base.get("base", {}).get("skills", {}))
    base_subskill = normalize_skill_map(base.get("base", {}).get("subskills", {}))

    # bio info (optional)
    bio = base.get("bio", {}) or {}
    breast_size = bio.get("breast_size")
    body_shape  = bio.get("body_shape")
    age         = bio.get("age")
    height_cm   = bio.get("height_cm")
    weight_kg   = bio.get("weight_kg")
    traits      = bio.get("traits", [])

    # preferences (optional)
    prefs = base.get("prefs", {}) or {}
    prefs_skills    = normalize_prefs(prefs.get("skills", {}), MAIN_SKILLS)
    prefs_subskills = normalize_prefs(prefs.get("subskills", {}), SUB_SKILLS)

    g = Girl(
        uid=_alloc_girl_uid(base_id, 0, counter),  # temp, будет заменён снаружи реальным номером
        base_id=base_id,
        name=name,
        rarity=rarity,
        level=base_level,
        image_url=image_url,
        skills=base_skills,
        subskills=base_subskill,
        # bio
        breast_size=breast_size,
        body_shape=body_shape,
        age=age,
        height_cm=height_cm,
        weight_kg=weight_kg,
        traits=traits,
        # prefs
        prefs_skills=prefs_skills,
        prefs_subskills=prefs_subskills,
    )
    g.normalize_skill_structs()
    return g

def grant_starter_pack(uid: int) -> Player:
    """
    Create a player with 500 coins and 1 random R/SR/SSR/UR girl from catalog.
    """
    cat = load_catalog()
    girls = cat.get("girls", [])
    if not girls:
        raise RuntimeError("Girls catalog is empty.")

    # weighted choice by rarity
    pool = [(g, g.get("rarity", "R")) for g in girls]
    weights = []
    for _, r in pool:
        weights.append({
            "R": 70, "SR": 20, "SSR": 9, "UR": 1
        }.get(r, 1))
    idx = random.choices(range(len(pool)), weights=weights, k=1)[0]
    base = girls[idx]

    # create player
    pl = Player(user_id=uid, currency=500, girls=[])
    # create first girl
    g = _make_girl_from_catalog_entry(base, counter=1)
    g.uid = _alloc_girl_uid(g.base_id, uid, 1)
    pl.girls.append(g)

    save_player(pl)
    return pl

def roll_gacha(uid: int, times: int = 1) -> List[Girl]:
    """
    Roll `times` girls and append to player's collection.
    Returns the list of newly obtained girls.
    """
    pl = load_player(uid)
    if not pl:
        raise RuntimeError("Player not found.")

    cat = load_catalog()
    girls = cat.get("girls", [])
    if not girls:
        raise RuntimeError("Girls catalog is empty.")

    # Weighted table for rarity
    def pick_entry() -> dict:
        idx = random.choices(
            range(len(girls)),
            weights=[{"R":70,"SR":20,"SSR":9,"UR":1}.get(x.get("rarity","R"),1) for x in girls],
            k=1
        )[0]
        return girls[idx]

    added: List[Girl] = []
    start_idx = len(pl.girls) + 1
    for i in range(times):
        base = pick_entry()
        g = _make_girl_from_catalog_entry(base, counter=start_idx + i)
        g.uid = _alloc_girl_uid(g.base_id, uid, start_idx + i)
        pl.girls.append(g)
        added.append(g)

    save_player(pl)
    return added

# -----------------------------------------------------------------------------
# Market
# -----------------------------------------------------------------------------

def _market_path(uid: int) -> str:
    return os.path.join(MARKET_DIR, f"{uid}.json")

def save_market(m: Market):
    _write_json(_market_path(m.user_id), m.model_dump(mode="json"))

def load_market(uid: int) -> Optional[Market]:
    raw = _read_json(_market_path(uid))
    return Market(**raw) if raw else None

def generate_market(uid: int, jobs_count: int = 5, forced_level: int | None = None) -> Market:
    """
    Generate market based on player's reputation → market level.
    Optional forced_level overrides the reputation-based level.
    """
    pl = load_player(uid)  # fixed: no self-import
    lvl = forced_level if forced_level is not None else market_level_from_rep(pl.reputation if pl else 0)

    jobs: List[Job] = []
    for i in range(jobs_count):
        demand_main = random.choice(MAIN_SKILLS)
        demand_level = random.randint(0, max(1, lvl + 1))
        demand_sub = random.choice(SUB_SKILLS)
        demand_sub_level = random.randint(0, max(1, lvl + 1))
        pay = 50 + demand_level * 20 + demand_sub_level * 15 + lvl * 10
        jobs.append(Job(
            job_id=f"J{i+1}",
            demand_main=demand_main,
            demand_level=demand_level,
            demand_sub=demand_sub,
            demand_sub_level=demand_sub_level,
            pay=pay,
            difficulty=random.randint(1, 3),
        ))
    return Market(user_id=uid, jobs=jobs, level=lvl)

def refresh_market_if_stale(uid: int, max_age_sec: int = 300, forced_level: int | None = None) -> Market:
    """
    Return cached market if it's fresh enough; otherwise regenerate & save.
    If max_age_sec == 0 → force refresh.
    forced_level forces a specific market level.
    """
    m = load_market(uid)
    if (not m or max_age_sec == 0 or (time.time() - m.ts) > max_age_sec or
            (forced_level is not None and m.level != forced_level)):
        m = generate_market(uid, forced_level=forced_level)
        m.ts = int(time.time())
        save_market(m)
    return m

# -----------------------------------------------------------------------------
# Job resolution
# -----------------------------------------------------------------------------

def resolve_job(pl: Player, job: Job, girl: Girl) -> dict:
    """
    Business rules:
    - Hard fail if girl's skills are below the required levels.
    - Refuse job if main/sub skill is BLOCKED by preferences.
    - Payout bonuses from girl's level and overmatching.
    - L0 requirements are valid (>= demand, including 0).
    - Deterministic skill XP with preference multipliers.
    - 3% pregnancy chance on VAGINAL success if not already pregnant.
    """
    # Regen before we check/consume stamina (also auto-frees pregnancy at 30/30)
    girl.apply_regen()

    # 🚫 Block any job while pregnant
    if girl.pregnant:
        return {"ok": False, "reason": "Girl is pregnant", "reward": 0}

    STA_COST = 10
    if girl.stamina < STA_COST:
        return {"ok": False, "reason": "Not enough stamina", "reward": 0}

    # Preference-based refusal
    if girl.prefs_skills.get(job.demand_main, "true") == PREF_BLOCKED:
        return {"ok": False, "reason": f"Refused: main skill {job.demand_main} is blocked", "reward": 0}
    if job.demand_sub and girl.prefs_subskills.get(job.demand_sub, "true") == PREF_BLOCKED:
        return {"ok": False, "reason": f"Refused: sub-skill {job.demand_sub} is blocked", "reward": 0}

    # Level checks (>= demand)
    main_lvl = get_level(girl.skills, job.demand_main)
    if main_lvl < job.demand_level:
        return {"ok": False, "reason": "Skill mismatch (main too low)", "reward": 0}

    sub_name = getattr(job, "demand_sub", None)
    sub_need = getattr(job, "demand_sub_level", 0)
    sub_lvl = 0
    if sub_name:
        sub_lvl = get_level(girl.subskills, sub_name)
        if sub_lvl < sub_need:
            return {"ok": False, "reason": "Skill mismatch (sub-skill too low)", "reward": 0}

    # Payout with bonuses
    level_bonus = (girl.level - 1) * 5
    over_main = max(0, main_lvl - job.demand_level) * 10
    over_sub  = max(0, sub_lvl  - sub_need)         * 10 if sub_name else 0
    reward = int(job.pay + level_bonus + over_main + over_sub)

    # Consume stamina
    girl.stamina = max(0, girl.stamina - STA_COST)

    # Girl EXP / level-ups (cap 9999)
    girl.exp += 10 + job.difficulty * 5
    while girl.level < 9999 and girl.exp >= level_xp_threshold(girl.level):
        girl.exp -= level_xp_threshold(girl.level)
        girl.level += 1
        if girl.level >= 9999:
            girl.exp = 0
            break

    # Deterministic skill XP with preference multipliers
    def _mul(pref_map: Dict[str, str], key: str) -> float:
        return 1.5 if pref_map.get(key, "true") == PREF_FAV else 1.0

    main_mul = _mul(girl.prefs_skills, job.demand_main)
    main_xp  = int((8 + job.difficulty * 2 + max(0, main_lvl - job.demand_level) * 3) * main_mul)
    add_skill_xp(girl.skills, job.demand_main, main_xp)

    if sub_name:
        sub_mul = _mul(girl.prefs_subskills, sub_name)
        sub_xp  = int((5 + job.difficulty * 2 + max(0, sub_lvl - sub_need) * 3) * sub_mul)
        add_skill_xp(girl.subskills, sub_name, sub_xp)

    # Currency + reputation
    pl.currency += reward
    pl.reputation += 5 + job.difficulty * 2

    # Pregnancy: 3% on VAGINAL success if not pregnant
    if sub_name == "VAGINAL" and not girl.pregnant:
        if random.random() < 0.03:
            girl.pregnant = True
            girl.pregnant_since_ts = int(time.time())

    return {"ok": True, "reason": "Success", "reward": reward}

# -----------------------------------------------------------------------------
# Dismantle
# -----------------------------------------------------------------------------

def dismantle_girl(pl: Player, girl_uid: str) -> dict:
    """
    Remove a girl from player's roster and convert her to coins.
    Reputation gain is based on rarity.
    """
    g = pl.get_girl(girl_uid)
    if not g:
        return {"ok": False, "reason": "Girl not found", "reward": 0, "name": "", "rarity": ""}

    base_reward = {"R": 50, "SR": 150, "SSR": 400, "UR": 1000}
    reward = base_reward.get(g.rarity, 50) + g.level * 20

    # payout
    pl.currency += reward
    # remove
    pl.girls = [gg for gg in pl.girls if gg.uid != girl_uid]

    # reputation gain (rarity-based)
    rep_gain_by_rarity = {"R": 1, "SR": 2, "SSR": 4, "UR": 6}
    pl.reputation += rep_gain_by_rarity.get(g.rarity, 1)

    return {
        "ok": True,
        "reason": "Dismantled",
        "reward": reward,
        "name": g.name,
        "rarity": g.rarity,
    }
