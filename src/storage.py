from __future__ import annotations

import json
import os
import random
import time
from typing import Optional, Tuple, Dict, Any, List

from .models import (
    Player, Girl, Market, Job, BrothelState,
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

    pl = Player(**raw)
    pl.ensure_brothel()
    for g in pl.girls:
        g.normalize_skill_structs()
        # ensure new stat fields exist even if data was created before the update
        g.ensure_stat_defaults()
    return pl

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
    g.health = g.health_max
    g.stamina = g.stamina_max
    g.lust = g.lust_max
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
    pl.ensure_brothel()
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
    brothel = pl.ensure_brothel() if pl else None
    lvl = forced_level if forced_level is not None else market_level_from_rep(pl.reputation if pl else 0)

    base_jobs = jobs_count
    if brothel:
        dynamic_jobs = 2 + lvl + brothel.rooms
        dynamic_jobs += max(0, brothel.popularity // 40)
        base_jobs = max(base_jobs, dynamic_jobs)
    jobs_total = int(max(3, min(8, base_jobs)))

    jobs: List[Job] = []
    for i in range(jobs_total):
        demand_main = random.choice(MAIN_SKILLS)
        demand_level = random.randint(0, max(1, lvl + 1))
        demand_sub = random.choice(SUB_SKILLS)
        demand_sub_level = random.randint(0, max(1, lvl + 1))
        pay = 50 + demand_level * 20 + demand_sub_level * 15 + lvl * 10
        if brothel:
            pay += brothel.allure_level * 12
            pay += brothel.popularity // 5
            pay += max(-20, int((brothel.cleanliness - 70) * 0.8))
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

def evaluate_job(girl: Girl, job: Job, brothel: BrothelState | None = None) -> dict:
    """Compute derived metrics for a girl attempting a job."""
    girl.ensure_stat_defaults()
    if brothel:
        brothel.ensure_bounds()

    main_lvl = get_level(girl.skills, job.demand_main)
    sub_name = getattr(job, "demand_sub", None)
    sub_need = getattr(job, "demand_sub_level", 0)
    sub_lvl = get_level(girl.subskills, sub_name) if sub_name else 0

    blocked_main = girl.prefs_skills.get(job.demand_main, "true") == PREF_BLOCKED
    blocked_sub = False
    if sub_name:
        blocked_sub = girl.prefs_subskills.get(sub_name, "true") == PREF_BLOCKED

    meets_main = main_lvl >= job.demand_level
    meets_sub = (sub_lvl >= sub_need) if sub_name else True

    stamina_cost_base = 12 + job.difficulty * 4
    stamina_cost = int(max(6, stamina_cost_base - max(0, girl.endurance_level - 1) * 2))

    stamina_ratio = girl.stamina / girl.stamina_max if girl.stamina_max else 0
    health_ratio = girl.health / girl.health_max if girl.health_max else 0
    lust_ratio = girl.lust / girl.lust_max if girl.lust_max else 0

    diff_main = main_lvl - job.demand_level
    diff_sub = sub_lvl - sub_need

    lust_cost_base = 9 + job.difficulty * 3
    lust_cost = int(max(4, lust_cost_base - max(0, girl.lust_level - 1)))
    lust_ok = girl.lust >= lust_cost

    success_chance = 0.55
    success_chance += diff_main * 0.08
    success_chance += diff_sub * 0.05
    success_chance += (stamina_ratio - 0.5) * 0.25
    success_chance += (health_ratio - 0.5) * 0.20
    success_chance += max(0, girl.endurance_level - 1) * 0.03
    success_chance += (lust_ratio - 0.5) * 0.28
    if lust_ratio < 0.3:
        success_chance -= (0.3 - lust_ratio) * 0.35
    success_chance -= (job.difficulty - 1) * 0.08

    reward_multiplier = 1.0
    reward_multiplier += diff_main * 0.06
    reward_multiplier += diff_sub * 0.03
    reward_multiplier += (girl.level - 1) * 0.02
    reward_multiplier += max(0, girl.endurance_level - 1) * 0.04
    reward_multiplier += (stamina_ratio - 0.7) * 0.15
    reward_multiplier += (health_ratio - 0.7) * 0.12
    reward_multiplier += (lust_ratio - 0.6) * 0.32
    if lust_ratio > 0.85:
        reward_multiplier += (lust_ratio - 0.85) * 0.14

    injury_base = 0.12 + (job.difficulty - 1) * 0.08
    injury_base -= diff_main * 0.025
    injury_base -= diff_sub * 0.015
    injury_base -= max(0, girl.endurance_level - 1) * 0.03
    injury_base -= stamina_ratio * 0.12
    injury_base -= health_ratio * 0.10
    injury_base -= (lust_ratio - 0.5) * 0.12
    if lust_ratio < 0.25:
        injury_base += (0.25 - lust_ratio) * 0.28
    if lust_ratio > 0.9:
        injury_base += (lust_ratio - 0.9) * 0.35

    if brothel:
        success_chance += brothel.success_bonus()
        reward_multiplier *= brothel.reward_modifier()
        injury_base *= brothel.injury_modifier()
        lust_cost = max(1, int(lust_cost * brothel.lust_modifier()))

    success_chance = max(0.05, min(0.97, success_chance))

    reward_multiplier = max(0.45, min(2.5, reward_multiplier))

    injury_chance = max(0.03, min(0.7, injury_base))

    injury_min = max(5, 8 + job.difficulty * 4 - max(0, diff_main) * 2)
    injury_max = max(injury_min + 2, 18 + job.difficulty * 6 - max(0, diff_main + diff_sub) * 2)

    base_reward = job.pay + max(0, girl.level - 1) * 5
    base_reward += max(0, diff_main) * 10
    if sub_name:
        base_reward += max(0, diff_sub) * 10

    health_ok = girl.health > 0
    stamina_ok = girl.stamina >= stamina_cost
    can_attempt = (
        not blocked_main
        and not blocked_sub
        and meets_main
        and meets_sub
        and health_ok
        and stamina_ok
        and lust_ok
    )

    return {
        "main_lvl": main_lvl,
        "sub_lvl": sub_lvl,
        "blocked_main": blocked_main,
        "blocked_sub": blocked_sub,
        "meets_main": meets_main,
        "meets_sub": meets_sub,
        "health_ok": health_ok,
        "stamina_ok": stamina_ok,
        "lust_ok": lust_ok,
        "can_attempt": can_attempt,
        "stamina_cost": stamina_cost,
        "stamina_ratio": stamina_ratio,
        "health_ratio": health_ratio,
        "lust_cost": lust_cost,
        "lust_ratio": lust_ratio,
        "success_chance": success_chance,
        "reward_multiplier": reward_multiplier,
        "injury_chance": injury_chance,
        "injury_range": (injury_min, injury_max),
        "base_reward": base_reward,
        "expected_reward": base_reward * success_chance * (reward_multiplier if can_attempt else 0),
    }


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
    brothel = pl.ensure_brothel()
    brothel.apply_decay()

    # 🚫 Block any job while pregnant
    if girl.pregnant:
        return {"ok": False, "reason": "Girl is pregnant", "reward": 0}

    info = evaluate_job(girl, job, brothel)

    STA_COST = info["stamina_cost"]
    if girl.health <= 0:
        return {"ok": False, "reason": "Girl is injured", "reward": 0}
    if girl.stamina < STA_COST:
        return {"ok": False, "reason": "Not enough stamina", "reward": 0}
    if not info["lust_ok"]:
        return {
            "ok": False,
            "reason": "Not aroused enough",
            "reward": 0,
            "success_chance": info["success_chance"],
            "injury_chance": info["injury_chance"],
            "stamina_cost": STA_COST,
            "lust_cost": info["lust_cost"],
        }

    # Preference-based refusal
    if info["blocked_main"]:
        return {"ok": False, "reason": f"Refused: main skill {job.demand_main} is blocked", "reward": 0}
    if job.demand_sub and info["blocked_sub"]:
        return {"ok": False, "reason": f"Refused: sub-skill {job.demand_sub} is blocked", "reward": 0}

    # Level checks (>= demand)
    main_lvl = info["main_lvl"]
    if not info["meets_main"]:
        return {"ok": False, "reason": "Skill mismatch (main too low)", "reward": 0}

    sub_name = getattr(job, "demand_sub", None)
    sub_need = getattr(job, "demand_sub_level", 0)
    sub_lvl = info["sub_lvl"] if sub_name else 0
    if sub_name:
        if not info["meets_sub"]:
            return {"ok": False, "reason": "Skill mismatch (sub-skill too low)", "reward": 0}

    # Payout with bonuses
    base_reward = info["base_reward"]

    # Consume stamina
    girl.stamina = max(0, girl.stamina - STA_COST)
    girl.stamina_last_ts = int(time.time())

    lust_before = girl.lust

    # Determine outcome chances
    success_roll = random.random()
    success = success_roll < info["success_chance"]
    reward_multiplier = info["reward_multiplier"] if success else 0.0
    reward = int(base_reward * reward_multiplier)

    clean_before = brothel.cleanliness
    morale_before = brothel.morale
    pop_before = brothel.popularity
    pool_before = brothel.upkeep_pool
    facility_levels_before = {
        key: brothel.facility_level(key)
        for key in ("comfort", "hygiene", "security", "allure")
    }

    # Girl EXP / level-ups (cap 9999)
    base_xp_gain = 8 + job.difficulty * 5
    if success:
        base_xp_gain += max(0, main_lvl - job.demand_level) * 2
    else:
        base_xp_gain = max(4, base_xp_gain // 2)
    girl.exp += base_xp_gain
    while girl.level < 9999 and girl.exp >= level_xp_threshold(girl.level):
        girl.exp -= level_xp_threshold(girl.level)
        girl.level += 1
        if girl.level >= 9999:
            girl.exp = 0
            break
    girl.recalc_limits()
    girl.health = min(girl.health, girl.health_max)
    girl.stamina = min(girl.stamina, girl.stamina_max)

    # Deterministic skill XP with preference multipliers
    def _mul(pref_map: Dict[str, str], key: str) -> float:
        return 1.5 if pref_map.get(key, "true") == PREF_FAV else 1.0

    main_mul = _mul(girl.prefs_skills, job.demand_main)
    base_main_xp = 6 + job.difficulty * 2 + max(0, main_lvl - job.demand_level) * 3
    main_xp = int(base_main_xp * main_mul * (1.0 if success else 0.4))
    add_skill_xp(girl.skills, job.demand_main, main_xp)

    if sub_name:
        sub_mul = _mul(girl.prefs_subskills, sub_name)
        base_sub_xp = 4 + job.difficulty * 2 + max(0, sub_lvl - sub_need) * 3
        sub_xp  = int(base_sub_xp * sub_mul * (1.0 if success else 0.4))
        add_skill_xp(girl.subskills, sub_name, sub_xp)

    # Currency + reputation
    if reward > 0:
        pl.currency += reward
        pl.reputation += 5 + job.difficulty * 2

    # Pregnancy: 3% on VAGINAL success if not pregnant
    if sub_name == "VAGINAL" and not girl.pregnant:
        if success and random.random() < 0.03:
            girl.pregnant = True
            girl.pregnant_since_ts = int(time.time())

    # Injury resolution
    injury_chance = info["injury_chance"]
    if not success:
        injury_chance = min(0.95, injury_chance * 1.5)
    injured = False
    injury_amount = 0
    if random.random() < injury_chance:
        inj_min, inj_max = info["injury_range"]
        injury_amount = random.randint(inj_min, inj_max)
        girl.health = max(0, girl.health - injury_amount)
        injured = injury_amount > 0

    # Lust consumption + XP progression
    lust_cost = info["lust_cost"]
    if success:
        lust_spent = min(lust_before, max(1, int(lust_cost * 1.0)))
    else:
        lust_spent = min(lust_before, max(1, lust_cost // 2))
    girl.lust = max(0, girl.lust - lust_spent)
    girl.lust_last_ts = int(time.time())

    lust_xp_gain = 4 + job.difficulty * (3 if success else 2)
    lust_xp_gain += int(info["lust_ratio"] * 5)
    if success and reward_multiplier >= 1.1:
        lust_xp_gain += 2
    if injured:
        lust_xp_gain = max(2, lust_xp_gain - 1)
    girl.gain_lust_xp(lust_xp_gain)

    # Stat XP progression for vitality/endurance
    endurance_xp_gain = max(1, int(STA_COST * (1.1 if success else 0.7)) + job.difficulty * (3 if success else 2))
    girl.gain_endurance_xp(endurance_xp_gain)
    vitality_xp_gain = 2 + job.difficulty * (3 if success else 2)
    if injured:
        vitality_xp_gain += max(1, injury_amount // 4)
    girl.gain_vitality_xp(vitality_xp_gain)

    brothel.register_job_outcome(success, injured, job, reward)
    brothel_deltas = {
        "cleanliness": brothel.cleanliness - clean_before,
        "morale": brothel.morale - morale_before,
        "popularity": brothel.popularity - pop_before,
        "upkeep": brothel.upkeep_pool - pool_before,
    }
    brothel_levels = {
        key: brothel.facility_level(key) - facility_levels_before[key]
        for key in facility_levels_before
    }

    return {
        "ok": success,
        "reason": "Success" if success else "Failed",
        "reward": reward,
        "base_reward": base_reward,
        "success_chance": info["success_chance"],
        "injury_chance": injury_chance,
        "injured": injured,
        "injury_amount": injury_amount,
        "stamina_cost": STA_COST,
        "reward_multiplier": reward_multiplier,
        "lust_cost": lust_spent,
        "lust_before": lust_before,
        "lust_after": girl.lust,
        "lust_after_ratio": girl.lust / girl.lust_max if girl.lust_max else 0.0,
        "lust_ratio_before": info["lust_ratio"],
        "brothel_diff": brothel_deltas,
        "brothel_levels": brothel_levels,
    }

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
