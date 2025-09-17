import os
import time
from typing import Any, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..storage import (
    load_player,
    save_player,
    grant_starter_pack,
    roll_gacha,
    refresh_market_if_stale,
    load_market,
    save_market,
    resolve_job,
    dismantle_girl,
    evaluate_job,
    iter_user_ids,
    brothel_leaderboard,
    girl_leaderboard,
    get_config,
)
from ..models import (
    MAIN_SKILLS,
    SUB_SKILLS,
    PREF_BLOCKED,
    RARITY_COLORS,
    PROMOTE_COINS_PER_RENOWN,
    make_bar,
    market_level_from_rep,
)
from ..assets_util import profile_image_path
from ..game.constants import (
    EMOJI_ALLURE,
    EMOJI_BODY,
    EMOJI_CLEAN,
    EMOJI_COIN,
    EMOJI_COMFORT,
    EMOJI_DIMENSION,
    EMOJI_ENERGY,
    EMOJI_FACILITY,
    EMOJI_GIRL,
    EMOJI_HEART,
    EMOJI_HYGIENE,
    EMOJI_LUST,
    EMOJI_MARKET,
    EMOJI_MORALE,
    EMOJI_OK,
    EMOJI_POPULARITY,
    EMOJI_PROFILE,
    EMOJI_ROOMS,
    EMOJI_SECURITY,
    EMOJI_SPARK,
    EMOJI_STAT_END,
    EMOJI_STAT_VIT,
    EMOJI_TRAIT,
    EMOJI_X,
    FACILITY_INFO,
)
from ..game.embeds import (
    brothel_facility_lines,
    brothel_overview_lines,
    build_brothel_embed,
    build_girl_embed,
)
from ..game.utils import choice_value
from ..game.views import MarketWorkView, Paginator


BROTHEL_ALLOWED_ACTIONS = {"view", "upgrade", "maintain", "promote", "expand"}


MIN_TRAINING_SECONDS = 15 * 60


def normalize_brothel_action(
    action: app_commands.Choice[str] | None,
) -> str:
    """Normalize the incoming action choice for /brothel commands."""

    action_val = (choice_value(action, default="view") or "view").lower()
    if action_val not in BROTHEL_ALLOWED_ACTIONS:
        return "view"
    return action_val


# -----------------------------------------------------------------------------
# Core Cog
# -----------------------------------------------------------------------------
class Core(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        config = get_config()
        self.market_refresh_minutes = self._resolve_refresh_minutes(config)
        self.market_refresher.change_interval(minutes=self.market_refresh_minutes)
        self.market_refresher.start()

    def cog_unload(self):
        self.market_refresher.cancel()

    @tasks.loop(minutes=5)
    async def market_refresher(self):
        """Refresh all users' markets by scanning the users directory."""
        try:
            for uid in iter_user_ids():
                refresh_market_if_stale(uid, max_age_sec=0)
        except Exception as exc:
            print("[market_refresher] error:", exc)

    @staticmethod
    def _resolve_refresh_minutes(config: Optional[dict]) -> float:
        default_minutes = 5.0
        if not isinstance(config, dict):
            return default_minutes
        market_cfg = config.get("market")
        if not isinstance(market_cfg, dict):
            return default_minutes
        raw_value = market_cfg.get("refresh_minutes", default_minutes)
        try:
            minutes = float(raw_value)
        except (TypeError, ValueError):
            return default_minutes
        if minutes <= 0:
            return default_minutes
        return minutes

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

        if brothel.renown < 25:
            notes.append("📣 Renown is low — consider promotions.")
        elif brothel.renown > 160:
            notes.append("🔥 Renown is soaring; expect premium clients.")

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
        embed = build_brothel_embed(user_name, pl, notes)
        status = self._brothel_status_notes(brothel)
        if status:
            embed.add_field(name="Status notes", value="\n".join(status), inline=False)
        return embed

    async def _send_response(
        self,
        interaction: discord.Interaction,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
        ephemeral: bool = True,
    ) -> None:
        """Send a response or follow-up message, handling already-responded interactions."""

        sender = interaction.response.send_message
        if interaction.response.is_done():
            sender = interaction.followup.send

        payload: dict[str, Any] = {"ephemeral": ephemeral}
        if content is not None:
            payload["content"] = content
        if embed is not None:
            payload["embed"] = embed

        await sender(**payload)

    async def _save_and_respond(
        self,
        interaction: discord.Interaction,
        pl,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
        ephemeral: bool = True,
    ) -> None:
        """Persist the player state before replying to the interaction."""

        save_player(pl)
        await self._send_response(
            interaction,
            content=content,
            embed=embed,
            ephemeral=ephemeral,
        )

    async def _prepare_player(
        self,
        interaction: discord.Interaction,
        *,
        regen_girls: bool = False,
    ) -> tuple[Any | None, Any | None]:
        """Load the player and brothel state, applying decay and optional girl regeneration."""

        pl = load_player(interaction.user.id)
        if not pl:
            await self._send_response(
                interaction,
                content="Use /start first.",
                ephemeral=True,
            )
            return None, None

        brothel = pl.ensure_brothel()
        brothel.apply_decay()
        pl.renown = brothel.renown

        if regen_girls:
            for girl in pl.girls:
                girl.normalize_skill_structs()
                girl.apply_regen(brothel)

        return pl, brothel

    @staticmethod
    def _resolve_brothel_facility(
        facility: app_commands.Choice[str] | None,
    ) -> str | None:
        facility_val = choice_value(facility)
        if not facility_val:
            return None
        facility_val = facility_val.lower()
        if facility_val not in FACILITY_INFO:
            return None
        return facility_val

    def _brothel_upgrade_notes(
        self,
        brothel,
        facility: str,
        invest: int,
    ) -> list[str]:
        icon, label = FACILITY_INFO[facility]
        before_lvl, before_xp, before_need = brothel.facility_progress(facility)
        brothel.gain_facility_xp(facility, invest)
        after_lvl, after_xp, after_need = brothel.facility_progress(facility)
        notes = [
            f"{icon} **{label}**: L{before_lvl} {before_xp}/{before_need} → L{after_lvl} {after_xp}/{after_need}"
        ]
        delta_lvl = after_lvl - before_lvl
        if delta_lvl > 0:
            notes.append(f"{icon} Level up +{delta_lvl}!")
        return notes

    def _brothel_maintain_notes(self, brothel, invest: int) -> list[str]:
        result = brothel.maintain(invest)
        cleanliness = int(result.get("cleanliness", 0))
        notes = [
            f"{EMOJI_CLEAN} Cleanliness +{cleanliness} (now {brothel.cleanliness}/100)."
        ]
        morale = int(result.get("morale", 0))
        if morale:
            notes.append(
                f"{EMOJI_MORALE} Morale +{morale} (now {brothel.morale}/100)."
            )
        pool_used = int(result.get("pool_used", 0))
        if pool_used:
            notes.append(
                f"{EMOJI_COIN} Used {pool_used} from upkeep reserve."
            )
        return notes

    def _brothel_promote_notes(self, brothel, invest: int) -> list[str]:
        result = brothel.promote(invest)
        renown_gain = int(result.get("renown", 0))
        notes: list[str] = []
        if renown_gain > 0:
            notes.append(
                f"{EMOJI_POPULARITY} Renown +{renown_gain} (now {brothel.renown})."
            )
        else:
            notes.append(
                f"{EMOJI_POPULARITY} Investment too small to gain renown. Spend at least "
                f"{PROMOTE_COINS_PER_RENOWN} coins for +1."
            )

        morale = int(result.get("morale", 0))
        if morale:
            notes.append(
                f"{EMOJI_MORALE} Morale +{morale} (now {brothel.morale}/100)."
            )
        return notes

    def _brothel_expand_notes(self, brothel, invest: int) -> list[str]:
        result = brothel.expand_rooms(invest)
        rooms_gained = int(result.get("rooms", 0))
        if rooms_gained:
            return [
                f"{EMOJI_ROOMS} Rooms +{rooms_gained} (now {brothel.rooms})."
            ]

        progress = int(result.get("progress", 0))
        next_cost = int(result.get("next_cost", brothel.next_room_cost()))
        return [
            f"{EMOJI_ROOMS} Progress {progress}/{next_cost} to next room."
        ]

    @staticmethod
    def _format_training_focus(kind: Optional[str], value: Optional[str]) -> str:
        normalized = (kind or "any").lower()
        if normalized == "main" and value:
            return f"{value} (main skill)"
        if normalized == "sub" and value:
            return f"{value.title()} (sub-skill)"
        return "general technique"

    @staticmethod
    def _resolve_training_focus(
        focus_type: Optional[app_commands.Choice[str]],
        main_skill: Optional[app_commands.Choice[str]],
        sub_skill: Optional[app_commands.Choice[str]],
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        main_choice = choice_value(main_skill)
        sub_choice = choice_value(sub_skill)
        focus_type_val = (choice_value(focus_type) or "").lower()

        if main_choice and sub_choice:
            return None, None, "Select either a main skill or a sub-skill, not both."

        if focus_type_val not in {"main", "sub"}:
            if main_choice and not sub_choice:
                focus_type_val = "main"
            elif sub_choice and not main_choice:
                focus_type_val = "sub"

        if focus_type_val not in {"main", "sub"}:
            return None, None, "Specify which skill category to train (main or sub)."

        focus_name = main_choice if focus_type_val == "main" else sub_choice
        if not focus_name:
            return None, None, "Select a concrete skill for the mentorship."

        if focus_type_val == "main" and focus_name not in MAIN_SKILLS:
            return None, None, "Unknown main skill."
        if focus_type_val == "sub" and focus_name not in SUB_SKILLS:
            return None, None, "Unknown sub-skill."

        return focus_type_val, focus_name, None

    @staticmethod
    def _is_focus_blocked(girl, focus_type: str, focus_name: str) -> bool:
        prefs = (
            getattr(girl, "prefs_skills", {})
            if focus_type == "main"
            else getattr(girl, "prefs_subskills", {})
        )
        return str(prefs.get(focus_name, "true")).lower() == PREF_BLOCKED

    @staticmethod
    def _training_total_skill(girl) -> int:
        main_total = sum(int(v.get("level", 0)) for v in getattr(girl, "skills", {}).values())
        sub_total = sum(int(v.get("level", 0)) for v in getattr(girl, "subskills", {}).values())
        return main_total + sub_total

    @classmethod
    def _mentor_more_experienced(cls, mentor_girl, student_girl) -> bool:
        mentor_level = getattr(mentor_girl, "level", 0)
        student_level = getattr(student_girl, "level", 0)
        if mentor_level > student_level:
            return True
        return cls._training_total_skill(mentor_girl) > cls._training_total_skill(student_girl)

    @classmethod
    def _calculate_training_bonus(cls, assignment, mentor_girl, student_girl) -> float:
        since_ts = getattr(assignment, "since_ts", None) or 0.0
        duration_hours = max(0.0, (time.time() - since_ts) / 3600)
        effective_hours = min(6.0, duration_hours)
        level_gap = max(0, getattr(mentor_girl, "level", 0) - getattr(student_girl, "level", 0))
        skill_gap = max(
            0,
            cls._training_total_skill(mentor_girl)
            - cls._training_total_skill(student_girl),
        )
        vitality_gap = max(
            0,
            getattr(mentor_girl, "vitality_level", 0)
            - getattr(student_girl, "vitality_level", 0),
        )
        progress_ratio = min(1.0, effective_hours / 1.0)
        bonus = 0.12 * effective_hours
        gap_bonus = 0.0
        gap_bonus += level_gap * 0.04
        gap_bonus += skill_gap * 0.002
        gap_bonus += vitality_gap * 0.01
        bonus += progress_ratio * gap_bonus
        return min(0.6, bonus)

    async def _handle_train_list(self, interaction, pl, brothel) -> None:
        if not brothel.training:
            await self._save_and_respond(
                interaction,
                pl,
                content="No active mentorships.",
                ephemeral=True,
            )
            return

        lines: list[str] = []
        now_ts = time.time()
        for assignment in brothel.training:
            mentor_girl = pl.get_girl(assignment.mentor_uid)
            student_girl = pl.get_girl(assignment.student_uid)
            if not mentor_girl or not student_girl:
                continue
            minutes = max(0, int((now_ts - assignment.since_ts) // 60))
            focus_text = self._format_training_focus(assignment.focus_type, assignment.focus)
            lines.append(
                f"📘 **{mentor_girl.name}** → **{student_girl.name}** • {focus_text} • {minutes} min"
            )

        message = "\n".join(lines[:20]) if lines else "No active mentorships."
        await self._save_and_respond(
            interaction,
            pl,
            content=message,
            ephemeral=True,
        )

    async def _handle_train_assign(
        self,
        interaction,
        pl,
        brothel,
        mentor: Optional[str],
        student: Optional[str],
        focus_type: Optional[app_commands.Choice[str]],
        main_skill: Optional[app_commands.Choice[str]],
        sub_skill: Optional[app_commands.Choice[str]],
    ) -> None:
        mentor_uid = (mentor or "").strip()
        student_uid = (student or "").strip()

        if not mentor_uid or not student_uid:
            await self._save_and_respond(
                interaction,
                pl,
                content="Specify mentor and student UIDs.",
                ephemeral=True,
            )
            return

        mentor_girl = pl.get_girl(mentor_uid)
        student_girl = pl.get_girl(student_uid)
        if not mentor_girl or not student_girl:
            await self._save_and_respond(
                interaction,
                pl,
                content="Mentor or student not found.",
                ephemeral=True,
            )
            return

        if mentor_girl.uid == student_girl.uid:
            await self._save_and_respond(
                interaction,
                pl,
                content="Mentor and student must be different.",
                ephemeral=True,
            )
            return

        if brothel.training_for(mentor_girl.uid) or brothel.training_for(student_girl.uid):
            await self._save_and_respond(
                interaction,
                pl,
                content="One of the girls is already in training.",
                ephemeral=True,
            )
            return

        if not self._mentor_more_experienced(mentor_girl, student_girl):
            await self._save_and_respond(
                interaction,
                pl,
                content="Mentor must be more experienced than the student.",
                ephemeral=True,
            )
            return

        focus_type_val, focus_name, error = self._resolve_training_focus(
            focus_type,
            main_skill,
            sub_skill,
        )
        if error:
            await self._save_and_respond(
                interaction,
                pl,
                content=error,
                ephemeral=True,
            )
            return

        if not focus_type_val or not focus_name:
            await self._save_and_respond(
                interaction,
                pl,
                content="Select a concrete skill for the mentorship.",
                ephemeral=True,
            )
            return

        if self._is_focus_blocked(mentor_girl, focus_type_val, focus_name) or self._is_focus_blocked(
            student_girl,
            focus_type_val,
            focus_name,
        ):
            message = (
                "Blocked skills cannot be taught or studied."
                if focus_type_val == "main"
                else "Blocked sub-skills cannot be taught or studied."
            )
            await self._save_and_respond(
                interaction,
                pl,
                content=message,
                ephemeral=True,
            )
            return

        assignment = brothel.start_training(
            mentor_girl.uid,
            student_girl.uid,
            focus_type_val,
            focus_name,
        )
        if not assignment:
            await self._save_and_respond(
                interaction,
                pl,
                content="Unable to start training.",
                ephemeral=True,
            )
            return

        focus_text = self._format_training_focus(focus_type_val, focus_name)
        await self._save_and_respond(
            interaction,
            pl,
            content=(
                f"📘 **{mentor_girl.name}** is now mentoring **{student_girl.name}** in {focus_text}."
            ),
            ephemeral=True,
        )

    async def _handle_train_finish(
        self,
        interaction,
        pl,
        brothel,
        mentor: Optional[str],
        student: Optional[str],
    ) -> None:
        target_uid = (student or mentor or "").strip()
        if not target_uid:
            await self._save_and_respond(
                interaction,
                pl,
                content="Specify mentor or student UID to finish training.",
                ephemeral=True,
            )
            return

        assignment = brothel.training_for(target_uid)
        if not assignment:
            await self._save_and_respond(
                interaction,
                pl,
                content="No mentorship found for that UID.",
                ephemeral=True,
            )
            return

        mentor_girl = pl.get_girl(assignment.mentor_uid)
        student_girl = pl.get_girl(assignment.student_uid)
        if not mentor_girl or not student_girl:
            brothel.stop_training(assignment.mentor_uid)
            await self._save_and_respond(
                interaction,
                pl,
                content="Girls not found.",
                ephemeral=True,
            )
            return

        since_ts = getattr(assignment, "since_ts", None) or 0.0
        elapsed_seconds = max(0.0, time.time() - since_ts)
        if elapsed_seconds < MIN_TRAINING_SECONDS:
            elapsed_minutes = elapsed_seconds / 60
            required_minutes = int(MIN_TRAINING_SECONDS // 60)
            await self._save_and_respond(
                interaction,
                pl,
                content=(
                    "Training is too short "
                    f"({elapsed_minutes:.1f} minutes). Let them train for at least "
                    f"{required_minutes} minutes before finishing."
                ),
                ephemeral=True,
            )
            return

        brothel.stop_training(assignment.mentor_uid)
        bonus = self._calculate_training_bonus(assignment, mentor_girl, student_girl)
        focus_kind = assignment.focus_type or "any"
        student_girl.grant_training_bonus(
            mentor_girl.uid,
            bonus,
            focus_kind,
            assignment.focus,
        )

        focus_text = self._format_training_focus(focus_kind, assignment.focus)
        focus_kind_norm = (focus_kind or "any").lower()
        target_line = (
            "next job" if focus_kind_norm == "any" else f"next {focus_text} job"
        )
        await self._save_and_respond(
            interaction,
            pl,
            content=(
                f"📘 Training finished. **{student_girl.name}** gains +{int(bonus * 100)}% XP on {target_line}."
            ),
            ephemeral=True,
        )

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
        starter_coins = pl.currency

        embed = discord.Embed(
            title=f"{EMOJI_SPARK} Starter Pack",
            description=(
                f"You received {EMOJI_COIN} **{starter_coins}** and your first girl!"
            ),
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
        pl.renown = brothel.renown
        for g in pl.girls:
            g.normalize_skill_structs()
            g.apply_regen(brothel)
        save_player(pl)

        # Reputation progress to next market level
        rep = int(pl.renown)
        mkt_lvl = market_level_from_rep(rep)
        next_cap = (mkt_lvl + 1) * 100
        base_cap = mkt_lvl * 100
        cur_seg = rep - base_cap
        need_seg = max(1, next_cap - base_cap)
        rep_bar = make_bar(cur_seg, need_seg, length=12)

        embed = discord.Embed(title=f"{interaction.user.display_name}'s Profile", color=0x60A5FA)
        embed.add_field(name=f"{EMOJI_COIN} Coins", value=str(pl.currency))
        embed.add_field(name=f"{EMOJI_GIRL} Girls", value=str(len(pl.girls)))
        embed.add_field(name="⭐ Renown", value=f"{rep} / {next_cap}  {rep_bar}", inline=False)
        embed.add_field(name="🏷️ Market Level", value=str(mkt_lvl))

        overview, reserves = brothel_overview_lines(brothel, len(pl.girls))
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
            app_commands.Choice(name="Expand rooms", value="expand"),
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
        pl, brothel = await self._prepare_player(interaction)
        if not pl:
            return

        action_val = normalize_brothel_action(action)
        facility_val = self._resolve_brothel_facility(facility)
        invest = max(0, coins or 0)

        if action_val == "view":
            embed = self._build_brothel_embed(interaction.user.display_name, pl)
            await self._save_and_respond(interaction, pl, embed=embed, ephemeral=True)
            return

        if action_val == "upgrade" and not facility_val:
            await self._save_and_respond(
                interaction,
                pl,
                content="Select which facility to upgrade.",
                ephemeral=True,
            )
            return

        if invest <= 0:
            await self._save_and_respond(
                interaction,
                pl,
                content="Specify how many coins to spend.",
                ephemeral=True,
            )
            return

        if pl.currency < invest:
            await self._save_and_respond(
                interaction,
                pl,
                content=f"Not enough coins. Need {EMOJI_COIN} {invest}.",
                ephemeral=True,
            )
            return

        handlers = {
            "upgrade": lambda: self._brothel_upgrade_notes(brothel, facility_val, invest)
            if facility_val
            else [],
            "maintain": lambda: self._brothel_maintain_notes(brothel, invest),
            "promote": lambda: self._brothel_promote_notes(brothel, invest),
            "expand": lambda: self._brothel_expand_notes(brothel, invest),
        }

        if action_val not in handlers:
            await self._save_and_respond(
                interaction,
                pl,
                content="Unknown action.",
                ephemeral=True,
            )
            return

        notes = handlers[action_val]()
        pl.currency -= invest
        notes = [f"{EMOJI_COIN} Spent {invest} coins.", *notes]

        brothel.ensure_bounds()
        pl.renown = brothel.renown

        embed = self._build_brothel_embed(
            interaction.user.display_name,
            pl,
            notes=notes,
        )
        await self._save_and_respond(interaction, pl, embed=embed, ephemeral=True)

    @app_commands.command(name="gacha", description="Roll the gacha (100 coins per roll)")
    @app_commands.describe(times="How many times to roll (1-10)")
    async def gacha(self, interaction: discord.Interaction, times: int = 1):
        times = max(1, min(times, 10))
        pl = load_player(interaction.user.id)
        if not pl:
            await interaction.response.send_message("Use /start first.", ephemeral=True)
            return
        try:
            girls, total_cost = roll_gacha(interaction.user.id, times)
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

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
            content=f"Spent {EMOJI_COIN} **{total_cost}**. You got **{len(girls)}** roll(s).",
            embeds=embeds[:10],
        )

    @app_commands.command(name="train", description="Manage mentorship training assignments")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="List", value="list"),
            app_commands.Choice(name="Assign", value="assign"),
            app_commands.Choice(name="Finish", value="finish"),
        ],
        focus_type=[
            app_commands.Choice(name="Main skill", value="main"),
            app_commands.Choice(name="Sub-skill", value="sub"),
        ],
        main_skill=[app_commands.Choice(name=name, value=name) for name in MAIN_SKILLS],
        sub_skill=[
            app_commands.Choice(name=name.title(), value=name) for name in SUB_SKILLS
        ],
    )
    @app_commands.describe(
        mentor="Mentor girl UID",
        student="Student girl UID",
        focus_type="Focus category for the mentorship",
        main_skill="Main skill to train",
        sub_skill="Sub-skill to train",
    )
    async def train(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        mentor: Optional[str] = None,
        student: Optional[str] = None,
        focus_type: Optional[app_commands.Choice[str]] = None,
        main_skill: Optional[app_commands.Choice[str]] = None,
        sub_skill: Optional[app_commands.Choice[str]] = None,
    ):
        pl, brothel = await self._prepare_player(interaction, regen_girls=True)
        if not pl:
            return

        action_val = (choice_value(action) or "list").lower()

        if action_val == "list":
            await self._handle_train_list(interaction, pl, brothel)
            return

        if action_val == "assign":
            await self._handle_train_assign(
                interaction,
                pl,
                brothel,
                mentor,
                student,
                focus_type,
                main_skill,
                sub_skill,
            )
            return

        if action_val == "finish":
            await self._handle_train_finish(
                interaction,
                pl,
                brothel,
                mentor,
                student,
            )
            return

        await self._save_and_respond(
            interaction,
            pl,
            content="Unknown action.",
            ephemeral=True,
        )

    @app_commands.command(name="girls", description="List your girls")
    async def girls(self, interaction: discord.Interaction):
        pl = load_player(interaction.user.id)
        if not pl or not pl.girls:
            await interaction.response.send_message("You have no girls. Use /start or /gacha.", ephemeral=True)
            return

        brothel = pl.ensure_brothel()

        pages: list[discord.Embed] = []
        files: list[str | None] = []

        for girl in pl.girls:
            embed, image_path = build_girl_embed(girl, brothel)
            if image_path and os.path.exists(image_path):
                files.append(image_path)
            else:
                files.append(None)
            pages.append(embed)

        save_player(pl)
        view = Paginator(pages, interaction.user.id, timeout=120, files=files)
        await view.send(interaction)

    @app_commands.command(name="top", description="Show leaderboards for brothels or girls")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="Brothels", value="brothel"),
            app_commands.Choice(name="Girls", value="girls"),
        ]
    )
    async def top(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str] | None = None,
    ):
        cat = (choice_value(category) or "brothel").lower()
        if cat not in {"brothel", "girls"}:
            cat = "brothel"

        if cat == "brothel":
            entries = brothel_leaderboard(10)
            embed = discord.Embed(title="Top Brothels", color=0xF59E0B)
            if not entries:
                embed.description = "No data yet."
            for idx, (score, player) in enumerate(entries, start=1):
                user = interaction.client.get_user(player.user_id) or interaction.guild and interaction.guild.get_member(player.user_id)
                mention = f"<@{player.user_id}>" if user is None else user.mention
                brothel = player.ensure_brothel()
                embed.add_field(
                    name=f"{idx}. {mention}",
                    value=(
                        f"Score {score} • Rooms {brothel.rooms} • "
                        f"Renown {player.renown}"
                    ),
                    inline=False,
                )
        else:
            entries = girl_leaderboard(10)
            embed = discord.Embed(title="Top Girls", color=0x8B5CF6)
            if not entries:
                embed.description = "No girls ranked yet."
            for idx, (score, player, girl) in enumerate(entries, start=1):
                user = interaction.client.get_user(player.user_id) or interaction.guild and interaction.guild.get_member(player.user_id)
                owner = f"<@{player.user_id}>" if user is None else user.mention
                embed.add_field(
                    name=f"{idx}. {girl.name} [{girl.rarity}]",
                    value=(
                        f"Owner {owner} • Lv{girl.level} • Score {score}"
                    ),
                    inline=False,
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)

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
        pl.renown = brothel.renown
        for g in pl.girls:
            g.normalize_skill_structs()
            g.apply_regen(brothel)
        save_player(pl)

        max_lvl = market_level_from_rep(pl.renown)
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

        brothel = pl.ensure_brothel()
        girl.normalize_skill_structs()
        girl.apply_regen(brothel)

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
                def __init__(self, invoker_id: int, girl_uid: str):
                    super().__init__(timeout=20)
                    self.invoker_id = invoker_id
                    self.girl_uid = girl_uid

                @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="💥")
                async def confirm_btn(self, i: discord.Interaction, b: discord.ui.Button):
                    if i.user.id != self.invoker_id:
                        await i.response.send_message("This isn't your view.", ephemeral=True)
                        return

                    fresh_player = load_player(self.invoker_id)
                    if not fresh_player:
                        await i.response.edit_message(
                            content=f"{EMOJI_X} Profile not found.",
                            view=None,
                            embed=None,
                        )
                        return

                    target_girl = fresh_player.get_girl(self.girl_uid)
                    if not target_girl:
                        await i.response.edit_message(
                            content=f"{EMOJI_X} Girl not found or already dismantled.",
                            view=None,
                            embed=None,
                        )
                        return

                    res = dismantle_girl(fresh_player, self.girl_uid)
                    if res.get("ok"):
                        save_player(fresh_player)
                        await i.response.edit_message(
                            content=(
                                f"{EMOJI_OK} Dismantled **{res['name']}** [{res['rarity']}] "
                                f"→ {EMOJI_COIN} **{res['reward']}**"
                            ),
                            view=None,
                            embed=None,
                        )
                    else:
                        await i.response.edit_message(
                            content=f"{EMOJI_X} {res.get('reason', 'Failed')}",
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
                await interaction.response.send_message(
                    embed=embed,
                    view=ConfirmView(interaction.user.id, girl_id),
                    ephemeral=True,
                    file=discord.File(img),
                )
            else:
                embed.set_image(url=g.image_url)
                await interaction.response.send_message(
                    embed=embed,
                    view=ConfirmView(interaction.user.id, girl_id),
                    ephemeral=True,
                )
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
