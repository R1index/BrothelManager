import unittest
from unittest.mock import patch

from src.cogs.core import Core
from src.models import Player


class DummyResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class DummyUser:
    def __init__(self, uid: int, display_name: str = "Tester"):
        self.id = uid
        self.display_name = display_name


class DummyInteraction:
    def __init__(self, uid: int):
        self.user = DummyUser(uid)
        self.response = DummyResponse()


class GachaCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_gacha_roll_keeps_balance(self):
        core = Core.__new__(Core)
        uid = 123
        interaction = DummyInteraction(uid)

        player = Player(user_id=uid, currency=500, girls=[])
        player.ensure_brothel()

        with patch("src.cogs.core.load_player", return_value=player) as mock_load, \
                patch("src.cogs.core.save_player") as mock_save, \
                patch("src.cogs.core.roll_gacha", side_effect=RuntimeError("Catalog empty")):
            await Core.gacha.callback(core, interaction, times=1)

        self.assertEqual(player.currency, 500)
        mock_save.assert_not_called()
        mock_load.assert_called_once()
        self.assertTrue(interaction.response.messages)
        message_args, message_kwargs = interaction.response.messages[0]
        self.assertEqual(message_args, ("Catalog empty",))
        self.assertTrue(message_kwargs.get("ephemeral"))


if __name__ == "__main__":
    unittest.main()
