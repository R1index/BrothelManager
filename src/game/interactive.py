"""Interactive Discord view components used by core commands."""

from __future__ import annotations

import math
from typing import Callable, Iterable, Optional

import discord

from ..models import MAIN_SKILLS, SUB_SKILLS
from .constants import (
    EMOJI_COIN,
    EMOJI_GIRL,
    EMOJI_SKILL,
    EMOJI_SUBSKILL,
    FACILITY_INFO,
)


BrothelActionCallback = Callable[[str, Optional[str], int], tuple[Optional[Iterable[str]], Optional[str]]]
BrothelEmbedBuilder = Callable[[Optional[Iterable[str]]], discord.Embed]

TrainingAssignCallback = Callable[[Optional[str], Optional[str], Optional[str], Optional[str]], tuple[Optional[str], Optional[str]]]
TrainingFinishCallback = Callable[[Optional[str]], tuple[Optional[str], Optional[str]]]
TrainingStatusCallback = Callable[[], list[str]]


class BrothelManageView(discord.ui.View):
    """Interactive view for managing brothel facilities."""

    ACTION_INFO = {
        "view": ("View status", "📊"),
        "upgrade": ("Upgrade facility", "⬆️"),
        "maintain": ("Maintain cleanliness", "🧽"),
        "promote": ("Promote services", "📣"),
        "expand": ("Expand rooms", "🏗️"),
    }

    PAGES = ("Overview", "Facilities")

    def __init__(
        self,
        *,
        invoker_id: int,
        user_name: str,
        player,
        brothel,
        build_overview_embed: BrothelEmbedBuilder,
        build_facilities_embed: BrothelEmbedBuilder,
        execute_action: BrothelActionCallback,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.invoker_id = invoker_id
        self.user_name = user_name
        self.player = player
        self.brothel = brothel
        self._build_overview_embed = build_overview_embed
        self._build_facilities_embed = build_facilities_embed
        self._execute_action = execute_action

        self.page_index = 0
        self.current_action = "view"
        self.selected_facility: str | None = None
        self.invest_amount = 0
        self.last_notes: list[str] = []
        self.message: discord.Message | None = None

        self.action_select = self.ActionSelect(self)
        self.action_select.row = 0
        self.facility_select = self.FacilitySelect(self)
        self.facility_select.row = 0
        self.add_item(self.action_select)
        self.add_item(self.facility_select)

        self._update_components()

    async def send(self, interaction: discord.Interaction) -> None:
        embed = self._build_embed()
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
        try:
            self.message = await interaction.original_response()
        except discord.HTTPException:
            self.message = None

    def disable_all_items(self) -> None:
        for child in self.children:
            child.disabled = True

    async def on_timeout(self) -> None:
        self.disable_all_items()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def _ensure_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            sender = (
                interaction.response.send_message
                if not interaction.response.is_done()
                else interaction.followup.send
            )

            async def _notify() -> None:
                await sender("This view belongs to another player.", ephemeral=True)

            interaction.client.loop.create_task(_notify())
            return False
        return True

    def _update_components(self) -> None:
        self.facility_select.disabled = self.current_action != "upgrade"
        page_label = self.PAGES[self.page_index]
        self.facility_select.placeholder = (
            f"Facility ({page_label})"
            if self.current_action == "upgrade"
            else "Facility"
        )
        self.reset_button.disabled = self.invest_amount <= 0
        self.page_prev.disabled = self.page_index <= 0
        self.page_next.disabled = self.page_index >= len(self.PAGES) - 1
        self.execute_button.label = f"Apply ({self.invest_amount} coins)"

    def _pending_action_lines(self) -> list[str]:
        action_label, _ = self.ACTION_INFO.get(
            self.current_action,
            (self.current_action.title(), ""),
        )
        lines = [f"Action: **{action_label}**"]
        if self.current_action == "upgrade":
            if self.selected_facility:
                icon, label = FACILITY_INFO[self.selected_facility]
                lines.append(f"Facility: {icon} {label}")
            else:
                lines.append("Facility: —")
        if self.current_action != "view":
            if self.invest_amount > 0:
                lines.append(f"{EMOJI_COIN} Invest: {self.invest_amount}")
            else:
                lines.append(f"{EMOJI_COIN} Invest: —")
        return lines

    def _build_embed(self) -> discord.Embed:
        notes = self.last_notes or None
        if self.page_index == 0:
            embed = self._build_overview_embed(notes)
        else:
            embed = self._build_facilities_embed(notes)

        pending_lines = self._pending_action_lines()
        if pending_lines:
            embed.add_field(
                name="Pending action",
                value="\n".join(pending_lines),
                inline=False,
            )
        return embed

    async def _refresh(
        self,
        interaction: discord.Interaction,
        *,
        update_embed: bool,
    ) -> None:
        self._update_components()
        if update_embed:
            embed = self._build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)

    class ActionSelect(discord.ui.Select):
        def __init__(self, view: "BrothelManageView") -> None:
            options = [
                discord.SelectOption(
                    label=label,
                    value=key,
                    emoji=emoji,
                    default=key == "view",
                )
                for key, (label, emoji) in view.ACTION_INFO.items()
            ]
            super().__init__(
                placeholder="Choose action",
                min_values=1,
                max_values=1,
                options=options,
            )
            self._parent = view

        async def callback(self, interaction: discord.Interaction) -> None:
            parent = self._parent
            if not parent._ensure_owner(interaction):
                return
            parent.current_action = self.values[0]
            if parent.current_action != "upgrade":
                parent.selected_facility = None
            await parent._refresh(interaction, update_embed=True)

    class FacilitySelect(discord.ui.Select):
        def __init__(self, view: "BrothelManageView") -> None:
            options = [
                discord.SelectOption(
                    label=label,
                    value=key,
                    emoji=icon,
                )
                for key, (icon, label) in FACILITY_INFO.items()
            ]
            super().__init__(
                placeholder="Select facility",
                min_values=1,
                max_values=1,
                options=options,
            )
            self._parent = view

        async def callback(self, interaction: discord.Interaction) -> None:
            parent = self._parent
            if not parent._ensure_owner(interaction):
                return
            parent.selected_facility = self.values[0]
            await parent._refresh(interaction, update_embed=False)

    @discord.ui.button(label="+50", style=discord.ButtonStyle.secondary, row=1)
    async def add_50(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        self.invest_amount = min(self.player.currency, self.invest_amount + 50)
        await self._refresh(interaction, update_embed=True)

    @discord.ui.button(label="+100", style=discord.ButtonStyle.secondary, row=1)
    async def add_100(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        self.invest_amount = min(self.player.currency, self.invest_amount + 100)
        await self._refresh(interaction, update_embed=True)

    @discord.ui.button(label="+500", style=discord.ButtonStyle.secondary, row=1)
    async def add_500(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        self.invest_amount = min(self.player.currency, self.invest_amount + 500)
        await self._refresh(interaction, update_embed=True)

    @discord.ui.button(label="Reset", style=discord.ButtonStyle.secondary, row=1)
    async def reset_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        self.invest_amount = 0
        await self._refresh(interaction, update_embed=True)

    @discord.ui.button(label="◀ Page", style=discord.ButtonStyle.secondary, row=2)
    async def page_prev(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        if self.page_index > 0:
            self.page_index -= 1
        await self._refresh(interaction, update_embed=True)

    @discord.ui.button(label="Page ▶", style=discord.ButtonStyle.secondary, row=2)
    async def page_next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        if self.page_index < len(self.PAGES) - 1:
            self.page_index += 1
        await self._refresh(interaction, update_embed=True)

    @discord.ui.button(label="Apply", style=discord.ButtonStyle.success, row=2)
    async def execute_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return

        action = self.current_action
        facility = self.selected_facility if action == "upgrade" else None
        invest = self.invest_amount

        notes, error = self._execute_action(action, facility, invest)

        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        if notes is not None:
            self.last_notes = list(notes)
        if action != "view":
            self.invest_amount = 0
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)


class TrainingManageView(discord.ui.View):
    """Interactive view for managing mentorship assignments."""

    PAGE_TITLES = ("Mentorship", "Roster")
    ROSTER_PAGE_SIZE = 6
    SELECT_PAGE_SIZE = 25

    def __init__(
        self,
        *,
        invoker_id: int,
        user_name: str,
        player,
        brothel,
        list_status: TrainingStatusCallback,
        assign_training: TrainingAssignCallback,
        finish_training: TrainingFinishCallback,
        timeout: float = 240.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.invoker_id = invoker_id
        self.user_name = user_name
        self.player = player
        self.brothel = brothel
        self._list_status = list_status
        self._assign_training = assign_training
        self._finish_training = finish_training

        self.girls = sorted(player.girls, key=lambda g: g.name.lower())
        self.page_index = 0
        self.roster_page = 0
        self.mentor_page = 0
        self.student_page = 0
        self.current_action = "list"
        self.mentor_uid: str | None = None
        self.student_uid: str | None = None
        self.focus_type: str | None = None
        self.focus_value: str | None = None
        self.last_message: str | None = None
        self.message: discord.Message | None = None

        self.action_select = self.ActionSelect(self)
        self.action_select.row = 0
        self.add_item(self.action_select)

        self.mentor_select = self.GirlSelect(self, role="mentor")
        self.mentor_select.row = 1
        self.add_item(self.mentor_select)

        self.student_select = self.GirlSelect(self, role="student")
        self.student_select.row = 2
        self.add_item(self.student_select)

        self.focus_type_select = self.FocusTypeSelect(self)
        self.focus_type_select.row = 3
        self.add_item(self.focus_type_select)

        self.main_skill_select = self.MainSkillSelect(self)
        self.main_skill_select.row = 3
        self.add_item(self.main_skill_select)

        self.sub_skill_select = self.SubSkillSelect(self)
        self.sub_skill_select.row = 3
        self.add_item(self.sub_skill_select)

        self._update_components()

    async def send(self, interaction: discord.Interaction) -> None:
        embed = self._build_embed()
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
        try:
            self.message = await interaction.original_response()
        except discord.HTTPException:
            self.message = None

    def disable_all_items(self) -> None:
        for child in self.children:
            child.disabled = True

    async def on_timeout(self) -> None:
        self.disable_all_items()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def _ensure_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            sender = (
                interaction.response.send_message
                if not interaction.response.is_done()
                else interaction.followup.send
            )

            async def _notify() -> None:
                await sender("This view belongs to another player.", ephemeral=True)

            interaction.client.loop.create_task(_notify())
            return False
        return True

    def _page_count(self) -> int:
        return max(1, math.ceil(max(len(self.girls), 1) / self.SELECT_PAGE_SIZE))

    @property
    def total_roster_pages(self) -> int:
        return max(1, math.ceil(max(len(self.girls), 1) / self.ROSTER_PAGE_SIZE))

    def _update_components(self) -> None:
        has_girls = bool(self.girls)
        for select in (self.mentor_select, self.student_select):
            select.disabled = not has_girls

        focus_type = (self.focus_type or "").lower()
        self.main_skill_select.disabled = self.current_action != "assign" or focus_type != "main"
        self.sub_skill_select.disabled = self.current_action != "assign" or focus_type != "sub"

        total_pages = self._page_count()
        self.mentor_prev.disabled = self.mentor_page <= 0
        self.mentor_next.disabled = self.mentor_page >= total_pages - 1
        self.student_prev.disabled = self.student_page <= 0
        self.student_next.disabled = self.student_page >= total_pages - 1

        self.page_prev.disabled = self.page_index <= 0
        self.page_next.disabled = self.page_index >= len(self.PAGE_TITLES) - 1
        self.roster_prev.disabled = self.page_index != 1 or self.roster_page <= 0
        self.roster_next.disabled = self.page_index != 1 or self.roster_page >= self.total_roster_pages - 1

        self.execute_button.label = (
            "Apply" if self.current_action != "list" else "Refresh"
        )

        self._refresh_girl_selects()

    def _refresh_girl_selects(self) -> None:
        mentor_options = self._build_girl_options(self.mentor_page, selected=self.mentor_uid)
        student_options = self._build_girl_options(self.student_page, selected=self.student_uid)

        if mentor_options:
            self.mentor_select.options = mentor_options
            total = self._page_count()
            self.mentor_select.placeholder = f"Mentor (page {self.mentor_page + 1}/{total})"
        else:
            self.mentor_select.options = [
                discord.SelectOption(label="No girls", value="none")
            ]
            self.mentor_select.placeholder = "No mentors"

        if student_options:
            total = self._page_count()
            self.student_select.options = student_options
            self.student_select.placeholder = f"Student (page {self.student_page + 1}/{total})"
        else:
            self.student_select.options = [
                discord.SelectOption(label="No girls", value="none")
            ]
            self.student_select.placeholder = "No students"

    def _build_girl_options(
        self,
        page_index: int,
        *,
        selected: Optional[str],
    ) -> list[discord.SelectOption]:
        if not self.girls:
            return []
        start = page_index * self.SELECT_PAGE_SIZE
        end = start + self.SELECT_PAGE_SIZE
        options: list[discord.SelectOption] = []
        for girl in self.girls[start:end]:
            in_training = bool(self.brothel.training_for(girl.uid))
            label = f"{girl.name} Lv{girl.level}"
            desc_parts = [f"{girl.rarity}", f"UID {girl.uid}"]
            if in_training:
                desc_parts.append("Training")
            options.append(
                discord.SelectOption(
                    label=label,
                    value=girl.uid,
                    description=" • ".join(desc_parts),
                    default=girl.uid == selected,
                )
            )
        return options

    def _build_embed(self) -> discord.Embed:
        if self.page_index == 0:
            lines = self._list_status()
            embed = discord.Embed(
                title=f"📘 {self.user_name}'s Mentorships",
                color=0x60A5FA,
            )
            embed.description = "\n".join(lines) if lines else "No active mentorships."
        else:
            embed = discord.Embed(
                title=f"{EMOJI_GIRL} {self.user_name}'s Roster",
                color=0x8B5CF6,
            )
            embed.description = self._roster_page_description()

        if self.last_message:
            embed.add_field(name="Last action", value=self.last_message, inline=False)

        embed.add_field(
            name="Current selection",
            value="\n".join(self._pending_selection_lines()),
            inline=False,
        )

        embed.set_footer(
            text=f"Girls {len(self.girls)} • Coins {self.player.currency}"
        )
        return embed

    def _pending_selection_lines(self) -> list[str]:
        lines = [f"Action: **{self.current_action.title()}**"]
        mentor = self.player.get_girl(self.mentor_uid) if self.mentor_uid else None
        student = self.player.get_girl(self.student_uid) if self.student_uid else None
        lines.append("Mentor: " + (f"**{mentor.name}**" if mentor else "—"))
        lines.append("Student: " + (f"**{student.name}**" if student else "—"))
        if self.current_action == "assign":
            focus_label = "—"
            if self.focus_type and self.focus_value:
                if self.focus_type == "main":
                    focus_label = f"Main • {self.focus_value}"
                elif self.focus_type == "sub":
                    focus_label = f"Sub • {self.focus_value.title()}"
            lines.append(f"Focus: {focus_label}")
        return lines

    def _roster_page_description(self) -> str:
        if not self.girls:
            return "No girls recruited yet."
        total_pages = self.total_roster_pages
        self.roster_page = min(self.roster_page, total_pages - 1)
        start = self.roster_page * self.ROSTER_PAGE_SIZE
        end = start + self.ROSTER_PAGE_SIZE
        slice_girls = self.girls[start:end]
        parts: list[str] = []
        for girl in slice_girls:
            in_training = bool(self.brothel.training_for(girl.uid))
            status = "Training" if in_training else "Available"
            parts.append(
                (
                    f"{girl.name} [{girl.rarity}] • Lv{girl.level} • UID {girl.uid}\n"
                    f"Health {girl.health}/{girl.health_max} • Stamina {girl.stamina}/{girl.stamina_max}"
                    f" • {status}"
                )
            )
        parts.append(f"Page {self.roster_page + 1}/{total_pages}")
        return "\n\n".join(parts)

    async def _refresh(
        self,
        interaction: discord.Interaction,
        *,
        update_embed: bool,
    ) -> None:
        self._update_components()
        if update_embed:
            embed = self._build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)

    class ActionSelect(discord.ui.Select):
        OPTIONS = [
            discord.SelectOption(label="List mentorships", value="list", emoji="📘", default=True),
            discord.SelectOption(label="Assign mentorship", value="assign", emoji="🤝"),
            discord.SelectOption(label="Finish mentorship", value="finish", emoji="✅"),
        ]

        def __init__(self, view: "TrainingManageView") -> None:
            super().__init__(
                placeholder="Select action",
                min_values=1,
                max_values=1,
                options=self.OPTIONS,
            )
            self._parent = view

        async def callback(self, interaction: discord.Interaction) -> None:
            parent = self._parent
            if not parent._ensure_owner(interaction):
                return
            parent.current_action = self.values[0]
            await parent._refresh(interaction, update_embed=True)

    class GirlSelect(discord.ui.Select):
        def __init__(self, view: "TrainingManageView", *, role: str) -> None:
            self._parent = view
            self.role = role
            placeholder = "Mentor" if role == "mentor" else "Student"
            options = view._build_girl_options(0, selected=None)
            super().__init__(
                placeholder=f"{placeholder} (page 1)",
                min_values=1,
                max_values=1,
                options=options or [
                    discord.SelectOption(label="No girls available", value="none")
                ],
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            parent = self._parent
            if not parent._ensure_owner(interaction):
                return
            value = self.values[0]
            if value == "none":
                await interaction.response.send_message("No girls to select.", ephemeral=True)
                return
            if self.role == "mentor":
                parent.mentor_uid = value
            else:
                parent.student_uid = value
            await parent._refresh(interaction, update_embed=False)

    class FocusTypeSelect(discord.ui.Select):
        OPTIONS = [
            discord.SelectOption(label="Main skill", value="main", emoji=EMOJI_SKILL),
            discord.SelectOption(label="Sub-skill", value="sub", emoji=EMOJI_SUBSKILL),
        ]

        def __init__(self, view: "TrainingManageView") -> None:
            super().__init__(
                placeholder="Focus type",
                min_values=1,
                max_values=1,
                options=self.OPTIONS,
            )
            self._parent = view

        async def callback(self, interaction: discord.Interaction) -> None:
            parent = self._parent
            if not parent._ensure_owner(interaction):
                return
            parent.focus_type = self.values[0]
            parent.focus_value = None
            await parent._refresh(interaction, update_embed=False)

    class MainSkillSelect(discord.ui.Select):
        def __init__(self, view: "TrainingManageView") -> None:
            options = [
                discord.SelectOption(label=name, value=name, emoji=EMOJI_SKILL)
                for name in MAIN_SKILLS
            ]
            super().__init__(
                placeholder="Main skill",
                min_values=1,
                max_values=1,
                options=options,
            )
            self._parent = view

        async def callback(self, interaction: discord.Interaction) -> None:
            parent = self._parent
            if not parent._ensure_owner(interaction):
                return
            parent.focus_type = "main"
            parent.focus_value = self.values[0]
            await parent._refresh(interaction, update_embed=False)

    class SubSkillSelect(discord.ui.Select):
        def __init__(self, view: "TrainingManageView") -> None:
            options = [
                discord.SelectOption(label=name.title(), value=name, emoji=EMOJI_SUBSKILL)
                for name in SUB_SKILLS
            ]
            super().__init__(
                placeholder="Sub-skill",
                min_values=1,
                max_values=1,
                options=options,
            )
            self._parent = view

        async def callback(self, interaction: discord.Interaction) -> None:
            parent = self._parent
            if not parent._ensure_owner(interaction):
                return
            parent.focus_type = "sub"
            parent.focus_value = self.values[0]
            await parent._refresh(interaction, update_embed=False)

    @discord.ui.button(label="Mentor ◀", style=discord.ButtonStyle.secondary, row=1)
    async def mentor_prev(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        if self.mentor_page > 0:
            self.mentor_page -= 1
        await self._refresh(interaction, update_embed=False)

    @discord.ui.button(label="Mentor ▶", style=discord.ButtonStyle.secondary, row=1)
    async def mentor_next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        total = self._page_count()
        if self.mentor_page < total - 1:
            self.mentor_page += 1
        await self._refresh(interaction, update_embed=False)

    @discord.ui.button(label="Student ◀", style=discord.ButtonStyle.secondary, row=2)
    async def student_prev(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        if self.student_page > 0:
            self.student_page -= 1
        await self._refresh(interaction, update_embed=False)

    @discord.ui.button(label="Student ▶", style=discord.ButtonStyle.secondary, row=2)
    async def student_next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        total = self._page_count()
        if self.student_page < total - 1:
            self.student_page += 1
        await self._refresh(interaction, update_embed=False)

    @discord.ui.button(label="◀ Page", style=discord.ButtonStyle.secondary, row=4)
    async def page_prev(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        if self.page_index > 0:
            self.page_index -= 1
        await self._refresh(interaction, update_embed=True)

    @discord.ui.button(label="Page ▶", style=discord.ButtonStyle.secondary, row=4)
    async def page_next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        if self.page_index < len(self.PAGE_TITLES) - 1:
            self.page_index += 1
        await self._refresh(interaction, update_embed=True)

    @discord.ui.button(label="Roster ◀", style=discord.ButtonStyle.secondary, row=4)
    async def roster_prev(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        if self.page_index != 1:
            await interaction.response.send_message(
                "Switch to the roster page first.", ephemeral=True
            )
            return
        if self.roster_page > 0:
            self.roster_page -= 1
        await self._refresh(interaction, update_embed=True)

    @discord.ui.button(label="Roster ▶", style=discord.ButtonStyle.secondary, row=4)
    async def roster_next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return
        if self.page_index != 1:
            await interaction.response.send_message(
                "Switch to the roster page first.", ephemeral=True
            )
            return
        if self.roster_page < self.total_roster_pages - 1:
            self.roster_page += 1
        await self._refresh(interaction, update_embed=True)

    @discord.ui.button(label="Apply", style=discord.ButtonStyle.success, row=4)
    async def execute_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self._ensure_owner(interaction):
            return

        action = self.current_action
        if action == "list":
            lines = self._list_status()
            self.last_message = "\n".join(lines) if lines else "No active mentorships."
            await self._refresh(interaction, update_embed=True)
            return

        if action == "assign":
            message, error = self._assign_training(
                self.mentor_uid,
                self.student_uid,
                self.focus_type,
                self.focus_value,
            )
        else:
            target_uid = self.student_uid or self.mentor_uid
            message, error = self._finish_training(target_uid)

        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        self.last_message = message
        self.girls = sorted(self.player.girls, key=lambda g: g.name.lower())
        await self._refresh(interaction, update_embed=True)

