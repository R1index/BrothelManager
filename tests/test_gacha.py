import json
import tempfile
import unittest
from pathlib import Path

from src.game.repository import DataStore
from src.game.services import GameService


class GachaRollTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        self.roll_cost = 100

        config_data = {
            "gacha": {
                "roll_cost": self.roll_cost,
                "starter_coins": 500,
                "starter_girl_id": "g001",
            }
        }
        (self.base / "config.json").write_text(json.dumps(config_data))

        data_dir = self.base / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        catalog_data = {
            "girls": [
                {
                    "id": "g001",
                    "name": "Test Girl",
                    "rarity": "R",
                    "base": {
                        "level": 1,
                        "skills": {},
                        "subskills": {},
                    },
                }
            ]
        }
        (data_dir / "girls_catalog.json").write_text(json.dumps(catalog_data))

        store = DataStore(self.base)
        self.service = GameService(store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_double_roll_with_one_room_does_not_consume_extra_coins(self):
        uid = 123
        # Starter pack gives one girl and ample currency.
        self.service.grant_starter_pack(uid)
        # Spend one roll to leave exactly one free room before the scenario.
        self.service.roll_gacha(uid, times=1)

        snapshot = self.service.load_player(uid)
        self.assertIsNotNone(snapshot)
        brothel = snapshot.ensure_brothel()
        self.assertEqual(brothel.rooms - len(snapshot.girls), 1)
        coins_before = snapshot.currency

        girls, total_cost = self.service.roll_gacha(uid, times=1)
        self.assertEqual(len(girls), 1)
        self.assertEqual(total_cost, self.roll_cost)

        after_success = self.service.load_player(uid)
        self.assertEqual(after_success.currency, coins_before - total_cost)

        with self.assertRaises(RuntimeError):
            self.service.roll_gacha(uid, times=1)

        after_failure = self.service.load_player(uid)
        self.assertEqual(after_failure.currency, after_success.currency)

    def test_starter_coins_follow_config_value(self):
        uid = 456
        new_starter_coins = 987
        config_data = {
            "gacha": {
                "roll_cost": self.roll_cost,
                "starter_coins": new_starter_coins,
                "starter_girl_id": "g001",
            }
        }
        (self.base / "config.json").write_text(json.dumps(config_data))
        # Reset cached config so the updated value is picked up.
        self.service._config_cache = None

        player = self.service.grant_starter_pack(uid)
        self.assertEqual(player.currency, new_starter_coins)

        stored = self.service.load_player(uid)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.currency, new_starter_coins)


if __name__ == "__main__":
    unittest.main()
