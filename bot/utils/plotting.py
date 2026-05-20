"""Построение PNG-графиков через matplotlib (backend Agg)."""

import tempfile
from collections import Counter
from datetime import datetime, timezone
from typing import Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from bot.constants import (
    SLEEP_DURATION_LABELS,
    SLEEP_DURATION_TO_HOURS,
    SLEEP_PROBLEM_LABELS,
    SLEEP_QUALITY_LABELS,
    SLEEP_QUALITY_TO_SCORE,
)
from bot.models import SurveyEntry
from bot.utils.time_utils import get_tz


def _local_dt(dt: datetime, tz_name: str) -> datetime:
    """Конвертирует aware-datetime из БД в TZ пользователя и убирает tzinfo
    (matplotlib умеет и с aware, но единообразно проще)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_tz(tz_name)).replace(tzinfo=None)


def _xs(entries: Sequence[SurveyEntry], tz_name: str) -> list[datetime]:
    return [_local_dt(e.created_at, tz_name) for e in entries]


def _new_png() -> str:
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    f.close()
    return f.name


def _format_x(ax) -> None:
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m\n%H:%M"))


def _line_chart(
    entries: Sequence[SurveyEntry],
    field: str,
    title: str,
    ylabel: str,
    ymax: int,
    user_timezone: str,
) -> str | None:
    if not entries:
        return None
    xs = _xs(entries, user_timezone)
    ys = [getattr(e, field) for e in entries]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(xs, ys, marker="o", linewidth=1.5)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_ylim(-0.2, ymax + 0.2)
    ax.set_yticks(range(0, ymax + 1))
    ax.grid(True, alpha=0.3)
    _format_x(ax)
    fig.autofmt_xdate()
    path = _new_png()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_mood(entries: Sequence[SurveyEntry], user_timezone: str) -> str | None:
    if not entries:
        return None
    xs = _xs(entries, user_timezone)
    ys = [e.mood for e in entries]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.axhspan(0, 3, color="#c9d8ff", alpha=0.4, label="низкое состояние")
    ax.axhspan(4, 6, color="#d5f5d5", alpha=0.4, label="условно стабильная зона")
    ax.axhspan(7, 10, color="#ffe0c2", alpha=0.4, label="повышенное состояние")
    ax.plot(xs, ys, marker="o", linewidth=1.5, color="#222")
    ax.set_title("Настроение по времени")
    ax.set_ylabel("Настроение (0–10)")
    ax.set_ylim(-0.2, 10.2)
    ax.set_yticks(range(0, 11))
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)
    _format_x(ax)
    fig.autofmt_xdate()
    path = _new_png()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_anxiety(entries, user_timezone):
    return _line_chart(
        entries, "anxiety", "Тревога по времени", "Тревога (0–5)", 5, user_timezone
    )


def plot_energy(entries, user_timezone):
    return _line_chart(
        entries, "energy", "Энергия по времени", "Энергия (0–5)", 5, user_timezone
    )


def plot_irritability(entries, user_timezone):
    return _line_chart(
        entries, "irritability", "Раздражительность по времени",
        "Раздражительность (0–5)", 5, user_timezone,
    )


def plot_impulsivity(entries, user_timezone):
    return _line_chart(
        entries, "impulsivity", "Импульсивность по времени",
        "Импульсивность (0–5)", 5, user_timezone,
    )


def plot_mood_energy(
    entries: Sequence[SurveyEntry], user_timezone: str
) -> str | None:
    if not entries:
        return None
    xs = _xs(entries, user_timezone)
    mood = [e.mood for e in entries]
    energy = [e.energy for e in entries]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(xs, mood, marker="o", color="#1f77b4", label="Настроение (0–10)")
    ax.set_ylabel("Настроение (0–10)", color="#1f77b4")
    ax.set_ylim(-0.2, 10.2)
    ax.set_yticks(range(0, 11))
    ax2 = ax.twinx()
    ax2.plot(xs, energy, marker="s", color="#d62728", label="Энергия (0–5)")
    ax2.set_ylabel("Энергия (0–5)", color="#d62728")
    ax2.set_ylim(-0.2, 5.2)
    ax2.set_yticks(range(0, 6))
    ax.set_title("Настроение и энергия")
    ax.grid(True, alpha=0.3)
    _format_x(ax)
    fig.autofmt_xdate()
    path = _new_png()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_sleep_duration(
    entries: Sequence[SurveyEntry], user_timezone: str
) -> str | None:
    if not entries:
        return None
    by_day: dict[datetime, list[int]] = {}
    for e in entries:
        d = _local_dt(e.created_at, user_timezone).date()
        by_day.setdefault(d, []).append(
            SLEEP_DURATION_TO_HOURS.get(e.sleep_duration_category, 0)
        )
    days = sorted(by_day.keys())
    values = [max(by_day[d]) for d in days]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(days, values, color="#7eb6ff")
    ax.set_title("Длительность сна по дням")
    ax.set_ylabel("Часы (примерно)")
    ax.set_ylim(0, 11)
    ax.grid(True, axis="y", alpha=0.3)
    fig.autofmt_xdate()
    path = _new_png()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_sleep_quality(
    entries: Sequence[SurveyEntry], user_timezone: str
) -> str | None:
    if not entries:
        return None
    by_day: dict[datetime, list[int]] = {}
    for e in entries:
        d = _local_dt(e.created_at, user_timezone).date()
        by_day.setdefault(d, []).append(
            SLEEP_QUALITY_TO_SCORE.get(e.sleep_quality, 0)
        )
    days = sorted(by_day.keys())
    values = [max(by_day[d]) for d in days]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(days, values, color="#9bd49b")
    ax.set_title("Качество сна по дням")
    ax.set_ylabel("Оценка (1–5)")
    ax.set_yticks(range(1, 6))
    ax.set_ylim(0, 5.5)
    ax.grid(True, axis="y", alpha=0.3)
    fig.autofmt_xdate()
    path = _new_png()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_sleep_problems(
    entries: Sequence[SurveyEntry], user_timezone: str
) -> str | None:
    if not entries:
        return None
    counts = {key: 0 for key, _ in SLEEP_PROBLEM_LABELS.items()}
    for e in entries:
        for key in counts:
            if getattr(e, key):
                counts[key] += 1
    if all(v == 0 for v in counts.values()):
        return None
    labels = [SLEEP_PROBLEM_LABELS[k] for k in counts.keys()]
    values = list(counts.values())
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(labels, values, color="#caa6e3")
    ax.set_title("Отметки по проблемам сна")
    ax.invert_yaxis()
    ax.grid(True, axis="x", alpha=0.3)
    path = _new_png()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_mood_spread(
    entries: Sequence[SurveyEntry], user_timezone: str
) -> str | None:
    if not entries:
        return None
    by_day: dict[datetime, list[int]] = {}
    for e in entries:
        by_day.setdefault(_local_dt(e.created_at, user_timezone).date(), []).append(
            e.mood
        )
    spreads = {d: max(vs) - min(vs) for d, vs in by_day.items() if len(vs) >= 2}
    if not spreads:
        return None
    days = sorted(spreads.keys())
    values = [spreads[d] for d in days]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(days, values, color="#ffb482")
    ax.set_title("Дневной разброс настроения (max - min)")
    ax.set_ylabel("Разброс")
    ax.set_ylim(0, 10)
    ax.grid(True, axis="y", alpha=0.3)
    fig.autofmt_xdate()
    path = _new_png()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_medication(
    entries: Sequence[SurveyEntry], user_timezone: str = "UTC"
) -> str | None:
    if not entries:
        return None
    counter = Counter(e.medication_taken for e in entries)
    labels_map = {
        "yes": "Да",
        "no": "Нет",
        "partial": "Частично",
        "not_applicable": "Не применимо",
        "skipped": "Пропущено",
    }
    keys = list(labels_map.keys())
    values = [counter.get(k, 0) for k in keys]
    labels = [labels_map[k] for k in keys]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(labels, values, color="#f4a6c0")
    ax.set_title("Прием лекарств — распределение отметок")
    ax.set_ylabel("Записей")
    ax.grid(True, axis="y", alpha=0.3)
    path = _new_png()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
