"""Reusable Discord UI views."""

from __future__ import annotations

import os
import time
from typing import Iterable, Optional

import discord

from ..storage import (
    load_player,
    save_player,
    refresh_market_if_stale,
    load_market,
    save_market,
    resolve_job,
    evaluate_job,
)
from .constants import (
    EMOJI_COIN,
    EMOJI_ENERGY,
    EMOJI_FACILITY,
    EMOJI_GIRL,
    EMOJI_HEART,
    EMOJI_LUST,
    EMOJI_MARKET,
    EMOJI_OK,
    EMOJI_SKILL,
    EMOJI_SPARK,
    EMOJI_SUBSKILL,
    EMOJI_X,
    FACILITY_INFO,
    SKILL_ICONS,
    SUB_SKILL_ICONS,
)
from .embeds import brothel_overview_lines
from .utils import lust_state_icon, lust_state_label


class Paginator(discord.ui.View):
    """Simple paginator supporting per-page file attachments."""

    def __init__(self, pages: list[discord.Embed], invoker_id: int, timeout: float = 120.0, files: Optional[Iterable[Optional[str]]] = None):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.invoker_id = invoker_id
        self.index = 0
        file_list = list(files or [])
        if file_list and len(file_list) != len(pages):
            # pad to match page count
            file_list.extend([None] * (len(pages) - len(file_list)))
        self.page_paths = file_list or [None] * len(pages)
        self._update_buttons()

    def _update_buttons(self):
        self.first_btn.disabled = self.index <= 0
        self.prev_btn.disabled = self.index <= 0
        self.next_btn.disabled = self.index >= len(self.pages) - 1
        self.last_btn.disabled = self.index >= len(self.pages) - 1

    def _make_file(self) -> Optional[discord.File]:
        path = self.page_paths[self.index]
        if path and os.path.exists(path):
            return discord.File(path, filename=os.path.basename(path))
        return None

    async def send(self, interaction: discord.Interaction):
        file = self._make_file()
        if file:
            await interaction.response.send_message(embed=self.pages[self.index], view=self, file=file)
        else:
            await interaction.response.send_message(embed=self.pages[self.index], view=self)

    async def _edit_page(self, interaction: discord.Interaction):
        file = self._make_file()
        if file:
            await interaction.response.edit_message(embed=self.pages[self.index], view=self, attachments=[file])
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


class MarketWorkView(discord.ui.View):
    """Combined market browser and work executor."""

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
        self._job_value_to_id: dict[str, str | None] = {"none": None}

        self.girl_select = self.GirlSelect(self, player)
        self.job_select = self.JobSelect(self, market)
        self.add_item(self.girl_select)
        self.add_item(self.job_select)
        self._apply_state(player, market)

    @staticmethod
    def _training_focus_display(focus_type: Optional[str], focus_value: Optional[str]) -> tuple[str, str]:
        focus_kind = (focus_type or "any").lower()
        if focus_kind == "main" and focus_value:
            icon = SKILL_ICONS.get(focus_value, EMOJI_SKILL)
            return icon, focus_value
        if focus_kind == "sub" and focus_value:
            icon = SUB_SKILL_ICONS.get(focus_value, EMOJI_SUBSKILL)
            return icon, focus_value.title()
        return EMOJI_SPARK, "General"

    @staticmethod
    def _training_matches_job(focus_type: Optional[str], focus_value: Optional[str], job) -> bool:
        kind = (focus_type or "any").lower()
        if kind == "any":
            return True
        if kind == "main":
            return bool(focus_value) and focus_value.lower() == job.demand_main.lower()
        if kind == "sub":
            sub_name = getattr(job, "demand_sub", "") or ""
            return bool(focus_value) and sub_name and focus_value.lower() == sub_name.lower()
        return False

    def _apply_state(self, player=None, market=None):
        if player is not None:
            self._player_cache = player
        if market is not None:
            self._market_cache = market

        player = self._player_cache
        market = self._market_cache

        brothel = player.ensure_brothel() if player else None

        if player and self.selected_girl_uid and not player.get_girl(self.selected_girl_uid):
            self.selected_girl_uid = None
        if market and self.selected_job_id and not any(j.job_id == self.selected_job_id for j in market.jobs):
            self.selected_job_id = None

        self.girl_select.options = self._build_girl_options(player, brothel)
        self.girl_select.disabled = not (player and player.girls)

        self.job_select.options = self._build_job_options(market)
        no_jobs = not (market and market.jobs)
        self.job_select.disabled = no_jobs
        if no_jobs:
            self.selected_job_id = None

        self._update_controls(player, brothel)

    def _update_controls(self, player=None, brothel=None):
        can_work = (
            self.selected_girl_uid is not None
            and self.selected_job_id is not None
            and self._market_cache
            and any(j.job_id == self.selected_job_id for j in self._market_cache.jobs)
        )
        in_training = False
        if brothel and self.selected_girl_uid:
            in_training = brothel.training_for(self.selected_girl_uid) is not None
        self.work_btn.disabled = (not can_work) or in_training

    def _build_girl_options(self, player, brothel) -> list[discord.SelectOption]:
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
            option_label = f"{g.name} ({g.uid})"
            lust_ratio = g.lust / g.lust_max if g.lust_max else 0.0
            mood = lust_state_label(lust_ratio)
            mood_icon = lust_state_icon(lust_ratio)
            base_desc = (
                f"{mood_icon} {EMOJI_HEART} {g.health}/{g.health_max} • "
                f"{EMOJI_ENERGY} {g.stamina}/{g.stamina_max} • "
                f"{EMOJI_LUST} {g.lust}/{g.lust_max} [{mood}]"
            )
            desc = base_desc
            emoji = EMOJI_GIRL
            if brothel and brothel.training_for(g.uid):
                desc = f"📘 Training • {base_desc}"
                emoji = "📘"
            elif g.mentorship_bonus > 0:
                icon, focus_label = self._training_focus_display(
                    g.mentorship_focus_type, g.mentorship_focus
                )
                mentorship_text = (
                    f"📈 {icon} {focus_label} +{int(g.mentorship_bonus * 100)}%"
                )
                desc = f"{option_label} • {mentorship_text} • {base_desc}"
            options.append(
                discord.SelectOption(
                    label=option_label[:100],
                    value=g.uid,
                    description=desc[:100],
                    default=g.uid == self.selected_girl_uid,
                    emoji=emoji,
                )
            )
        return options

    def _allocate_job_option_value(self, canonical: str, seen_values: set[str], idx: int) -> str:
        base_value = (canonical or f"J{idx}").strip() or f"J{idx}"
        max_len = 100
        trimmed = base_value[:max_len]
        if trimmed not in seen_values:
            seen_values.add(trimmed)
            return trimmed

        suffix = 2
        while True:
            suffix_text = f"-{suffix}"
            allowed = max_len - len(suffix_text)
            if allowed <= 0:
                candidate = suffix_text[-max_len:]
            else:
                candidate = f"{trimmed[:allowed]}{suffix_text}"
            if candidate not in seen_values:
                seen_values.add(candidate)
                return candidate
            suffix += 1

    def _build_job_options(self, market) -> list[discord.SelectOption]:
        options = [
            discord.SelectOption(
                label="— Select job —",
                value="none",
                default=self.selected_job_id is None,
            )
        ]
        self._job_value_to_id = {"none": None}
        if not market or not market.jobs:
            return options

        seen_normalized: set[str] = {"none"}
        seen_values: set[str] = {"none"}
        sanitized = False

        for idx, job in enumerate(market.jobs[:24], start=1):
            raw_id = getattr(job, "job_id", None)
            job_id = str(raw_id).strip() if raw_id is not None else ""
            base_id = job_id if job_id and job_id.lower() != "none" else f"J{idx}"
            base_id = base_id.strip() or f"J{idx}"

            candidate = base_id
            suffix = 2
            normalized = candidate.strip().casefold()
            while (
                not normalized
                or normalized == "none"
                or normalized in seen_normalized
            ):
                candidate = f"{base_id}-{suffix}"
                suffix += 1
                normalized = candidate.strip().casefold()

            if candidate != job_id:
                try:
                    job.job_id = candidate
                    sanitized = True
                except Exception:
                    pass
                if self.selected_job_id == job_id:
                    self.selected_job_id = candidate

            seen_normalized.add(normalized)

            option_value = self._allocate_job_option_value(candidate, seen_values, idx)
            self._job_value_to_id[option_value] = candidate

            sub_part = f" + {job.demand_sub} L{job.demand_sub_level}" if job.demand_sub else ""
            label = f"{candidate} • {job.demand_main} L{job.demand_level}{sub_part}"
            desc = f"Pay {job.pay} • Diff {job.difficulty}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=option_value,
                    description=desc[:100],
                    default=candidate == self.selected_job_id,
                )
            )

        if sanitized:
            try:
                save_market(market)
            except Exception:
                pass

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
        pl.renown = brothel.renown
        for g in pl.girls:
            g.normalize_skill_structs()
            g.apply_regen(brothel)
        save_player(pl)
        return pl

    def _load_market(self, force_refresh: bool = False):
        if force_refresh:
            return refresh_market_if_stale(self.user_id, max_age_sec=0, forced_level=self.forced_level)
        market = load_market(self.user_id)
        if not market:
            return refresh_market_if_stale(self.user_id, max_age_sec=0, forced_level=self.forced_level)
        if self.forced_level is not None and market.level != self.forced_level:
            return refresh_market_if_stale(self.user_id, max_age_sec=0, forced_level=self.forced_level)
        if time.time() - market.ts > 300:
            return refresh_market_if_stale(self.user_id, max_age_sec=0, forced_level=self.forced_level)
        return market

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
            girl_count = len(player.girls) if player else None
            overview, reserves = brothel_overview_lines(brothel, girl_count)
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

        girl_for_preview = girl
        for job in market.jobs:
            highlight = "⭐" if job.job_id == self.selected_job_id else "•"
            sub_part = f" + {job.demand_sub} L{job.demand_sub_level}" if job.demand_sub else ""
            field_name = f"{highlight} `{job.job_id}` • {job.demand_main} L{job.demand_level}{sub_part}"
            value_lines = [f"{EMOJI_COIN} Base pay: **{job.pay}** • Difficulty: {job.difficulty}"]

            if girl_for_preview:
                info = evaluate_job(girl_for_preview, job, brothel)
                if info["blocked_main"] or (job.demand_sub and info["blocked_sub"]):
                    value_lines.append("🚫 Preferences block this job.")
                elif info.get("training_blocked"):
                    value_lines.append("📘 Girl is in mentorship training.")
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
                        f"⚠️ Requires {info['stamina_cost']} stamina (current {girl_for_preview.stamina})."
                    )
                elif not info["lust_ok"]:
                    value_lines.append(
                        f"🔥 Needs {info['lust_cost']} lust (current {girl_for_preview.lust})."
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
                    bonus_ready = info.get("mentorship_bonus") or 0.0
                    if bonus_ready:
                        focus_type = info.get("mentorship_focus_type")
                        focus_value = info.get("mentorship_focus")
                        icon, label = self._training_focus_display(focus_type, focus_value)
                        matches = self._training_matches_job(focus_type, focus_value, job)
                        pct = int(bonus_ready * 100)
                        if matches:
                            value_lines.append(
                                f"📈 Mentorship boost ready: +{pct}% XP ({icon} {label})"
                            )
                        elif (focus_type or "").lower() != "any":
                            value_lines.append(
                                f"📘 Mentor focus: {icon} {label} (pick matching job to use boost)"
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
            diff_parts.append(f"🧼 {diff['cleanliness']:+}")
        if diff.get("morale"):
            diff_parts.append(f"😊 {diff['morale']:+}")
        if diff.get("renown"):
            diff_parts.append(f"📣 {diff['renown']:+}")
        if diff.get("upkeep"):
            diff_parts.append(f"{EMOJI_COIN} {diff['upkeep']:+}")
        if diff_parts:
            lines.append(f"{EMOJI_FACILITY} {' • '.join(diff_parts)}")

        bonus_used = result.get("training_bonus_used") or 0.0
        if bonus_used:
            icon, label = self._training_focus_display(
                result.get("training_bonus_focus_type"),
                result.get("training_bonus_focus"),
            )
            suffix = f" ({icon} {label})" if label else ""
            lines.append(
                f"📈 Mentorship applied: +{int(bonus_used * 100)}% XP{suffix}"
            )
        if result.get("renown_delta"):
            lines.append(f"📣 Renown {result['renown_delta']:+}")
        return lines

    class GirlSelect(discord.ui.Select):
        def __init__(self, outer: "MarketWorkView", player):
            self.outer = outer
            brothel = player.ensure_brothel() if player else None
            super().__init__(
                placeholder="Preview with girl...",
                options=outer._build_girl_options(player, brothel),
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
            if value == "none":
                self.outer.selected_job_id = None
            else:
                canonical = self.outer._job_value_to_id.get(value)
                self.outer.selected_job_id = canonical or value
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
