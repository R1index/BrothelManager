"""Высокоуровневая игровая логика."""
from __future__ import annotations

import json
import random
from dataclasses import asdict
from typing import Dict, Iterable, List, Optional, Sequence

from .. import assets_util
from ..models import (
    BrothelState,
    Girl,
    Job,
    Market,
    Player,
    TrainingAssignment,
    now_ts,
)
from .repository import DataStore

__all__ = ["GameService"]


class GameService:
    def __init__(self, store: Optional[DataStore] = None) -> None:
        self.store = store or DataStore()
        self._config_cache: Optional[dict] = None
        self._catalog_cache: Optional[dict] = None

    # ------------------------- конфигурация -------------------------
    @property
    def config(self) -> dict:
        if self._config_cache is None:
            self._config_cache = self._load_config()
        return self._config_cache

    def _load_config(self) -> dict:
        config = self.store.read_json(self.store.config_path)
        if not isinstance(config, dict):
            config = {}
        paths = config.get("paths") if isinstance(config.get("paths"), dict) else None
        self.store.configure_paths(paths)
        assets_util.set_assets_dir(self.store.assets_dir)
        return config

    # ------------------------- сериализация -------------------------
    def _girl_from_payload(self, payload: dict) -> Girl:
        return Girl(
            uid=payload.get("uid", payload.get("id", "")),
            base_id=payload.get("base_id", payload.get("id", "")),
            name=payload.get("name", "Unknown"),
            rarity=payload.get("rarity", "R"),
            level=int(payload.get("level", 1)),
            exp=int(payload.get("exp", 0)),
            health=int(payload.get("health", 100)),
            health_max=int(payload.get("health_max", payload.get("max_health", 100))),
            stamina=int(payload.get("stamina", 100)),
            stamina_max=int(payload.get("stamina_max", payload.get("max_stamina", 100))),
            lust=int(payload.get("lust", 80)),
            lust_max=int(payload.get("lust_max", payload.get("max_lust", 100))),
            stamina_last_ts=int(payload.get("stamina_last_ts", now_ts())),
            lust_last_ts=int(payload.get("lust_last_ts", now_ts())),
            vitality_level=int(payload.get("vitality_level", payload.get("vitality", 1))),
            vitality_xp=int(payload.get("vitality_xp", 0)),
            endurance_level=int(payload.get("endurance_level", payload.get("endurance", 1))),
            endurance_xp=int(payload.get("endurance_xp", 0)),
            lust_level=int(payload.get("lust_level", 1)),
            lust_xp=int(payload.get("lust_xp", 0)),
            skills=payload.get("skills"),
            subskills=payload.get("subskills"),
        )

    def _girl_to_payload(self, girl: Girl) -> dict:
        return {
            "uid": girl.uid,
            "base_id": girl.base_id,
            "name": girl.name,
            "rarity": girl.rarity,
            "level": girl.level,
            "exp": girl.exp,
            "health": girl.health,
            "health_max": girl.health_max,
            "stamina": girl.stamina,
            "stamina_max": girl.stamina_max,
            "lust": girl.lust,
            "lust_max": girl.lust_max,
            "stamina_last_ts": girl.stamina_last_ts,
            "lust_last_ts": girl.lust_last_ts,
            "vitality_level": girl.vitality_level,
            "vitality_xp": girl.vitality_xp,
            "endurance_level": girl.endurance_level,
            "endurance_xp": girl.endurance_xp,
            "lust_level": girl.lust_level,
            "lust_xp": girl.lust_xp,
            "skills": girl.skills,
            "subskills": girl.subskills,
        }

    def _brothel_from_payload(self, payload: dict) -> BrothelState:
        return BrothelState(
            rooms=int(payload.get("rooms", 3)),
            renown=int(payload.get("renown", payload.get("popularity", 15))),
            morale=float(payload.get("morale", 70)),
            cleanliness=float(payload.get("cleanliness", 85)),
            comfort_level=int(payload.get("comfort_level", payload.get("comfort", 1))),
            hygiene_level=int(payload.get("hygiene_level", payload.get("hygiene", 1))),
            security_level=int(payload.get("security_level", payload.get("security", 1))),
            allure_level=int(payload.get("allure_level", payload.get("allure", 1))),
            upkeep_pool=int(payload.get("upkeep_pool", 0)),
            last_tick_ts=int(payload.get("last_tick_ts", now_ts())),
        )

    def _brothel_to_payload(self, brothel: BrothelState) -> dict:
        return {
            "rooms": brothel.rooms,
            "renown": int(brothel.renown),
            "popularity": int(brothel.renown),
            "morale": brothel.morale,
            "cleanliness": brothel.cleanliness,
            "comfort_level": brothel.comfort_level,
            "hygiene_level": brothel.hygiene_level,
            "security_level": brothel.security_level,
            "allure_level": brothel.allure_level,
            "upkeep_pool": brothel.upkeep_pool,
            "last_tick_ts": brothel.last_tick_ts,
        }

    def _player_from_payload(self, payload: dict, uid: int) -> Player:
        girls = [self._girl_from_payload(g) for g in payload.get("girls", [])]
        brothel_payload = payload.get("brothel") or {}
        brothel = self._brothel_from_payload(brothel_payload) if brothel_payload else None
        renown = payload.get("renown")
        if renown is None:
            renown = payload.get("reputation")
        if renown is None:
            renown = brothel_payload.get("renown") or brothel_payload.get("popularity")
        if renown is None:
            renown = 15
        player = Player(
            user_id=uid,
            currency=int(payload.get("currency", 0)),
            renown=int(renown),
            girls=girls,
            brothel=brothel,
        )
        if player.brothel is not None:
            player.brothel.renown = player.renown
        return player

    def _player_to_payload(self, player: Player) -> dict:
        brothel = player.ensure_brothel()
        brothel.renown = player.renown
        return {
            "user_id": player.user_id,
            "currency": player.currency,
            "renown": player.renown,
            "reputation": player.renown,
            "girls": [self._girl_to_payload(g) for g in player.girls],
            "brothel": self._brothel_to_payload(brothel),
        }

    # ------------------------- каталоги -------------------------
    def _catalog_index(self) -> dict:
        if self._catalog_cache is None:
            catalog = self.store.load_catalog()
            girls = catalog.get("girls") if isinstance(catalog, dict) else []
            self._catalog_cache = {g["id"]: g for g in girls if "id" in g}
        return self._catalog_cache

    # ------------------------- операции с игроками -------------------------
    def load_player(self, uid: int) -> Optional[Player]:
        path = self.store.user_path(uid)
        payload = self.store.read_json(path)
        if not payload:
            return None
        return self._player_from_payload(payload, uid)

    def save_player(self, player: Player) -> None:
        payload = self._player_to_payload(player)
        self.store.write_json(self.store.user_path(player.user_id), payload)

    def grant_starter_pack(self, uid: int) -> Player:
        player = self.load_player(uid)
        if player is None:
            player = Player(user_id=uid)
        gacha_cfg = self.config.get("gacha", {}) if isinstance(self.config, dict) else {}
        starter_coins = int(gacha_cfg.get("starter_coins", 500))
        player.currency = starter_coins
        starter_id = gacha_cfg.get("starter_girl_id")
        if starter_id:
            girl_entry = self._catalog_index().get(starter_id)
            if girl_entry:
                new_uid = f"{starter_id}#{len(player.girls) + 1:03d}"
                girl = Girl(
                    uid=new_uid,
                    base_id=girl_entry.get("id", starter_id),
                    name=girl_entry.get("name", "Starter"),
                    rarity=girl_entry.get("rarity", "R"),
                    skills=(girl_entry.get("base") or {}).get("skills"),
                    subskills=(girl_entry.get("base") or {}).get("subskills"),
                )
                player.add_girl(girl)
        brothel = player.ensure_brothel()
        brothel.renown = player.renown = max(player.renown, 15)
        self.save_player(player)
        return player

    # ------------------------- гача -------------------------
    def roll_gacha(self, uid: int, times: int = 1) -> tuple[List[Girl], int]:
        player = self.load_player(uid)
        if player is None:
            raise RuntimeError("Player not found")
        brothel = player.ensure_brothel()
        roll_cfg = self.config.get("gacha", {})
        roll_cost = int(roll_cfg.get("roll_cost", 100))
        free_rooms = brothel.rooms - len(player.girls)
        if free_rooms <= 0:
            raise RuntimeError("No free rooms")
        attempts = min(int(times), free_rooms)
        total_cost = roll_cost * attempts
        if player.currency < total_cost:
            raise RuntimeError("Not enough currency")
        player.currency -= total_cost

        catalog = list(self._catalog_index().values())
        if not catalog:
            raise RuntimeError("Catalog is empty")
        granted: List[Girl] = []
        for i in range(attempts):
            entry = random.choice(catalog)
            uid_suffix = len(player.girls) + 1
            new_uid = f"{entry['id']}#{uid_suffix:03d}"
            girl = Girl(
                uid=new_uid,
                base_id=entry.get("id", ""),
                name=entry.get("name", "Unknown"),
                rarity=entry.get("rarity", "R"),
                skills=(entry.get("base") or {}).get("skills"),
                subskills=(entry.get("base") or {}).get("subskills"),
            )
            player.add_girl(girl)
            granted.append(girl)
        self.save_player(player)
        return granted, total_cost

    # ------------------------- рынок -------------------------
    def generate_market(self, uid: int, forced_level: Optional[int] = None) -> Market:
        player = self.load_player(uid) or Player(user_id=uid)
        brothel = player.ensure_brothel()
        level = forced_level or max(1, brothel.renown // 20 + 1)
        market_cfg = self.config.get("market", {})
        jobs_per_level = int(market_cfg.get("jobs_per_level", 3))
        job_count = max(1, jobs_per_level * 2)
        jobs: List[Job] = []
        for idx in range(job_count):
            main = random.choice(list(self._catalog_index() or {"Human": None}.keys()))
            if main not in ("Human", "Beast", "Monster", "Insect"):
                main = "Human"
            sub = random.choice(["VAGINAL", "ORAL", "ANAL", "GROUP"])
            job = Job(
                job_id=f"job-{uid}-{level}-{idx}",
                demand_main=main,
                demand_level=max(1, level + idx % 2),
                demand_sub=sub,
                demand_sub_level=max(0, level // 2),
                pay=50 + level * 10 + idx * 5,
                difficulty=max(1, level + idx % 3),
            )
            jobs.append(job)
        market = Market(user_id=uid, jobs=jobs, level=level)
        self.save_market(market)
        return market

    def load_market(self, uid: int) -> Optional[Market]:
        payload = self.store.read_json(self.store.market_path(uid))
        if not payload:
            return None
        jobs = [
            Job(
                job_id=j["job_id"],
                demand_main=j["demand_main"],
                demand_level=j["demand_level"],
                demand_sub=j["demand_sub"],
                demand_sub_level=j["demand_sub_level"],
                pay=j["pay"],
                difficulty=j["difficulty"],
            )
            for j in payload.get("jobs", [])
        ]
        return Market(
            user_id=payload.get("user_id", uid),
            jobs=jobs,
            level=payload.get("level", 1),
            expires_ts=payload.get("expires_ts", now_ts()),
        )

    def save_market(self, market: Market) -> None:
        payload = {
            "user_id": market.user_id,
            "level": market.level,
            "expires_ts": market.expires_ts,
            "jobs": [
                {
                    "job_id": job.job_id,
                    "demand_main": job.demand_main,
                    "demand_level": job.demand_level,
                    "demand_sub": job.demand_sub,
                    "demand_sub_level": job.demand_sub_level,
                    "pay": job.pay,
                    "difficulty": job.difficulty,
                }
                for job in market.jobs
            ],
        }
        self.store.write_json(self.store.market_path(market.user_id), payload)

    def refresh_market_if_stale(self, uid: int, max_age_sec: int = 0) -> Market:
        market = self.load_market(uid)
        if market is None or market.expires_ts <= now_ts() + max_age_sec:
            market = self.generate_market(uid)
        return market

    # ------------------------- оценка заданий -------------------------
    def evaluate_job(
        self,
        girl: Girl,
        job: Job,
        brothel: Optional[BrothelState] = None,
    ) -> dict:
        brothel = brothel or BrothelState()
        skill_delta = girl.get_skill_level(job.demand_main) - job.demand_level
        sub_delta = girl.get_subskill_level(job.demand_sub) - job.demand_sub_level
        lust_cost = 12 + job.difficulty * 3 - brothel.comfort_level * 0.8 - max(0, brothel.morale - 60) / 25
        lust_cost = max(4, int(round(lust_cost)))
        stamina_cost = 10 + job.difficulty * 4
        lust_ok = girl.lust >= lust_cost
        stamina_ok = girl.stamina >= stamina_cost
        success_chance = 0.6 + skill_delta * 0.05 + sub_delta * 0.03 + brothel.renown / 400
        success_chance = max(0.1, min(0.95, success_chance))
        can_attempt = lust_ok and stamina_ok and girl.health >= 50
        return {
            "lust_cost": lust_cost,
            "stamina_cost": stamina_cost,
            "lust_ok": lust_ok,
            "stamina_ok": stamina_ok,
            "success_chance": success_chance,
            "can_attempt": can_attempt,
        }

    # ------------------------- выполнение заданий -------------------------
    def resolve_job(self, player: Player, job: Job, girl: Girl) -> dict:
        brothel = player.ensure_brothel()
        brothel.apply_decay()
        assessment = self.evaluate_job(girl, job, brothel)
        if not assessment["can_attempt"]:
            return {
                "ok": False,
                "reason": "Requirements not met",
                "reward": 0,
                "spent_resources": False,
            }

        lust_cost = assessment["lust_cost"]
        stamina_cost = assessment["stamina_cost"]
        girl.lust = max(0, girl.lust - lust_cost)
        girl.stamina = max(0, girl.stamina - stamina_cost)
        now = now_ts()
        girl.lust_last_ts = now
        girl.stamina_last_ts = now

        success_roll = random.random()
        success = success_roll <= assessment["success_chance"]
        injury_roll = random.random()
        hygiene_factor = max(0.05, 0.25 - brothel.hygiene_level * 0.01)
        injury = injury_roll < (0.08 + job.difficulty * 0.03) * (1 + hygiene_factor)

        reward = 0
        if success:
            reward = int(job.pay * (1 + brothel.renown / 120))
            player.currency += reward
            girl.exp += 12 + job.difficulty * 4
            main_xp = 18 + job.difficulty * 6
            sub_xp = 10 + job.difficulty * 4
            if girl.mentorship_bonus and girl.mentorship_focus_type == "main" and girl.mentorship_focus == job.demand_main:
                main_xp *= 1 + girl.mentorship_bonus
            girl.add_main_xp(job.demand_main, main_xp)
            girl.add_sub_xp(job.demand_sub, sub_xp)
            girl.lust_xp += 6 + job.difficulty * 2
            girl.endurance_xp += 5 + job.difficulty * 2
            girl.vitality_xp += 4 + job.difficulty
        brothel.register_job_outcome(success, injury, job, reward)
        return {
            "ok": success,
            "reward": reward,
            "injured": injury,
            "spent_resources": True,
        }

    # ------------------------- лидерборды -------------------------
    def gather_brothel_top(self, limit: int = 10) -> List[dict]:
        result: List[dict] = []
        for uid in self.store.iter_user_ids():
            player = self.load_player(uid)
            if not player:
                continue
            brothel = player.ensure_brothel()
            result.append({"user_id": uid, "renown": brothel.renown, "rooms": brothel.rooms})
        return sorted(result, key=lambda item: item["renown"], reverse=True)[:limit]

    def gather_girl_top(self, limit: int = 10) -> List[dict]:
        entries: List[dict] = []
        for uid in self.store.iter_user_ids():
            player = self.load_player(uid)
            if not player:
                continue
            for girl in player.girls:
                total = girl.level + sum(s["level"] for s in girl.skills.values())
                entries.append({"user_id": uid, "girl": girl.name, "score": total})
        return sorted(entries, key=lambda item: item["score"], reverse=True)[:limit]

