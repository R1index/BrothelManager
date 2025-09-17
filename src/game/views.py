"""Упрощённые представления Discord-компонентов для тестов."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from ..models import Girl, Job, Market, Player

__all__ = ["MarketWorkView", "SelectOption", "Select", "Button"]


@dataclass
class SelectOption:
    value: str
    label: str
    description: str = ""


class Select:
    def __init__(self) -> None:
        self.options: List[SelectOption] = []
        self.placeholder: str = ""


class Button:
    def __init__(self) -> None:
        self.disabled: bool = False


class MarketWorkView:
    """Неблокирующая версия интерактивного вида.

    Класс не зависит от discord.py и предоставляет только ту поверхность,
    которая используется в тестах: пагинацию по девушкам, подготовку опций
    и форматирование результатов.
    """

    GIRLS_PER_PAGE = 24

    def __init__(
        self,
        *,
        user_id: int,
        invoker_id: int,
        forced_level: Optional[int],
        player: Player,
        market: Market,
    ) -> None:
        self.user_id = user_id
        self.invoker_id = invoker_id
        self.forced_level = forced_level
        self.player = player
        self.market = market

        self.girl_page = 0
        self.girl_select = Select()
        self.job_select = Select()
        self.girl_prev_page_btn = Button()
        self.girl_next_page_btn = Button()
        self._job_value_to_id: Dict[str, Optional[str]] = {}

        self._build_job_options()
        self._apply_state()

    # ------------------------- построение опций -------------------------
    def _build_job_options(self) -> None:
        options: List[SelectOption] = [
            SelectOption("none", "Не выбирать работу", "Пропустить выполнение"),
        ]
        self._job_value_to_id = {"none": None}
        seen: Dict[str, int] = {}
        for index, job in enumerate(self.market.jobs):
            canonical = (job.job_id or "").strip() or f"job-{index}"
            seq = seen.get(canonical, 0)
            seen[canonical] = seq + 1
            value = f"job-{index}-{seq}"[:100]
            canonical_id = canonical if seq == 0 else f"{canonical}#{seq}"
            self._job_value_to_id[value] = canonical_id
            label = f"{job.demand_main}/{job.demand_sub} — {job.pay}💰"
            description = f"{canonical_id} • diff {job.difficulty}"
            options.append(SelectOption(value, label, description))
        self.job_select.options = options
        self.job_select.placeholder = "Выберите задание"

    # ------------------------- пагинация -------------------------
    def _apply_state(self) -> None:
        girls = sorted(self.player.girls, key=lambda g: g.uid)
        per_page = self.GIRLS_PER_PAGE
        total_pages = max(1, math.ceil(len(girls) / per_page))
        self.girl_page = max(0, min(self.girl_page, total_pages - 1))
        start = self.girl_page * per_page
        end = start + per_page
        page_slice = girls[start:end]

        options: List[SelectOption] = [
            SelectOption("none", "Не назначать девушку", "Можно выбрать позже"),
        ]
        for girl in page_slice:
            percent = int(round(girl.mentorship_bonus * 100)) if girl.mentorship_bonus else 0
            label = f"{girl.name} ({girl.uid})"
            description = f"{girl.name} • {girl.uid}"
            if percent:
                label += f" +{percent}%"
                description += f" • +{percent}% mentorship"
            options.append(SelectOption(girl.uid, label, description))

        self.girl_select.options = options
        self.girl_select.placeholder = f"Page {self.girl_page + 1}/{total_pages}"
        self.girl_prev_page_btn.disabled = self.girl_page <= 0
        self.girl_next_page_btn.disabled = self.girl_page >= total_pages - 1

    # ------------------------- вспомогательные методы -------------------------
    def _format_result_lines(self, result: dict, girl: Girl, job: Job) -> List[str]:
        if result.get("ok"):
            reward = result.get("reward", 0)
            return [
                f"✅ {girl.name} выполнила задание и заработала {reward} монет.",
            ]
        reason = result.get("reason", "Задание отклонено")
        lines = [f"❌ {reason}"]
        if result.get("spent_resources"):
            lines.append("Расходы: потрачены сила и страсть.")
        else:
            lines.append("No resources spent")
        return lines

