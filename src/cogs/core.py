import os
import time
from typing import Any, Optional, Tuple, Callable

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
from ..game.views import MarketWorkView, Paginator, TopLeaderboardView


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

    async def _handle_brothel_compat(
        self,
        interaction: discord.Interaction,
        pl,
        brothel,
        action: app_commands.Choice[str] | None,
        facility: app_commands.Choice[str] | None,
        coins: int | None,
    ) -> None:
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

        handlers: dict[str, Callable[[], list[str]]] = {
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

    def _training_overview_lines(self, pl, brothel) -> list[str]:
        lines: list[str] = []
        training = getattr(brothel, "training", None)
        if not training:
            return lines

        now_ts = time.time()
        for assignment in training:
            mentor_girl = pl.get_girl(assignment.mentor_uid)
            student_girl = pl.get_girl(assignment.student_uid)
            if not mentor_girl or not student_girl:
                continue
            minutes = max(0, int((now_ts - assignment.since_ts) // 60))
            focus_text = self._format_training_focus(
                assignment.focus_type,
                assignment.focus,
            )
            lines.append(
                f"📘 **{mentor_girl.name}** → **{student_girl.name}** • {focus_text} • {minutes} min"
            )

        return lines

    def _assign_training(
        self,
        pl,
        brothel,
        mentor_uid: Optional[str],
        student_uid: Optional[str],
        focus_type: Optional[str],
        focus_name: Optional[str],
    ) -> tuple[bool, str]:
        mentor_uid = (mentor_uid or "").strip()
        student_uid = (student_uid or "").strip()

        if not mentor_uid or not student_uid:
            return False, "Specify mentor and student UIDs."

        mentor_girl = pl.get_girl(mentor_uid)
        student_girl = pl.get_girl(student_uid)
        if not mentor_girl or not student_girl:
            return False, "Mentor or student not found."

        if mentor_girl.uid == student_girl.uid:
            return False, "Mentor and student must be different."

        if brothel.training_for(mentor_girl.uid) or brothel.training_for(student_girl.uid):
            return False, "One of the girls is already in training."

        if not self._mentor_more_experienced(mentor_girl, student_girl):
            return False, "Mentor must be more experienced than the student."

        focus_type_val = (focus_type or "").lower() or None
        focus_name_val = focus_name or None

        if not focus_type_val or not focus_name_val:
            return False, "Select a concrete skill for the mentorship."

        if focus_type_val == "main" and focus_name_val not in MAIN_SKILLS:
            return False, "Unknown main skill."
        if focus_type_val == "sub" and focus_name_val not in SUB_SKILLS:
            return False, "Unknown sub-skill."

        if self._is_focus_blocked(mentor_girl, focus_type_val, focus_name_val) or self._is_focus_blocked(
            student_girl,
            focus_type_val,
            focus_name_val,
        ):
            message = (
                "Blocked skills cannot be taught or studied."
                if focus_type_val == "main"
                else "Blocked sub-skills cannot be taught or studied."
            )
            return False, message

        assignment = brothel.start_training(
            mentor_girl.uid,
            student_girl.uid,
            focus_type_val,
            focus_name_val,
        )
        if not assignment:
            return False, "Unable to start training."

        focus_text = self._format_training_focus(focus_type_val, focus_name_val)
        return (
            True,
            f"📘 **{mentor_girl.name}** is now mentoring **{student_girl.name}** in {focus_text}.",
        )

    def _finish_training(
        self,
        pl,
        brothel,
        target_uid: Optional[str],
    ) -> tuple[bool, str]:
        target_uid = (target_uid or "").strip()
        if not target_uid:
            return False, "Specify mentor or student UID to finish training."

        assignment = brothel.training_for(target_uid)
        if not assignment:
            return False, "No mentorship found for that UID."

        mentor_girl = pl.get_girl(assignment.mentor_uid)
        student_girl = pl.get_girl(assignment.student_uid)
        if not mentor_girl or not student_girl:
            brothel.stop_training(assignment.mentor_uid)
            return False, "Girls not found."

        since_ts = getattr(assignment, "since_ts", None) or 0.0
        elapsed_seconds = max(0.0, time.time() - since_ts)
        if elapsed_seconds < MIN_TRAINING_SECONDS:
            elapsed_minutes = elapsed_seconds / 60
            required_minutes = int(MIN_TRAINING_SECONDS // 60)
            return (
                False,
                "Training is too short "
                f"({elapsed_minutes:.1f} minutes). Let them train for at least "
                f"{required_minutes} minutes before finishing.",
            )

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
        return (
            True,
            f"📘 Training finished. **{student_girl.name}** gains +{int(bonus * 100)}% XP on {target_line}.",
        )

    async def _handle_train_finish(
        self,
        interaction: discord.Interaction,
        pl,
        brothel,
        mentor: Optional[str],
        student: Optional[str],
    ) -> None:
        target_uid = (student or mentor or "").strip()
        success, message = self._finish_training(pl, brothel, target_uid)
        await self._save_and_respond(
            interaction,
            pl,
            content=message,
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

        if action is not None or facility is not None or coins is not None:
            await self._handle_brothel_compat(interaction, pl, brothel, action, facility, coins)
            return

        save_player(pl)
        view = BrothelManageView(
            cog=self,
            user_name=interaction.user.display_name,
            invoker_id=interaction.user.id,
            player=pl,
            brothel=brothel,
        )
        await view.start(interaction)

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
    async def train(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str] | None = None,
        mentor: Optional[str] = None,
        student: Optional[str] = None,
        focus_type: Optional[app_commands.Choice[str]] = None,
        main_skill: Optional[app_commands.Choice[str]] = None,
        sub_skill: Optional[app_commands.Choice[str]] = None,
    ):
        pl, brothel = await self._prepare_player(interaction, regen_girls=True)
        if not pl:
            return

        if action is not None:
            action_val = (choice_value(action) or "list").lower()
            if action_val == "list":
                lines = self._training_overview_lines(pl, brothel)
                message = "\n".join(lines[:20]) if lines else "No active mentorships."
                await self._save_and_respond(
                    interaction,
                    pl,
                    content=message,
                    ephemeral=True,
                )
                return

            if action_val == "assign":
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

                success, message = self._assign_training(
                    pl,
                    brothel,
                    mentor_uid,
                    student_uid,
                    focus_type_val,
                    focus_name,
                )
                await self._save_and_respond(
                    interaction,
                    pl,
                    content=message,
                    ephemeral=True,
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
            return

        save_player(pl)
        view = TrainingManageView(
            cog=self,
            user_name=interaction.user.display_name,
            invoker_id=interaction.user.id,
            player=pl,
            brothel=brothel,
        )
        await view.start(interaction)

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

        def fmt_number(value: int) -> str:
            return f"{value:,}".replace(",", " ")

        view: TopLeaderboardView | None = None
        used_entry_values: set[str] = set()

        def unique_entry_value(base: str) -> str:
            value = base
            suffix = 2
            while value in used_entry_values:
                value = f"{base}-{suffix}"
                suffix += 1
            used_entry_values.add(value)
            return value

        if cat == "brothel":
            raw_entries = brothel_leaderboard(10)
            embed = discord.Embed(title="Top Brothels", color=0xF59E0B)
            entries_for_view: list[dict[str, Any]] = []

            if not raw_entries:
                embed.description = "No data yet."
            else:
                embed.description = (
                    "Top establishments by facility strength, rooms and renown.\n"
                    "Use the selector below to inspect any brothel in detail."
                )

            for idx, (score, player) in enumerate(raw_entries, start=1):
                user = interaction.client.get_user(player.user_id) or (
                    interaction.guild and interaction.guild.get_member(player.user_id)
                )
                display_name = user.display_name if user else f"Player {player.user_id}"
                mention = user.mention if user else f"<@{player.user_id}>"
                brothel = player.ensure_brothel()
                girls_count = len(player.girls)
                score_text = fmt_number(score)
                field_lines = [
                    f"Owner: {mention}",
                    (
                        f"{EMOJI_COIN} Score {score_text} • {EMOJI_ROOMS} {brothel.rooms} • "
                        f"{EMOJI_GIRL} {girls_count}"
                    ),
                    (
                        f"{EMOJI_POPULARITY} Renown {player.renown} • "
                        f"{EMOJI_CLEAN} {brothel.cleanliness}/100 • "
                        f"{EMOJI_MORALE} {brothel.morale}/100"
                    ),
                ]
                embed.add_field(
                    name=f"#{idx} {display_name}",
                    value="\n".join(field_lines),
                    inline=False,
                )
                entries_for_view.append(
                    {
                        "value": unique_entry_value(str(player.user_id)),
                        "label": f"#{idx} {display_name}",
                        "description": (
                            f"Score {score_text} • Rooms {brothel.rooms} • Girls {girls_count}"
                        ),
                        "player": player,
                        "display_name": display_name,
                        "mention": mention,
                        "score": score,
                        "score_text": score_text,
                        "rank": idx,
                    }
                )

            if entries_for_view:
                embed.set_footer(
                    text="Select a brothel below to view its full profile."
                )
                view = TopLeaderboardView(
                    invoker_id=interaction.user.id,
                    category="brothel",
                    entries=entries_for_view,
                    leaderboard_embed=embed,
                )
        else:
            raw_entries = girl_leaderboard(10)
            embed = discord.Embed(title="Top Girls", color=0x8B5CF6)
            entries_for_view = []

            if not raw_entries:
                embed.description = "No girls ranked yet."
            else:
                embed.description = (
                    "Highest-scoring girls in the city.\n"
                    "Use the selector below to open their full profiles."
                )

            for idx, (score, player, girl) in enumerate(raw_entries, start=1):
                user = interaction.client.get_user(player.user_id) or (
                    interaction.guild and interaction.guild.get_member(player.user_id)
                )
                owner_display = user.display_name if user else f"Player {player.user_id}"
                owner_mention = user.mention if user else f"<@{player.user_id}>"
                score_text = fmt_number(score)
                field_lines = [
                    f"Owner: {owner_mention}",
                    (
                        f"{EMOJI_COIN} Score {score_text} • Lv{girl.level} • {girl.rarity}"
                    ),
                    (
                        f"{EMOJI_HEART} {girl.health}/{girl.health_max} • "
                        f"{EMOJI_ENERGY} {girl.stamina}/{girl.stamina_max} • "
                        f"{EMOJI_LUST} {girl.lust}/{girl.lust_max}"
                    ),
                ]
                embed.add_field(
                    name=f"#{idx} {girl.name} [{girl.rarity}]",
                    value="\n".join(field_lines),
                    inline=False,
                )
                entries_for_view.append(
                    {
                        "value": unique_entry_value(str(girl.uid)),
                        "label": f"#{idx} {girl.name}",
                        "description": (
                            f"Owner {owner_display} • Lv{girl.level} • Score {score_text}"
                        ),
                        "player": player,
                        "girl": girl,
                        "owner_display": owner_display,
                        "owner_mention": owner_mention,
                        "score": score,
                        "score_text": score_text,
                        "rank": idx,
                    }
                )

            if entries_for_view:
                embed.set_footer(
                    text="Select a girl below to view a detailed profile."
                )
                view = TopLeaderboardView(
                    invoker_id=interaction.user.id,
                    category="girls",
                    entries=entries_for_view,
                    leaderboard_embed=embed,
                )

        if view:
            await interaction.response.send_message(
                embed=embed, view=view, ephemeral=True
            )
        else:
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



class BrothelManageView(discord.ui.View):
    """Interactive manager for the /brothel command."""

    ACTION_LABELS = {
        "view": "View status",
        "upgrade": "Upgrade facility",
        "maintain": "Maintain cleanliness",
        "promote": "Promote services",
        "expand": "Expand rooms",
    }
    COIN_PRESETS = (25, 50, 100, 250, 500, 1000, 2000)

    def __init__(
        self,
        *,
        cog: "Core",
        user_name: str,
        invoker_id: int,
        player,
        brothel,
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.user_name = user_name
        self.invoker_id = invoker_id
        self.player = player
        self.brothel = brothel
        self.selected_action = "view"
        self.selected_facility: str | None = None
        self.invest_amount: int = 0
        self._message: discord.Message | None = None

        self.action_select = self.ActionSelect(self)
        self.facility_select = self.FacilitySelect(self)
        self.coin_select = self.CoinSelect(self)

        self.add_item(self.action_select)
        self.add_item(self.facility_select)
        self.add_item(self.coin_select)
        self._update_components()

    async def start(self, interaction: discord.Interaction) -> None:
        embed = self._build_embed()
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
        try:
            self._message = await interaction.original_response()
        except Exception:
            self._message = None

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This isn't your panel.", ephemeral=True)
            return False
        return True

    def _build_coin_options(self) -> list[discord.SelectOption]:
        coins = max(0, int(getattr(self.player, "currency", 0)))
        amounts: list[int] = []
        for preset in self.COIN_PRESETS:
            if preset <= coins:
                amounts.append(int(preset))
        if coins:
            half = coins // 2
            if half and half not in amounts:
                amounts.append(half)
            if coins not in amounts:
                amounts.append(coins)
        options: list[discord.SelectOption] = [
            discord.SelectOption(label="No investment", value="0", description="Only view status"),
        ]
        for amt in sorted(set(amounts))[:24]:
            label = f"{amt} coins"
            description = None
            if coins and amt == coins:
                label = f"All coins ({coins})"
                description = "Spend everything from your wallet"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(amt),
                    description=description,
                )
            )
        if len(options) == 1:
            options.append(
                discord.SelectOption(label="No coins available", value="0", description="Wallet is empty")
            )
        return options[:25]

    def _action_summary(self) -> str:
        label = self.ACTION_LABELS.get(self.selected_action, self.selected_action.title())
        if self.selected_action == "upgrade" and self.selected_facility:
            icon, facility_label = FACILITY_INFO[self.selected_facility]
            summary = f"{label}: {icon} {facility_label}"
        elif self.selected_action == "view":
            summary = label
        else:
            summary = label
        if self.selected_action != "view" and self.invest_amount > 0:
            summary += f" • {EMOJI_COIN} {self.invest_amount}"
        return summary

    def _build_embed(self, *, notes: list[str] | None = None) -> discord.Embed:
        embed = self.cog._build_brothel_embed(self.user_name, self.player, notes)
        if self.selected_action != "view":
            embed.add_field(
                name="Selected action",
                value=self._action_summary(),
                inline=False,
            )
        return embed

    async def _send_update(self, interaction: discord.Interaction, *, notes: list[str] | None = None) -> None:
        embed = self._build_embed(notes=notes)
        await interaction.response.edit_message(embed=embed, view=self)

    def _update_components(self) -> None:
        label = self.ACTION_LABELS.get(self.selected_action, self.selected_action.title())
        self.action_select.placeholder = label

        if self.selected_action == "upgrade":
            self.facility_select.disabled = False
            if self.selected_facility:
                icon, facility_label = FACILITY_INFO[self.selected_facility]
                self.facility_select.placeholder = f"{icon} {facility_label}"
            else:
                self.facility_select.placeholder = "Choose facility"
        else:
            self.facility_select.disabled = True
            self.facility_select.placeholder = "Facility (upgrade only)"

        if self.selected_action == "view":
            self.coin_select.disabled = True
            self.coin_select.placeholder = "No coins needed"
            self.invest_amount = 0
        else:
            self.coin_select.disabled = False
            if self.invest_amount > 0:
                self.coin_select.placeholder = f"{self.invest_amount} coins selected"
            else:
                self.coin_select.placeholder = "Select coins to invest"
        self.coin_select.refresh_options()

    def _reset_after_action(self) -> None:
        self.selected_action = "view"
        self.selected_facility = None
        self.invest_amount = 0
        self._update_components()

    async def _run_action(self, interaction: discord.Interaction) -> None:
        if self.selected_action == "view":
            await self._send_update(interaction)
            return

        invest = max(0, self.invest_amount)
        if self.selected_action == "upgrade" and not self.selected_facility:
            await self._send_update(interaction, notes=["Select a facility to upgrade."])
            return

        if invest <= 0:
            await self._send_update(interaction, notes=["Select how many coins to invest."])
            return

        if self.player.currency < invest:
            await self._send_update(
                interaction,
                notes=[f"Not enough coins. Need {EMOJI_COIN} {invest}."]
            )
            return

        handlers: dict[str, Callable[[], list[str]]] = {
            "upgrade": lambda: self.cog._brothel_upgrade_notes(self.brothel, self.selected_facility, invest)
            if self.selected_facility
            else [],
            "maintain": lambda: self.cog._brothel_maintain_notes(self.brothel, invest),
            "promote": lambda: self.cog._brothel_promote_notes(self.brothel, invest),
            "expand": lambda: self.cog._brothel_expand_notes(self.brothel, invest),
        }

        if self.selected_action not in handlers:
            await self._send_update(interaction, notes=["Unknown action."])
            return

        notes = handlers[self.selected_action]()
        self.player.currency -= invest
        notes = [f"{EMOJI_COIN} Spent {invest} coins.", *notes]

        self.brothel.ensure_bounds()
        self.player.renown = self.brothel.renown
        save_player(self.player)

        self._reset_after_action()
        await self._send_update(interaction, notes=notes)

    class ActionSelect(discord.ui.Select):
        def __init__(self, parent: "BrothelManageView") -> None:
            self.manager: "BrothelManageView" = parent
            options = [
                discord.SelectOption(label=label, value=value)
                for value, label in BrothelManageView.ACTION_LABELS.items()
            ]
            super().__init__(
                placeholder=BrothelManageView.ACTION_LABELS["view"],
                min_values=1,
                max_values=1,
                options=options,
                row=0,
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            if not await self.manager._check_owner(interaction):
                return
            self.manager.selected_action = self.values[0]
            if self.manager.selected_action == "view":
                self.manager.invest_amount = 0
            self.manager._update_components()
            await self.manager._send_update(interaction)

    class FacilitySelect(discord.ui.Select):
        def __init__(self, parent: "BrothelManageView") -> None:
            self.manager: "BrothelManageView" = parent
            options = [
                discord.SelectOption(label=f"{icon} {label}", value=key)
                for key, (icon, label) in FACILITY_INFO.items()
            ]
            super().__init__(
                placeholder="Facility (upgrade only)",
                min_values=1,
                max_values=1,
                options=options,
                disabled=True,
                row=1,
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            if not await self.manager._check_owner(interaction):
                return
            self.manager.selected_facility = self.values[0]
            icon, label = FACILITY_INFO[self.manager.selected_facility]
            self.placeholder = f"{icon} {label}"
            await self.manager._send_update(interaction)

    class CoinSelect(discord.ui.Select):
        def __init__(self, parent: "BrothelManageView") -> None:
            self.manager: "BrothelManageView" = parent
            super().__init__(
                placeholder="Select coins to invest",
                min_values=1,
                max_values=1,
                options=parent._build_coin_options(),
                disabled=True,
                row=2,
            )

        def refresh_options(self) -> None:
            self.options = self.manager._build_coin_options()

        async def callback(self, interaction: discord.Interaction) -> None:
            if not await self.manager._check_owner(interaction):
                return
            try:
                value = int(self.values[0])
            except ValueError:
                value = 0
            self.manager.invest_amount = max(0, value)
            if self.manager.invest_amount > 0:
                self.placeholder = f"{self.manager.invest_amount} coins selected"
            else:
                self.placeholder = "No coins selected"
            await self.manager._send_update(interaction)

    @discord.ui.button(label="Execute", style=discord.ButtonStyle.success, emoji="✅", row=3)
    async def execute_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        await self._run_action(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="✖️", row=3)
    async def close_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        self.stop()
        await interaction.response.edit_message(view=None)

    async def on_timeout(self) -> None:
        if self._message is None:
            return
        try:
            await self._message.edit(view=None)
        except Exception:
            pass


class TrainingManageView(discord.ui.View):
    """Interactive manager for the /train command."""

    ACTION_LABELS = {
        "list": "List mentorships",
        "assign": "Assign mentorship",
        "finish": "Finish mentorship",
    }

    def __init__(
        self,
        *,
        cog: "Core",
        user_name: str,
        invoker_id: int,
        player,
        brothel,
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.user_name = user_name
        self.invoker_id = invoker_id
        self.player = player
        self.brothel = brothel
        self.current_action = "list"
        self.selected_mentor: str | None = None
        self.selected_student: str | None = None
        self.selected_focus_type: str | None = None
        self.selected_focus_name: str | None = None
        self.selected_assignment_uid: str | None = None
        self._message: discord.Message | None = None

        self.action_select = self.ActionSelect(self)
        self.mentor_select = self.MentorSelect(self)
        self.student_select = self.StudentSelect(self)
        self.focus_select = self.FocusSelect(self)
        self.assignment_select = self.AssignmentSelect(self)

        self.add_item(self.action_select)
        self._sync_component_layout()
        self._update_components()

    async def start(self, interaction: discord.Interaction) -> None:
        embed = self._build_embed()
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
        try:
            self._message = await interaction.original_response()
        except Exception:
            self._message = None

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This isn't your panel.", ephemeral=True)
            return False
        return True

    def _girl_name(self, uid: str | None) -> str | None:
        if not uid:
            return None
        girl = self.player.get_girl(uid)
        return girl.name if girl else None

    def _assignment_label(self, mentor_uid: str | None) -> str | None:
        if not mentor_uid:
            return None
        assignment = self.brothel.training_for(mentor_uid)
        if not assignment:
            return None
        mentor = self.player.get_girl(assignment.mentor_uid)
        student = self.player.get_girl(assignment.student_uid)
        if not mentor or not student:
            return None
        focus_text = self.cog._format_training_focus(assignment.focus_type, assignment.focus)
        return f"{mentor.name} → {student.name} • {focus_text}"

    def _build_girl_options(self, *, exclude_uid: str | None = None) -> list[discord.SelectOption]:
        girls = sorted(
            list(getattr(self.player, "girls", [])),
            key=lambda g: (-getattr(g, "level", 0), g.name),
        )
        options: list[discord.SelectOption] = []
        for girl in girls:
            if exclude_uid and girl.uid == exclude_uid:
                continue
            if self.brothel.training_for(girl.uid):
                continue
            label = f"{girl.name} (L{getattr(girl, 'level', 0)})"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=girl.uid,
                    description=f"UID: {girl.uid}",
                )
            )
            if len(options) >= 25:
                break
        return options

    def _build_assignment_options(self) -> list[discord.SelectOption]:
        options: list[discord.SelectOption] = []
        training = getattr(self.brothel, "training", [])
        for assignment in training:
            mentor = self.player.get_girl(assignment.mentor_uid)
            student = self.player.get_girl(assignment.student_uid)
            if not mentor or not student:
                continue
            focus_text = self.cog._format_training_focus(assignment.focus_type, assignment.focus)
            label = f"{mentor.name} → {student.name}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=assignment.mentor_uid,
                    description=focus_text[:100],
                )
            )
            if len(options) >= 25:
                break
        return options

    def _refresh_assignment_options(self) -> None:
        options = self._build_assignment_options()
        self.assignment_select.options = options or [self.assignment_select.EMPTY_OPTION]

    def _sync_component_layout(self) -> None:
        if self.action_select not in self.children:
            self.add_item(self.action_select)

        assign_items = (
            self.mentor_select,
            self.student_select,
            self.focus_select,
        )

        if self.current_action == "assign":
            for item in assign_items:
                if item not in self.children:
                    self.add_item(item)
            if self.assignment_select in self.children:
                self.remove_item(self.assignment_select)
        elif self.current_action == "finish":
            for item in assign_items:
                if item in self.children:
                    self.remove_item(item)
            if self.assignment_select not in self.children:
                self.add_item(self.assignment_select)
        else:
            for item in (*assign_items, self.assignment_select):
                if item in self.children:
                    self.remove_item(item)

    def _update_components(self) -> None:
        self._sync_component_layout()

        label = self.ACTION_LABELS.get(self.current_action, self.current_action.title())
        self.action_select.placeholder = label

        self.mentor_select.refresh_options()
        self.student_select.refresh_options()
        self._refresh_assignment_options()

        is_assign = self.current_action == "assign"
        is_finish = self.current_action == "finish"

        mentor_has_options = any(opt.value != "none" for opt in self.mentor_select.options)
        student_has_options = any(opt.value != "none" for opt in self.student_select.options)
        assignment_has_options = any(opt.value != "none" for opt in self.assignment_select.options)

        self.mentor_select.disabled = not is_assign or not mentor_has_options
        self.student_select.disabled = not is_assign or not student_has_options
        self.focus_select.disabled = not is_assign or not (mentor_has_options and student_has_options)
        self.assignment_select.disabled = not is_finish or not assignment_has_options

        mentor_name = self._girl_name(self.selected_mentor)
        self.mentor_select.placeholder = (
            f"Mentor: {mentor_name}" if mentor_name else "Select mentor"
        )

        student_name = self._girl_name(self.selected_student)
        self.student_select.placeholder = (
            f"Student: {student_name}" if student_name else "Select student"
        )

        if self.selected_focus_type and self.selected_focus_name:
            focus_text = self.cog._format_training_focus(
                self.selected_focus_type,
                self.selected_focus_name,
            )
            self.focus_select.placeholder = f"Focus: {focus_text}"
        else:
            self.focus_select.placeholder = "Select skill focus"

        assignment_label = self._assignment_label(self.selected_assignment_uid)
        if assignment_label:
            self.assignment_select.placeholder = assignment_label[:100]
        else:
            self.assignment_select.placeholder = "Select mentorship"

    def _action_summary(self) -> str:
        label = self.ACTION_LABELS.get(self.current_action, self.current_action.title())
        if self.current_action == "assign":
            mentor = self._girl_name(self.selected_mentor) or "mentor?"
            student = self._girl_name(self.selected_student) or "student?"
            if self.selected_focus_type and self.selected_focus_name:
                focus_text = self.cog._format_training_focus(
                    self.selected_focus_type,
                    self.selected_focus_name,
                )
            else:
                focus_text = "select focus"
            return f"{label}: {mentor} → {student} • {focus_text}"
        if self.current_action == "finish":
            assignment_label = self._assignment_label(self.selected_assignment_uid) or "select mentorship"
            return f"{label}: {assignment_label}"
        return label

    def _build_embed(self, *, notes: list[str] | None = None) -> discord.Embed:
        lines = self.cog._training_overview_lines(self.player, self.brothel)
        overview = "\n".join(lines) if lines else "No active mentorships."
        embed = discord.Embed(
            title=f"{self.user_name}'s Mentorships",
            color=0x60A5FA,
        )
        embed.add_field(name=f"{EMOJI_COIN} Coins", value=str(self.player.currency))
        embed.add_field(name="Active mentorships", value=overview, inline=False)
        if self.current_action != "list":
            embed.add_field(
                name="Selected action",
                value=self._action_summary(),
                inline=False,
            )
        if notes:
            embed.add_field(name="Status", value="\n".join(notes), inline=False)
        return embed

    async def _send_update(self, interaction: discord.Interaction, *, notes: list[str] | None = None) -> None:
        embed = self._build_embed(notes=notes)
        await interaction.response.edit_message(embed=embed, view=self)

    class ActionSelect(discord.ui.Select):
        def __init__(self, parent: "TrainingManageView") -> None:
            self.manager: "TrainingManageView" = parent
            options = [
                discord.SelectOption(label=label, value=value)
                for value, label in TrainingManageView.ACTION_LABELS.items()
            ]
            super().__init__(
                placeholder=TrainingManageView.ACTION_LABELS["list"],
                min_values=1,
                max_values=1,
                options=options,
                row=0,
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            if not await self.manager._check_owner(interaction):
                return
            self.manager.current_action = self.values[0]
            if self.manager.current_action != "assign":
                self.manager.selected_mentor = None
                self.manager.selected_student = None
                self.manager.selected_focus_type = None
                self.manager.selected_focus_name = None
            if self.manager.current_action != "finish":
                self.manager.selected_assignment_uid = None
            self.manager._update_components()
            await self.manager._send_update(interaction)

    class MentorSelect(discord.ui.Select):
        EMPTY_OPTION = discord.SelectOption(label="No eligible girls", value="none")

        def __init__(self, parent: "TrainingManageView") -> None:
            self.manager: "TrainingManageView" = parent
            options = parent._build_girl_options() or [self.EMPTY_OPTION]
            super().__init__(
                placeholder="Select mentor",
                min_values=1,
                max_values=1,
                options=options,
                row=1,
            )

        def refresh_options(self) -> None:
            options = self.manager._build_girl_options(exclude_uid=self.manager.selected_student)
            self.options = options or [self.EMPTY_OPTION]

        async def callback(self, interaction: discord.Interaction) -> None:
            if not await self.manager._check_owner(interaction):
                return
            value = self.values[0]
            if value == "none":
                await interaction.response.send_message("No available mentors.", ephemeral=True)
                return
            self.manager.selected_mentor = value
            mentor_name = self.manager._girl_name(self.manager.selected_mentor) or "Mentor"
            self.placeholder = f"Mentor: {mentor_name}"
            await self.manager._send_update(interaction)

    class StudentSelect(discord.ui.Select):
        EMPTY_OPTION = discord.SelectOption(label="No eligible girls", value="none")

        def __init__(self, parent: "TrainingManageView") -> None:
            self.manager: "TrainingManageView" = parent
            options = parent._build_girl_options() or [self.EMPTY_OPTION]
            super().__init__(
                placeholder="Select student",
                min_values=1,
                max_values=1,
                options=options,
                row=2,
            )

        def refresh_options(self) -> None:
            options = self.manager._build_girl_options(exclude_uid=self.manager.selected_mentor)
            self.options = options or [self.EMPTY_OPTION]

        async def callback(self, interaction: discord.Interaction) -> None:
            if not await self.manager._check_owner(interaction):
                return
            value = self.values[0]
            if value == "none":
                await interaction.response.send_message("No available students.", ephemeral=True)
                return
            self.manager.selected_student = value
            student_name = self.manager._girl_name(self.manager.selected_student) or "Student"
            self.placeholder = f"Student: {student_name}"
            await self.manager._send_update(interaction)

    class FocusSelect(discord.ui.Select):
        def __init__(self, parent: "TrainingManageView") -> None:
            self.manager: "TrainingManageView" = parent
            options = [
                discord.SelectOption(label=f"Main • {name}", value=f"main:{name}")
                for name in MAIN_SKILLS
            ] + [
                discord.SelectOption(label=f"Sub • {name.title()}", value=f"sub:{name}")
                for name in SUB_SKILLS
            ]
            super().__init__(
                placeholder="Select skill focus",
                min_values=1,
                max_values=1,
                options=options,
                row=3,
                disabled=True,
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            if not await self.manager._check_owner(interaction):
                return
            raw = self.values[0]
            kind, _, name = raw.partition(":")
            self.manager.selected_focus_type = kind or None
            self.manager.selected_focus_name = name or None
            focus_text = self.manager.cog._format_training_focus(
                self.manager.selected_focus_type,
                self.manager.selected_focus_name,
            )
            self.placeholder = f"Focus: {focus_text}"
            await self.manager._send_update(interaction)

    class AssignmentSelect(discord.ui.Select):
        EMPTY_OPTION = discord.SelectOption(label="No active mentorships", value="none")

        def __init__(self, parent: "TrainingManageView") -> None:
            self.manager: "TrainingManageView" = parent
            options = parent._build_assignment_options() or [self.EMPTY_OPTION]
            super().__init__(
                placeholder="Select mentorship",
                min_values=1,
                max_values=1,
                options=options,
                row=1,
                disabled=True,
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            if not await self.manager._check_owner(interaction):
                return
            value = self.values[0]
            if value == "none":
                await interaction.response.send_message("No mentorships to finish.", ephemeral=True)
                return
            self.manager.selected_assignment_uid = value
            assignment_label = (
                self.manager._assignment_label(self.manager.selected_assignment_uid)
                or "Mentorship"
            )
            self.placeholder = assignment_label[:100]
            await self.manager._send_update(interaction)

    @discord.ui.button(label="Execute", style=discord.ButtonStyle.success, emoji="✅", row=4)
    async def execute_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return

        if self.current_action == "list":
            lines = self.cog._training_overview_lines(self.player, self.brothel)
            note = (
                [f"Active mentorships: {len(lines)}"] if lines else ["No active mentorships."]
            )
            await self._send_update(interaction, notes=note)
            return

        if self.current_action == "assign":
            if not self.selected_mentor or not self.selected_student:
                await self._send_update(interaction, notes=["Select mentor and student first."])
                return
            if not (self.selected_focus_type and self.selected_focus_name):
                await self._send_update(interaction, notes=["Select a skill focus for the mentorship."])
                return
            success, message = self.cog._assign_training(
                self.player,
                self.brothel,
                self.selected_mentor,
                self.selected_student,
                self.selected_focus_type,
                self.selected_focus_name,
            )
            notes = [message]
            if success:
                save_player(self.player)
                self.selected_assignment_uid = None
            self._update_components()
            await self._send_update(interaction, notes=notes)
            return

        if self.current_action == "finish":
            if not self.selected_assignment_uid:
                await self._send_update(interaction, notes=["Select which mentorship to finish."])
                return
            success, message = self.cog._finish_training(
                self.player,
                self.brothel,
                self.selected_assignment_uid,
            )
            notes = [message]
            if success:
                save_player(self.player)
                self.selected_assignment_uid = None
            self._update_components()
            await self._send_update(interaction, notes=notes)
            return

        await self._send_update(interaction, notes=["Unknown action."])

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="✖️", row=4)
    async def close_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        self.stop()
        await interaction.response.edit_message(view=None)

    async def on_timeout(self) -> None:
        if self._message is None:
            return
        try:
            await self._message.edit(view=None)
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Core(bot))
