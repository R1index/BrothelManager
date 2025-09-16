import unittest

from src.game.views import MarketWorkView
from src.models import Girl, Player


class MarketWorkViewOptionTests(unittest.TestCase):
    def test_mentorship_option_includes_name_and_uid(self):
        girl = Girl(uid="g-mentor", base_id="base", name="Mentor", rarity="R")
        girl.mentorship_bonus = 0.25
        girl.mentorship_focus_type = "main"
        girl.mentorship_focus = "Human"

        player = Player(user_id=123, girls=[girl])
        brothel = player.ensure_brothel()

        view = MarketWorkView.__new__(MarketWorkView)
        view.selected_girl_uid = None

        options = view._build_girl_options(player, brothel)
        girl_option = next(opt for opt in options if opt.value == girl.uid)

        self.assertIn(girl.name, girl_option.label)
        self.assertIn(girl.uid, girl_option.label)
        self.assertIsNotNone(girl_option.description)
        self.assertIn(girl.name, girl_option.description)
        self.assertIn(girl.uid, girl_option.description)


if __name__ == "__main__":
    unittest.main()
