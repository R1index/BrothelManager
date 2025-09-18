import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from src.cogs.core import Core


def _make_interaction(**overrides):
    response = SimpleNamespace(send_message=AsyncMock(), is_done=MagicMock(return_value=False))
    followup = SimpleNamespace(send=AsyncMock())
    data = {
        "user": SimpleNamespace(id=1, display_name="Tester"),
        "response": response,
        "followup": followup,
        "client": SimpleNamespace(get_user=lambda *_: None),
        "guild": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _sent_message(async_mock: AsyncMock) -> str | None:
    call = async_mock.await_args
    if call is None:
        return None
    if call.kwargs.get("content") is not None:
        return call.kwargs["content"]
    if call.args:
        return call.args[0]
    return None


def test_start_rejects_existing_profile(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: object())

    interaction = _make_interaction()

    asyncio.run(core.start.callback(core, interaction))

    args = interaction.response.send_message.await_args
    assert _sent_message(interaction.response.send_message) == "You already have a profile."
    assert args.kwargs["ephemeral"] is True


def test_start_grants_starter_pack(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: None)

    girl = SimpleNamespace(
        name="Алина",
        rarity="Rare",
        uid="g1",
        base_id="base",
        image_url="https://example.com/girl.png",
    )
    pack = SimpleNamespace(currency=250, girls=[girl])
    monkeypatch.setattr("src.cogs.core.grant_starter_pack", lambda uid: pack)
    monkeypatch.setattr("src.cogs.core.profile_image_path", lambda *_: "fake/path.png")
    monkeypatch.setattr("src.cogs.core.os.path.exists", lambda _: False)

    interaction = _make_interaction()

    asyncio.run(core.start.callback(core, interaction))

    args = interaction.response.send_message.await_args
    embed: discord.Embed = args.kwargs["embed"]
    assert isinstance(embed, discord.Embed)
    assert embed.image.url == girl.image_url


def test_profile_requires_registration(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: None)

    interaction = _make_interaction()

    asyncio.run(core.profile.callback(core, interaction))

    args = interaction.response.send_message.await_args
    assert _sent_message(interaction.response.send_message) == "Use /start first."
    assert args.kwargs["ephemeral"] is True


def test_profile_renders_embed(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    girl = SimpleNamespace(
        normalize_skill_structs=MagicMock(),
        apply_regen=MagicMock(),
    )
    brothel = SimpleNamespace(apply_decay=MagicMock(), renown=150)
    player = SimpleNamespace(
        currency=400,
        girls=[girl],
        renown=0,
        ensure_brothel=lambda: brothel,
    )

    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: player)
    save_mock = MagicMock()
    monkeypatch.setattr("src.cogs.core.save_player", save_mock)
    monkeypatch.setattr("src.cogs.core.market_level_from_rep", lambda rep: 2)
    monkeypatch.setattr("src.cogs.core.make_bar", lambda *_, **__: "████")
    monkeypatch.setattr("src.cogs.core.brothel_overview_lines", lambda *_: ("Обзор", "Резервы"))
    monkeypatch.setattr("src.cogs.core.brothel_facility_lines", lambda *_: ["Строка"])

    interaction = _make_interaction()

    asyncio.run(core.profile.callback(core, interaction))

    save_mock.assert_called_once_with(player)
    embed: discord.Embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert "Profile" in embed.title


def test_brothel_opens_view_for_default_action(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    player = SimpleNamespace()
    brothel = SimpleNamespace()
    core._prepare_player = AsyncMock(return_value=(player, brothel))
    save_mock = MagicMock()
    monkeypatch.setattr("src.cogs.core.save_player", save_mock)

    started = {}

    class DummyBrothelView:
        def __init__(self, **kwargs):
            started["kwargs"] = kwargs
            self.start = AsyncMock()
            started["instance"] = self

    monkeypatch.setattr("src.cogs.core.BrothelManageView", DummyBrothelView)

    interaction = _make_interaction()

    asyncio.run(core.brothel.callback(core, interaction))

    save_mock.assert_called_once_with(player)
    assert started["kwargs"]["player"] is player
    started_instance = started["instance"]
    started_instance.start.assert_awaited()
    assert started_instance.start.await_args.args[0] is interaction


def test_brothel_delegates_to_handler(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    player = SimpleNamespace()
    brothel = SimpleNamespace()
    core._prepare_player = AsyncMock(return_value=(player, brothel))
    handler = AsyncMock()
    core._handle_brothel_compat = handler

    interaction = _make_interaction()

    asyncio.run(
        core.brothel.callback(
            core,
            interaction,
            action=SimpleNamespace(value="upgrade"),
            facility=None,
            coins=100,
        )
    )

    handler.assert_awaited()
    assert handler.await_args.args[1] is player
    assert handler.await_args.args[2] is brothel


def test_gacha_requires_profile(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: None)

    interaction = _make_interaction()

    asyncio.run(core.gacha.callback(core, interaction, times=3))

    args = interaction.response.send_message.await_args
    assert _sent_message(interaction.response.send_message) == "Use /start first."
    assert args.kwargs["ephemeral"] is True


def test_gacha_rolls_and_replies(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: object())
    girl = SimpleNamespace(
        name="Лора",
        rarity="Epic",
        image_url="https://example.com",
        level=1,
        skills={},
        subskills={},
    )
    roll_mock = MagicMock(return_value=([girl], 100))
    monkeypatch.setattr("src.cogs.core.roll_gacha", roll_mock)

    interaction = _make_interaction()

    asyncio.run(core.gacha.callback(core, interaction, times=25))

    roll_mock.assert_called_once_with(interaction.user.id, 10)
    message = _sent_message(interaction.response.send_message)
    assert message and "Spent" in message


def test_gacha_handles_error(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: object())

    def raise_error(uid, times):
        raise RuntimeError("No coins")

    monkeypatch.setattr("src.cogs.core.roll_gacha", raise_error)

    interaction = _make_interaction()

    asyncio.run(core.gacha.callback(core, interaction, times=2))

    assert _sent_message(interaction.response.send_message) == "No coins"


def test_train_assigns_mentorship(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    player = SimpleNamespace()
    brothel = SimpleNamespace()
    core._prepare_player = AsyncMock(return_value=(player, brothel))

    monkeypatch.setattr(
        "src.cogs.core.Core._resolve_training_focus",
        staticmethod(lambda *args: ("main", "Human", None)),
    )
    assign_mock = MagicMock(return_value=(True, "ok"))
    core._assign_training = assign_mock
    responder = AsyncMock()
    core._save_and_respond = responder

    interaction = _make_interaction()

    asyncio.run(
        core.train.callback(
            core,
            interaction,
            action=SimpleNamespace(value="assign"),
            mentor="m1",
            student="s1",
            focus_type=SimpleNamespace(value="main"),
            main_skill=SimpleNamespace(value="Human"),
            sub_skill=None,
        )
    )

    assign_mock.assert_called_once()
    responder.assert_awaited()
    assert responder.await_args.kwargs["content"] == "ok"


def test_train_finish_delegates(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    player = SimpleNamespace()
    brothel = SimpleNamespace()
    core._prepare_player = AsyncMock(return_value=(player, brothel))
    finish_mock = AsyncMock()
    core._handle_train_finish = finish_mock

    interaction = _make_interaction()

    asyncio.run(
        core.train.callback(
            core,
            interaction,
            action=SimpleNamespace(value="finish"),
            mentor="m",
            student="s",
        )
    )

    finish_mock.assert_awaited()
    assert finish_mock.await_args.args[1] is player
    assert finish_mock.await_args.args[2] is brothel


def test_train_view_started_without_action(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    player = SimpleNamespace()
    brothel = SimpleNamespace()
    core._prepare_player = AsyncMock(return_value=(player, brothel))
    save_mock = MagicMock()
    monkeypatch.setattr("src.cogs.core.save_player", save_mock)

    started = {}

    class DummyTrainingView:
        def __init__(self, **kwargs):
            started["kwargs"] = kwargs
            self.start = AsyncMock()
            started["instance"] = self

    monkeypatch.setattr("src.cogs.core.TrainingManageView", DummyTrainingView)

    interaction = _make_interaction()

    asyncio.run(core.train.callback(core, interaction))

    save_mock.assert_called_once_with(player)
    started_instance = started["instance"]
    started_instance.start.assert_awaited()
    assert started_instance.start.await_args.args[0] is interaction


def test_girls_requires_collection(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: None)

    interaction = _make_interaction()

    asyncio.run(core.girls.callback(core, interaction))

    message = _sent_message(interaction.response.send_message)
    assert message and "You have no girls" in message


def test_girls_lists_owned_girls(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    girl = SimpleNamespace()
    brothel = SimpleNamespace(apply_decay=lambda: None, renown=42)
    player = SimpleNamespace(girls=[girl], ensure_brothel=lambda: brothel)
    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: player)
    save_mock = MagicMock()
    monkeypatch.setattr("src.cogs.core.save_player", save_mock)

    embeds = []
    captures = {}

    def fake_build_girl_embed(girl_obj, brothel_obj):
        embed = discord.Embed(title="Герл")
        embeds.append(embed)
        return embed, None

    monkeypatch.setattr("src.cogs.core.build_girl_embed", fake_build_girl_embed)

    class DummyPaginator:
        def __init__(self, pages, invoker_id, timeout, files):
            self.pages = pages
            self.send = AsyncMock()
            self.files = files
            captures["instance"] = self

    monkeypatch.setattr("src.cogs.core.Paginator", DummyPaginator)

    interaction = _make_interaction()

    asyncio.run(core.girls.callback(core, interaction))

    save_mock.assert_called_once_with(player)
    paginator = captures["instance"]
    paginator.send.assert_awaited()


def test_top_brothel_leaderboard(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    brothel = SimpleNamespace(rooms=3, cleanliness=80, morale=90)
    player = SimpleNamespace(user_id=7, renown=120, girls=[1, 2], ensure_brothel=lambda: brothel)
    monkeypatch.setattr("src.cogs.core.brothel_leaderboard", lambda limit: [(12345, player)])
    monkeypatch.setattr("src.cogs.core.girl_leaderboard", lambda limit: [])

    created = {}

    class DummyTopView:
        def __init__(self, **kwargs):
            created["kwargs"] = kwargs

    monkeypatch.setattr("src.cogs.core.TopLeaderboardView", DummyTopView)

    interaction = _make_interaction()

    asyncio.run(core.top.callback(core, interaction, category=None))

    args = interaction.response.send_message.await_args
    assert isinstance(args.kwargs["embed"], discord.Embed)
    assert args.kwargs["view"] is not None
    assert created["kwargs"]["category"] == "brothel"


def test_top_girl_leaderboard(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    girl = SimpleNamespace(
        uid="g1",
        name="Лия",
        rarity="Epic",
        level=30,
        health=90,
        health_max=100,
        stamina=50,
        stamina_max=60,
        lust=40,
        lust_max=50,
    )
    player = SimpleNamespace(user_id=9, renown=300, girls=[girl], ensure_brothel=lambda: SimpleNamespace())
    monkeypatch.setattr("src.cogs.core.brothel_leaderboard", lambda limit: [])
    monkeypatch.setattr("src.cogs.core.girl_leaderboard", lambda limit: [(5555, player, girl)])

    captures = {}

    class DummyTopView:
        def __init__(self, **kwargs):
            captures["kwargs"] = kwargs

    monkeypatch.setattr("src.cogs.core.TopLeaderboardView", DummyTopView)

    interaction = _make_interaction()

    asyncio.run(
        core.top.callback(
            core,
            interaction,
            category=SimpleNamespace(value="girls"),
        )
    )

    args = interaction.response.send_message.await_args
    assert isinstance(args.kwargs["embed"], discord.Embed)
    assert args.kwargs["view"] is not None
    assert captures["kwargs"]["category"] == "girls"


def test_market_validates_level(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    brothel = SimpleNamespace(apply_decay=MagicMock(), renown=0)
    player = SimpleNamespace(
        ensure_brothel=lambda: brothel,
        girls=[],
        renown=0,
    )
    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: player)
    monkeypatch.setattr("src.cogs.core.save_player", MagicMock())
    monkeypatch.setattr("src.cogs.core.market_level_from_rep", lambda *_: 1)

    interaction = _make_interaction()

    asyncio.run(core.market.callback(core, interaction, level=5))

    message = _sent_message(interaction.response.send_message)
    assert message and "Level must be between" in message


def test_market_shows_embed(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    girl = SimpleNamespace(normalize_skill_structs=MagicMock(), apply_regen=MagicMock())
    brothel = SimpleNamespace(apply_decay=MagicMock(), renown=120)
    player = SimpleNamespace(
        ensure_brothel=lambda: brothel,
        girls=[girl],
        renown=0,
    )
    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: player)
    monkeypatch.setattr("src.cogs.core.save_player", MagicMock())
    monkeypatch.setattr("src.cogs.core.market_level_from_rep", lambda *_: 3)
    monkeypatch.setattr("src.cogs.core.refresh_market_if_stale", lambda *_ , **__: SimpleNamespace())

    class DummyMarketView:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def build_embed(self):
            return discord.Embed(title="Market")

    monkeypatch.setattr("src.cogs.core.MarketWorkView", DummyMarketView)

    interaction = _make_interaction()

    asyncio.run(core.market.callback(core, interaction, level=None))

    args = interaction.response.send_message.await_args
    assert isinstance(args.kwargs["embed"], discord.Embed)
    assert isinstance(args.kwargs["view"], DummyMarketView)


def test_heal_validations(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    girl = SimpleNamespace()
    player = SimpleNamespace(get_girl=lambda _: None)
    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: None)

    interaction = _make_interaction()

    asyncio.run(core.heal.callback(core, interaction, girl_id="g1"))

    assert _sent_message(interaction.response.send_message) == "Use /start first."

    player = SimpleNamespace(get_girl=lambda uid: None)
    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: player)

    interaction = _make_interaction()

    asyncio.run(core.heal.callback(core, interaction, girl_id="g1"))
    assert _sent_message(interaction.response.send_message) == "Girl not found."


def test_heal_process(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    girl = SimpleNamespace(
        normalize_skill_structs=MagicMock(),
        apply_regen=MagicMock(),
        health=40,
        health_max=100,
        level=10,
        name="Алиса",
    )
    player = SimpleNamespace(
        currency=1000,
        get_girl=lambda uid: girl,
        ensure_brothel=lambda: SimpleNamespace(),
    )

    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: player)
    save_mock = MagicMock()
    monkeypatch.setattr("src.cogs.core.save_player", save_mock)

    interaction = _make_interaction()

    asyncio.run(core.heal.callback(core, interaction, girl_id="g1", amount=20))

    save_mock.assert_called_once_with(player)
    message = _sent_message(interaction.response.send_message)
    assert message and "Restored" in message


def test_heal_checks_coins(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    girl = SimpleNamespace(
        normalize_skill_structs=MagicMock(),
        apply_regen=MagicMock(),
        health=10,
        health_max=20,
        level=60,
        name="Кира",
    )
    player = SimpleNamespace(
        currency=10,
        get_girl=lambda uid: girl,
        ensure_brothel=lambda: SimpleNamespace(),
    )

    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: player)

    interaction = _make_interaction()

    asyncio.run(core.heal.callback(core, interaction, girl_id="g1", amount=20))

    message = _sent_message(interaction.response.send_message)
    assert message and "Not enough coins" in message


def test_dismantle_shows_confirmation(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    girl = SimpleNamespace(name="Лия", rarity="Rare", uid="g1", base_id="b1", image_url="https://img")
    player = SimpleNamespace(get_girl=lambda uid: girl)
    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: player)
    monkeypatch.setattr("src.cogs.core.profile_image_path", lambda *_: "path.png")
    monkeypatch.setattr("src.cogs.core.os.path.exists", lambda _: False)

    interaction = _make_interaction()

    asyncio.run(core.dismantle.callback(core, interaction, girl_id="g1", confirm=False))

    args = interaction.response.send_message.await_args
    assert args.kwargs["view"].__class__.__name__ == "ConfirmView"


def test_dismantle_executes(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    girl = SimpleNamespace(name="Лия", rarity="Rare", uid="g1")
    player = SimpleNamespace(get_girl=lambda uid: girl)
    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: player)
    save_mock = MagicMock()
    monkeypatch.setattr("src.cogs.core.save_player", save_mock)
    monkeypatch.setattr(
        "src.cogs.core.dismantle_girl",
        lambda pl, uid: {"ok": True, "name": girl.name, "rarity": girl.rarity, "reward": 100},
    )

    interaction = _make_interaction()

    asyncio.run(core.dismantle.callback(core, interaction, girl_id="g1", confirm=True))

    save_mock.assert_called_once_with(player)
    message = _sent_message(interaction.response.send_message)
    assert message and "Dismantled" in message


def test_dismantle_handles_failure(monkeypatch):
    core = Core.__new__(Core)
    core.bot = MagicMock()

    girl = SimpleNamespace(name="Лия", rarity="Rare", uid="g1")
    player = SimpleNamespace(get_girl=lambda uid: girl)
    monkeypatch.setattr("src.cogs.core.load_player", lambda uid: player)
    save_mock = MagicMock()
    monkeypatch.setattr("src.cogs.core.save_player", save_mock)
    monkeypatch.setattr(
        "src.cogs.core.dismantle_girl",
        lambda pl, uid: {"ok": False, "reason": "No"},
    )

    interaction = _make_interaction()

    asyncio.run(core.dismantle.callback(core, interaction, girl_id="g1", confirm=True))

    message = _sent_message(interaction.response.send_message)
    assert message == "❌ No"

