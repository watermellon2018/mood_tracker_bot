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
from bot.constants_questions import QUESTION_DEFINITIONS
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


def _exclude_additional(entries: Sequence[SurveyEntry]) -> list[SurveyEntry]:
    """Графики шкал не должны включать дополнительный сон (там нули в шкалах)."""
    return [e for e in entries if e.sleep_type != "additional"]


def _only_with_sleep(entries: Sequence[SurveyEntry]) -> list[SurveyEntry]:
    """Графики сна — только записи, где сон реально заполнен."""
    return [
        e for e in entries
        if e.sleep_type in ("main", "additional")
        and e.sleep_duration_category != "skipped"
    ]


def _only_with_medication(entries: Sequence[SurveyEntry]) -> list[SurveyEntry]:
    return [e for e in entries if e.medication_filled]


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
    entries = _exclude_additional(entries)
    # Фильтруем записи, где поле None (опциональные шкалы могут отсутствовать).
    entries = [e for e in entries if getattr(e, field) is not None]
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
    entries = _exclude_additional(entries)
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
    entries = _exclude_additional(entries)
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


def plot_sleep(
    entries: Sequence[SurveyEntry], user_timezone: str
) -> str | None:
    """Сводный график сна: длительность (часы) и качество (1-5) бок-о-бок
    с прозрачностью, двумя Y-осями. Один день — две полупрозрачные колонки."""
    entries = _only_with_sleep(entries)
    if not entries:
        return None

    by_day_hours: dict = {}
    by_day_qual: dict = {}
    for e in entries:
        d = _local_dt(e.created_at, user_timezone).date()
        by_day_hours.setdefault(d, []).append(
            SLEEP_DURATION_TO_HOURS.get(e.sleep_duration_category, 0)
        )
        by_day_qual.setdefault(d, []).append(
            SLEEP_QUALITY_TO_SCORE.get(e.sleep_quality, 0)
        )

    days = sorted(set(by_day_hours.keys()) | set(by_day_qual.keys()))
    hours = [max(by_day_hours.get(d, [0])) for d in days]
    quality = [max(by_day_qual.get(d, [0])) for d in days]

    # Сдвиг колонок по X на пол-ширины: длительность слева, качество справа.
    # mdates.date2num конвертирует date -> float, чтобы можно было сдвигать.
    x = mdates.date2num(days)
    width = 0.4

    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars1 = ax.bar(
        x - width / 2, hours,
        width=width, color="#7eb6ff", alpha=0.65,
        edgecolor="#3a78c2", linewidth=0.8,
        label="Длительность (часы)",
    )
    ax.set_ylabel("Часы (примерно)", color="#3a78c2")
    ax.set_ylim(0, 11)
    ax.tick_params(axis="y", labelcolor="#3a78c2")

    ax2 = ax.twinx()
    bars2 = ax2.bar(
        x + width / 2, quality,
        width=width, color="#9bd49b", alpha=0.65,
        edgecolor="#3f8a3f", linewidth=0.8,
        label="Качество (1–5)",
    )
    ax2.set_ylabel("Оценка качества (1–5)", color="#3f8a3f")
    ax2.set_ylim(0, 5.5)
    ax2.set_yticks(range(0, 6))
    ax2.tick_params(axis="y", labelcolor="#3f8a3f")

    ax.set_title("Сон: длительность и качество по дням")
    ax.grid(True, axis="y", alpha=0.25)
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))

    # Общая легенда (двух осей).
    handles = [bars1, bars2]
    labels = [h.get_label() for h in handles]
    ax.legend(handles, labels, loc="upper left", fontsize=8)

    fig.autofmt_xdate()
    path = _new_png()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_sleep_problems(
    entries: Sequence[SurveyEntry], user_timezone: str
) -> str | None:
    entries = _only_with_sleep(entries)
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
    entries = _exclude_additional(entries)
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


def plot_custom_question(
    answers: list[dict],
    question_id: int,
    question_text: str,
    answer_type: str,
    user_timezone: str,
    min_points: int = 2,
) -> str | None:
    """График для одного пользовательского вопроса.

    answers — список dict с ключами 'created_at', 'custom_question_id',
    'answer_type', 'answer_numeric', 'answer_bool', 'answer_text'.
    Тексты не графитим — возвращаем None.
    """
    rows = [
        a for a in answers
        if a.get("custom_question_id") == question_id
    ]
    if len(rows) < min_points:
        return None

    title = (question_text or "").strip().rstrip("?")
    if len(title) > 70:
        title = title[:67] + "…"

    if answer_type == "scale_0_5":
        rows = [a for a in rows if a.get("answer_numeric") is not None]
        if len(rows) < min_points:
            return None
        rows = sorted(rows, key=lambda a: a["created_at"])
        xs = [_local_dt(a["created_at"], user_timezone) for a in rows]
        ys = [float(a["answer_numeric"]) for a in rows]
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot(xs, ys, marker="o", linewidth=1.5, color="#5a6acf")
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("Шкала 0–5")
        ax.set_ylim(-0.3, 5.3)
        ax.set_yticks(range(0, 6))
        ax.grid(True, alpha=0.3)
        _format_x(ax)
        fig.autofmt_xdate()
        path = _new_png()
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        return path

    if answer_type == "boolean":
        # Бар-чарт: Да / Нет за период.
        yes_count = sum(1 for a in rows if a.get("answer_bool") is True)
        no_count = sum(1 for a in rows if a.get("answer_bool") is False)
        if yes_count + no_count < min_points:
            return None
        fig, ax = plt.subplots(figsize=(7, 4.5))
        ax.bar(["Да", "Нет"], [yes_count, no_count], color=["#9bd49b", "#f4a6c0"])
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("Записей за период")
        ax.grid(True, axis="y", alpha=0.3)
        path = _new_png()
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        return path

    # text — без графика.
    return None


def plot_optional_question(
    answers: list[dict],
    question_code: str,
    user_timezone: str,
    min_points: int = 2,
) -> str | None:
    """Линейный график для одного опционального вопроса.

    `answers` — список dict с ключами 'created_at', 'question_code',
    'answer_numeric', 'answer_value'. Используются только те, у которых
    question_code совпадает и answer_numeric не None.

    Возвращает путь к PNG или None, если данных < min_points.
    """
    rows = [
        a for a in answers
        if a.get("question_code") == question_code
        and a.get("answer_numeric") is not None
    ]
    if len(rows) < min_points:
        return None

    rows = sorted(rows, key=lambda a: a["created_at"])
    xs = [_local_dt(a["created_at"], user_timezone) for a in rows]
    ys = [float(a["answer_numeric"]) for a in rows]

    defn = QUESTION_DEFINITIONS.get(question_code, {})
    title = defn.get("question_text", question_code).rstrip("?")
    options = defn.get("options")

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(xs, ys, marker="o", linewidth=1.5, color="#5a6acf")
    ax.set_title(title, fontsize=10)
    ax.set_ylim(-0.3, 4.3)
    ax.set_yticks(range(0, 5))
    if options and len(options) == 5:
        # подписи кнопок 0..4 как тики
        ax.set_yticklabels(options, fontsize=8)
    ax.grid(True, alpha=0.3)
    _format_x(ax)
    fig.autofmt_xdate()
    path = _new_png()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
