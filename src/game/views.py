"""UI-компоненты Discord."""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional

import discord

from ..models import Girl, Job, Market, Player

__all__ = ["Paginator", "MarketWorkView", "TopLeaderboardView"]


class Paginator(discord.ui.View):
    """Простейший пагинатор по списку Embed."""

    def __init__(self, *, embeds: List[discord.Embed], timeout: Optional[float] = 120.0) -> None:
        super().__init__(timeout=timeout)
        if not embeds:
            raise ValueError("Paginator requires at least one embed")
        self.embeds = embeds
        self.index = 0
        self.prev_button = discord.ui.Button(label="←", style=discord.ButtonStyle.secondary)
        self.next_button = discord.ui.Button(label="→", style=discord.ButtonStyle.secondary)
        self.prev_button.disabled = True
        self.next_button.disabled = len(embeds) <= 1
        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    def current(self) -> discord.Embed:
        return self.embeds[self.index]

    def turn_page(self, delta: int) -> discord.Embed:
        self.index = max(0, min(len(self.embeds) - 1, self.index + delta))
        self.prev_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= len(self.embeds) - 1
        return self.current()


class MarketWorkView(discord.ui.View):
    """Выбор девушки и задания на рынке."""

    GIRLS_PER_PAGE = 24

    def __init__(
        self,
        *,
        user_id: int,
        invoker_id: int,
        player: Player,
        market: Market,
        forced_level: Optional[int],
        timeout: Optional[float] = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.invoker_id = invoker_id
        self.player = player
        self.market = market
        self.forced_level = forced_level
        self.girl_page = 0
        self._girl_options: List[discord.SelectOption] = []
        self._job_value_to_id: Dict[str, str] = {}

        self.girl_select = discord.ui.Select(custom_id="girl", min_values=1, max_values=1)
        self.job_select = discord.ui.Select(custom_id="job", min_values=1, max_values=1)
        self.girl_prev_page_btn = discord.ui.Button(label="←", style=discord.ButtonStyle.secondary)
        self.girl_next_page_btn = discord.ui.Button(label="→", style=discord.ButtonStyle.secondary)

        self.add_item(self.girl_prev_page_btn)
        self.add_item(self.girl_select)
        self.add_item(self.girl_next_page_btn)
        self.add_item(self.job_select)

        self._build_girl_options()
        self._build_job_options()
        self._apply_state()

    # ------------------------------------------------------------------
    def _build_girl_options(self) -> None:
        options: List[discord.SelectOption] = [
            discord.SelectOption(label="Не выбирать", value="none", description="Пропустить выбор девушки"),
        ]
        for girl in sorted(self.player.girls, key=lambda g: g.name):
            description = f"{girl.name} • {girl.uid} • Ур.{girl.level} • {girl.rarity}"
            if girl.mentorship_bonus:
                bonus = int(girl.mentorship_bonus * 100)
                description += f" • Наставник +{bonus}%"
            options.append(
                discord.SelectOption(
                    label=f"{girl.name} ({girl.uid})"[:100],
                    value=girl.uid,
                    description=description[:100],
                )
            )
        self._girl_options = options

    def _build_job_options(self) -> None:
        self._jobs_by_id: Dict[str, Job] = {}
        options: List[discord.SelectOption] = [
            discord.SelectOption(label="Не выбирать", value="none", description="Отменить выбор работы"),
        ]
        used_values: set[str] = {"none"}
        used_canonical: set[str] = set()
        counter = 0
        for job in self.market.jobs:
            raw_value = (job.job_id or "").strip().lower()
            if not raw_value or raw_value in used_values or len(raw_value) > 100 or raw_value == "none":
                counter += 1
                raw_value = f"job-{counter}"
                while raw_value in used_values:
                    counter += 1
                    raw_value = f"job-{counter}"
            raw_value = raw_value[:100]
            used_values.add(raw_value)
            canonical = (job.job_id or "").strip() or f"{job.demand_main}-{job.demand_sub or 'none'}"
            canonical = canonical[:100]
            base = canonical
            suffix = 1
            while canonical.lower() in used_canonical:
                canonical = f"{base}#{suffix}"[:100]
                suffix += 1
            used_canonical.add(canonical.lower())
            self._job_value_to_id[raw_value] = canonical
            self._jobs_by_id[canonical] = job
            label = f"{job.demand_main} / {job.demand_sub or '—'}"
            description = f"Оплата {job.pay} • Сложность {job.difficulty}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=raw_value,
                    description=description[:100],
                )
            )
        self.job_select.options = options

    def _total_pages(self) -> int:
        total_girls = max(0, len(self._girl_options) - 1)
        pages = math.ceil(total_girls / self.GIRLS_PER_PAGE)
        return max(1, pages)

    def _apply_state(self) -> None:
        total_pages = self._total_pages()
        self.girl_page = max(0, min(self.girl_page, total_pages - 1))
        start = self.girl_page * self.GIRLS_PER_PAGE + 1
        end = start + self.GIRLS_PER_PAGE
        page_options = [self._girl_options[0]] + self._girl_options[start:end]
        self.girl_select.options = page_options
        self.girl_select.placeholder = f"Девушки • Page {self.girl_page + 1}/{total_pages}"
        self.girl_prev_page_btn.disabled = self.girl_page <= 0
        self.girl_next_page_btn.disabled = self.girl_page >= total_pages - 1

    # ------------------------------------------------------------------
    def _format_result_lines(self, result: Dict[str, object], girl: Girl, job: Job) -> List[str]:
        if not result.get("ok"):
            reason = result.get("reason", "Задание отклонено")
            return [str(reason), "No resources spent"]
        reward = result.get("reward", 0)
        lines = [
            f"Успех! {girl.name} заработала {reward} монет",
            f"Потрачено выносливости: {result.get('stamina_cost', '?')}",
            f"Потрачено страсти: {result.get('lust_cost', '?')}",
        ]
        if result.get("injured"):
            lines.append("Получено повреждение, требуется лечение")
        return lines


class TopLeaderboardView(discord.ui.View):
    """Упрощённый просмотр топов."""

    def __init__(self, *, entries: Iterable[str], timeout: Optional[float] = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.entries = list(entries)
        self.index = 0
        self.prev_button = discord.ui.Button(label="←", style=discord.ButtonStyle.secondary)
        self.next_button = discord.ui.Button(label="→", style=discord.ButtonStyle.secondary)
        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    def current(self) -> str:
        if not self.entries:
            return "Список пуст"
        return self.entries[self.index]

    def turn(self, delta: int) -> str:
        if not self.entries:
            return "Список пуст"
        self.index = max(0, min(len(self.entries) - 1, self.index + delta))
        return self.current()


