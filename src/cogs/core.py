"""Игровой ког с минимально необходимой функциональностью."""
from __future__ import annotations

import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..models import BrothelState, Player
from ..storage import get_config, iter_user_ids, load_player, refresh_market_if_stale, save_player

BROTHEL_ALLOWED_ACTIONS = {"view", "upgrade", "maintain", "promote", "expand"}
MIN_TRAINING_SECONDS = 15 * 60


def normalize_brothel_action(action: Optional[app_commands.Choice[str]]) -> str:
    value = getattr(action, "value", None)
    if not value:
        return "view"
    normalized = str(value).lower()
    return normalized if normalized in BROTHEL_ALLOWED_ACTIONS else "view"


class Core(commands.Cog):
    """Облегчённый ког с логикой, покрытой тестами."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        config = get_config()
        self.market_refresh_minutes = self._resolve_refresh_minutes(config)
        self.market_refresher.change_interval(minutes=self.market_refresh_minutes)
        self.market_refresher.start()

    def cog_unload(self) -> None:
        self.market_refresher.cancel()

    @tasks.loop(minutes=5)
    async def market_refresher(self) -> None:
        try:
            for uid in iter_user_ids():
                refresh_market_if_stale(uid, max_age_sec=0)
        except Exception as exc:  # pragma: no cover - защитная мера
            print("[market_refresher]", exc)

    @staticmethod
    def _resolve_refresh_minutes(config: Optional[dict]) -> float:
        default = 5.0
        if not isinstance(config, dict):
            return default
        market_cfg = config.get("market")
        if not isinstance(market_cfg, dict):
            return default
        try:
            minutes = float(market_cfg.get("refresh_minutes", default))
        except (TypeError, ValueError):
            return default
        return minutes if minutes > 0 else default

    async def _send_response(
        self,
        interaction: discord.Interaction,
        *,
        content: str,
        ephemeral: bool = True,
    ) -> None:
        sender = interaction.response.send_message
        if interaction.response.is_done():
            sender = interaction.followup.send
        await sender(content=content, ephemeral=ephemeral)

    # ------------------------- Slash-команды -------------------------
    @app_commands.command(name="brothel")
    async def brothel(
        self,
        interaction: discord.Interaction,
        action: Optional[app_commands.Choice[str]] = None,
        facility: Optional[app_commands.Choice[str]] = None,
        coins: int = 0,
    ) -> None:
        player = load_player(interaction.user.id) or Player(user_id=interaction.user.id)
        brothel_state = player.ensure_brothel()
        brothel_state.apply_decay()
        action_name = normalize_brothel_action(action)
        message = "Состояние борделя обновлено."
        if action_name == "promote":
            result = brothel_state.promote(max(0, coins))
            gained = 0
            if isinstance(result, dict):
                try:
                    gained = int(result.get("renown", 0))
                except (TypeError, ValueError):
                    gained = 0
            if gained > 0:
                player.renown = brothel_state.renown
                message = f"Слава выросла на {gained} очков."
            else:
                message = "Недостаточно вложений для роста славы."
        save_player(player)
        await self._send_response(interaction, content=message)

    @app_commands.command(name="train")
    async def train(
        self,
        interaction: discord.Interaction,
        action: Optional[app_commands.Choice[str]] = None,
        mentor: Optional[str] = None,
        student: Optional[str] = None,
    ) -> None:
        player = load_player(interaction.user.id) or Player(user_id=interaction.user.id)
        brothel_state = player.ensure_brothel()
        brothel_state.apply_decay()
        action_name = (getattr(action, "value", "") or "").lower()
        if action_name == "list":
            assignments = brothel_state.training
            if not assignments:
                message = "Сейчас нет активных тренировок."
            else:
                message = "\n".join(
                    f"{a.student_uid} тренируется с {a.mentor_uid}" for a in assignments
                )
            save_player(player)
            await self._send_response(interaction, content=message)
            return
        await self._handle_train_finish(interaction, player, brothel_state, mentor, student)

    # ------------------------- Тренировочная логика -------------------------
    @staticmethod
    def _resolve_training_focus(
        current: Optional[tuple[str, str]],
        main_choice: Optional[app_commands.Choice[str]],
        sub_choice: Optional[app_commands.Choice[str]],
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        if main_choice and sub_choice:
            return None, None, "Select either a main skill or a sub-skill, not both."
        if main_choice:
            return "main", str(main_choice.value), None
        if sub_choice:
            return "sub", str(sub_choice.value), None
        if current:
            return current[0], current[1], None
        return None, None, None

    @staticmethod
    def _format_training_focus(focus_type: Optional[str], focus: Optional[str]) -> str:
        if not focus_type or not focus:
            return "general technique"
        label = focus.capitalize()
        if focus_type == "sub":
            label = focus.capitalize().replace("_", " ") + " (sub-skill)"
        elif focus_type == "main":
            label = focus.capitalize()
        return label

    @staticmethod
    def _calculate_training_bonus(assignment, mentor, student) -> float:
        elapsed = max(0.0, time.time() - getattr(assignment, "since_ts", time.time()))
        base = 0.02
        mentor_level = getattr(mentor, "level", 1)
        student_level = getattr(student, "level", 1)
        base += max(0, mentor_level - student_level) * 0.01
        vitality_gap = getattr(mentor, "vitality_level", 1) - getattr(student, "vitality_level", 1)
        base += max(0, vitality_gap) * 0.005
        skill_values = list(getattr(mentor, "skills", {}).values())
        if skill_values:
            base += sum(max(0, node.get("level", 0) - getattr(student, "skills", {}).get(name, {"level": 0}).get("level", 0))
                        for name, node in getattr(mentor, "skills", {}).items()) * 0.002
        time_factor = min(3.0, elapsed / MIN_TRAINING_SECONDS)
        return max(0.0, round(base * time_factor, 4))

    async def _handle_train_finish(
        self,
        interaction: discord.Interaction,
        player: Player,
        brothel: BrothelState,
        mentor: Optional[str],
        student: Optional[str],
    ) -> None:
        assignment = brothel.training_for(student)
        if assignment is None:
            save_player(player)
            await self._send_response(interaction, content="Активная тренировка не найдена.")
            return
        elapsed = time.time() - assignment.since_ts
        if elapsed < MIN_TRAINING_SECONDS:
            save_player(player)
            await self._send_response(
                interaction,
                content="Training session is too short for any benefits.",
            )
            return
        mentor_girl = player.get_girl(assignment.mentor_uid) if hasattr(player, "get_girl") else None
        student_girl = player.get_girl(assignment.student_uid) if hasattr(player, "get_girl") else None
        if mentor_girl is None or student_girl is None:
            save_player(player)
            await self._send_response(interaction, content="Девушки не найдены.")
            return
        bonus = self._calculate_training_bonus(assignment, mentor_girl, student_girl)
        student_girl.grant_training_bonus(assignment.mentor_uid, bonus, assignment.focus_type, assignment.focus)
        brothel.stop_training(assignment.student_uid)
        save_player(player)
        focus_label = self._format_training_focus(assignment.focus_type, assignment.focus)
        await self._send_response(
            interaction,
            content=f"Сессия завершена, бонус {bonus:.0%} к {focus_label}.",
        )

