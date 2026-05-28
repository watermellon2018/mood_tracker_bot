"""Графики специально для PDF-отчёта. Используют matplotlib Agg, как и
основной модуль utils/plotting.py, но возвращают PNG-файлы под управлением
вызывающего (с возможностью указать output_dir).

Все функции возвращают str-путь к PNG или None, если нечего рисовать.
Рендерим в выбранную директорию (а не tempfile), чтобы builder мог
почистить всё одной операцией.
"""
from __future__ import annotations

import logging
import os
from collections import Counter
from datetime import date
from typing import Iterable, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)


# Минимальное число точек, чтобы строить линейный график. С 1 точкой
# matplotlib рисует одинокую засечку — бесполезно. Bar/pie рисуем с 1+.
MIN_POINTS_LINE = 2

# Стиль PDF-графиков: чуть меньше DPI, чтобы файл не разрастался.
_DPI = 140
_FIGSIZE = (7.0, 3.0)
_FIGSIZE_SHORT = (7.0, 2.5)


def _save(fig, output_dir: str, filename: str) -> str:
    path = os.path.join(output_dir, filename)
    fig.tight_layout()
    fig.savefig(path, dpi=_DPI)
    plt.close(fig)
    return path


def _format_date_axis(ax) -> None:
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    for label in ax.get_xticklabels():
        label.set_rotation(0)
        label.set_horizontalalignment("center")


def render_line_chart(
    by_date: dict[date, float],
    title: str,
    output_dir: str,
    filename: str,
    *,
    y_min: float | None = None,
    y_max: float | None = None,
    y_label: str = "",
) -> str | None:
    """Линейный график медианных значений по дням. None, если точек < 2."""
    if len(by_date) < MIN_POINTS_LINE:
        return None
    xs = sorted(by_date.keys())
    ys = [by_date[d] for d in xs]
    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.plot(xs, ys, marker="o", linewidth=1.5)
    ax.set_title(title)
    ax.set_ylabel(y_label)
    if y_min is not None or y_max is not None:
        ax.set_ylim(bottom=y_min, top=y_max)
    ax.grid(True, linestyle=":", linewidth=0.6, alpha=0.6)
    _format_date_axis(ax)
    return _save(fig, output_dir, filename)


def render_bar_distribution(
    counter: Counter,
    title: str,
    output_dir: str,
    filename: str,
    *,
    order: Sequence[str] | None = None,
    x_label: str = "",
) -> str | None:
    """Bar chart распределения. None если counter пуст.

    order — желаемый порядок категорий; неизвестные категории добавляются в
    конец в порядке убывания частоты.
    """
    if not counter:
        return None
    labels: list[str] = []
    values: list[int] = []
    if order:
        for k in order:
            if k in counter:
                labels.append(k)
                values.append(counter[k])
        for k, v in counter.most_common():
            if k not in labels:
                labels.append(k)
                values.append(v)
    else:
        for k, v in counter.most_common():
            labels.append(str(k))
            values.append(v)
    fig, ax = plt.subplots(figsize=_FIGSIZE_SHORT)
    ax.bar(range(len(labels)), values)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.set_title(title)
    if x_label:
        ax.set_xlabel(x_label)
    ax.grid(True, axis="y", linestyle=":", linewidth=0.6, alpha=0.6)
    return _save(fig, output_dir, filename)


def render_boolean_frequency(
    yes_days: int,
    total_days: int,
    title: str,
    output_dir: str,
    filename: str,
) -> str | None:
    """Простой 2-bar: Да / Нет."""
    if total_days <= 0:
        return None
    no_days = max(total_days - yes_days, 0)
    fig, ax = plt.subplots(figsize=(4.5, 2.2))
    ax.bar(["Да", "Нет"], [yes_days, no_days])
    ax.set_title(title)
    ax.grid(True, axis="y", linestyle=":", linewidth=0.6, alpha=0.6)
    return _save(fig, output_dir, filename)


def render_sleep_chart(
    by_date_hours: dict[date, float],
    output_dir: str,
    filename: str = "sleep_hours.png",
) -> str | None:
    return render_line_chart(
        by_date_hours,
        title="Сон (часы)",
        output_dir=output_dir,
        filename=filename,
        y_min=0,
        y_label="часы",
    )


def render_medication_chart(
    counter: Counter,
    output_dir: str,
    filename: str = "medication.png",
) -> str | None:
    """Bar по вариантам приёма лекарств. Использует MEDICATION_LABELS как порядок."""
    from bot.constants import MEDICATION_OPTIONS
    if not counter:
        return None
    labels = []
    values = []
    for key, label in MEDICATION_OPTIONS:
        cnt = counter.get(key, 0)
        if cnt:
            labels.append(label)
            values.append(cnt)
    if not labels:
        return None
    fig, ax = plt.subplots(figsize=_FIGSIZE_SHORT)
    ax.bar(range(len(labels)), values)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_title("Приём лекарств — распределение по дням")
    ax.grid(True, axis="y", linestyle=":", linewidth=0.6, alpha=0.6)
    return _save(fig, output_dir, filename)


def cleanup_paths(paths: Iterable[str | None]) -> None:
    for p in paths:
        if not p:
            continue
        try:
            os.unlink(p)
        except OSError:
            pass
