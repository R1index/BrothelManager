"""Административные команды."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..storage import get_config


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="sync", description="Перерегистрировать slash-команды")
    async def sync(self, interaction: discord.Interaction) -> None:
        config = get_config()
        guild_id = ((config.get("discord") or {}).get("guild_id"))
        try:
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                synced = await self.bot.tree.sync(guild=guild)
            else:
                synced = await self.bot.tree.sync()
            await interaction.response.send_message(
                f"Синхронизировано {len(synced)} команд", ephemeral=True
            )
        except Exception as exc:  # pragma: no cover - отладочная ветка
            await interaction.response.send_message(f"Ошибка синхронизации: {exc}", ephemeral=True)

    @app_commands.command(name="invite", description="Получить ссылку-приглашение")
    async def invite(self, interaction: discord.Interaction) -> None:
        app_info = await self.bot.application_info()
        perms = discord.Permissions(administrator=False)
        perms.update(send_messages=True, embed_links=True, attach_files=True)
        url = discord.utils.oauth_url(app_info.id, permissions=perms, scopes=("bot", "applications.commands"))
        await interaction.response.send_message(url, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))


__all__ = ["Admin", "setup"]
