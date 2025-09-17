"""Игровые сервисы и бизнес-логика."""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple
from ..models import (
    MAIN_SKILLS,
    SUB_SKILLS,
    BrothelState,
    Girl,
    Job,
    Market,
    Player,
    add_skill_xp,
    get_level,
    market_level_from_rep,
    now_ts,
)
from .repository import DataStore

__all__ = ["GameService"]


DEFAULT_CONFIG: Dict[str, Dict] = {
    "paths": {},
    "gacha": {"roll_cost": 100, "starter_coins": 500, "starter_girl_id": "starter"},
    "market": {"jobs_per_level": 3, "refresh_minutes": 5},
}


class GameService:
    """Высокоуровневый сервис игрового состояния."""

    def __init__(self, store: Optional[DataStore] = None) -> None:
        self.store = store or DataStore()
        self._config_cache: Optional[Dict] = None
        self._catalog_cache: Optional[Dict[str, List[Dict]]] = None
        self.store.ensure_dirs()

    # ------------------------------------------------------------------
    @property
    def config(self) -> Dict:
        if self._config_cache is None:
            raw = self.store.read_json(self.store.config_path)
            merged = {**DEFAULT_CONFIG, **(raw or {})}
            for key, default_val in DEFAULT_CONFIG.items():
                if isinstance(default_val, dict):
                    merged[key] = {**default_val, **(merged.get(key) or {})}
            self._config_cache = merged
            self.store.configure_paths(merged.get("paths"))
            self.store.apply_assets_dir()
            self._catalog_cache = None
        return self._config_cache

    # ------------------------------------------------------------------
    def _catalog(self) -> List[Dict]:
        if self._catalog_cache is None:
            payload = self.store.load_catalog()
            self._catalog_cache = payload
        return self._catalog_cache.get("girls", [])

    # ------------------------------------------------------------------
    # Работа с игроками
    # ------------------------------------------------------------------
    def load_player(self, user_id: int) -> Optional[Player]:
        data = self.store.read_json(self.store.user_path(user_id))
        if not data:
            return None
        player = Player.from_dict(data)
        return player

    def save_player(self, player: Player) -> None:
        player.renown = player.ensure_brothel().renown
        payload = player.to_dict()
        self.store.write_json(self.store.user_path(player.user_id), payload)

    def grant_starter_pack(self, uid: int) -> Player:
        player = self.load_player(uid)
        if player:
            return player
        cfg = self.config.get("gacha", {})
        starter_id = cfg.get("starter_girl_id")
        starter_coins = int(cfg.get("starter_coins", 500))
        player = Player(user_id=uid, currency=starter_coins)
        player.renown = 15
        player.brothel = BrothelState(renown=player.renown)
        starter_template = self._find_catalog_entry(starter_id)
        if starter_template:
            player.add_girl(self._instantiate_girl(player, starter_template))
        self.save_player(player)
        return player

    def _find_catalog_entry(self, base_id: Optional[str]) -> Optional[Dict]:
        if not base_id:
            return None
        for entry in self._catalog():
            if entry.get("id") == base_id:
                return entry
        return None

    def _instantiate_girl(self, player: Player, template: Dict) -> Girl:
        base_id = template.get("id") or template.get("base_id")
        name = template.get("name", base_id or "Unknown")
        counter = sum(1 for girl in player.girls if girl.base_id == base_id)
        uid = f"{base_id}#{counter + 1}" if base_id else f"g{now_ts()}"
        girl_payload = {
            "uid": uid,
            "base_id": base_id or uid,
            "name": name,
            "rarity": template.get("rarity", "R"),
            "skills": (template.get("base") or {}).get("skills"),
            "subskills": (template.get("base") or {}).get("subskills"),
        }
        return Girl.from_dict(girl_payload)

    # ------------------------------------------------------------------
    def roll_gacha(self, uid: int, *, times: int = 1) -> Tuple[List[Girl], int]:
        if times <= 0:
            raise ValueError("times must be positive")
        player = self.load_player(uid)
        if player is None:
            raise RuntimeError("Player not found")
        cfg = self.config.get("gacha", {})
        cost_per_roll = int(cfg.get("roll_cost", 100))
        available_rooms = player.free_rooms()
        if available_rooms <= 0:
            raise RuntimeError("No free rooms available")
        actual_rolls = min(times, available_rooms)
        total_cost = cost_per_roll * actual_rolls
        if player.currency < total_cost:
            raise RuntimeError("Not enough currency")
        player.currency -= total_cost
        obtained: List[Girl] = []
        catalog = self._catalog()
        if not catalog:
            raise RuntimeError("Catalog is empty")
        for _ in range(actual_rolls):
            template = random.choice(catalog)
            girl = self._instantiate_girl(player, template)
            player.add_girl(girl)
            obtained.append(girl)
        self.save_player(player)
        return obtained, total_cost

    # ------------------------------------------------------------------
    def generate_market(self, uid: int, *, forced_level: Optional[int] = None) -> Market:
        player = self.load_player(uid)
        renown = player.renown if player else 15
        level = forced_level if forced_level is not None else market_level_from_rep(renown)
        level = max(1, level)
        cfg = self.config.get("market", {})
        per_level = int(cfg.get("jobs_per_level", 3))
        total_jobs = max(1, per_level * 2)
        rng = random.Random(uid + level + now_ts())
        jobs: List[Job] = []
        for index in range(total_jobs):
            main = MAIN_SKILLS[index % len(MAIN_SKILLS)]
            sub = SUB_SKILLS[index % len(SUB_SKILLS)]
            job_id = f"{uid}-{level}-{index}-{rng.randint(100, 999)}"
            job = Job(
                job_id=job_id,
                demand_main=main,
                demand_level=max(1, level + index // per_level),
                demand_sub=sub,
                demand_sub_level=max(0, level - 1),
                pay=60 + level * 15 + index * 5,
                difficulty=max(1, level + index // (per_level or 1) - 1),
            )
            jobs.append(job)
        market = Market(user_id=uid, jobs=jobs, level=level, generated_ts=now_ts())
        self.save_market(market)
        return market

    def save_market(self, market: Market) -> None:
        self.store.write_json(self.store.market_path(market.user_id), market.to_dict())

    def load_market(self, uid: int) -> Optional[Market]:
        data = self.store.read_json(self.store.market_path(uid))
        if not data:
            return None
        return Market.from_dict(data)

    def refresh_market_if_stale(self, uid: int, *, max_age_sec: int = 600) -> Market:
        market = self.load_market(uid)
        if market is None:
            return self.generate_market(uid)
        if max_age_sec <= 0:
            return self.generate_market(uid, forced_level=market.level)
        age = now_ts() - market.generated_ts
        if age >= max_age_sec:
            return self.generate_market(uid, forced_level=market.level)
        return market

    # ------------------------------------------------------------------
    def evaluate_job(
        self,
        girl: Girl,
        job: Job,
        brothel: Optional[BrothelState] = None,
    ) -> Dict[str, object]:
        brothel = brothel or BrothelState()
        comfort_bonus = brothel.comfort_level * 0.6
        lust_cost = max(5, int(12 + job.difficulty * 2 - comfort_bonus))
        stamina_cost = max(8, int(16 + job.difficulty * 3))
        lust_ok = girl.lust >= lust_cost
        stamina_ok = girl.stamina >= stamina_cost
        main_level = get_level(girl.skills, job.demand_main)
        sub_level = get_level(girl.subskills, job.demand_sub) if job.demand_sub else 0
        level_gap = main_level - job.demand_level
        success_chance = max(0.1, min(0.98, 0.65 + level_gap * 0.05 + brothel.allure_level * 0.01))
        injury_chance = max(0.02, min(0.4, 0.18 - brothel.hygiene_level * 0.015))
        return {
            "lust_cost": lust_cost,
            "stamina_cost": stamina_cost,
            "lust_ok": lust_ok,
            "stamina_ok": stamina_ok,
            "can_attempt": lust_ok and stamina_ok,
            "success_chance": success_chance,
            "injury_chance": injury_chance,
            "main_level": main_level,
            "sub_level": sub_level,
        }

    def resolve_job(self, player: Player, job: Job, girl: Girl, *, brothel: Optional[BrothelState] = None) -> Dict[str, object]:
        brothel = brothel or player.ensure_brothel()
        brothel.apply_decay()
        girl.regen_stamina()
        girl.regen_lust()
        evaluation = self.evaluate_job(girl, job, brothel)
        if not evaluation["can_attempt"]:
            return {
                "ok": False,
                "reason": "Girl lacks resources",
                "reward": 0,
            }

        girl.consume_stamina(evaluation["stamina_cost"])
        girl.consume_lust(evaluation["lust_cost"])

        success_roll = random.random()
        injury_roll = random.random()
        success = success_roll < evaluation["success_chance"]
        injury = injury_roll < evaluation["injury_chance"]

        reward = 0
        base_reward = job.pay
        if success:
            bonus = max(0, evaluation["main_level"] - job.demand_level)
            reward = base_reward + int(base_reward * bonus * 0.1)
            player.currency += reward
        else:
            reward = base_reward // 5

        xp_award = 20 + job.difficulty * 5
        main_xp = 12 + job.difficulty * 3
        sub_xp = 6 + job.difficulty * 2
        lust_xp = 4 + job.difficulty * 2
        endurance_xp = 3 + job.difficulty * 2
        vitality_xp = 2 + job.difficulty

        mult = 1.0
        focus_type = girl.mentorship_focus_type
        focus = girl.mentorship_focus
        if girl.mentorship_bonus and focus_type and focus:
            if focus_type == "main" and focus.lower() == job.demand_main.lower():
                mult += girl.mentorship_bonus
            if focus_type == "sub" and job.demand_sub and focus.lower() == job.demand_sub.lower():
                mult += girl.mentorship_bonus

        add_skill_xp(girl.skills, job.demand_main, int(main_xp * mult))
        if job.demand_sub:
            add_skill_xp(girl.subskills, job.demand_sub, sub_xp)
        girl.gain_exp(xp_award)
        girl.gain_stat_xp(lust=lust_xp, endurance=endurance_xp, vitality=vitality_xp)

        brothel_outcome = brothel.register_job_outcome(
            success=success,
            injured=injury,
            job=job,
            reward=reward,
        )

        return {
            "ok": success,
            "reward": reward,
            "injured": injury,
            "xp": xp_award,
            "brothel": brothel_outcome,
        }

    # ------------------------------------------------------------------
    # Лидерборды (упрощённые реализации)
    # ------------------------------------------------------------------
    def gather_brothel_top(self, limit: int = 10) -> List[Tuple[int, int]]:
        results: List[Tuple[int, int]] = []
        for uid in self.store.iter_user_ids():
            player = self.load_player(uid)
            if not player:
                continue
            results.append((uid, player.renown))
        results.sort(key=lambda item: item[1], reverse=True)
        return results[:limit]

    def gather_girl_top(self, limit: int = 10) -> List[Tuple[int, Girl]]:
        ranking: List[Tuple[int, Girl]] = []
        for uid in self.store.iter_user_ids():
            player = self.load_player(uid)
            if not player:
                continue
            for girl in player.girls:
                ranking.append((uid, girl))
        ranking.sort(key=lambda item: item[1].level, reverse=True)
        return ranking[:limit]


