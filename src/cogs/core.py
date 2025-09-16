import os
import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..storage import (
    load_player, save_player, grant_starter_pack, roll_gacha,
    refresh_market_if_stale, load_market, save_market,
    resolve_job, dismantle_girl, evaluate_job
)
from ..models import (
    RARITY_COLORS, make_bar, skill_xp_threshold, get_level, get_xp, market_level_from_rep,
    MAIN_SKILLS, SUB_SKILLS, stat_xp_threshold,
)
from ..assets_util import profile_image_path

EMOJI_COIN = "🪙"
EMOJI_SPARK = "✨"
EMOJI_GIRL = "👧"
EMOJI_MARKET = "🛒"
EMOJI_ENERGY = "⚡"
EMOJI_HEART = "❤️"
EMOJI_OK = "✅"
EMOJI_X = "❌"


# -----------------------------------------------------------------------------
# Paginator that supports per-page local file attachments (paths)
# -----------------------------------------------------------------------------
class Paginator(discord.ui.View):
    def __init__(self, pages, invoker_id, timeout: float = 120.0, files=None):
        """
        pages: list[discord.Embed]
        files: list[str | None]  -> absolute paths to local files or None
        """
        super().__init__(timeout=timeout)
        self.pages = pages
        self.invoker_id = invoker_id
        self.index = 0
        self.page_paths = files or [None] * len(pages)
        self._update_buttons()

    def _update_buttons(self):
        self.first_btn.disabled = self.index <= 0
        self.prev_btn.disabled = self.index <= 0
        self.next_btn.disabled = self.index >= len(self.pages) - 1
        self.last_btn.disabled = self.index >= len(self.pages) - 1

    def _make_file(self):
        p = self.page_paths[self.index]
        if p and os.path.exists(p):
            return discord.File(p, filename=os.path.basename(p))
        return None

    async def send(self, interaction: discord.Interaction):
        f = self._make_file()
        if f:
            await interaction.response.send_message(embed=self.pages[self.index], view=self, file=f)
        else:
            await interaction.response.send_message(embed=self.pages[self.index], view=self)

    async def _edit_page(self, interaction: discord.Interaction):
        f = self._make_file()
        if f:
            await interaction.response.edit_message(embed=self.pages[self.index], view=self, attachments=[f])
        else:
            await interaction.response.edit_message(embed=self.pages[self.index], view=self, attachments=[])

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.secondary)
    async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This isn't your view.", ephemeral=True)
            return
        self.index = 0
        self._update_buttons()
        await self._edit_page(interaction)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This isn't your view.", ephemeral=True)
            return
        if self.index > 0:
            self.index -= 1
        self._update_buttons()
        await self._edit_page(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This isn't your view.", ephemeral=True)
            return
        if self.index < len(self.pages) - 1:
            self.index += 1
        self._update_buttons()
        await self._edit_page(interaction)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary)
    async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This isn't your view.", ephemeral=True)
            return
        self.index = len(self.pages) - 1
        self._update_buttons()
        await self._edit_page(interaction)


# -----------------------------------------------------------------------------
# Core Cog
# -----------------------------------------------------------------------------
class Core(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.market_refresher.start()

    def cog_unload(self):
        self.market_refresher.cancel()

    @tasks.loop(minutes=5)
    async def market_refresher(self):
        """Refresh all users' markets every 5 minutes by scanning data/users directory."""
        try:
            from ..storage import USERS_DIR
            with os.scandir(USERS_DIR) as it:
                for entry in it:
                    if not entry.name.endswith(".json"):
                        continue
                    try:
                        uid = int(entry.name[:-5])
                    except ValueError:
                        continue
                    # force refresh to keep market in sync with reputation-based level
                    refresh_market_if_stale(uid, max_age_sec=0)
        except Exception as e:
            print("[market_refresher] error:", e)

    # -------------------------------------------------------------------------
    # Commands
    # -------------------------------------------------------------------------
    @app_commands.command(name="start", description="Create your profile and get a starter pack")
    async def start(self, interaction: discord.Interaction):
        uid = interaction.user.id
        pl = load_player(uid)
        if pl:
            await interaction.response.send_message("You already have a profile.", ephemeral=True)
            return

        pl = grant_starter_pack(uid)
        girl = pl.girls[0]

        embed = discord.Embed(
            title=f"{EMOJI_SPARK} Starter Pack",
            description=f"You received {EMOJI_COIN} **500** and your first girl!",
            color=0x60A5FA,
        )
        embed.add_field(
            name=f"{EMOJI_GIRL} Girl",
            value=f"**{girl.name}** [{girl.rarity}] • `{girl.uid}`",
            inline=False
        )

        # Prefer local profile art if present
        img = profile_image_path(girl.name, girl.base_id)
        if img and os.path.exists(img):
            embed.set_image(url=f"attachment://{os.path.basename(img)}")
            await interaction.response.send_message(embed=embed, file=discord.File(img))
        else:
            embed.set_image(url=girl.image_url)
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="profile", description="Show your profile")
    async def profile(self, interaction: discord.Interaction):
        pl = load_player(interaction.user.id)
        if not pl:
            await interaction.response.send_message("Use /start first.", ephemeral=True)
            return

        # Normalize / regen before render
        for g in pl.girls:
            g.normalize_skill_structs()
            g.apply_regen()
        save_player(pl)

        # Reputation progress to next market level
        rep = int(pl.reputation)
        mkt_lvl = market_level_from_rep(rep)
        next_cap = (mkt_lvl + 1) * 100
        base_cap = mkt_lvl * 100
        cur_seg = rep - base_cap
        need_seg = max(1, next_cap - base_cap)
        rep_bar = make_bar(cur_seg, need_seg, length=12)

        embed = discord.Embed(title=f"{interaction.user.display_name}'s Profile", color=0x60A5FA)
        embed.add_field(name=f"{EMOJI_COIN} Coins", value=str(pl.currency))
        embed.add_field(name=f"{EMOJI_GIRL} Girls", value=str(len(pl.girls)))
        embed.add_field(name="⭐ Reputation", value=f"{rep} / {next_cap}  {rep_bar}", inline=False)
        embed.add_field(name="🏷️ Market Level", value=str(mkt_lvl))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="gacha", description="Roll the gacha (100 coins per roll)")
    @app_commands.describe(times="How many times to roll (1-10)")
    async def gacha(self, interaction: discord.Interaction, times: int = 1):
        times = max(1, min(times, 10))
        pl = load_player(interaction.user.id)
        if not pl:
            await interaction.response.send_message("Use /start first.", ephemeral=True)
            return
        cost = 100 * times
        if pl.currency < cost:
            await interaction.response.send_message("Not enough coins.", ephemeral=True)
            return

        pl.currency -= cost
        save_player(pl)

        girls = roll_gacha(interaction.user.id, times)
        # re-load to display current state if needed
        pl = load_player(interaction.user.id)

        embeds = []
        for g in girls:
            em = discord.Embed(
                title=f"{EMOJI_GIRL} {g.name} [{g.rarity}]",
                color=RARITY_COLORS.get(g.rarity, 0x999999)
            )
            # For /gacha we use remote images to avoid multiple local attachments
            em.set_image(url=g.image_url)
            em.add_field(name="Level", value=str(g.level))
            em.add_field(name="Skills", value=", ".join([f"{k}: L{v.get('level',0)}" for k, v in g.skills.items()]) or "—")
            em.add_field(name="Sub-skills", value=", ".join([f"{k}: L{v.get('level',0)}" for k, v in g.subskills.items()]) or "—")
            embeds.append(em)

        await interaction.response.send_message(
            content=f"Spent {EMOJI_COIN} **{cost}**. You got **{len(girls)}** roll(s).",
            embeds=embeds[:10],
        )

    @app_commands.command(name="girls", description="List your girls")
    async def girls(self, interaction: discord.Interaction):
        pl = load_player(interaction.user.id)
        if not pl or not pl.girls:
            await interaction.response.send_message("You have no girls. Use /start or /gacha.", ephemeral=True)
            return

        pages = []
        files = []  # per-page local file paths (or None)

        for g in pl.girls:
            g.normalize_skill_structs()
            g.apply_regen()

            em = discord.Embed(
                title=f"{EMOJI_GIRL} {g.name} [{g.rarity}] • `{g.uid}`",
                color=0x9CA3AF
            )

            # prefer local profile art if present
            img_path = profile_image_path(g.name, g.base_id)

            if img_path and os.path.exists(img_path):
                em.set_image(url=f"attachment://{os.path.basename(img_path)}")
                files.append(img_path)
            else:
                em.set_image(url=g.image_url)
                files.append(None)

            # base stats
            vit_need = stat_xp_threshold(g.vitality_level)
            end_need = stat_xp_threshold(g.endurance_level)
            vit_bar = make_bar(g.vitality_xp, vit_need, length=10)
            end_bar = make_bar(g.endurance_xp, end_need, length=10)
            em.add_field(name="Lvl / EXP", value=f"{g.level} / {g.exp}", inline=True)
            em.add_field(
                name="Vitals",
                value=f"{EMOJI_HEART} {g.health}/{g.health_max}\n{EMOJI_ENERGY} {g.stamina}/{g.stamina_max}",
                inline=True,
            )
            em.add_field(
                name="Resilience",
                value=(
                    f"Vit L{g.vitality_level} {vit_bar} {g.vitality_xp}/{vit_need}\n"
                    f"End L{g.endurance_level} {end_bar} {g.endurance_xp}/{end_need}"
                ),
                inline=False,
            )

            # bio block
            bio_lines = []
            if g.breast_size: bio_lines.append(f"Breast: **{g.breast_size}**")
            if g.body_shape:  bio_lines.append(f"Body: **{g.body_shape}**")
            dims = []
            if g.height_cm: dims.append(f"{g.height_cm} cm")
            if g.weight_kg: dims.append(f"{g.weight_kg} kg")
            if g.age:       dims.append(f"{g.age} y/o")
            if dims: bio_lines.append(" / ".join(dims))
            if g.traits: bio_lines.append("Traits: " + ", ".join(g.traits))
            if g.pregnant:
                pts = g.pregnancy_points()
                preg_bar = make_bar(pts, 30, length=12)
                bio_lines.append(f"🤰 Pregnant {pts}/30  {preg_bar}")
            else:
                bio_lines.append("Not pregnant")
            em.add_field(name="Profile", value="\n".join(bio_lines) or "—", inline=False)

            # progress lines with prefs tags
            def fmt_skill_lines(skmap, names, prefs):
                lines = []
                for nm in names:
                    lvl  = get_level(skmap, nm)
                    xp   = get_xp(skmap, nm)
                    need = skill_xp_threshold(lvl)
                    bar  = make_bar(xp, need, length=12)
                    pref = str(prefs.get(nm, "true")).lower()
                    tag  = "🚫" if pref == "false" else ("💗" if pref == "fav" else "•")
                    lines.append(f"{tag} **{nm}** L{lvl} {bar} {xp}/{need}")
                return "\n".join(lines)

            em.add_field(
                name="Skills",
                value=fmt_skill_lines(g.skills, MAIN_SKILLS, g.prefs_skills),
                inline=False
            )
            em.add_field(
                name="Sub",
                value=fmt_skill_lines(g.subskills, SUB_SKILLS, g.prefs_subskills),
                inline=False
            )

            pages.append(em)

        save_player(pl)
        view = Paginator(pages, interaction.user.id, timeout=120, files=files)
        await view.send(interaction)

    @app_commands.command(name="market", description="Show the service market (auto-refreshes every 5 minutes). Optionally specify a level")
    @app_commands.describe(level="Optional market level override")
    async def market(self, interaction: discord.Interaction, level: int | None = None):
        uid = interaction.user.id
        pl = load_player(uid)
        if not pl:
            await interaction.response.send_message("Use /start first.", ephemeral=True)
            return

        for g in pl.girls:
            g.normalize_skill_structs()
            g.apply_regen()
        save_player(pl)

        max_lvl = market_level_from_rep(pl.reputation)
        if level is not None:
            if not (0 <= level <= max_lvl):
                await interaction.response.send_message(
                    f"Level must be between 0 and {max_lvl}.", ephemeral=True
                )
                return

        m = refresh_market_if_stale(uid, max_age_sec=300, forced_level=level)

        def build_market_embed(market, selected_girl=None):
            embed = discord.Embed(
                title=f"{EMOJI_MARKET} Service Market — Lv{market.level}",
                color=0x34D399
            )
            if not market.jobs:
                embed.description = "No jobs available right now."
            elif selected_girl:
                embed.description = (
                    f"Previewing with **{selected_girl.name}** • `{selected_girl.uid}`\n"
                    f"{EMOJI_HEART} {selected_girl.health}/{selected_girl.health_max} • "
                    f"{EMOJI_ENERGY} {selected_girl.stamina}/{selected_girl.stamina_max}"
                )
            else:
                embed.description = "Select a girl below to preview success, reward and injury chances."

            for j in market.jobs:
                sub_part = f" + {j.demand_sub} L{j.demand_sub_level}" if j.demand_sub else ""
                field_name = f"`{j.job_id}` • {j.demand_main} L{j.demand_level}{sub_part}"
                value_lines = [f"{EMOJI_COIN} Base pay: **{j.pay}** • Difficulty: {j.difficulty}"]

                if selected_girl:
                    info = evaluate_job(selected_girl, j)
                    if info["blocked_main"] or (j.demand_sub and info["blocked_sub"]):
                        value_lines.append("🚫 Preferences block this job.")
                    elif not info["meets_main"] or not info["meets_sub"]:
                        lacking = []
                        if not info["meets_main"]:
                            lacking.append(f"{j.demand_main} L{j.demand_level}")
                        if j.demand_sub and not info["meets_sub"]:
                            lacking.append(f"{j.demand_sub} L{j.demand_sub_level}")
                        value_lines.append("⚠️ Needs: " + ", ".join(lacking))
                    elif not info["health_ok"]:
                        value_lines.append("⚠️ Needs healing before working.")
                    elif not info["stamina_ok"]:
                        value_lines.append(
                            f"⚠️ Requires {info['stamina_cost']} stamina (current {selected_girl.stamina})."
                        )
                    else:
                        success_pct = int(round(info["success_chance"] * 100))
                        injury_pct = int(round(info["injury_chance"] * 100))
                        potential_pay = max(0, int(info["base_reward"] * info["reward_multiplier"]))
                        expected_pay = max(0, int(info["expected_reward"]))
                        value_lines.append(
                            "\n".join(
                                [
                                    f"🎯 Success: {success_pct}% • Injury: {injury_pct}%",
                                    f"{EMOJI_COIN} Potential: **{potential_pay}** (x{info['reward_multiplier']:.2f})",
                                    f"⚡ Cost: {info['stamina_cost']} • E[pay] ≈ {expected_pay}",
                                ]
                            )
                        )
                else:
                    value_lines.append("Use the selector to preview with one of your girls.")

                embed.add_field(name=field_name, value="\n".join(value_lines), inline=False)

            embed.set_footer(text="Auto-refresh: every 5 minutes • Preview considers stamina, health and endurance")
            return embed

        class MarketView(discord.ui.View):
            def __init__(self, market, invoker_id, level, player, user_id, selected_uid=None):
                super().__init__(timeout=90)
                self.market = market
                self.invoker_id = invoker_id
                self.level = level
                self.player = player
                self.user_id = user_id
                self.selected_uid = selected_uid

                options = [discord.SelectOption(label="— No preview —", value="none", default=selected_uid is None)]
                for g in player.girls[:24]:  # Discord limit: 25 options
                    label = f"{g.name} ({g.uid})"[:100]
                    desc = f"HP {g.health}/{g.health_max} • STA {g.stamina}/{g.stamina_max}"[:100]
                    options.append(discord.SelectOption(label=label, value=g.uid, description=desc, default=selected_uid == g.uid))

                self.selector = discord.ui.Select(placeholder="Preview with girl...", options=options)

                async def _on_select(interaction2: discord.Interaction):
                    if interaction2.user.id != self.invoker_id:
                        await interaction2.response.send_message("This isn't your view.", ephemeral=True)
                        return
                    choice = self.selector.values[0]
                    new_selected = None if choice == "none" else choice
                    pl_updated = load_player(self.user_id)
                    if pl_updated:
                        for gg in pl_updated.girls:
                            gg.normalize_skill_structs()
                            gg.apply_regen()
                        save_player(pl_updated)
                    selected = pl_updated.get_girl(new_selected) if (pl_updated and new_selected) else None
                    embed2 = build_market_embed(self.market, selected)
                    await interaction2.response.edit_message(
                        embed=embed2,
                        view=MarketView(self.market, self.invoker_id, self.level, pl_updated or self.player, self.user_id, new_selected),
                    )

                self.selector.callback = _on_select
                self.add_item(self.selector)

            @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary, emoji="🔄")
            async def refresh(self, interaction2: discord.Interaction, button: discord.ui.Button):
                if interaction2.user.id != self.invoker_id:
                    await interaction2.response.send_message("This isn't your view.", ephemeral=True)
                    return
                # force refresh, keeping selected level
                m2 = refresh_market_if_stale(self.user_id, max_age_sec=0, forced_level=self.level)
                pl_updated = load_player(self.user_id)
                if pl_updated:
                    for gg in pl_updated.girls:
                        gg.normalize_skill_structs()
                        gg.apply_regen()
                    save_player(pl_updated)
                selected = pl_updated.get_girl(self.selected_uid) if (pl_updated and self.selected_uid) else None
                embed2 = build_market_embed(m2, selected)
                await interaction2.response.edit_message(
                    embed=embed2,
                    view=MarketView(m2, self.invoker_id, self.level, pl_updated or self.player, self.user_id, self.selected_uid),
                )

        selected_girl = None
        embed = build_market_embed(m, selected_girl)
        await interaction.response.send_message(
            embed=embed,
            view=MarketView(m, uid, level, pl, uid, None),
            ephemeral=True,
        )

    @app_commands.command(name="heal", description="Heal a girl using coins")
    @app_commands.describe(girl_id="Girl UID to heal", amount="Amount of health to restore (default: full)")
    async def heal(self, interaction: discord.Interaction, girl_id: str, amount: int | None = None):
        uid = interaction.user.id
        pl = load_player(uid)
        if not pl:
            await interaction.response.send_message("Use /start first.", ephemeral=True)
            return

        girl = pl.get_girl(girl_id)
        if not girl:
            await interaction.response.send_message("Girl not found.", ephemeral=True)
            return

        girl.normalize_skill_structs()
        girl.apply_regen()

        missing = girl.health_max - girl.health
        if missing <= 0:
            await interaction.response.send_message("She is already at full health.", ephemeral=True)
            return

        if amount is None:
            heal_amount = missing
        else:
            heal_amount = min(missing, max(1, amount))

        cost_per_hp = max(1, 2 + girl.level // 5)
        total_cost = heal_amount * cost_per_hp
        if pl.currency < total_cost:
            await interaction.response.send_message(
                f"Not enough coins. Need {EMOJI_COIN} {total_cost} to heal that much.",
                ephemeral=True,
            )
            return

        pl.currency -= total_cost
        girl.health = min(girl.health_max, girl.health + heal_amount)
        save_player(pl)

        lines = [
            f"{EMOJI_HEART} Restored **{heal_amount}** HP for **{girl.name}**.",
            f"Cost: {EMOJI_COIN} **{total_cost}** ({cost_per_hp} per HP)",
            f"Current HP: {girl.health}/{girl.health_max}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="work", description="Do a market job with a selected girl")
    @app_commands.describe(job_id="Job ID, e.g. J1", girl_id="Girl UID, e.g. g001#1234")
    async def work(self, interaction: discord.Interaction, job_id: str, girl_id: str):
        uid = interaction.user.id
        pl = load_player(uid)
        if not pl:
            await interaction.response.send_message("Use /start first.", ephemeral=True)
            return
        m = load_market(uid)
        if not m:
            await interaction.response.send_message(
                "Use /market to generate the market first.", ephemeral=True
            )
            return
        job = next((j for j in m.jobs if j.job_id == job_id), None)
        if not job:
            await interaction.response.send_message("Invalid job ID.", ephemeral=True)
            return
        girl = pl.get_girl(girl_id)
        if not girl:
            await interaction.response.send_message("Invalid girl ID.", ephemeral=True)
            return

        result = resolve_job(pl, job, girl)
        if result["ok"]:
            # remove job, persist changes
            m.jobs = [j for j in m.jobs if j.job_id != job_id]
            save_market(m)
            save_player(pl)

            chance_pct = int(round(result.get("success_chance", 0.0) * 100))
            injury_pct = int(round(result.get("injury_chance", 0.0) * 100))
            lines = [
                f"{EMOJI_OK} Success! Reward: {EMOJI_COIN} **{result['reward']}**",
                f"Base pay {EMOJI_COIN} {result.get('base_reward', job.pay)} × {result.get('reward_multiplier', 1.0):.2f}",
                f"🎯 Chance: {chance_pct}%",
                f"⚡ Stamina used: {result.get('stamina_cost', 0)}",
                f"🩹 Injury chance rolled: {injury_pct}%",
            ]
            if result.get("injured"):
                lines.append(
                    f"⚠️ {girl.name} took {result.get('injury_amount', 0)} damage (HP {girl.health}/{girl.health_max})."
                )
            em = discord.Embed(description="\n".join(lines), color=0x22C55E)
            await interaction.response.send_message(embed=em)
        else:
            save_player(pl)
            chance_pct = int(round(result.get("success_chance", 0.0) * 100))
            injury_pct = int(round(result.get("injury_chance", 0.0) * 100))
            lines = [
                f"{EMOJI_X} {result['reason']}. No payout.",
                f"🎯 Chance was {chance_pct}%",
                f"⚡ Stamina used: {result.get('stamina_cost', 0)}",
                f"🩹 Injury chance rolled: {injury_pct}%",
            ]
            if result.get("injured"):
                lines.append(
                    f"⚠️ Injury: -{result.get('injury_amount', 0)} HP (now {girl.health}/{girl.health_max})."
                )
            if girl.health <= 0:
                lines.append("🚑 Girl is incapacitated. Use /heal to restore health before working again.")
            em = discord.Embed(description="\n".join(lines), color=0xEF4444)
            await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="dismantle", description="Dismantle (disenchant) a girl into coins")
    @app_commands.describe(girl_id="Girl UID to dismantle", confirm="Confirm dismantle")
    async def dismantle(self, interaction: discord.Interaction, girl_id: str, confirm: bool = False):
        uid = interaction.user.id
        pl = load_player(uid)
        if not pl:
            await interaction.response.send_message("Use /start first.", ephemeral=True)
            return
        g = pl.get_girl(girl_id)
        if not g:
            await interaction.response.send_message("Girl not found.", ephemeral=True)
            return

        if not confirm:
            class ConfirmView(discord.ui.View):
                def __init__(self, invoker_id):
                    super().__init__(timeout=20)
                    self.invoker_id = invoker_id

                @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="💥")
                async def confirm_btn(self, i: discord.Interaction, b: discord.ui.Button):
                    if i.user.id != self.invoker_id:
                        await i.response.send_message("This isn't your view.", ephemeral=True)
                        return
                    res = dismantle_girl(pl, girl_id)
                    save_player(pl)
                    await i.response.edit_message(
                        content=f"{EMOJI_OK} Dismantled **{res['name']}** [{res['rarity']}] → {EMOJI_COIN} **{res['reward']}**",
                        view=None,
                        embed=None,
                    )

                @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
                async def cancel_btn(self, i: discord.Interaction, b: discord.ui.Button):
                    if i.user.id != self.invoker_id:
                        await i.response.send_message("This isn't your view.", ephemeral=True)
                        return
                    await i.response.edit_message(content="Cancelled.", view=None, embed=None)

            embed = discord.Embed(
                title="Dismantle Confirmation",
                description=(
                    f"Are you sure you want to dismantle **{g.name}** [{g.rarity}] • `{g.uid}`?\n"
                    f"You will receive coins depending on rarity and level."
                ),
                color=0xEF4444,
            )
            img = profile_image_path(g.name, g.base_id)
            if img and os.path.exists(img):
                embed.set_image(url=f"attachment://{os.path.basename(img)}")
                await interaction.response.send_message(embed=embed, view=ConfirmView(interaction.user.id), ephemeral=True, file=discord.File(img))
            else:
                embed.set_image(url=g.image_url)
                await interaction.response.send_message(embed=embed, view=ConfirmView(interaction.user.id), ephemeral=True)
            return

        res = dismantle_girl(pl, girl_id)
        save_player(pl)
        if res["ok"]:
            await interaction.response.send_message(
                f"{EMOJI_OK} Dismantled **{res['name']}** [{res['rarity']}] → {EMOJI_COIN} **{res['reward']}**"
            )
        else:
            await interaction.response.send_message(f"{EMOJI_X} {res['reason']}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Core(bot))
