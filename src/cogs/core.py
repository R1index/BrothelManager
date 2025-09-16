import os
import time
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
    MAIN_SKILLS, SUB_SKILLS, stat_xp_threshold, PREF_FAV, PREF_BLOCKED,
)
from ..assets_util import profile_image_path

EMOJI_COIN = "🪙"
EMOJI_SPARK = "✨"
EMOJI_GIRL = "👧"
EMOJI_MARKET = "🛒"
EMOJI_ENERGY = "⚡"
EMOJI_HEART = "❤️"
EMOJI_LUST = "🔥"
EMOJI_OK = "✅"
EMOJI_X = "❌"
EMOJI_CONDITION = "🩺"
EMOJI_SKILL = "🎯"
EMOJI_SUBSKILL = "🧩"
EMOJI_PROFILE = "📜"
EMOJI_STAT_VIT = "💪"
EMOJI_STAT_END = "🛡️"
EMOJI_TRAIT = "✨"
EMOJI_DIMENSION = "📏"
EMOJI_BODY = "🧍"
EMOJI_CLEAN = "🧼"
EMOJI_MORALE = "😊"
EMOJI_POPULARITY = "📣"
EMOJI_ROOMS = "🚪"
EMOJI_FACILITY = "🏛️"
EMOJI_COMFORT = "🛋️"
EMOJI_HYGIENE = "🧴"
EMOJI_SECURITY = "🛡️"
EMOJI_ALLURE = "🎀"

EMBED_SPACER = "⠀"  # Braille blank to create column spacing in embeds

SKILL_ICONS = {
    "Human": "🧠",
    "Insect": "🐜",
    "Beast": "🐾",
    "Monster": "👾",
}

SUB_SKILL_ICONS = {
    "VAGINAL": "💞",
    "ANAL": "🍑",
    "ORAL": "👄",
    "BREAST": "🤱",
    "HAND": "🤲",
    "FOOT": "🦶",
    "TOY": "🧸",
}

FACILITY_INFO = {
    "comfort": (EMOJI_COMFORT, "Comfort"),
    "hygiene": (EMOJI_HYGIENE, "Hygiene"),
    "security": (EMOJI_SECURITY, "Security"),
    "allure": (EMOJI_ALLURE, "Allure"),
}

PREF_ICONS = {
    PREF_FAV: "💖",
    PREF_BLOCKED: "⛔",
}


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


def lust_state_label(ratio: float) -> str:
    """Textual description for lust ratio (0..1)."""
    if ratio >= 0.9:
        return "Overdrive"
    if ratio >= 0.7:
        return "Heated"
    if ratio >= 0.45:
        return "Aroused"
    if ratio >= 0.25:
        return "Warming up"
    return "Dormant"


def lust_state_icon(ratio: float) -> str:
    if ratio >= 0.9:
        return "💥"
    if ratio >= 0.7:
        return "🔥"
    if ratio >= 0.45:
        return "❤️"
    if ratio >= 0.25:
        return "✨"
    return "❄️"


def brothel_overview_lines(brothel) -> tuple[str, str]:
    summary = (
        f"{EMOJI_ROOMS} Rooms {brothel.rooms} • "
        f"{EMOJI_CLEAN} Clean {brothel.cleanliness}/100 • "
        f"{EMOJI_MORALE} Morale {brothel.morale}/100 • "
        f"{EMOJI_POPULARITY} Pop {brothel.popularity}"
    )
    facility_short = " | ".join(
        f"{FACILITY_INFO[key][0]} L{brothel.facility_level(key)}"
        for key in ("comfort", "hygiene", "security", "allure")
    )
    reserve = f"{EMOJI_COIN} Reserve {brothel.upkeep_pool}"
    return summary, f"{reserve} • {facility_short}"


def brothel_facility_lines(brothel) -> list[str]:
    lines: list[str] = []
    for key in ("comfort", "hygiene", "security", "allure"):
        icon, label = FACILITY_INFO[key]
        lvl, xp, need = brothel.facility_progress(key)
        bar = make_bar(xp, need, length=8)
        lines.append(f"{icon} {label} L{lvl} [{bar}] {xp}/{need}")
    return lines


class MarketWorkView(discord.ui.View):
    BASE_COLOR = 0x34D399
    SUCCESS_COLOR = 0x22C55E
    FAILURE_COLOR = 0xEF4444

    def __init__(self, *, user_id: int, invoker_id: int, forced_level: int | None, player, market):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.invoker_id = invoker_id
        self.forced_level = forced_level
        self.selected_girl_uid: str | None = None
        self.selected_job_id: str | None = None
        self.last_result_lines: list[str] | None = None
        self.last_result_color: int | None = None
        self._player_cache = player
        self._market_cache = market

        self.girl_select = self.GirlSelect(self, player)
        self.job_select = self.JobSelect(self, market)
        self.add_item(self.girl_select)
        self.add_item(self.job_select)
        self._apply_state(player, market)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _apply_state(self, player=None, market=None):
        if player is not None:
            self._player_cache = player
        if market is not None:
            self._market_cache = market

        player = self._player_cache
        market = self._market_cache

        if player:
            player.ensure_brothel()

        if player and self.selected_girl_uid and not player.get_girl(self.selected_girl_uid):
            self.selected_girl_uid = None
        if market and self.selected_job_id and not any(j.job_id == self.selected_job_id for j in market.jobs):
            self.selected_job_id = None

        self.girl_select.options = self._build_girl_options(player)
        self.girl_select.disabled = not (player and player.girls)

        self.job_select.options = self._build_job_options(market)
        no_jobs = not (market and market.jobs)
        self.job_select.disabled = no_jobs
        if no_jobs:
            self.selected_job_id = None

        self._update_controls()

    def _update_controls(self):
        can_work = (
            self.selected_girl_uid is not None
            and self.selected_job_id is not None
            and self._market_cache
            and any(j.job_id == self.selected_job_id for j in self._market_cache.jobs)
        )
        self.work_btn.disabled = not can_work

    def _build_girl_options(self, player) -> list[discord.SelectOption]:
        options = [
            discord.SelectOption(
                label="— No preview —",
                value="none",
                default=self.selected_girl_uid is None,
                emoji="👁️",
            )
        ]
        if not player or not player.girls:
            return options
        for g in player.girls[:24]:
            label = f"{g.name} ({g.uid})"
            lust_ratio = g.lust / g.lust_max if g.lust_max else 0.0
            mood = lust_state_label(lust_ratio)
            mood_icon = lust_state_icon(lust_ratio)
            desc = (
                f"{mood_icon} {EMOJI_HEART} {g.health}/{g.health_max} • "
                f"{EMOJI_ENERGY} {g.stamina}/{g.stamina_max} • "
                f"{EMOJI_LUST} {g.lust}/{g.lust_max} [{mood}]"
            )
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=g.uid,
                    description=desc[:100],
                    default=g.uid == self.selected_girl_uid,
                    emoji=EMOJI_GIRL,
                )
            )
        return options

    def _build_job_options(self, market) -> list[discord.SelectOption]:
        options = [
            discord.SelectOption(
                label="— Select job —",
                value="none",
                default=self.selected_job_id is None,
            )
        ]
        if not market or not market.jobs:
            return options
        for job in market.jobs[:24]:
            sub_part = f" + {job.demand_sub} L{job.demand_sub_level}" if job.demand_sub else ""
            label = f"{job.job_id} • {job.demand_main} L{job.demand_level}{sub_part}"
            desc = f"Pay {job.pay} • Diff {job.difficulty}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=job.job_id,
                    description=desc[:100],
                    default=job.job_id == self.selected_job_id,
                )
            )
        return options

    def _get_selected_girl(self):
        if not self._player_cache or not self.selected_girl_uid:
            return None
        return self._player_cache.get_girl(self.selected_girl_uid)

    def _get_selected_job(self):
        if not self._market_cache or not self.selected_job_id:
            return None
        for job in self._market_cache.jobs:
            if job.job_id == self.selected_job_id:
                return job
        return None

    def _load_player(self):
        pl = load_player(self.user_id)
        if not pl:
            return None
        brothel = pl.ensure_brothel()
        brothel.apply_decay()
        for g in pl.girls:
            g.normalize_skill_structs()
            g.apply_regen()
        save_player(pl)
        return pl

    def _load_market(self, force_refresh: bool = False):
        if force_refresh:
            return refresh_market_if_stale(self.user_id, max_age_sec=0, forced_level=self.forced_level)
        m = load_market(self.user_id)
        if not m:
            return refresh_market_if_stale(self.user_id, max_age_sec=0, forced_level=self.forced_level)
        if self.forced_level is not None and m.level != self.forced_level:
            return refresh_market_if_stale(self.user_id, max_age_sec=0, forced_level=self.forced_level)
        if time.time() - m.ts > 300:
            return refresh_market_if_stale(self.user_id, max_age_sec=0, forced_level=self.forced_level)
        return m

    async def _ensure_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This isn't your view.", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        market = self._market_cache
        player = self._player_cache
        brothel = getattr(player, "brothel", None)
        color = self.last_result_color or self.BASE_COLOR
        level = market.level if market else 0
        embed = discord.Embed(
            title=f"{EMOJI_MARKET} Service Market — Lv{level}",
            color=color,
        )
        desc_parts: list[str] = []
        if self.last_result_lines:
            desc_parts.append("\n".join(self.last_result_lines))

        if brothel:
            overview, reserves = brothel_overview_lines(brothel)
            desc_parts.append(overview)
            desc_parts.append(reserves)

        girl = self._get_selected_girl()
        if girl:
            ratio = girl.lust / girl.lust_max if girl.lust_max else 0.0
            mood = lust_state_label(ratio)
            desc_parts.append(
                f"Previewing **{girl.name}** • `{girl.uid}`\n"
                f"{EMOJI_HEART} {girl.health}/{girl.health_max} • "
                f"{EMOJI_ENERGY} {girl.stamina}/{girl.stamina_max} • "
                f"{EMOJI_LUST} {girl.lust}/{girl.lust_max} ({mood})"
            )
        else:
            desc_parts.append("Select a girl and job to preview or deploy.")
        embed.description = "\n\n".join(desc_parts)

        if not market or not market.jobs:
            embed.add_field(name="Jobs", value="No jobs available right now.", inline=False)
            embed.set_footer(text="Select a girl and job, then press Work. Market autorefreshes every 5 minutes.")
            return embed

        for job in market.jobs:
            highlight = "⭐" if job.job_id == self.selected_job_id else "•"
            sub_part = f" + {job.demand_sub} L{job.demand_sub_level}" if job.demand_sub else ""
            field_name = f"{highlight} `{job.job_id}` • {job.demand_main} L{job.demand_level}{sub_part}"
            value_lines = [f"{EMOJI_COIN} Base pay: **{job.pay}** • Difficulty: {job.difficulty}"]

            if girl:
                info = evaluate_job(girl, job, brothel)
                if info["blocked_main"] or (job.demand_sub and info["blocked_sub"]):
                    value_lines.append("🚫 Preferences block this job.")
                elif not info["meets_main"] or not info["meets_sub"]:
                    lacking = []
                    if not info["meets_main"]:
                        lacking.append(f"{job.demand_main} L{job.demand_level}")
                    if job.demand_sub and not info["meets_sub"]:
                        lacking.append(f"{job.demand_sub} L{job.demand_sub_level}")
                    value_lines.append("⚠️ Needs: " + ", ".join(lacking))
                elif not info["health_ok"]:
                    value_lines.append("⚠️ Needs healing before working.")
                elif not info["stamina_ok"]:
                    value_lines.append(
                        f"⚠️ Requires {info['stamina_cost']} stamina (current {girl.stamina})."
                    )
                elif not info["lust_ok"]:
                    value_lines.append(
                        f"🔥 Needs {info['lust_cost']} lust (current {girl.lust})."
                    )
                else:
                    success_pct = int(round(info["success_chance"] * 100))
                    injury_pct = int(round(info["injury_chance"] * 100))
                    potential_pay = max(0, int(info["base_reward"] * info["reward_multiplier"]))
                    expected_pay = max(0, int(info["expected_reward"]))
                    mood = lust_state_label(info["lust_ratio"])
                    value_lines.append(f"🎯 Success: {success_pct}% • Injury: {injury_pct}%")
                    value_lines.append(
                        f"⚡ {info['stamina_cost']} • {EMOJI_LUST} {info['lust_cost']} • Mood: {mood}"
                    )
                    value_lines.append(
                        f"{EMOJI_COIN} Potential: **{potential_pay}** (x{info['reward_multiplier']:.2f}) • E≈ {expected_pay}"
                    )
            else:
                value_lines.append("Use the selectors to preview with one of your girls.")

            embed.add_field(name=field_name, value="\n".join(value_lines), inline=False)

        embed.set_footer(text="Select a girl and job, then press Work. Market autorefreshes every 5 minutes.")
        return embed

    def _format_result_lines(self, result: dict, girl, job) -> list[str]:
        chance_pct = int(round(result.get("success_chance", 0.0) * 100))
        injury_pct = int(round(result.get("injury_chance", 0.0) * 100))
        stamina_cost = result.get("stamina_cost", 0)
        lust_cost = result.get("lust_cost", 0)
        lust_after = result.get("lust_after", girl.lust)
        after_ratio = result.get("lust_after_ratio", girl.lust / girl.lust_max if girl.lust_max else 0.0)
        mood_after = lust_state_label(after_ratio)
        lines: list[str] = []

        if result.get("ok"):
            reward = result.get("reward", 0)
            base_reward = result.get("base_reward", job.pay if job else 0)
            multiplier = result.get("reward_multiplier", 1.0)
            lines.append(f"{EMOJI_OK} Success! Reward: {EMOJI_COIN} **{reward}**")
            lines.append(f"{EMOJI_COIN} Base {base_reward} × {multiplier:.2f}")
        else:
            reason = result.get("reason", "Failed")
            lines.append(f"{EMOJI_X} {reason}.")

        if chance_pct or injury_pct:
            lines.append(f"🎯 {chance_pct}% • 🩹 {injury_pct}% chance")

        if result.get("lust_before") is None:
            lines.append(f"⚡ Needs {stamina_cost} • {EMOJI_LUST} Needs {lust_cost}")
        else:
            lines.append(f"⚡ Spent {stamina_cost} • {EMOJI_LUST} Spent {lust_cost}")
        lines.append(f"{EMOJI_LUST} Mood now: {mood_after} ({lust_after}/{girl.lust_max})")

        if result.get("injured"):
            lines.append(
                f"⚠️ Took {result.get('injury_amount', 0)} damage (HP {girl.health}/{girl.health_max})."
            )
        if not result.get("ok") and girl.health <= 0:
            lines.append("🚑 Girl is incapacitated. Use /heal before working again.")

        diff = result.get("brothel_diff") or {}
        diff_parts: list[str] = []
        if diff.get("cleanliness"):
            diff_parts.append(f"{EMOJI_CLEAN} {diff['cleanliness']:+}")
        if diff.get("morale"):
            diff_parts.append(f"{EMOJI_MORALE} {diff['morale']:+}")
        if diff.get("popularity"):
            diff_parts.append(f"{EMOJI_POPULARITY} {diff['popularity']:+}")
        if diff.get("upkeep"):
            diff_parts.append(f"{EMOJI_COIN} {diff['upkeep']:+}")
        if diff_parts:
            lines.append(f"{EMOJI_FACILITY} {' • '.join(diff_parts)}")

        level_diff = result.get("brothel_levels") or {}
        level_parts = []
        for key, delta in level_diff.items():
            if delta > 0:
                icon, label = FACILITY_INFO.get(key, ("✨", key.title()))
                level_parts.append(f"{icon} {label} +{delta}")
        if level_parts:
            lines.append(f"{EMOJI_FACILITY} Upgrades: {', '.join(level_parts)}")
        return lines

    # ------------------------------------------------------------------
    # UI callbacks
    # ------------------------------------------------------------------
    class GirlSelect(discord.ui.Select):
        def __init__(self, outer: "MarketWorkView", player):
            self.outer = outer
            super().__init__(
                placeholder="Preview with girl...",
                options=outer._build_girl_options(player),
                min_values=1,
                max_values=1,
            )

        async def callback(self, interaction: discord.Interaction):
            if not await self.outer._ensure_owner(interaction):
                return
            value = self.values[0]
            self.outer.selected_girl_uid = None if value == "none" else value
            player = self.outer._load_player()
            market = self.outer._load_market()
            self.outer._apply_state(player, market)
            embed = self.outer.build_embed()
            await interaction.response.edit_message(embed=embed, view=self.outer)

    class JobSelect(discord.ui.Select):
        def __init__(self, outer: "MarketWorkView", market):
            self.outer = outer
            super().__init__(
                placeholder="Select job...",
                options=outer._build_job_options(market),
                min_values=1,
                max_values=1,
            )

        async def callback(self, interaction: discord.Interaction):
            if not await self.outer._ensure_owner(interaction):
                return
            value = self.values[0]
            self.outer.selected_job_id = None if value == "none" else value
            player = self.outer._load_player()
            market = self.outer._load_market()
            self.outer._apply_state(player, market)
            embed = self.outer.build_embed()
            await interaction.response.edit_message(embed=embed, view=self.outer)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._ensure_owner(interaction):
            return
        market = self._load_market(force_refresh=True)
        player = self._load_player()
        self._apply_state(player, market)
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Work", style=discord.ButtonStyle.success, emoji="🛠️")
    async def work_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._ensure_owner(interaction):
            return
        if not self.selected_girl_uid or not self.selected_job_id:
            await interaction.response.send_message("Select a girl and job first.", ephemeral=True)
            return

        player = self._load_player()
        market = self._load_market()
        if not player:
            await interaction.response.send_message("Player profile not found.", ephemeral=True)
            return
        girl = player.get_girl(self.selected_girl_uid)
        if not girl:
            self.selected_girl_uid = None
            self._apply_state(player, market)
            embed = self.build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            return
        if not market:
            market = self._load_market(force_refresh=True)
        job = None
        if market:
            for j in market.jobs:
                if j.job_id == self.selected_job_id:
                    job = j
                    break
        if not job:
            self.selected_job_id = None
            self._apply_state(player, market)
            embed = self.build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send("Selected job is no longer available.", ephemeral=True)
            return

        result = resolve_job(player, job, girl)
        success = result.get("ok")
        if success:
            market.jobs = [j for j in market.jobs if j.job_id != job.job_id]
            market.ts = int(time.time())
            save_market(market)
            self.selected_job_id = None

        save_player(player)
        self.last_result_color = self.SUCCESS_COLOR if success else self.FAILURE_COLOR
        self.last_result_lines = self._format_result_lines(result, girl, job)
        self._apply_state(player, market)
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

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

    def _brothel_status_notes(self, brothel) -> list[str]:
        notes: list[str] = []
        if brothel.cleanliness < 40:
            notes.append("🧽 Cleanliness is low — schedule maintenance soon.")
        elif brothel.cleanliness > 85:
            notes.append("✨ Rooms are sparkling and impressing clients.")

        if brothel.morale < 55:
            notes.append("😊 Staff morale is dipping; give them a break or bonuses.")
        elif brothel.morale > 90:
            notes.append("🎉 Spirits are high — expect better service quality.")

        if brothel.popularity < 25:
            notes.append("📣 Consider promotions to attract more clientele.")
        elif brothel.popularity > 120:
            notes.append("🔥 Demand is surging; premium jobs may appear more often.")

        comfort_lvl = brothel.facility_level("comfort")
        security_lvl = brothel.facility_level("security")
        if security_lvl + 1 < comfort_lvl:
            notes.append("🛡️ Security lags behind comfort — risk of injuries rises.")

        if brothel.upkeep_pool < 50:
            notes.append("🪙 Upkeep reserve is thin; stash some coins for cleaning.")
        elif brothel.upkeep_pool > 200:
            notes.append("💰 Reserve is healthy; maintenance will be more efficient.")

        return notes

    def _build_brothel_embed(self, user_name: str, pl, notes: list[str] | None = None) -> discord.Embed:
        brothel = pl.ensure_brothel()
        overview, reserves = brothel_overview_lines(brothel)
        description_parts: list[str] = []
        if notes:
            description_parts.extend(notes)
            description_parts.append(EMBED_SPACER)
        description_parts.extend([overview, reserves])

        embed = discord.Embed(
            title=f"{EMOJI_FACILITY} {user_name}'s Brothel",
            color=0xF97316,
            description="\n".join(description_parts),
        )
        embed.add_field(name="Facilities", value="\n".join(brothel_facility_lines(brothel)), inline=False)
        status = self._brothel_status_notes(brothel)
        if status:
            embed.add_field(name="Status notes", value="\n".join(status), inline=False)
        embed.set_footer(text=f"{EMOJI_COIN} Wallet {pl.currency} • ⭐ Rep {pl.reputation}")
        return embed

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
        brothel = pl.ensure_brothel()
        brothel.apply_decay()
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

        overview, reserves = brothel_overview_lines(brothel)
        embed.add_field(name=f"{EMOJI_FACILITY} Brothel", value=f"{overview}\n{reserves}", inline=False)
        facility_lines = "\n".join(brothel_facility_lines(brothel))
        embed.add_field(name="Facilities", value=facility_lines, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="brothel", description="Manage your establishment facilities")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="View status", value="view"),
            app_commands.Choice(name="Upgrade facility", value="upgrade"),
            app_commands.Choice(name="Maintain cleanliness", value="maintain"),
            app_commands.Choice(name="Promote services", value="promote"),
        ]
    )
    @app_commands.choices(
        facility=[
            app_commands.Choice(name="Comfort", value="comfort"),
            app_commands.Choice(name="Hygiene", value="hygiene"),
            app_commands.Choice(name="Security", value="security"),
            app_commands.Choice(name="Allure", value="allure"),
        ]
    )
    @app_commands.describe(coins="Coins to invest into the selected action")
    async def brothel(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str] | None = None,
        facility: app_commands.Choice[str] | None = None,
        coins: int | None = None,
    ):
        pl = load_player(interaction.user.id)
        if not pl:
            await interaction.response.send_message("Use /start first.", ephemeral=True)
            return

        brothel = pl.ensure_brothel()
        brothel.apply_decay()

        action_val = (action.value if action else "view").lower()
        if action_val not in {"view", "upgrade", "maintain", "promote"}:
            action_val = "view"
        facility_val = facility.value if facility else None
        invest = max(0, coins or 0)

        if action_val == "view":
            save_player(pl)
            embed = self._build_brothel_embed(interaction.user.display_name, pl)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if action_val == "upgrade" and not facility_val:
            await interaction.response.send_message("Select which facility to upgrade.", ephemeral=True)
            return

        if invest <= 0:
            await interaction.response.send_message("Specify how many coins to spend.", ephemeral=True)
            return
        if pl.currency < invest:
            await interaction.response.send_message(
                f"Not enough coins. Need {EMOJI_COIN} {invest}.",
                ephemeral=True,
            )
            return

        pl.currency -= invest
        notes: list[str] = [f"{EMOJI_COIN} Spent {invest} coins."]

        if action_val == "upgrade" and facility_val:
            icon, label = FACILITY_INFO[facility_val]
            before_lvl, before_xp, before_need = brothel.facility_progress(facility_val)
            brothel.gain_facility_xp(facility_val, invest)
            after_lvl, after_xp, after_need = brothel.facility_progress(facility_val)
            delta_lvl = after_lvl - before_lvl
            notes.append(
                f"{icon} **{label}**: L{before_lvl} {before_xp}/{before_need} → L{after_lvl} {after_xp}/{after_need}"
            )
            if delta_lvl > 0:
                notes.append(f"{icon} Level up +{delta_lvl}!")
        elif action_val == "maintain":
            result = brothel.maintain(invest)
            notes.append(
                f"{EMOJI_CLEAN} Cleanliness +{result['cleanliness']} (now {brothel.cleanliness}/100)."
            )
            if result.get("morale"):
                notes.append(
                    f"{EMOJI_MORALE} Morale +{result['morale']} (now {brothel.morale}/100)."
                )
            if result.get("pool_used"):
                notes.append(
                    f"{EMOJI_COIN} Used {result['pool_used']} from upkeep reserve."
                )
        elif action_val == "promote":
            result = brothel.promote(invest)
            notes.append(
                f"{EMOJI_POPULARITY} Popularity +{result['popularity']} (now {brothel.popularity})."
            )
            if result.get("morale"):
                notes.append(
                    f"{EMOJI_MORALE} Morale +{result['morale']} (now {brothel.morale}/100)."
                )

        brothel.ensure_bounds()
        save_player(pl)

        embed = self._build_brothel_embed(
            interaction.user.display_name,
            pl,
            notes=notes,
        )
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

            # condition & progression
            vit_need = stat_xp_threshold(g.vitality_level)
            end_need = stat_xp_threshold(g.endurance_level)
            lust_need = stat_xp_threshold(g.lust_level)
            vit_bar = make_bar(g.vitality_xp, vit_need, length=10)
            end_bar = make_bar(g.endurance_xp, end_need, length=10)
            lust_bar = make_bar(g.lust_xp, lust_need, length=10)
            lust_ratio = g.lust / g.lust_max if g.lust_max else 0.0
            mood = lust_state_label(lust_ratio)
            mood_icon = lust_state_icon(lust_ratio)
            condition_lines = [
                f"{EMOJI_SPARK} Lv **{g.level}** — EXP {g.exp}",
                "",
                f"{EMOJI_HEART} HP **{g.health}/{g.health_max}**",
                f"{EMOJI_ENERGY} STA **{g.stamina}/{g.stamina_max}**",
                f"{mood_icon} {EMOJI_LUST} Lust **{g.lust}/{g.lust_max}** • {mood}",
                "",
                f"{EMOJI_STAT_VIT} Vitality L{g.vitality_level} [{vit_bar}] {g.vitality_xp}/{vit_need}",
                f"{EMOJI_STAT_END} Endurance L{g.endurance_level} [{end_bar}] {g.endurance_xp}/{end_need}",
                f"{EMOJI_LUST} Mastery L{g.lust_level} [{lust_bar}] {g.lust_xp}/{lust_need}",
            ]
            em.add_field(
                name=f"{EMOJI_CONDITION} Condition",
                value="\n".join(condition_lines),
                inline=True,
            )

            em.add_field(name=EMBED_SPACER, value=EMBED_SPACER, inline=True)

            # progress lines with prefs tags
            def fmt_skill_lines(skmap, names, prefs, header: str, icons_map: dict[str, str]):
                entries: list[str] = []
                for nm in names:
                    lvl = get_level(skmap, nm)
                    xp = get_xp(skmap, nm)
                    need = skill_xp_threshold(lvl)
                    bar = make_bar(xp, need, length=8)
                    pref = str(prefs.get(nm, "true")).lower()
                    tag = PREF_ICONS.get(pref, "🔹")
                    typ = icons_map.get(nm, "✨")
                    progress = f"{xp}/{need}" if need else str(xp)
                    entries.append(
                        f"{tag}{typ} **{nm}** L{lvl} [{bar}] {progress}"
                    )

                if not entries:
                    entries = [f"{EMOJI_X} No training yet."]

                lines: list[str] = []
                if header:
                    lines.append(f"*{header}*")
                    lines.append(EMBED_SPACER)

                lines.extend(entries)
                return "\n".join(lines)

            em.add_field(
                name=f"{EMOJI_SKILL} Skills",
                value=fmt_skill_lines(g.skills, MAIN_SKILLS, g.prefs_skills, "Focus", SKILL_ICONS),
                inline=True,
            )

            # bio block
            bio_entries: list[str] = []

            details: list[str] = []
            if g.breast_size:
                details.append(f"🎀 Bust **{g.breast_size}**")
            if g.body_shape:
                details.append(f"{EMOJI_BODY} Body **{g.body_shape}**")
            if details:
                bio_entries.append(" • ".join(details))

            dims = []
            if g.height_cm:
                dims.append(f"{g.height_cm} cm")
            if g.weight_kg:
                dims.append(f"{g.weight_kg} kg")
            if g.age:
                dims.append(f"{g.age} y/o")
            if dims:
                bio_entries.append(
                    f"{EMOJI_DIMENSION} Stats: {' • '.join(dims)}"
                )

            if g.traits:
                trait_text = " • ".join(g.traits)
                bio_entries.append(f"{EMOJI_TRAIT} Traits: {trait_text}")

            if g.pregnant:
                pts = g.pregnancy_points()
                preg_bar = make_bar(pts, 30, length=10)
                bio_entries.append(
                    f"🤰 Pregnant {pts}/30 {preg_bar}"
                )
            else:
                bio_entries.append("👶 Not pregnant")

            if not bio_entries:
                bio_entries.append(f"{EMOJI_X} —")

            em.add_field(
                name=f"{EMOJI_PROFILE} Profile",
                value="\n".join(bio_entries),
                inline=True,
            )

            em.add_field(name=EMBED_SPACER, value=EMBED_SPACER, inline=True)

            em.add_field(
                name=f"{EMOJI_SUBSKILL} Sub-skills",
                value=fmt_skill_lines(g.subskills, SUB_SKILLS, g.prefs_subskills, "Techniques", SUB_SKILL_ICONS),
                inline=True
            )

            pages.append(em)

        save_player(pl)
        view = Paginator(pages, interaction.user.id, timeout=120, files=files)
        await view.send(interaction)

    @app_commands.command(name="market", description="Browse the market and send a girl to work")
    @app_commands.describe(level="Optional market level override")
    async def market(self, interaction: discord.Interaction, level: int | None = None):
        uid = interaction.user.id
        pl = load_player(uid)
        if not pl:
            await interaction.response.send_message("Use /start first.", ephemeral=True)
            return

        brothel = pl.ensure_brothel()
        brothel.apply_decay()
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

        market = refresh_market_if_stale(uid, max_age_sec=300, forced_level=level)

        view = MarketWorkView(
            user_id=uid,
            invoker_id=interaction.user.id,
            forced_level=level,
            player=pl,
            market=market,
        )
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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
