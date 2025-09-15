import os
import json
import discord
from discord.ext import commands
from discord import app_commands

from .cogs import core, admin


def load_config():
    """Load config.json (must exist in project root)."""
    path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise RuntimeError(f"Missing config.json at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    config = load_config()
    token = config.get("discord", {}).get("token")
    if not token:
        raise RuntimeError("Missing bot token in config.json")

    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.message_content = True  # useful if you want text triggers

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
        print(f"[INVITE] https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=0&scope=bot%20applications.commands")

    async def setup_hook():
        await bot.load_extension("src.cogs.core")
        await bot.load_extension("src.cogs.admin")
        # Sync commands for all guilds
        for guild in bot.guilds:
            await bot.tree.sync(guild=guild)
            print(f"[SYNC] Guild {guild.id}: {len(bot.tree.get_commands(guild=guild))} commands")

    bot.setup_hook = setup_hook

    bot.run(token)


if __name__ == "__main__":
    main()

