import unittest
from unittest.mock import MagicMock, patch, call
from types import SimpleNamespace

from src.cogs.core import Core, normalize_brothel_action


class BrothelActionNormalizationTests(unittest.TestCase):
    def test_expand_choice_is_preserved(self):
        choice = SimpleNamespace(value="expand")
        self.assertEqual(normalize_brothel_action(choice), "expand")

    def test_invalid_choice_defaults_to_view(self):
        choice = SimpleNamespace(value="invalid")
        self.assertEqual(normalize_brothel_action(choice), "view")

    def test_none_choice_defaults_to_view(self):
        self.assertEqual(normalize_brothel_action(None), "view")


class MarketRefresherConfigTests(unittest.TestCase):
    def test_refresh_interval_uses_config_value(self):
        with patch("src.cogs.core.get_config", return_value={"market": {"refresh_minutes": 7}}), \
            patch("discord.ext.tasks.Loop.change_interval") as mock_change_interval, \
            patch("discord.ext.tasks.Loop.start") as mock_start:
            core = Core(MagicMock())
            self.assertGreaterEqual(mock_change_interval.call_count, 1)
            self.assertEqual(mock_change_interval.call_args_list[-1], call(minutes=7.0))
            mock_start.assert_called_once()
            self.assertEqual(core.market_refresh_minutes, 7.0)
            core.cog_unload()


if __name__ == "__main__":
    unittest.main()
