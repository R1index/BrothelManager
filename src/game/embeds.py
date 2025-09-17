"""Формирование Discord Embed."""

from __future__ import annotations

import discord

from ..models import BrothelState, Girl, Player, make_bar
from .constants import (
    EMOJI_ALLURE,
    EMOJI_CLEAN,
    EMOJI_COMFORT,
    EMOJI_COIN,
    EMOJI_GIRL,
    EMOJI_HEART,
    EMOJI_LUST,
    EMOJI_MARKET,
    EMOJI_MORALE,
    EMOJI_PROFILE,
    EMOJI_ROOMS,
    EMOJI_SECURITY,
    EMOJI_SPARK,
    EMOJI_STAT_END,
)


def brothel_overview_lines(player: Player, brothel: BrothelState) -> list[str]:
    return [
        f"{EMOJI_COIN} Монеты: **{player.currency}**",
        f"{EMOJI_ROOMS} Комнаты: **{brothel.rooms}** (свободно {brothel.rooms_free(len(player.girls))})",
        f"{EMOJI_MORALE} Мораль: **{brothel.morale}%**",
        f"{EMOJI_CLEAN} Чистота: **{brothel.cleanliness}%**",
    ]


def brothel_facility_lines(brothel: BrothelState) -> list[str]:
    return [
        f"{EMOJI_COMFORT} Комфорт: **{brothel.comfort_level}**",
        f"{EMOJI_SECURITY} Безопасность: **{brothel.security_level}**",
        f"{EMOJI_ALLURE} Привлекательность: **{brothel.allure_level}**",
        f"{EMOJI_MARKET} Гигиена: **{brothel.hygiene_level}**",
    ]


def format_training_lines(brothel: BrothelState, player: Player) -> list[str]:
    lines: list[str] = []
    for assignment in brothel.training:
        mentor = player.get_girl(assignment.mentor_uid)
        student = player.get_girl(assignment.student_uid)
        if not mentor or not student:
            continue
        focus = "общая подготовка"
        if assignment.focus_type == "main" and assignment.focus:
            focus = f"главный навык **{assignment.focus}**"
        elif assignment.focus_type == "sub" and assignment.focus:
            focus = f"саб-скилл **{assignment.focus}**"
        lines.append(
            f"{EMOJI_SPARK} {mentor.name} обучает {student.name} — {focus}"
        )
    return lines or ["Нет активных тренировок"]


def build_brothel_embed(user_name: str, player: Player, notes: list[str] | None = None) -> discord.Embed:
    brothel = player.ensure_brothel()
    embed = discord.Embed(title=f"{EMOJI_PROFILE} Профиль {user_name}")
    embed.add_field(name="Обзор", value="\n".join(brothel_overview_lines(player, brothel)), inline=False)
    embed.add_field(name="Инфраструктура", value="\n".join(brothel_facility_lines(brothel)), inline=False)
    embed.add_field(name="Наставничество", value="\n".join(format_training_lines(brothel, player)), inline=False)
    if notes:
        embed.add_field(name="Советы", value="\n".join(notes), inline=False)
    return embed


def build_girl_embed(girl: Girl) -> discord.Embed:
    embed = discord.Embed(title=f"{EMOJI_GIRL} {girl.name}")
    embed.add_field(
        name="Уровень",
        value=f"{girl.level} ({make_bar(girl.exp, 100)})",
        inline=True,
    )
    embed.add_field(name="Здоровье", value=f"{EMOJI_HEART} {girl.health}/{girl.health_max}", inline=True)
    embed.add_field(name="Выносливость", value=f"{EMOJI_STAT_END} {girl.stamina}/{girl.stamina_max}", inline=True)
    embed.add_field(name="Страсть", value=f"{EMOJI_LUST} {girl.lust}/{girl.lust_max}", inline=True)
    return embed


__all__ = [
    "build_brothel_embed",
    "build_girl_embed",
    "brothel_overview_lines",
    "brothel_facility_lines",
    "format_training_lines",
]
