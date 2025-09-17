"""Точка входа для Discord-бота."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

import discord
from discord.ext import commands

from .storage import get_config

log = logging.getLogger("brothel")


class BrothelBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        await self.load_extension("src.cogs.core")
        await self.load_extension("src.cogs.admin")
        config = get_config()
        guild_id = ((config.get("discord") or {}).get("guild_id"))
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Slash-команды синхронизированы с гильдией %s", guild_id)
        else:
            await self.tree.sync()
            log.info("Slash-команды синхронизированы глобально")

    async def on_ready(self) -> None:
        app_info = await self.application_info()
        log.info("Бот авторизован как %s", self.user)
        log.info("Приглашение: %s", discord.utils.oauth_url(app_info.id, scopes=("bot", "applications.commands")))


def load_token(config: dict[str, Any]) -> str:
    token = ((config.get("discord") or {}).get("token"))
    if not token:
        raise RuntimeError("В config.json не указан discord.token")
    return token


async def run_bot(bot: BrothelBot, token: str) -> None:
    try:
        await bot.start(token)
    finally:
        if bot.is_closed():
            return
        await bot.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
    config = get_config()
    token = load_token(config)
    bot = BrothelBot()
    try:
        asyncio.run(run_bot(bot, token))
    except discord.LoginFailure as exc:
        log.error("Не удалось авторизоваться: %s. Проверьте discord.token в config.json.", exc)
        sys.exit(1)
    except discord.HTTPException as exc:
        log.error("API Discord вернул ошибку при запуске бота: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
