import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.cogs.admin import Admin


def _make_interaction(user_id=1):
    response = SimpleNamespace(send_message=AsyncMock())
    return SimpleNamespace(user=SimpleNamespace(id=user_id), response=response)


def _sent_message(interaction) -> str | None:
    call = interaction.response.send_message.await_args
    if call is None:
        return None
    if call.kwargs.get("content") is not None:
        return call.kwargs["content"]
    if call.args:
        return call.args[0]
    return None


def test_sync_commands_for_guild(monkeypatch):
    bot = MagicMock()
    bot.tree = MagicMock()
    bot.tree.copy_global_to = MagicMock()
    bot.tree.sync = AsyncMock(return_value=[SimpleNamespace(name="start"), SimpleNamespace(name="profile")])
    admin = Admin(bot)

    monkeypatch.setattr("src.cogs.admin.load_cfg", lambda: {"guild_id": 123})

    report = asyncio.run(admin._sync_commands(report_changes=True))

    assert report["scope"] == "guild"
    assert report["guild_id"] == 123
    assert report["synced_count"] == 2
    bot.tree.copy_global_to.assert_called_once()
    bot.tree.sync.assert_awaited()


def test_sync_commands_global_fallback(monkeypatch):
    bot = MagicMock()
    bot.tree = MagicMock()
    bot.tree.sync = AsyncMock(return_value=[SimpleNamespace(name="start")])
    admin = Admin(bot)

    monkeypatch.setattr("src.cogs.admin.load_cfg", lambda: {"guild_id": "abc"})

    report = asyncio.run(admin._sync_commands(report_changes=True))

    assert report["scope"] == "global"
    assert report["fallback_reason"] == "invalid_guild_id"
    assert report["invalid_value"] == "abc"
    bot.tree.sync.assert_awaited()


def test_sync_command_requires_owner(monkeypatch):
    bot = MagicMock()
    bot.application_info = AsyncMock(return_value=SimpleNamespace(owner=SimpleNamespace(id=1)))
    admin = Admin(bot)

    interaction = _make_interaction(user_id=2)

    asyncio.run(admin.sync.callback(admin, interaction))

    message = _sent_message(interaction)
    assert message and message.startswith("Only the bot application owner")


def test_sync_command_reports_changes(monkeypatch):
    bot = MagicMock()
    bot.application_info = AsyncMock(return_value=SimpleNamespace(owner=SimpleNamespace(id=1)))
    admin = Admin(bot)

    interaction = _make_interaction(user_id=1)

    monkeypatch.setattr(
        "src.cogs.admin.Admin._sync_commands",
        AsyncMock(return_value={"scope": "global", "synced_count": 3, "fallback_reason": None}),
    )

    asyncio.run(admin.sync.callback(admin, interaction))

    message = _sent_message(interaction)
    assert message and "Globally synced 3 commands" in message


def test_invite_requires_user(monkeypatch):
    bot = MagicMock()
    bot.user = None
    admin = Admin(bot)

    interaction = _make_interaction()

    asyncio.run(admin.invite.callback(admin, interaction))

    assert _sent_message(interaction) == "The bot is not initialized yet."


def test_invite_returns_url():
    bot = MagicMock()
    bot.user = SimpleNamespace(id=555)
    admin = Admin(bot)

    interaction = _make_interaction()

    asyncio.run(admin.invite.callback(admin, interaction))

    message = _sent_message(interaction)
    assert message and "https://discord.com/api/oauth2/authorize" in message
