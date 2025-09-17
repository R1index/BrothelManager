"""Основной ког с игровыми командами."""

from __future__ import annotations

import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..game.embeds import build_brothel_embed
from ..game.utils import choice_value
from ..models import Player
from ..storage import (
    get_config,
    grant_starter_pack,
    iter_user_ids,
    load_player,
    refresh_market_if_stale,
    save_player,
)

BROTHEL_ALLOWED_ACTIONS = {"view", "upgrade", "maintain", "promote", "expand"}
MIN_TRAINING_SECONDS = 15 * 60


def normalize_brothel_action(action: app_commands.Choice[str] | None) -> str:
    raw = (choice_value(action, default="view") or "view").lower()
    if raw not in BROTHEL_ALLOWED_ACTIONS:
        return "view"
    return raw


class Core(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        cfg = get_config() or {}
        self.market_refresh_minutes = self._resolve_refresh_minutes(cfg)
        self.market_refresher.change_interval(minutes=self.market_refresh_minutes)
        self.market_refresher.start()

    def cog_unload(self) -> None:
        self.market_refresher.cancel()

    @staticmethod
    def _resolve_refresh_minutes(config: Optional[dict]) -> float:
        default = 5.0
        try:
            value = float(((config or {}).get("market") or {}).get("refresh_minutes", default))
            if value <= 0:
                return default
            return value
        except (TypeError, ValueError):
            return default

    @tasks.loop(minutes=5)
    async def market_refresher(self) -> None:
        try:
            for uid in iter_user_ids():
                refresh_market_if_stale(uid, max_age_sec=0)
        except Exception as exc:  # pragma: no cover - защитная ветка
            print(f"[market_refresher] {exc}")

    async def _send_response(
        self,
        interaction: discord.Interaction,
        *,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        ephemeral: bool = True,
    ) -> None:
        sender = interaction.response.send_message
        if interaction.response.is_done():
            sender = interaction.followup.send
        payload = {"ephemeral": ephemeral}
        if content is not None:
            payload["content"] = content
        if embed is not None:
            payload["embed"] = embed
        await sender(**payload)

    async def _brothel_view(self, interaction: discord.Interaction, player: Player) -> None:
        brothel = player.ensure_brothel()
        brothel.apply_decay()
        embed = build_brothel_embed(interaction.user.display_name, player, None)
        await self._send_response(interaction, embed=embed)

    @app_commands.command(name="brothel", description="Просмотр состояния борделя")
    async def brothel(
        self,
        interaction: discord.Interaction,
        action: Optional[app_commands.Choice[str]] = None,
        facility: Optional[app_commands.Choice[str]] = None,
        coins: int = 0,
    ) -> None:
        player = load_player(interaction.user.id)
        if player is None:
            player = grant_starter_pack(interaction.user.id)
        brothel_state = player.ensure_brothel()
        action_name = normalize_brothel_action(action)
        brothel_state.apply_decay()

        message = ""
        if action_name == "promote":
            if coins <= 0:
                message = "Укажите сумму инвестиций для рекламы."
            else:
                delta = brothel_state.promote(coins)
                player.renown = brothel_state.renown
                message = f"Реклама проведена, слава +{delta['renown']}"
        else:
            message = "Сводка обновлена."

        save_player(player)
        await self._send_response(interaction, content=message, embed=build_brothel_embed(interaction.user.display_name, player))

    # ------------------------------------------------------------------
    @app_commands.command(name="train", description="Управление тренировками")
    async def train(
        self,
        interaction: discord.Interaction,
        action: Optional[app_commands.Choice[str]] = None,
        mentor: Optional[app_commands.Choice[str]] = None,
        student: Optional[app_commands.Choice[str]] = None,
        focus_main: Optional[app_commands.Choice[str]] = None,
        focus_sub: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        player = load_player(interaction.user.id)
        if player is None:
            player = grant_starter_pack(interaction.user.id)
        brothel = player.ensure_brothel()
        brothel.apply_decay()
        action_name = (choice_value(action, "list") or "list").lower()
        if action_name == "list":
            if not brothel.training:
                await self._send_response(interaction, content="Нет активных тренировок.")
            else:
                lines = [
                    f"{assignment.mentor_uid} -> {assignment.student_uid}" for assignment in brothel.training
                ]
                await self._send_response(interaction, content="\n".join(lines))
            save_player(player)
            return
        if action_name == "finish" and student:
            await self._handle_train_finish(
                interaction,
                player,
                brothel,
                mentor=choice_value(mentor),
                student=choice_value(student),
            )
            return
        await self._send_response(interaction, content="Команда не распознана.")
        save_player(player)

    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_training_focus(
        focus_choice: Optional[app_commands.Choice[str]],
        main_choice: Optional[app_commands.Choice[str]],
        sub_choice: Optional[app_commands.Choice[str]],
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        main_value = choice_value(main_choice)
        sub_value = choice_value(sub_choice)
        if main_value and sub_value:
            return None, None, "Select either a main skill or a sub-skill, not both."
        if main_value:
            return "main", main_value, None
        if sub_value:
            return "sub", sub_value, None
        explicit = choice_value(focus_choice)
        if explicit:
            return explicit, None, None
        return None, None, None

    @staticmethod
    def _format_training_focus(focus_type: Optional[str], focus_name: Optional[str]) -> str:
        if focus_type == "main" and focus_name:
            return f"{focus_name.title()} (main skill)"
        if focus_type == "sub" and focus_name:
            return f"{focus_name.title()} (sub-skill)"
        return "general technique"

    @staticmethod
    def _calculate_training_bonus(assignment, mentor, student) -> float:
        duration = max(0, time.time() - assignment.since_ts)
        hours = duration / 3600.0
        mentor_factor = 0.05 + (getattr(mentor, "level", 1) + getattr(mentor, "vitality_level", 1)) * 0.01
        student_factor = 0.1 + getattr(student, "level", 1) * 0.02
        bonus = hours * (mentor_factor / student_factor)
        return max(0.0, min(0.75, bonus))

    async def _handle_train_finish(
        self,
        interaction: discord.Interaction,
        player: Player,
        brothel,
        *,
        mentor: Optional[str],
        student: Optional[str],
    ) -> None:
        assignment = brothel.training_for(student or "") if student else None
        if not assignment:
            await self._send_response(interaction, content="Тренировка не найдена.")
            save_player(player)
            return
        if time.time() - assignment.since_ts < MIN_TRAINING_SECONDS:
            await self._send_response(
                interaction,
                content="Session too short — training requires more time.",
            )
            save_player(player)
            return
        student_girl = player.get_girl(assignment.student_uid)
        mentor_girl = player.get_girl(assignment.mentor_uid)
        if not student_girl or not mentor_girl:
            brothel.stop_training(assignment.student_uid)
            await self._send_response(interaction, content="Участники тренировки не найдены.")
            save_player(player)
            return
        bonus = self._calculate_training_bonus(assignment, mentor_girl, student_girl)
        focus_type = assignment.focus_type
        focus = assignment.focus
        student_girl.grant_training_bonus(mentor_girl.uid, bonus, focus_type, focus)
        brothel.stop_training(student_girl.uid)
        save_player(player)
        await self._send_response(
            interaction,
            content=f"Тренировка завершена, бонус {bonus:.0%} ({self._format_training_focus(focus_type, focus)})",
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Core(bot))


__all__ = ["Core", "normalize_brothel_action", "setup"]
