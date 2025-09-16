from __future__ import annotations

import discord, json, os
from typing import Any, Dict, Optional
from discord import app_commands
from discord.ext import commands

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(os.path.dirname(BASE_DIR), "config.json")

def load_cfg() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    return {}

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _sync_commands(self, *, report_changes: bool = False) -> Optional[Dict[str, Any]]:
        cfg = load_cfg()
        raw_guild_id: Any = None
        if isinstance(cfg, dict):
            raw_guild_id = cfg.get("guild_id")
            if raw_guild_id is None:
                discord_section = cfg.get("discord")
                if isinstance(discord_section, dict):
                    raw_guild_id = discord_section.get("guild_id")

        guild_id: Optional[int] = None
        invalid_guild_value: Any = None
        if isinstance(raw_guild_id, int):
            guild_id = raw_guild_id if raw_guild_id > 0 else None
        elif isinstance(raw_guild_id, str):
            trimmed = raw_guild_id.strip()
            if trimmed:
                try:
                    guild_id = int(trimmed)
                except ValueError:
                    invalid_guild_value = raw_guild_id
            else:
                guild_id = None
        elif raw_guild_id not in (None, "", 0):
            invalid_guild_value = raw_guild_id

        result: Dict[str, Any] = {
            "scope": "guild" if guild_id else "global",
            "guild_id": guild_id,
            "synced_count": 0,
            "commands": [],
            "fallback_reason": None,
        }

        if guild_id:
            guild_obj = discord.Object(id=guild_id)
            self.bot.tree.copy_global_to(guild=guild_obj)
            synced = await self.bot.tree.sync(guild=guild_obj)
            result["commands"] = [cmd.name for cmd in synced]
            result["synced_count"] = len(synced)
        else:
            if invalid_guild_value is not None:
                result["fallback_reason"] = "invalid_guild_id"
                result["invalid_value"] = invalid_guild_value
            synced = await self.bot.tree.sync()
            result["commands"] = [cmd.name for cmd in synced]
            result["synced_count"] = len(synced)

        if report_changes:
            return result
        return None

    @app_commands.command(name="sync", description="Resync slash commands (owner only)")
    async def sync(self, interaction: discord.Interaction) -> None:
        app_info = await self.bot.application_info()
        owner = getattr(app_info, "owner", None) if app_info else None

        if owner is not None:
            is_owner = interaction.user.id == owner.id
        else:
            is_owner = await self.bot.is_owner(interaction.user)

        if not is_owner:
            await interaction.response.send_message(
                "Only the bot application owner can do this.", ephemeral=True
            )
            return

        report = await self._sync_commands(report_changes=True)
        message: str
        if report is None:
            message = "No commands were synchronized."
        else:
            scope = report.get("scope")
            count = report.get("synced_count", 0)
            fallback = report.get("fallback_reason")
            if scope == "guild" and report.get("guild_id"):
                message = f"Synced {count} commands for guild {report['guild_id']}."
            else:
                message = f"Globally synced {count} commands."
                if fallback == "invalid_guild_id":
                    invalid_value = report.get("invalid_value")
                    message = (
                        f"Invalid guild id {invalid_value!r}; globally synced {count} commands instead."
                    )

        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="invite", description="Get bot invite link (applications.commands + bot)")
    async def invite(self, interaction: discord.Interaction) -> None:
        user = self.bot.user
        if not user:
            await interaction.response.send_message("The bot is not initialized yet.", ephemeral=True)
            return
        url = f"https://discord.com/api/oauth2/authorize?client_id={user.id}&permissions=0&scope=bot%20applications.commands"
        await interaction.response.send_message(f"Invite: {url}", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
