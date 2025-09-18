import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src import assets_util
from src.game.services import GameService
from src.models import (
    BrothelState,
    Girl,
    Job,
    MAIN_SKILLS,
    Player,
    SUB_SKILLS,
    now_ts,
)
from src.game.repository import DataStore


def _write_config(base: Path, payload: dict) -> None:
    (base / "config.json").write_text(json.dumps(payload), encoding="utf-8")


class SkillNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.tmpdir.name)
        self.store = DataStore(self.base_path)
        self.service = GameService(self.store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_player_filters_unknown_keys(self):
        raw_player = {
            "user_id": 1,
            "currency": 42,
            "girls": [
                {
                    "uid": "g001#1",
                    "base_id": "g001",
                    "name": "Legacy",
                    "rarity": "R",
                    "skills": {
                        "Human": {"level": 3, "exp": 20},
                        "Monster": {"level": 1, "xp": 5},
                        "Forbidden": {"level": 7},
                    },
                    "subskills": {
                        "VAGINAL": {"level": 1, "xp": 4},
                        "ANAL": 2,
                        "Unknown": 5,
                    },
                }
            ],
        }

        self.store.write_json(self.store.user_path(1), raw_player)

        player = self.service.load_player(1)
        self.assertIsNotNone(player)
        self.assertEqual(len(player.girls), 1)

        girl = player.girls[0]
        self.assertEqual(set(girl.skills), set(MAIN_SKILLS))
        self.assertEqual(set(girl.subskills), set(SUB_SKILLS))
        self.assertEqual(girl.skills["Human"], {"level": 3, "xp": 20})
        self.assertEqual(girl.skills["Monster"], {"level": 1, "xp": 5})
        self.assertEqual(girl.subskills["ANAL"], {"level": 2, "xp": 0})
        self.assertEqual(girl.subskills["VAGINAL"], {"level": 1, "xp": 4})


class EvaluateJobTests(unittest.TestCase):
    def setUp(self):
        self.service = GameService()
        self.job = Job(
            job_id="job-test",
            demand_main="Human",
            demand_level=1,
            demand_sub="VAGINAL",
            demand_sub_level=0,
            pay=50,
            difficulty=1,
        )

    def _make_girl(self, lust: int) -> Girl:
        girl = Girl(
            uid="g-test",
            base_id="base",
            name="Test Girl",
            rarity="R",
            lust=lust,
        )
        for name in girl.skills:
            girl.skills[name]["level"] = 2 if name == "Human" else 0
        return girl

    def test_brothel_lust_modifier_updates_lust_gate(self):
        girl = self._make_girl(lust=9)
        baseline = self.service.evaluate_job(girl, self.job)
        self.assertFalse(baseline["lust_ok"])
        self.assertFalse(baseline["can_attempt"])

        brothel = BrothelState(comfort_level=10, morale=100, cleanliness=90)
        adjusted = self.service.evaluate_job(girl, self.job, brothel)

        self.assertLess(adjusted["lust_cost"], baseline["lust_cost"])
        self.assertTrue(adjusted["lust_ok"])
        self.assertTrue(adjusted["can_attempt"])


class ConfigOverridesTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(lambda: assets_util.set_assets_dir(None))
        self.base_path = Path(self.tmpdir.name)
        _write_config(
            self.base_path,
            {
                "paths": {
                    "data_dir": "save_data",
                    "catalog": "configs/catalog.json",
                    "assets": "art/girls",
                },
                "market": {"jobs_per_level": 2, "refresh_minutes": 3},
            },
        )
        self.store = DataStore(base_dir=self.base_path)
        self.service = GameService(self.store)

    def test_paths_override_and_assets_applied(self):
        self.service.config  # trigger config load
        expected_data_dir = self.base_path / "save_data"
        self.assertEqual(self.store.data_dir, expected_data_dir)
        self.assertEqual(self.store.users_dir, expected_data_dir / "users")
        self.assertEqual(self.store.market_dir, expected_data_dir / "markets")
        self.assertEqual(self.store.catalog_path, self.base_path / "configs/catalog.json")
        self.assertEqual(assets_util.get_assets_dir(), self.base_path / "art/girls")

        asset_dir = self.store.assets_dir / "test_girl"
        asset_dir.mkdir(parents=True, exist_ok=True)
        profile_path = asset_dir / "test_girl_profile.png"
        profile_path.write_bytes(b"")
        self.assertEqual(
            assets_util.profile_image_path("Test Girl"),
            str(profile_path),
        )

    def test_jobs_per_level_influences_market_size(self):
        market = self.service.generate_market(uid=42, forced_level=1)
        self.assertEqual(len(market.jobs), 4)

    def test_config_changes_are_observed_on_disk(self):
        self.service.config  # trigger initial load and caching
        time.sleep(0.01)
        _write_config(
            self.base_path,
            {
                "paths": {
                    "data_dir": "save_data",
                    "catalog": "configs/catalog.json",
                    "assets": "art/girls",
                },
                "market": {"jobs_per_level": 3, "refresh_minutes": 3},
            },
        )

        market = self.service.generate_market(uid=13, forced_level=1)
        self.assertEqual(len(market.jobs), 6)

    def test_config_reload_survives_base_dir_override(self):
        override_root = self.base_path / "override_root"
        override_root.mkdir(parents=True, exist_ok=True)
        expected_initial_base = self.base_path.resolve()
        expected_override_base = override_root.resolve()

        self.assertEqual(self.store.base_dir, expected_initial_base)

        _write_config(
            self.base_path,
            {
                "paths": {
                    "base_dir": "override_root",
                    "data_dir": "save_data",
                    "catalog": "configs/catalog.json",
                    "assets": "art/girls",
                },
                "market": {"jobs_per_level": 2, "refresh_minutes": 3},
            },
        )

        first_market = self.service.generate_market(uid=21, forced_level=1)
        self.assertEqual(len(first_market.jobs), 4)
        self.assertEqual(self.store.base_dir, expected_override_base)

        time.sleep(0.01)
        _write_config(
            self.base_path,
            {
                "paths": {
                    "base_dir": "override_root",
                    "data_dir": "save_data",
                    "catalog": "configs/catalog.json",
                    "assets": "art/girls",
                },
                "market": {"jobs_per_level": 4, "refresh_minutes": 3},
            },
        )

        refreshed_market = self.service.generate_market(uid=22, forced_level=1)
        self.assertEqual(len(refreshed_market.jobs), 8)
        self.assertEqual(self.store.base_dir, expected_override_base)


class ResolveJobTests(unittest.TestCase):
    def setUp(self):
        self.service = GameService()
        self.job = Job(
            job_id="job-test",
            demand_main="Human",
            demand_level=1,
            demand_sub="VAGINAL",
            demand_sub_level=0,
            pay=60,
            difficulty=1,
        )

    def _make_player(self) -> tuple[Player, Girl, BrothelState]:
        girl = Girl(
            uid="g-resolve",
            base_id="base",
            name="Resolve Tester",
            rarity="R",
            health=90,
            health_max=100,
            stamina=80,
            stamina_max=100,
            lust=80,
            lust_max=100,
        )
        for name in girl.skills:
            girl.skills[name]["level"] = 3 if name == "Human" else 0
        for name in girl.subskills:
            girl.subskills[name]["level"] = 1 if name == "VAGINAL" else 0
        old_ts = now_ts() - 3600
        girl.stamina_last_ts = old_ts
        girl.lust_last_ts = old_ts

        player = Player(user_id=99, girls=[girl])
        brothel = player.ensure_brothel()
        brothel.cleanliness = 70
        brothel.morale = 80
        brothel.comfort_level = 3
        brothel.last_tick_ts = now_ts() - 5400
        return player, girl, brothel

    def _xp_snapshot(self, girl: Girl) -> dict[str, int]:
        return {
            "exp": girl.exp,
            "main": girl.skills["Human"]["xp"],
            "sub": girl.subskills["VAGINAL"]["xp"],
            "lust": girl.lust_xp,
            "endurance": girl.endurance_xp,
            "vitality": girl.vitality_xp,
        }

    def test_regen_uses_decayed_stats_after_idle(self):
        player, girl, brothel = self._make_player()
        initial_health = girl.health
        initial_cleanliness = brothel.cleanliness

        with patch("src.game.services.random.random", side_effect=[0.0, 0.5, 0.99]):
            result = self.service.resolve_job(player, self.job, girl)

        self.assertTrue(result["ok"])
        self.assertEqual(girl.health, initial_health)
        self.assertLessEqual(brothel.cleanliness, initial_cleanliness - 6)

    def test_main_training_bonus_only_boosts_main_skill_xp(self):
        player_plain, girl_plain, _ = self._make_player()
        player_trained, girl_trained, _ = self._make_player()

        before_plain = self._xp_snapshot(girl_plain)
        before_trained = self._xp_snapshot(girl_trained)

        girl_trained.grant_training_bonus("mentor", 0.5, "main", "Human")

        with patch("src.game.services.random.random", side_effect=[0.0, 0.5, 0.99]):
            self.service.resolve_job(player_plain, self.job, girl_plain)

        with patch("src.game.services.random.random", side_effect=[0.0, 0.5, 0.99]):
            self.service.resolve_job(player_trained, self.job, girl_trained)

        after_plain = self._xp_snapshot(girl_plain)
        after_trained = self._xp_snapshot(girl_trained)

        plain_delta = {key: after_plain[key] - before_plain[key] for key in before_plain}
        trained_delta = {
            key: after_trained[key] - before_trained[key] for key in before_trained
        }

        self.assertGreater(trained_delta["main"], plain_delta["main"])
        for key in ("exp", "sub", "lust", "endurance", "vitality"):
            self.assertEqual(trained_delta[key], plain_delta[key])


class StarterPackRenownTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(lambda: assets_util.set_assets_dir(None))
        self.base_path = Path(self.tmpdir.name)
        self.store = DataStore(base_dir=self.base_path)

        _write_config(
            self.base_path,
            {
                "gacha": {
                    "starter_girl_id": "starter",
                    "starter_coins": 250,
                }
            },
        )

        catalog_payload = {
            "girls": [
                {
                    "id": "starter",
                    "name": "Starter Girl",
                    "rarity": "R",
                    "base": {
                        "level": 1,
                        "skills": {"Human": {"level": 1}},
                        "subskills": {"VAGINAL": {"level": 0}},
                    },
                }
            ]
        }
        catalog_path = self.store.catalog_path
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(json.dumps(catalog_payload), encoding="utf-8")

        self.service = GameService(self.store)

    def test_starter_pack_preserves_initial_renown(self):
        player = self.service.grant_starter_pack(uid=123)

        self.assertEqual(player.renown, 15)
        self.assertEqual(player.brothel.renown, 15)

        loaded = self.service.load_player(123)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.renown, 15)
        self.assertEqual(loaded.brothel.renown, 15)

    def test_legacy_popularity_restored_for_player(self):
        payload = {
            "user_id": 999,
            "currency": 0,
            "girls": [],
            "brothel": {"popularity": 37, "rooms": 3},
        }
        path = self.store.user_path(999)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

        player = self.service.load_player(999)
        self.assertIsNotNone(player)
        self.assertEqual(player.renown, 37)
        self.assertEqual(player.brothel.renown, 37)

        brothel = player.ensure_brothel()
        self.assertEqual(player.renown, 37)
        self.assertEqual(brothel.renown, 37)

        self.service.save_player(player)
        saved = self.store.read_json(self.store.user_path(999))
        self.assertEqual(saved.get("reputation"), 37)
        self.assertEqual((saved.get("brothel") or {}).get("popularity"), 37)


if __name__ == "__main__":
    unittest.main()
