"""Embed builders and formatting helpers."""

from __future__ import annotations

import os
from typing import Iterable, Optional, Tuple

import discord

from ..assets_util import profile_image_path
from ..models import (
    BrothelState,
    Girl,
    MAIN_SKILLS,
    SUB_SKILLS,
    get_level,
    get_xp,
    make_bar,
    skill_xp_threshold,
    stat_xp_threshold,
)
from .constants import (
    EMBED_SPACER,
    EMOJI_BODY,
    EMOJI_CLEAN,
    EMOJI_CONDITION,
    EMOJI_DIMENSION,
    EMOJI_ENERGY,
    EMOJI_FACILITY,
    EMOJI_GIRL,
    EMOJI_HEART,
    EMOJI_LUST,
    EMOJI_MORALE,
    EMOJI_POPULARITY,
    EMOJI_PROFILE,
    EMOJI_ROOMS,
    EMOJI_SKILL,
    EMOJI_SPARK,
    EMOJI_STAT_END,
    EMOJI_STAT_VIT,
    EMOJI_SUBSKILL,
    EMOJI_TRAIT,
    EMOJI_COIN,
    FACILITY_INFO,
    SKILL_ICONS,
    SUB_SKILL_ICONS,
)
from .utils import lust_state_icon, lust_state_label, preference_icon


def brothel_overview_lines(brothel: BrothelState) -> Tuple[str, str]:
    """Return summary and reserves lines for a brothel."""

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


def brothel_facility_lines(brothel: BrothelState) -> list[str]:
    """Detailed facility progression lines."""

    lines: list[str] = []
    for key in ("comfort", "hygiene", "security", "allure"):
        icon, label = FACILITY_INFO[key]
        lvl, xp, need = brothel.facility_progress(key)
        bar = make_bar(xp, need, length=8)
        lines.append(f"{icon} {label} L{lvl} [{bar}] {xp}/{need}")
    return lines


def build_brothel_embed(
    user_name: str,
    player,
    notes: Optional[Iterable[str]] = None,
) -> discord.Embed:
    """Compose a brothel overview embed for the given player."""

    brothel = player.ensure_brothel()
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
    embed.add_field(
        name="Facilities",
        value="\n".join(brothel_facility_lines(brothel)),
        inline=False,
    )
    embed.set_footer(
        text=f"{EMOJI_COIN} Wallet {player.currency} • ⭐ Rep {player.reputation}"
    )
    return embed


def _stat_progress_line(label: str, level: int, xp: int, length: int = 10) -> str:
    need = stat_xp_threshold(level)
    bar = make_bar(xp, need, length=length)
    return f"{label} L{level} [{bar}] {xp}/{need}"


def _format_skill_lines(
    skmap: dict,
    names: Iterable[str],
    prefs: dict,
    header: str,
    icons_map: dict[str, str],
) -> str:
    entries: list[str] = []
    for name in names:
        lvl = get_level(skmap, name)
        xp = get_xp(skmap, name)
        need = skill_xp_threshold(lvl)
        bar = make_bar(xp, need, length=8)
        pref = preference_icon(prefs.get(name, "true"))
        icon = icons_map.get(name, "✨")
        progress = f"{xp}/{need}" if need else str(xp)
        entries.append(f"{pref}{icon} **{name}** L{lvl} [{bar}] {progress}")

    if not entries:
        entries = ["❌ No training yet."]

    lines: list[str] = []
    if header:
        lines.append(f"*{header}*")
        lines.append(EMBED_SPACER)
    lines.extend(entries)
    return "\n".join(lines)


def _profile_lines(girl: Girl) -> list[str]:
    entries: list[str] = []
    if girl.body_shape:
        entries.append(f"{EMOJI_BODY} Shape: {girl.body_shape}")
    if girl.breast_size:
        entries.append(f"{EMOJI_DIMENSION} Bust: {girl.breast_size}")
    if girl.height_cm or girl.weight_kg:
        hw: list[str] = []
        if girl.height_cm:
            hw.append(f"{girl.height_cm} cm")
        if girl.weight_kg:
            hw.append(f"{girl.weight_kg} kg")
        entries.append(f"📏 {' / '.join(hw)}")
    if girl.age:
        entries.append(f"🎂 Age: {girl.age}")
    if girl.traits:
        entries.append(f"{EMOJI_TRAIT} Traits: {', '.join(girl.traits)}")
    if girl.pregnant:
        pts = girl.pregnancy_progress_points()
        bar = make_bar(pts, girl.pregnancy_total_points(), length=10)
        entries.append(f"🤰 Pregnant {pts}/{girl.pregnancy_total_points()} {bar}")
    else:
        entries.append("👶 Not pregnant")
    if not entries:
        entries.append("❌ —")
    return entries


def build_girl_embed(girl: Girl) -> Tuple[discord.Embed, Optional[str]]:
    """Render a girl's profile embed and optional local image path."""

    embed = discord.Embed(
        title=f"{EMOJI_GIRL} {girl.name} [{girl.rarity}] • `{girl.uid}`",
        color=0x9CA3AF,
    )

    image_path = profile_image_path(girl.name, girl.base_id)
    if image_path:
        embed.set_image(url=f"attachment://{os.path.basename(image_path)}")
    else:
        embed.set_image(url=girl.image_url)

    girl.normalize_skill_structs()
    girl.apply_regen()

    vit_line = _stat_progress_line(f"{EMOJI_STAT_VIT} Vitality", girl.vitality_level, girl.vitality_xp)
    end_line = _stat_progress_line(f"{EMOJI_STAT_END} Endurance", girl.endurance_level, girl.endurance_xp)
    lust_line = _stat_progress_line(f"{EMOJI_LUST} Mastery", girl.lust_level, girl.lust_xp)
    lust_ratio = girl.lust / girl.lust_max if girl.lust_max else 0.0
    mood = lust_state_label(lust_ratio)
    mood_icon = lust_state_icon(lust_ratio)

    condition_lines = [
        f"{EMOJI_SPARK} Lv **{girl.level}** — EXP {girl.exp}",
        "",
        f"{EMOJI_HEART} HP **{girl.health}/{girl.health_max}**",
        f"{EMOJI_ENERGY} STA **{girl.stamina}/{girl.stamina_max}**",
        f"{mood_icon} {EMOJI_LUST} Lust **{girl.lust}/{girl.lust_max}** • {mood}",
        "",
        vit_line,
        end_line,
        lust_line,
    ]
    embed.add_field(
        name=f"{EMOJI_CONDITION} Condition",
        value="\n".join(condition_lines),
        inline=True,
    )

    embed.add_field(name=EMBED_SPACER, value=EMBED_SPACER, inline=True)

    main_skills = _format_skill_lines(
        girl.skills,
        MAIN_SKILLS,
        girl.prefs_skills,
        "Attributes",
        SKILL_ICONS,
    )
    embed.add_field(
        name=f"{EMOJI_SKILL} Skills",
        value=main_skills,
        inline=True,
    )

    embed.add_field(name=EMBED_SPACER, value=EMBED_SPACER, inline=True)

    sub_skills = _format_skill_lines(
        girl.subskills,
        SUB_SKILLS,
        girl.prefs_subskills,
        "Techniques",
        SUB_SKILL_ICONS,
    )
    embed.add_field(
        name=f"{EMOJI_SUBSKILL} Sub-skills",
        value=sub_skills,
        inline=True,
    )

    embed.add_field(name=EMBED_SPACER, value=EMBED_SPACER, inline=True)

    profile_section = "\n".join(_profile_lines(girl))
    embed.add_field(
        name=f"{EMOJI_PROFILE} Profile",
        value=profile_section,
        inline=True,
    )

    return embed, image_path
