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
    now_ts,
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


def brothel_overview_lines(brothel: BrothelState, girls_total: Optional[int] = None) -> Tuple[str, str]:
    """Return summary and reserves lines for a brothel."""

    occupancy = f"{girls_total}/{brothel.rooms}" if girls_total is not None else str(brothel.rooms)
    summary = (
        f"{EMOJI_ROOMS} {occupancy} • "
        f"{EMOJI_CLEAN} {brothel.cleanliness}/100 • "
        f"{EMOJI_MORALE} {brothel.morale}/100"
    )
    reserves = (
        f"{EMOJI_POPULARITY} Renown {brothel.renown} • "
        f"{EMOJI_COIN} Reserve {brothel.upkeep_pool}"
    )
    return summary, reserves


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
    overview, reserves = brothel_overview_lines(brothel, len(player.girls))
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

    training_lines = format_training_lines(brothel, player.girls)
    if training_lines:
        embed.add_field(name="Mentorship", value="\n".join(training_lines), inline=False)

    embed.add_field(
        name="Rooms",
        value=f"Expand: {EMOJI_COIN} {brothel.next_room_cost()} (progress {brothel.room_progress})",
        inline=False,
    )
    embed.set_footer(
        text=f"{EMOJI_COIN} Wallet {player.currency} • ⭐ Renown {player.renown}"
    )
    return embed


def format_training_lines(brothel: BrothelState, girls: Iterable[Girl]) -> list[str]:
    lookup = {g.uid: g for g in girls}
    lines: list[str] = []
    for assignment in brothel.training:
        mentor = lookup.get(assignment.mentor_uid)
        student = lookup.get(assignment.student_uid)
        if not mentor or not student:
            continue
        minutes = max(1, (now_ts() - assignment.since_ts) // 60)
        lines.append(f"📘 {mentor.name} → {student.name} ({minutes}m)")
    return lines


def _stat_progress_line(label: str, level: int, xp: int, length: int = 10) -> str:
    need = stat_xp_threshold(level)
    bar = make_bar(xp, need, length=length)
    return f"{label} L{level} [{bar}] {xp}/{need}"


def _format_skill_lines(
    skmap: dict,
    names: Iterable[str],
    prefs: dict,
    icons_map: dict[str, str],
) -> list[str]:
    lines: list[str] = []
    for name in names:
        lvl = get_level(skmap, name)
        xp = get_xp(skmap, name)
        need = skill_xp_threshold(lvl)
        bar = make_bar(xp, need, length=8)
        pref = preference_icon(prefs.get(name, "true"))
        icon = icons_map.get(name, "✨")
        progress = f"{xp}/{need}" if need else str(xp)
        lines.append(f"{pref}{icon} **{name}** L{lvl} [{bar}] {progress}")

    if not lines:
        lines.append("❌ No training yet.")

    return lines


def _profile_lines(girl: Girl, brothel: Optional[BrothelState] = None) -> list[str]:
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
    if brothel and brothel.training_for(girl.uid):
        entries.append("📘 In mentorship")
    if girl.mentorship_bonus > 0:
        entries.append(f"📈 Mentor boost +{int(girl.mentorship_bonus * 100)}%")
    if not entries:
        entries.append("❌ —")
    return entries


def build_girl_embed(girl: Girl, brothel: Optional[BrothelState] = None) -> Tuple[discord.Embed, Optional[str]]:
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
    girl.apply_regen(brothel)

    vit_line = _stat_progress_line(
        f"{EMOJI_STAT_VIT} Vitality", girl.vitality_level, girl.vitality_xp
    )
    end_line = _stat_progress_line(
        f"{EMOJI_STAT_END} Endurance", girl.endurance_level, girl.endurance_xp
    )
    lust_line = _stat_progress_line(
        f"{EMOJI_LUST} Mastery", girl.lust_level, girl.lust_xp
    )
    lust_ratio = girl.lust / girl.lust_max if girl.lust_max else 0.0
    mood = lust_state_label(lust_ratio)
    mood_icon = lust_state_icon(lust_ratio)

    hp_bar = make_bar(girl.health, girl.health_max, length=8)
    sta_bar = make_bar(girl.stamina, girl.stamina_max, length=8)
    lust_bar = make_bar(girl.lust, girl.lust_max, length=8)

    condition_lines = [
        f"{EMOJI_SPARK} Lv **{girl.level}** — EXP {girl.exp}",
        "",
        f"{EMOJI_HEART} HP **{girl.health}/{girl.health_max}** [{hp_bar}]",
        f"{EMOJI_ENERGY} STA **{girl.stamina}/{girl.stamina_max}** [{sta_bar}]",
        f"{mood_icon} {EMOJI_LUST} Lust **{girl.lust}/{girl.lust_max}** [{lust_bar}] {mood}",
        "",
        vit_line,
        end_line,
        lust_line,
    ]
    left_lines = [f"__{EMOJI_CONDITION} Condition__", *condition_lines]

    profile_lines = _profile_lines(girl, brothel)
    if profile_lines:
        left_lines.extend([EMBED_SPACER, f"__{EMOJI_PROFILE} Profile__", *profile_lines])

    embed.add_field(
        name=f"{EMOJI_CONDITION} Condition",
        value="\n".join(left_lines),
        inline=True,
    )

    main_skill_lines = _format_skill_lines(
        girl.skills,
        MAIN_SKILLS,
        girl.prefs_skills,
        SKILL_ICONS,
    )
    sub_skill_lines = _format_skill_lines(
        girl.subskills,
        SUB_SKILLS,
        girl.prefs_subskills,
        SUB_SKILL_ICONS,
    )

    right_lines = [f"__{EMOJI_SKILL} Skills__", *main_skill_lines]
    if sub_skill_lines:
        right_lines.extend(
            [EMBED_SPACER, f"__{EMOJI_SUBSKILL} Sub-skills__", *sub_skill_lines]
        )

    embed.add_field(
        name=f"{EMOJI_SKILL} Skills",
        value="\n".join(right_lines),
        inline=True,
    )

    embed.add_field(name=EMBED_SPACER, value=EMBED_SPACER, inline=True)

    return embed, image_path
