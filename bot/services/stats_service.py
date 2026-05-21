from collections import Counter
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.constants import (
    MEDICATION_LABELS,
    SLEEP_DURATION_TO_HOURS,
)
from bot.models import SurveyAnswer, SurveyEntry
from bot.utils.time_utils import get_tz


def fetch_optional_answers(
    session: Session, entry_ids: list[int]
) -> dict[int, list[SurveyAnswer]]:
    """Возвращает {entry_id: [SurveyAnswer, ...]} для переданных entry_id.
    Пустой dict, если entry_ids пуст."""
    if not entry_ids:
        return {}
    rows = session.scalars(
        select(SurveyAnswer).where(SurveyAnswer.entry_id.in_(entry_ids))
    ).all()
    out: dict[int, list[SurveyAnswer]] = {}
    for a in rows:
        out.setdefault(a.entry_id, []).append(a)
    return out


def to_local_date(dt: datetime, tz_name: str):
    """Возвращает дату записи в TZ пользователя.

    В БД created_at — UTC-aware. Если по какой-то причине пришёл naive datetime,
    считаем его UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_tz(tz_name)).date()


def fetch_entries(
    session: Session, user_id: int, since: datetime | None
) -> list[SurveyEntry]:
    stmt = select(SurveyEntry).where(SurveyEntry.user_id == user_id)
    if since is not None:
        stmt = stmt.where(SurveyEntry.created_at >= since)
    stmt = stmt.order_by(SurveyEntry.created_at.asc())
    return list(session.scalars(stmt).all())


def _avg(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def build_summary(
    entries: Sequence[SurveyEntry], days: int | None, user_timezone: str
) -> str:
    """Текстовая сводка. days=None — все данные.

    Дополнительный сон (sleep_type='additional') хранит нули в шкалах и не должен
    влиять на средние — фильтруем его из выборки для статистики настроения.
    """
    entries = [e for e in entries if e.sleep_type != "additional"]
    if not entries:
        return "Записей нет."

    moods = [e.mood for e in entries]
    anxieties = [e.anxiety for e in entries]
    energies = [e.energy for e in entries]
    # irritability/impulsivity теперь NULL-able (опциональные вопросы) —
    # учитываем только заполненные значения.
    irritabilities = [e.irritability for e in entries if e.irritability is not None]
    impulsivities = [e.impulsivity for e in entries if e.impulsivity is not None]

    by_day_mood: dict = {}
    by_day_anxiety: dict = {}
    by_day_sleep_hours: dict = {}
    by_day_little_sleep_good: dict = {}
    for e in entries:
        d = to_local_date(e.created_at, user_timezone)
        by_day_mood.setdefault(d, []).append(e.mood)
        by_day_anxiety.setdefault(d, []).append(e.anxiety)
        by_day_sleep_hours.setdefault(d, []).append(
            SLEEP_DURATION_TO_HOURS.get(e.sleep_duration_category, 0)
        )
        if e.little_sleep_but_feel_good:
            by_day_little_sleep_good[d] = True

    days_high_mood = sum(1 for vs in by_day_mood.values() if max(vs) >= 8)
    days_high_anx = sum(1 for vs in by_day_anxiety.values() if max(vs) >= 4)
    days_low_sleep = sum(
        1 for vs in by_day_sleep_hours.values() if max(vs) < 5
    )
    days_little_sleep_good = len(by_day_little_sleep_good)

    med_counter = Counter(e.medication_taken for e in entries)

    title = f"Статистика за {days} дней:" if days else "Статистика за все время:"

    lines = [
        title,
        "",
        f"Количество записей: {len(entries)}",
        "",
        f"Среднее настроение: {_avg(moods)}",
        f"Минимальное настроение: {min(moods)}",
        f"Максимальное настроение: {max(moods)}",
        "",
        f"Средняя тревога: {_avg(anxieties)}",
        f"Средняя энергия: {_avg(energies)}",
    ]
    if irritabilities:
        lines.append(f"Средняя раздражительность: {_avg(irritabilities)}")
    if impulsivities:
        lines.append(f"Средняя импульсивность: {_avg(impulsivities)}")
    lines.extend([
        "",
        f"Дней с настроением 8+: {days_high_mood}",
        f"Дней с тревогой 4+: {days_high_anx}",
        f"Дней со сном меньше 5 часов: {days_low_sleep}",
        f'Дней с отметкой "мало сна, но чувствую себя отлично": {days_little_sleep_good}',
        "",
        "Прием лекарств:",
    ])
    for key, label in MEDICATION_LABELS.items():
        cnt = med_counter.get(key, 0)
        if cnt:
            lines.append(f"{label}: {cnt}")

    return "\n".join(lines)
