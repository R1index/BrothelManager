import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

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


def test_brothel_error_saves_player(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    player = MagicMock()
    player.currency = 100
    player.girls = []
    player.renown = 0

    brothel = MagicMock()
    brothel.renown = 25
    brothel.apply_decay = MagicMock()
    player.ensure_brothel.return_value = brothel

    monkeypatch.setattr("src.cogs.core.load_player", lambda _: player)
    save_mock = MagicMock()
    monkeypatch.setattr("src.cogs.core.save_player", save_mock)

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=1, display_name="Tester"),
        response=SimpleNamespace(
            is_done=MagicMock(return_value=False),
            send_message=AsyncMock(),
        ),
        followup=SimpleNamespace(send=AsyncMock()),
    )

    asyncio.run(
        core.brothel.callback(
            core,
            interaction,
            action=SimpleNamespace(value="promote"),
            facility=None,
            coins=0,
        )
    )

    save_mock.assert_called_once_with(player)


def test_train_list_saves_player_when_empty(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    player = MagicMock()
    player.currency = 0
    player.girls = []
    player.renown = 0

    brothel = MagicMock()
    brothel.renown = 10
    brothel.apply_decay = MagicMock()
    brothel.training = []
    player.ensure_brothel.return_value = brothel

    monkeypatch.setattr("src.cogs.core.load_player", lambda _: player)
    save_mock = MagicMock()
    monkeypatch.setattr("src.cogs.core.save_player", save_mock)

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=2, display_name="Trainer"),
        response=SimpleNamespace(
            is_done=MagicMock(return_value=False),
            send_message=AsyncMock(),
        ),
        followup=SimpleNamespace(send=AsyncMock()),
    )

    asyncio.run(
        core.train.callback(
            core,
            interaction,
            SimpleNamespace(value="list"),
        )
    )

    save_mock.assert_called_once_with(player)


def test_resolve_training_focus_infers_main_choice():
    focus_type, focus_name, error = Core._resolve_training_focus(
        None,
        SimpleNamespace(value="Human"),
        None,
    )
    assert error is None
    assert focus_type == "main"
    assert focus_name == "Human"


def test_resolve_training_focus_conflict_returns_error():
    _, _, error = Core._resolve_training_focus(
        None,
        SimpleNamespace(value="Human"),
        SimpleNamespace(value="VAGINAL"),
    )
    assert error == "Select either a main skill or a sub-skill, not both."


def test_format_training_focus_labels():
    assert Core._format_training_focus("sub", "VAGINAL") == "Vaginal (sub-skill)"
    assert Core._format_training_focus(None, None) == "general technique"


def test_training_bonus_requires_time(monkeypatch):
    now = 1_000_000
    monkeypatch.setattr("src.cogs.core.time.time", lambda: now)

    mentor = SimpleNamespace(
        level=8,
        vitality_level=4,
        skills={"A": {"level": 4}, "B": {"level": 3}},
        subskills={"x": {"level": 2}},
    )
    student = SimpleNamespace(
        level=2,
        vitality_level=1,
        skills={"A": {"level": 1}},
        subskills={},
    )

    short_assignment = SimpleNamespace(since_ts=now - 120)
    long_assignment = SimpleNamespace(since_ts=now - 3600)

    short_bonus = Core._calculate_training_bonus(short_assignment, mentor, student)
    long_bonus = Core._calculate_training_bonus(long_assignment, mentor, student)

    assert short_bonus < 0.05
    assert long_bonus > short_bonus * 5


def test_train_finish_refuses_short_sessions(monkeypatch):
    now = 2_000_000
    monkeypatch.setattr("src.cogs.core.time.time", lambda: now)

    core = Core.__new__(Core)
    core.bot = MagicMock()

    player = MagicMock()
    mentor_girl = MagicMock()
    mentor_girl.uid = "mentor"
    mentor_girl.name = "Mentor"

    student_girl = MagicMock()
    student_girl.uid = "student"
    student_girl.name = "Student"

    player.get_girl.side_effect = lambda uid: {
        "mentor": mentor_girl,
        "student": student_girl,
    }.get(uid)

    assignment = SimpleNamespace(
        mentor_uid="mentor",
        student_uid="student",
        since_ts=now - 60,
        focus_type="main",
        focus="Human",
    )

    brothel = MagicMock()
    brothel.training_for.return_value = assignment
    brothel.stop_training = MagicMock()

    save_mock = MagicMock()
    monkeypatch.setattr("src.cogs.core.save_player", save_mock)

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=3, display_name="Manager"),
        response=SimpleNamespace(
            is_done=MagicMock(return_value=False),
            send_message=AsyncMock(),
        ),
        followup=SimpleNamespace(send=AsyncMock()),
    )

    asyncio.run(
        core._handle_train_finish(
            interaction,
            player,
            brothel,
            mentor=None,
            student="student",
        )
    )

    brothel.stop_training.assert_not_called()
    student_girl.grant_training_bonus.assert_not_called()
    assert "too short" in interaction.response.send_message.await_args.kwargs["content"].lower()
    save_mock.assert_called_once_with(player)


if __name__ == "__main__":
    unittest.main()
