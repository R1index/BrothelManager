"""Точка входа для запуска Discord-бота."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from .cogs.core import Core
from .storage import get_service

log = logging.getLogger(__name__)


def load_config() -> dict:
    return get_service().config


def create_bot() -> commands.Bot:
    intents = discord.Intents.none()
    intents.guilds = True
    intents.messages = False
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def setup_hook() -> None:  # pragma: no cover - инфраструктурный код
        await bot.add_cog(Core(bot))
        log.info("Core cog registered")

    return bot


def main() -> None:  # pragma: no cover - точка входа
    config = load_config()
    token = (config.get("discord") or {}).get("token")
    if not token:
        raise RuntimeError("Отсутствует discord.token в config.json")
    bot = create_bot()
    asyncio.run(bot.start(token))


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    main()
