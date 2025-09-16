import asyncio
import unittest

from src.game.views import MarketWorkView
from src.models import Girl, Market, Player


class MarketWorkViewPaginationTests(unittest.TestCase):
    def setUp(self):
        self.player = Player(user_id=123)
        self.player.girls = [
            Girl(uid=f"g{i:03d}", base_id="base", name=f"Girl {i:02d}", rarity="R")
            for i in range(1, 31)
        ]
        self.market = Market(user_id=123, jobs=[])
        async def _create_view():
            return MarketWorkView(
                user_id=123,
                invoker_id=123,
                forced_level=None,
                player=self.player,
                market=self.market,
            )

        self.view = asyncio.run(_create_view())

    def test_initial_page_respects_option_limit(self):
        values = [opt.value for opt in self.view.girl_select.options]
        self.assertIn("none", values)
        self.assertIn("g001", values)
        self.assertNotIn("g025", values)
        self.assertLessEqual(len(self.view.girl_select.options), 25)
        self.assertFalse(self.view.girl_next_page_btn.disabled)
        self.assertTrue(self.view.girl_prev_page_btn.disabled)

    def test_second_page_exposes_additional_girls(self):
        self.view.girl_page = 1
        self.view._apply_state()
        values = [opt.value for opt in self.view.girl_select.options]
        self.assertIn("g025", values)
        self.assertIn("g030", values)
        self.assertLessEqual(len(values), 25)
        placeholder = self.view.girl_select.placeholder
        self.assertIn("Page 2/2", placeholder)
        self.assertFalse(self.view.girl_prev_page_btn.disabled)
        self.assertTrue(self.view.girl_next_page_btn.disabled)


class MarketWorkViewMentorshipTests(unittest.TestCase):
    def setUp(self):
        self.player = Player(user_id=456)
        mentor = Girl(uid="g777", base_id="base", name="Mentor Girl", rarity="SR")
        mentor.mentorship_bonus = 0.15
        mentor.mentorship_focus_type = "main"
        mentor.mentorship_focus = "charm"
        self.player.girls = [mentor]
        self.market = Market(user_id=456, jobs=[])

        async def _create_view():
            return MarketWorkView(
                user_id=456,
                invoker_id=456,
                forced_level=None,
                player=self.player,
                market=self.market,
            )

        self.view = asyncio.run(_create_view())

    def test_mentorship_option_includes_name_and_uid(self):
        options_by_value = {opt.value: opt for opt in self.view.girl_select.options}
        girl_option = options_by_value["g777"]

        self.assertIn("Mentor Girl", girl_option.label)
        self.assertIn("g777", girl_option.label)
        self.assertIn("Mentor Girl", girl_option.description)
        self.assertIn("g777", girl_option.description)
        self.assertIn("+15%", girl_option.description)


if __name__ == "__main__":
    unittest.main()
