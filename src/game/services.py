"""High level game logic built on top of the data store."""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .repository import DataStore
from .balance import BalanceProfile, load_balance_profile
from ..models import (
    Player,
    Girl,
    Market,
    Job,
    BrothelState,
    MAIN_SKILLS,
    SUB_SKILLS,
    BROTHEL_FACILITY_NAMES,
    normalize_skill_map,
    normalize_prefs,
    get_level,
    add_skill_xp,
    level_xp_threshold,
    market_level_from_rep,
    PREF_BLOCKED,
    PREF_FAV,
)


class GameService:
    """Encapsulates the gameplay rules and persistence helpers."""

    def __init__(self, store: DataStore | None = None):
        self.store = store or DataStore()
        self._config_cache: dict | None = None
        self._config_cache_key: tuple[str, int | None] | None = None
        self._config_path: Path | None = None
        self._config_default_base = self.store.base_dir
        self._balance_cache: BalanceProfile | None = None

    def _load_config(self) -> dict:
        from .. import assets_util

        candidates: list[Path] = []
        if self._config_path is not None:
            candidates.append(self._config_path)

        default_path = (self._config_default_base / "config.json").resolve()
        if default_path not in candidates:
            candidates.append(default_path)

        current_path = (self.store.base_dir / "config.json").resolve()
        if current_path not in candidates:
            candidates.append(current_path)

        path = candidates[0]
        mtime: int | None = None
        for candidate in candidates:
            try:
                current_mtime = candidate.stat().st_mtime_ns
            except FileNotFoundError:
                continue

            path = candidate
            mtime = current_mtime
            if self._config_path != candidate:
                self._config_path = candidate
            break

        cache_key = (str(path), mtime)

        if self._config_cache is not None and self._config_cache_key == cache_key:
            assets_util.set_assets_dir(self.store.assets_dir)
            return self._config_cache

        if mtime is None:
            data = {}
        else:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (FileNotFoundError, json.JSONDecodeError):
                data = {}

        if not isinstance(data, dict):
            data = {}

        paths_cfg = data.get("paths") if isinstance(data, dict) else None
        self.store.configure_paths(paths_cfg if isinstance(paths_cfg, dict) else None)
        assets_util.set_assets_dir(self.store.assets_dir)

        self._config_cache = data
        self._config_cache_key = cache_key
        self._balance_cache = None
        return self._config_cache

    def get_config(self) -> dict:
        return self._load_config()

    @property
    def config(self) -> dict:
        return self._load_config()

    def get_balance_profile(self) -> BalanceProfile:
        if self._balance_cache is None:
            config = self._load_config()
            balance_cfg = config.get("balance") if isinstance(config, dict) else None
            mapping = balance_cfg if isinstance(balance_cfg, dict) else None
            self._balance_cache = load_balance_profile(mapping)
        return self._balance_cache

    def _starter_girl_from_config(self, entries: List[dict]) -> Optional[dict]:
        config = self._load_config()
        gacha_cfg = config.get("gacha")
        if not isinstance(gacha_cfg, dict):
            return None

        raw_id = gacha_cfg.get("starter_girl_id")
        if not raw_id:
            return None

        starter_id = str(raw_id).strip()
        if not starter_id:
            return None

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            if entry_id is None:
                continue
            if str(entry_id) == starter_id:
                return entry

        return None

    # ------------------------------------------------------------------
    # Player persistence
    # ------------------------------------------------------------------
    def save_player(self, player: Player) -> None:
        player.ensure_brothel()
        player.brothel.prune_training(player.girls)
        payload = player.model_dump(mode="json", by_alias=True)
        self.store.write_json(self.store.user_path(player.user_id), payload)

    def load_player(self, uid: int) -> Optional[Player]:
        raw = self.store.read_json(self.store.user_path(uid))
        if not raw:
            return None

        girls = raw.get("girls", [])
        for girl in girls:
            skills_raw = girl.get("skills") or {}
            if not isinstance(skills_raw, dict):
                skills_raw = {}
            girl["skills"] = normalize_skill_map(skills_raw, MAIN_SKILLS)

            subskills_raw = girl.get("subskills") or {}
            if not isinstance(subskills_raw, dict):
                subskills_raw = {}
            girl["subskills"] = normalize_skill_map(subskills_raw, SUB_SKILLS)

            girl["prefs_skills"] = normalize_prefs(girl.get("prefs_skills", {}), MAIN_SKILLS)
            girl["prefs_subskills"] = normalize_prefs(girl.get("prefs_subskills", {}), SUB_SKILLS)

        player = Player(**raw)
        brothel = player.ensure_brothel()
        player.renown = brothel.renown
        brothel.prune_training(player.girls)
        for g in player.girls:
            g.normalize_skill_structs()
            g.ensure_stat_defaults()
        return player

    # ------------------------------------------------------------------
    # Catalog / gacha
    # ------------------------------------------------------------------
    def _normalize_base_id(self, value: str | int | None) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    def _split_uid_counter(self, uid: str | None) -> tuple[str, int | None]:
        if not isinstance(uid, str):
            return "", None
        value = uid.strip()
        if not value:
            return "", None
        prefix, sep, suffix = value.partition("#")
        prefix = prefix.strip()
        if not sep:
            return prefix, None
        suffix = suffix.strip()
        if not suffix:
            return prefix, None
        try:
            counter = int(suffix)
        except ValueError:
            return prefix, None
        if counter <= 0:
            return prefix, None
        return prefix, counter

    def _collect_uid_usage(self, girls: Iterable[Girl | dict] | None) -> dict[str, set[int]]:
        usage: dict[str, set[int]] = {}
        if not girls:
            return usage

        for existing in girls:
            if isinstance(existing, Girl):
                existing_uid = existing.uid
                existing_base = existing.base_id
            elif isinstance(existing, dict):
                existing_uid = existing.get("uid")
                existing_base = existing.get("base_id")
            else:
                continue

            prefix, counter = self._split_uid_counter(existing_uid)
            existing_base_norm = self._normalize_base_id(existing_base)
            stripped_uid = existing_uid.strip() if isinstance(existing_uid, str) else ""

            keys = {existing_base_norm or "", prefix or ""}
            for key in keys:
                used = usage.setdefault(key, set())
                if counter is not None:
                    used.add(counter)
                elif stripped_uid == key:
                    used.add(1)

        return usage

    def _alloc_girl_uid(
        self,
        base_id: str | int,
        girls: Iterable[Girl] | None = None,
        uid_usage: dict[str, set[int]] | None = None,
    ) -> str:
        normalized_base = self._normalize_base_id(base_id)
        key = normalized_base or ""

        if uid_usage is not None:
            used = uid_usage.setdefault(key, set())
        else:
            used: set[int] = set()
            girls_iter: Iterable[Girl | dict]
            if girls is None:
                girls_iter = ()
            else:
                girls_iter = girls
            for existing in girls_iter:
                if isinstance(existing, Girl):
                    existing_uid = existing.uid
                    existing_base = existing.base_id
                elif isinstance(existing, dict):
                    existing_uid = existing.get("uid")
                    existing_base = existing.get("base_id")
                else:
                    continue

                prefix, counter = self._split_uid_counter(existing_uid)
                existing_base_norm = self._normalize_base_id(existing_base)

                matches_base = False
                if normalized_base:
                    if prefix == normalized_base or existing_base_norm == normalized_base:
                        matches_base = True
                else:
                    if prefix == "" or existing_base_norm == "":
                        matches_base = True
                if not matches_base:
                    continue

                if counter is not None:
                    used.add(counter)
                elif isinstance(existing_uid, str) and existing_uid.strip() == normalized_base:
                    used.add(1)

        counter = 1
        while counter in used:
            counter += 1

        if uid_usage is not None:
            used.add(counter)

        if normalized_base:
            return f"{normalized_base}#{counter}"
        return f"#{counter}"

    def _make_girl_from_catalog_entry(self, base: dict, uid: str) -> Girl:
        base_id = self._normalize_base_id(base["id"])
        name = base["name"]
        rarity = base["rarity"]
        image_url = base.get("image_url", "")

        base_level = int(base.get("base", {}).get("level", 1))
        base_skills = normalize_skill_map(base.get("base", {}).get("skills", {}), MAIN_SKILLS)
        base_subskills = normalize_skill_map(base.get("base", {}).get("subskills", {}), SUB_SKILLS)

        bio = base.get("bio", {}) or {}
        prefs = base.get("prefs", {}) or {}

        girl = Girl(
            uid=str(uid),
            base_id=base_id,
            name=name,
            rarity=rarity,
            level=base_level,
            image_url=image_url,
            skills=base_skills,
            subskills=base_subskills,
            breast_size=bio.get("breast_size"),
            body_shape=bio.get("body_shape"),
            age=bio.get("age"),
            height_cm=bio.get("height_cm"),
            weight_kg=bio.get("weight_kg"),
            traits=bio.get("traits", []),
            prefs_skills=normalize_prefs(prefs.get("skills", {}), MAIN_SKILLS),
            prefs_subskills=normalize_prefs(prefs.get("subskills", {}), SUB_SKILLS),
        )
        girl.normalize_skill_structs()
        girl.health = girl.health_max
        girl.stamina = girl.stamina_max
        girl.lust = girl.lust_max
        return girl

    def grant_starter_pack(self, uid: int) -> Player:
        catalog = self.store.load_catalog()
        entries = catalog.get("girls", [])
        if not entries:
            raise RuntimeError("Girls catalog is empty.")

        base_entry = self._starter_girl_from_config(entries)
        if base_entry is None:
            weights = [
                {"R": 70, "SR": 20, "SSR": 9, "UR": 1}.get(entry.get("rarity", "R"), 1)
                for entry in entries
            ]
            index = random.choices(range(len(entries)), weights=weights, k=1)[0]
            base_entry = entries[index]

        config = self._load_config()
        gacha_cfg = config.get("gacha") if isinstance(config, dict) else None
        raw_starter_coins = (gacha_cfg or {}).get("starter_coins", 500)
        try:
            starter_coins = int(raw_starter_coins)
        except (TypeError, ValueError):
            starter_coins = 500
        else:
            if starter_coins < 0:
                starter_coins = 0

        player = Player(user_id=uid, currency=starter_coins, girls=[])
        brothel = player.ensure_brothel()
        starter_renown = brothel.renown if brothel.renown > 0 else BrothelState().renown
        player.renown = starter_renown
        brothel.renown = starter_renown

        uid_usage = self._collect_uid_usage(player.girls)
        girl_uid = self._alloc_girl_uid(base_entry["id"], player.girls, uid_usage=uid_usage)
        girl = self._make_girl_from_catalog_entry(base_entry, uid=girl_uid)
        player.girls.append(girl)

        self.save_player(player)
        return player

    def roll_gacha(self, uid: int, times: int = 1) -> Tuple[List[Girl], int]:
        player = self.load_player(uid)
        if not player:
            raise RuntimeError("Player not found.")

        times = max(1, int(times))

        brothel = player.ensure_brothel()
        brothel.prune_training(player.girls)
        slots_left = max(0, brothel.rooms - len(player.girls))
        if slots_left <= 0:
            raise RuntimeError("All rooms are occupied. Expand your brothel first.")
        if times > slots_left:
            raise RuntimeError(
                f"Only {slots_left} room(s) available. Reduce rolls or expand rooms."
            )

        config = self._load_config()
        gacha_cfg = config.get("gacha") if isinstance(config, dict) else None
        raw_cost = (gacha_cfg or {}).get("roll_cost", 100)
        try:
            roll_cost = max(0, int(raw_cost))
        except (TypeError, ValueError):
            roll_cost = 100
        total_cost = roll_cost * times

        if player.currency < total_cost:
            raise RuntimeError("Not enough coins.")

        catalog = self.store.load_catalog()
        entries = catalog.get("girls", [])
        if not entries:
            raise RuntimeError("Girls catalog is empty.")

        weights = [
            {"R": 70, "SR": 20, "SSR": 9, "UR": 1}.get(entry.get("rarity", "R"), 1)
            for entry in entries
        ]

        def pick_entry() -> dict:
            return random.choices(entries, weights=weights, k=1)[0]

        original_currency = player.currency
        original_girls_len = len(player.girls)
        added: List[Girl] = []
        uid_usage = self._collect_uid_usage(player.girls)

        try:
            for _ in range(times):
                base_entry = pick_entry()
                girl_uid = self._alloc_girl_uid(
                    base_entry["id"], player.girls, uid_usage=uid_usage
                )
                girl = self._make_girl_from_catalog_entry(base_entry, uid=girl_uid)
                player.girls.append(girl)
                added.append(girl)

            if total_cost:
                player.currency -= total_cost

            self.save_player(player)
        except Exception:
            player.currency = original_currency
            del player.girls[original_girls_len:]
            raise

        return added, total_cost

    # ------------------------------------------------------------------
    # Market persistence
    # ------------------------------------------------------------------
    def save_market(self, market: Market) -> None:
        self.store.write_json(self.store.market_path(market.user_id), market.model_dump(mode="json"))

    def _dedupe_job_ids(self, raw_market: dict) -> bool:
        if not raw_market:
            return False
        jobs = raw_market.get("jobs")
        if not isinstance(jobs, list):
            return False
        seen: set[str] = set()
        changed = False
        for idx, job in enumerate(jobs, start=1):
            if not isinstance(job, dict):
                continue
            original_id = job.get("job_id")
            original_text = str(original_id) if original_id is not None else ""
            job_id = original_text.strip()
            base = job_id if job_id and job_id.lower() != "none" else f"J{idx}"
            base = base.strip() or f"J{idx}"
            candidate = base
            suffix = 2
            normalized = candidate.strip().casefold()
            while not normalized or normalized == "none" or normalized in seen:
                candidate = f"{base}-{suffix}"
                suffix += 1
                normalized = candidate.strip().casefold()
            if candidate != job_id or original_text != job_id:
                job["job_id"] = candidate
                changed = True
            seen.add(normalized)
        if changed:
            raw_market["jobs"] = jobs
        return changed

    def load_market(self, uid: int) -> Optional[Market]:
        raw = self.store.read_json(self.store.market_path(uid))
        if not raw:
            return None
        changed = self._dedupe_job_ids(raw)
        market = Market(**raw)
        if changed:
            self.save_market(market)
        return market

    def generate_market(self, uid: int, jobs_count: int = 5, forced_level: int | None = None) -> Market:
        config = self._load_config()
        market_cfg = config.get("market") if isinstance(config, dict) else None

        player = self.load_player(uid)
        brothel = player.ensure_brothel() if player else None
        renown = player.renown if player else 0
        level = forced_level if forced_level is not None else market_level_from_rep(renown)

        balance = self.get_balance_profile()

        facility_influence = 0
        if brothel:
            facility_influence = (
                brothel.facility_level("allure")
                + brothel.facility_level("comfort")
                + brothel.facility_level("security") // 2
            )
        fallback_jobs = int(jobs_count) if jobs_count else 1
        raw_jobs_per_level = (market_cfg or {}).get("jobs_per_level", fallback_jobs)
        try:
            jobs_per_level = int(raw_jobs_per_level)
        except (TypeError, ValueError):
            jobs_per_level = fallback_jobs
        if jobs_per_level <= 0:
            jobs_per_level = fallback_jobs or 1
        jobs_per_level = max(1, jobs_per_level)

        level_multiplier = max(1, level + 1)
        base_jobs = jobs_per_level * level_multiplier
        base_jobs += max(0, brothel.rooms - 2 if brothel else 0)
        base_jobs += facility_influence // 2
        base_jobs += renown // 120
        jobs_total = int(max(1, min(10, base_jobs)))

        jobs: List[Job] = []
        for idx in range(jobs_total):
            demand_main = random.choice(MAIN_SKILLS)
            demand_level = random.randint(0, max(1, level + 1))
            demand_sub = random.choice(SUB_SKILLS)
            demand_sub_level = random.randint(0, max(1, level + 1))
            market_balance = balance.market
            pay = (
                market_balance.base_pay
                + demand_level * market_balance.main_step
                + demand_sub_level * market_balance.sub_step
                + level * market_balance.level_step
            )
            max_difficulty = max(0, level)
            allure_rolls = 1
            if brothel:
                pay += brothel.allure_level * market_balance.allure_bonus
                pay += brothel.facility_level("comfort") * market_balance.comfort_bonus
                pay += brothel.facility_level("security") * market_balance.security_bonus
                cleanliness_shift = int(
                    (brothel.cleanliness - market_balance.cleanliness_baseline)
                    * market_balance.cleanliness_weight
                )
                cleanliness_shift = max(
                    market_balance.cleanliness_min_bonus,
                    min(market_balance.cleanliness_max_bonus, cleanliness_shift),
                )
                pay += cleanliness_shift
                pay += brothel.renown // max(1, market_balance.renown_divisor)
                allure_rolls = max(1, 1 + brothel.facility_level("allure") // 3)
            pay = max(market_balance.min_pay, min(market_balance.max_pay, pay))
            difficulty = 0
            for _ in range(allure_rolls):
                roll = random.randint(0, max_difficulty)
                if roll > difficulty:
                    difficulty = roll
            jobs.append(
                Job(
                    job_id=f"J{idx + 1}",
                    demand_main=demand_main,
                    demand_level=demand_level,
                    demand_sub=demand_sub,
                    demand_sub_level=demand_sub_level,
                    pay=pay,
                    difficulty=difficulty,
                )
            )
        return Market(user_id=uid, jobs=jobs, level=level)

    def refresh_market_if_stale(
        self,
        uid: int,
        max_age_sec: int = 300,
        forced_level: int | None = None,
    ) -> Market:
        market = self.load_market(uid)
        if (
            not market
            or max_age_sec == 0
            or (time.time() - market.ts) > max_age_sec
            or (forced_level is not None and market.level != forced_level)
        ):
            market = self.generate_market(uid, forced_level=forced_level)
            market.ts = int(time.time())
            self.save_market(market)
        return market

    # ------------------------------------------------------------------
    # Job evaluation / resolution
    # ------------------------------------------------------------------
    def evaluate_job(self, girl: Girl, job: Job, brothel: BrothelState | None = None) -> dict:
        girl.ensure_stat_defaults()
        if brothel:
            brothel.ensure_bounds()

        training_blocked = bool(brothel.training_for(girl.uid)) if brothel else False

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

        balance = self.get_balance_profile()
        costs = balance.costs
        stamina_cost_base = costs.stamina_base + job.difficulty * costs.stamina_per_difficulty
        stamina_discount = max(0.0, girl.endurance_level - 1) * costs.stamina_endurance_discount
        stamina_cost = int(max(costs.stamina_min, stamina_cost_base - stamina_discount))

        stamina_ratio = girl.stamina / girl.stamina_max if girl.stamina_max else 0
        health_ratio = girl.health / girl.health_max if girl.health_max else 0
        lust_ratio = girl.lust / girl.lust_max if girl.lust_max else 0

        diff_main = main_lvl - job.demand_level
        diff_sub = sub_lvl - sub_need

        lust_cost_base = costs.lust_base + job.difficulty * costs.lust_per_difficulty
        lust_discount = max(0.0, girl.lust_level - 1) * costs.lust_level_discount
        lust_cost = int(max(costs.lust_min, lust_cost_base - lust_discount))
        lust_ok = girl.lust >= lust_cost

        success = balance.success
        success_chance = success.base
        success_chance += diff_main * success.main_weight
        success_chance += diff_sub * success.sub_weight
        success_chance += (stamina_ratio - success.stamina_midpoint) * success.stamina_weight
        success_chance += (health_ratio - success.health_midpoint) * success.health_weight
        success_chance += max(0, girl.endurance_level - 1) * success.endurance_weight
        success_chance += (lust_ratio - success.lust_midpoint) * success.lust_weight
        if lust_ratio < success.low_lust_threshold:
            success_chance -= (success.low_lust_threshold - lust_ratio) * success.low_lust_penalty
        success_chance -= (job.difficulty - 1) * success.difficulty_penalty

        reward = balance.reward
        reward_multiplier = reward.base_multiplier
        reward_multiplier += diff_main * reward.main_weight
        reward_multiplier += diff_sub * reward.sub_weight
        reward_multiplier += (girl.level - 1) * reward.level_weight
        reward_multiplier += max(0, girl.endurance_level - 1) * reward.endurance_weight
        reward_multiplier += (stamina_ratio - reward.stamina_midpoint) * reward.stamina_weight
        reward_multiplier += (health_ratio - reward.health_midpoint) * reward.health_weight
        reward_multiplier += (lust_ratio - reward.lust_midpoint) * reward.lust_weight
        if lust_ratio > reward.high_lust_threshold:
            reward_multiplier += (lust_ratio - reward.high_lust_threshold) * reward.high_lust_bonus

        injury = balance.injury
        injury_base = injury.base + (job.difficulty - 1) * injury.difficulty_weight
        injury_base -= diff_main * injury.main_weight
        injury_base -= diff_sub * injury.sub_weight
        injury_base -= max(0, girl.endurance_level - 1) * injury.endurance_weight
        injury_base -= (stamina_ratio - injury.stamina_midpoint) * injury.stamina_weight
        injury_base -= (health_ratio - injury.health_midpoint) * injury.health_weight
        injury_base -= (lust_ratio - injury.lust_midpoint) * injury.lust_weight
        if lust_ratio < injury.low_lust_threshold:
            injury_base += (injury.low_lust_threshold - lust_ratio) * injury.low_lust_penalty
        if lust_ratio > injury.high_lust_threshold:
            injury_base += (lust_ratio - injury.high_lust_threshold) * injury.high_lust_penalty

        if brothel:
            success_chance += brothel.success_bonus()
            reward_multiplier *= brothel.reward_modifier()
            injury_base *= brothel.injury_modifier()
            lust_cost = max(1, int(lust_cost * brothel.lust_modifier()))
            lust_ok = girl.lust >= lust_cost

        min_success, max_success = success.cap
        success_chance = max(min_success, min(max_success, success_chance))
        min_reward, max_reward = reward.cap
        reward_multiplier = max(min_reward, min(max_reward, reward_multiplier))
        min_injury, max_injury = injury.cap
        injury_chance = max(min_injury, min(max_injury, injury_base))

        injury_min = max(
            injury.injury_min_base,
            injury.injury_min_base
            + job.difficulty * injury.injury_min_difficulty
            - max(0, diff_main) * injury.injury_min_diff_reduction,
        )
        injury_max = max(
            injury_min + 2,
            injury.injury_max_base
            + job.difficulty * injury.injury_max_difficulty
            - max(0, diff_main + diff_sub) * injury.injury_max_diff_reduction,
        )

        base_reward = job.pay
        skill_ratio = 1.0
        if diff_main > 0:
            skill_ratio += diff_main * reward.main_rate
        if sub_name and diff_sub > 0:
            skill_ratio += diff_sub * reward.sub_rate
        min_ratio, max_ratio = reward.skill_ratio_cap
        skill_ratio = max(min_ratio, min(max_ratio, skill_ratio))
        if abs(skill_ratio - 1.0) > 1e-6:
            base_reward = int(round(base_reward * skill_ratio))
        base_reward += max(0, girl.level - 1) * reward.base_level_bonus
        if diff_main > 0:
            base_reward += diff_main * reward.base_main_bonus
        if sub_name and diff_sub > 0:
            base_reward += diff_sub * reward.base_sub_bonus

        health_ok = girl.health > 0
        stamina_ok = girl.stamina >= stamina_cost
        can_attempt = (
            not blocked_main
            and not blocked_sub
            and not training_blocked
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
            "training_blocked": training_blocked,
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
            "mentorship_bonus": girl.mentorship_bonus,
            "mentorship_focus_type": girl.mentorship_focus_type,
            "mentorship_focus": girl.mentorship_focus,
        }

    def resolve_job(self, player: Player, job: Job, girl: Girl) -> dict:
        brothel = player.ensure_brothel()
        brothel.apply_decay()
        girl.apply_regen(brothel)
        player.renown = brothel.renown

        if girl.pregnant:
            return {"ok": False, "reason": "Girl is pregnant", "reward": 0}

        if brothel.training_for(girl.uid):
            return {"ok": False, "reason": "Girl is currently in mentorship training", "reward": 0}

        info = self.evaluate_job(girl, job, brothel)

        if info.get("training_blocked"):
            return {"ok": False, "reason": "Girl is currently in mentorship training", "reward": 0}

        stamina_cost = info["stamina_cost"]
        if girl.health <= 0:
            return {"ok": False, "reason": "Girl is injured", "reward": 0}
        if girl.stamina < stamina_cost:
            return {"ok": False, "reason": "Not enough stamina", "reward": 0}
        if not info["lust_ok"]:
            return {
                "ok": False,
                "reason": "Not aroused enough",
                "reward": 0,
                "success_chance": info["success_chance"],
                "injury_chance": info["injury_chance"],
                "stamina_cost": stamina_cost,
                "lust_cost": info["lust_cost"],
            }

        if info["blocked_main"]:
            return {"ok": False, "reason": f"Refused: main skill {job.demand_main} is blocked", "reward": 0}
        if job.demand_sub and info["blocked_sub"]:
            return {"ok": False, "reason": f"Refused: sub-skill {job.demand_sub} is blocked", "reward": 0}

        if not info["meets_main"]:
            return {"ok": False, "reason": "Skill mismatch (main too low)", "reward": 0}

        sub_name = getattr(job, "demand_sub", None)
        sub_need = getattr(job, "demand_sub_level", 0)
        sub_lvl = info["sub_lvl"] if sub_name else 0
        if sub_name and not info["meets_sub"]:
            return {"ok": False, "reason": "Skill mismatch (sub-skill too low)", "reward": 0}

        base_reward = info["base_reward"]

        girl.stamina = max(0, girl.stamina - stamina_cost)
        girl.stamina_last_ts = int(time.time())

        lust_before = girl.lust

        success = random.random() < info["success_chance"]
        reward_multiplier = info["reward_multiplier"] if success else 0.0
        reward = int(base_reward * reward_multiplier)

        clean_before = brothel.cleanliness
        morale_before = brothel.morale
        renown_before = player.renown
        pool_before = brothel.upkeep_pool

        training_bonus_used = 0.0
        training_focus_type: Optional[str] = None
        training_focus: Optional[str] = None

        stored_focus_type = (girl.mentorship_focus_type or "any").lower()

        main_bonus = girl.consume_training_bonus_for("main", job.demand_main)
        if main_bonus > 0:
            training_bonus_used = max(training_bonus_used, main_bonus)
            if stored_focus_type == "any":
                training_focus_type = "any"
                training_focus = None
            else:
                training_focus_type = "main"
                training_focus = job.demand_main

        sub_bonus = 0.0
        if sub_name:
            sub_bonus = girl.consume_training_bonus_for("sub", sub_name)
            if sub_bonus > training_bonus_used:
                training_bonus_used = sub_bonus
                if stored_focus_type == "any":
                    training_focus_type = "any"
                    training_focus = None
                else:
                    training_focus_type = "sub"
                    training_focus = sub_name

        legacy_bonus = girl.consume_training_bonus_for("any", None)
        if legacy_bonus > training_bonus_used:
            training_bonus_used = legacy_bonus
            if training_focus_type is None:
                training_focus_type = "any"
                training_focus = None

        overall_xp_multiplier = 1.0
        main_xp_multiplier = 1.0
        sub_xp_multiplier = 1.0

        if training_bonus_used > 0:
            bonus_multiplier = 1.0 + training_bonus_used
            focus_type_norm = (training_focus_type or "").lower()
            focus_name_norm = (training_focus or "").lower() if training_focus else None

            if focus_type_norm == "any":
                overall_xp_multiplier = bonus_multiplier
            elif focus_type_norm == "main":
                current_main = (job.demand_main or "").lower()
                if focus_name_norm is None or focus_name_norm == current_main:
                    main_xp_multiplier = bonus_multiplier
            elif focus_type_norm == "sub" and sub_name:
                current_sub = sub_name.lower()
                if focus_name_norm is None or focus_name_norm == current_sub:
                    sub_xp_multiplier = bonus_multiplier

        base_xp_gain = 8 + job.difficulty * 5
        if success:
            base_xp_gain += max(0, info["main_lvl"] - job.demand_level) * 2
        else:
            base_xp_gain = max(4, base_xp_gain // 2)
        girl.exp += int(base_xp_gain * overall_xp_multiplier)
        while girl.level < 9999 and girl.exp >= level_xp_threshold(girl.level):
            girl.exp -= level_xp_threshold(girl.level)
            girl.level += 1
            if girl.level >= 9999:
                girl.exp = 0
                break
        girl.recalc_limits()
        girl.health = min(girl.health, girl.health_max)
        girl.stamina = min(girl.stamina, girl.stamina_max)

        def pref_multiplier(pref_map: dict[str, str], key: str) -> float:
            return 1.5 if pref_map.get(key, "true") == PREF_FAV else 1.0

        main_mul = pref_multiplier(girl.prefs_skills, job.demand_main)
        base_main_xp = 6 + job.difficulty * 2 + max(0, info["main_lvl"] - job.demand_level) * 3
        main_xp = int(
            base_main_xp * main_mul * (1.0 if success else 0.4) * main_xp_multiplier
        )
        add_skill_xp(girl.skills, job.demand_main, main_xp)

        if sub_name:
            sub_mul = pref_multiplier(girl.prefs_subskills, sub_name)
            base_sub_xp = 4 + job.difficulty * 2 + max(0, sub_lvl - sub_need) * 3
            sub_xp = int(
                base_sub_xp * sub_mul * (1.0 if success else 0.4) * sub_xp_multiplier
            )
            add_skill_xp(girl.subskills, sub_name, sub_xp)

        if reward > 0:
            player.currency += reward

        renown_delta = 0
        if success:
            renown_delta += 6 + job.difficulty * 2
        else:
            renown_delta -= max(1, 2 + job.difficulty)
        player.renown = max(0, player.renown + renown_delta)
        brothel.renown = player.renown

        if sub_name == "VAGINAL" and not girl.pregnant:
            if success and random.random() < 0.03:
                girl.pregnant = True
                girl.pregnant_since_ts = int(time.time())

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

        lust_cost = info["lust_cost"]
        if success:
            lust_spent = min(lust_before, max(1, int(lust_cost)))
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
        girl.gain_lust_xp(int(lust_xp_gain))

        endurance_xp_gain = max(1, int(stamina_cost * (1.1 if success else 0.7)) + job.difficulty * (3 if success else 2))
        girl.gain_endurance_xp(int(endurance_xp_gain))
        vitality_xp_gain = 2 + job.difficulty * (3 if success else 2)
        if injured:
            vitality_xp_gain += max(1, injury_amount // 4)
        girl.gain_vitality_xp(int(vitality_xp_gain))

        brothel_diff = brothel.register_job_outcome(success, injured, job, reward)
        if not isinstance(brothel_diff, dict):
            brothel_diff = {}
        upkeep_delta = brothel.upkeep_pool - pool_before
        if "upkeep" not in brothel_diff:
            brothel_diff["upkeep"] = upkeep_delta
        renown_delta_value = player.renown - renown_before
        if renown_delta_value:
            brothel_diff["renown"] = brothel_diff.get("renown", 0) + renown_delta_value
        cleanliness_delta = brothel.cleanliness - clean_before
        if "cleanliness" not in brothel_diff:
            brothel_diff["cleanliness"] = cleanliness_delta
        morale_delta = brothel.morale - morale_before
        if "morale" not in brothel_diff:
            brothel_diff["morale"] = morale_delta

        return {
            "ok": success,
            "reason": "Success" if success else "Failed",
            "reward": reward,
            "base_reward": base_reward,
            "success_chance": info["success_chance"],
            "injury_chance": injury_chance,
            "injured": injured,
            "injury_amount": injury_amount,
            "stamina_cost": stamina_cost,
            "reward_multiplier": reward_multiplier,
            "lust_cost": lust_spent,
            "lust_before": lust_before,
            "lust_after": girl.lust,
            "lust_after_ratio": girl.lust / girl.lust_max if girl.lust_max else 0.0,
            "lust_ratio_before": info["lust_ratio"],
            "brothel_diff": brothel_diff,
            "training_bonus_used": training_bonus_used,
            "training_bonus_focus_type": training_focus_type,
            "training_bonus_focus": training_focus,
            "renown_delta": player.renown - renown_before,
        }

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
    def dismantle_girl(self, player: Player, girl_uid: str) -> dict:
        girl = player.get_girl(girl_uid)
        if not girl:
            return {"ok": False, "reason": "Girl not found", "reward": 0, "name": "", "rarity": ""}

        base_reward = {"R": 50, "SR": 150, "SSR": 400, "UR": 1000}
        reward = base_reward.get(girl.rarity, 50) + girl.level * 20

        brothel = player.ensure_brothel()
        brothel.stop_training(girl_uid)

        player.currency += reward
        player.girls = [g for g in player.girls if g.uid != girl_uid]

        renown_gain_by_rarity = {"R": 1, "SR": 2, "SSR": 4, "UR": 6}
        player.renown = max(0, player.renown + renown_gain_by_rarity.get(girl.rarity, 1))
        brothel.renown = player.renown

        return {
            "ok": True,
            "reason": "Dismantled",
            "reward": reward,
            "name": girl.name,
            "rarity": girl.rarity,
        }

    def _brothel_score(self, player: Player) -> int:
        brothel = player.ensure_brothel()
        facility_score = sum(
            max(0, brothel.facility_level(name) - 1) for name in BROTHEL_FACILITY_NAMES
        )
        room_score = max(0, brothel.rooms - 1) * 20
        renown_score = player.renown
        upkeep_bonus = brothel.cleanliness // 5 + brothel.morale // 5
        return facility_score * 25 + room_score + renown_score + upkeep_bonus

    def _girl_score(self, girl: Girl) -> int:
        main_total = sum(get_level(girl.skills, name) for name in MAIN_SKILLS)
        sub_total = sum(get_level(girl.subskills, name) for name in SUB_SKILLS)
        stat_total = girl.vitality_level + girl.endurance_level + girl.lust_level
        return girl.level * 30 + main_total * 8 + sub_total * 5 + stat_total * 6

    def gather_brothel_top(self, limit: int = 10) -> List[Tuple[int, Player]]:
        entries: List[Tuple[int, Player]] = []
        for uid in self.iter_user_ids():
            player = self.load_player(uid)
            if not player:
                continue
            score = self._brothel_score(player)
            entries.append((score, player))
        entries.sort(key=lambda item: item[0], reverse=True)
        return entries[:limit]

    def gather_girl_top(self, limit: int = 10) -> List[Tuple[int, Player, Girl]]:
        entries: List[Tuple[int, Player, Girl]] = []
        for uid in self.iter_user_ids():
            player = self.load_player(uid)
            if not player:
                continue
            for girl in player.girls:
                score = self._girl_score(girl)
                entries.append((score, player, girl))
        entries.sort(key=lambda item: item[0], reverse=True)
        return entries[:limit]

    def iter_user_ids(self) -> Iterable[int]:
        return self.store.iter_user_ids()
