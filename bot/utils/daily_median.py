"""Дневная агрегация числовых ответов медианой.

Используется для построения дневных графиков статистики, чтобы один день
давал одну точку, а не N (по количеству ответов в день).

Сырые данные в БД не меняются — это только подготовка к рендеру графиков.
Для нечисловых типов (boolean / text / choice / json) медиану не считаем.

Медиана выбрана как устойчивая к выбросам метрика типичного дня: один
случайно высокий ответ не сдвигает кривую целиком.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import median
from typing import Iterable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def _to_local_date(dt: datetime, tz_name: str) -> date:
    """Приводит aware-datetime из БД к локальной дате пользователя.

    Если по какой-то причине пришёл naive datetime — считаем его UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        return dt.astimezone(ZoneInfo(tz_name)).date()
    except Exception:
        # Fallback — UTC-дата. Произойдёт только при невалидной TZ.
        logger.warning("daily_median: bad tz=%s, fallback to UTC date", tz_name)
        return dt.astimezone(timezone.utc).date()


def aggregate_daily_median_by_date(
    points: Iterable[tuple[date, float | None]],
) -> list[tuple[date, float]]:
    """Группирует пары (local_date, value) по дате и возвращает медиану.

    None-значения отбрасываются. Пустые дни не возвращаются — на графике их
    рисовать не нужно. Результат отсортирован по дате.
    """
    grouped: dict[date, list[float]] = defaultdict(list)
    for d, v in points:
        if v is None:
            continue
        grouped[d].append(float(v))

    result = [(d, median(values)) for d, values in grouped.items()]
    result.sort(key=lambda x: x[0])
    return result


def aggregate_entries_daily_median(
    entries: Iterable,
    field: str,
    user_timezone: str,
) -> list[tuple[date, float]]:
    """Берёт коллекцию SurveyEntry и считает дневную медиану по полю field.

    Использует `local_date`, если он есть на entry (так уже хранится TZ-aware
    локальная дата на момент сохранения). Это корректный путь — медиана
    группируется в локальной TZ пользователя без двойной конвертации.

    Если `local_date` отсутствует (исторические записи или другая модель) —
    конвертирует `created_at` в TZ пользователя.
    """
    points: list[tuple[date, float | None]] = []
    for e in entries:
        value = getattr(e, field, None)
        if value is None:
            continue
        local_date = getattr(e, "local_date", None)
        if local_date is None:
            local_date = _to_local_date(e.created_at, user_timezone)
        points.append((local_date, value))

    result = aggregate_daily_median_by_date(points)
    logger.debug(
        "daily_median: field=%s raw_points=%d daily_points=%d",
        field, sum(1 for _ in points), len(result),
    )
    return result


def aggregate_rows_daily_median(
    rows: Iterable[dict],
    user_timezone: str,
    date_field: str = "created_at",
    value_field: str = "answer_numeric",
    log_date_field: str | None = "log_date",
) -> list[tuple[date, float]]:
    """Версия для dict-rows (как в answers_rows / custom_rows из stats handler).

    По умолчанию пытается использовать `log_date` (если он передан в row),
    иначе конвертирует `created_at` в локальную TZ пользователя.
    """
    points: list[tuple[date, float | None]] = []
    for row in rows:
        value = row.get(value_field)
        if value is None:
            continue
        local_date = None
        if log_date_field is not None:
            local_date = row.get(log_date_field)
        if local_date is None:
            dt = row.get(date_field)
            if dt is None:
                continue
            local_date = _to_local_date(dt, user_timezone)
        points.append((local_date, value))
    return aggregate_daily_median_by_date(points)
