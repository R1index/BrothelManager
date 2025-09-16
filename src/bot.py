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

        guild_id = config.get("discord", {}).get("guild_id")
        synced = []

        if guild_id:
            try:
                guild_obj = discord.Object(id=int(guild_id))
            except (TypeError, ValueError):
                print(f"[SYNC] Invalid guild id in config: {guild_id!r}. Falling back to global sync.")
                synced = await bot.tree.sync()
                print(f"[SYNC] Registered {len(synced)} global commands.")
            else:
                bot.tree.copy_global_to(guild=guild_obj)
                synced = await bot.tree.sync(guild=guild_obj)
                print(f"[SYNC] Guild {guild_id}: {len(synced)} commands")
        else:
            synced = await bot.tree.sync()
            print(f"[SYNC] Registered {len(synced)} global commands.")

    bot.setup_hook = setup_hook

    bot.run(token)


if __name__ == "__main__":
    main()

