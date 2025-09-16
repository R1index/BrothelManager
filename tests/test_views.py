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


if __name__ == "__main__":
    unittest.main()
