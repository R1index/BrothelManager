import discord, json, os
from discord import app_commands
from discord.ext import commands

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(os.path.dirname(BASE_DIR), "config.json")

def load_cfg():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="sync", description="Resync slash commands (owner only)")
    async def sync(self, interaction: discord.Interaction):
        app = self.bot.application
        if app is None or app.owner is None or interaction.user.id != app.owner.id:
            return await interaction.response.send_message("Only the bot application owner can do this.", ephemeral=True)
        cfg = load_cfg()
        guild_id = int(cfg.get("guild_id", 0))
        if guild_id:
            g = discord.Object(id=guild_id)
            self.bot.tree.copy_global_to(guild=g)
            synced = await self.bot.tree.sync(guild=g)
            await interaction.response.send_message(f"Synced {len(synced)} commands for guild {guild_id}.", ephemeral=True)
        else:
            synced = await self.bot.tree.sync()
            await interaction.response.send_message(f"Globally synced {len(synced)} команд.", ephemeral=True)

    @app_commands.command(name="invite", description="Get bot invite link (applications.commands + bot)")
    async def invite(self, interaction: discord.Interaction):
        user = self.bot.user
        if not user:
            return await interaction.response.send_message("The bot is not initialized yet.", ephemeral=True)
        url = f"https://discord.com/api/oauth2/authorize?client_id={user.id}&permissions=0&scope=bot%20applications.commands"
        await interaction.response.send_message(f"Invite: {url}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
