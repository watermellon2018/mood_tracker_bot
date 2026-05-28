"""Резолвинг период-кодов в (date_from, date_to) включительно.

Все границы — в локальной TZ пользователя. local_today передаётся снаружи,
чтобы тесты были детерминированы.
"""
from __future__ import annotations

from datetime import date, timedelta

# Жёсткий лимит для периода 'all', чтобы PDF не раздулся до сотен страниц.
ALL_PERIOD_HARD_LIMIT_DAYS = 365

PERIOD_CODES = ("7d", "30d", "current_month", "3m", "all")
PERIOD_LABELS: dict[str, str] = {
    "7d": "7 дней",
    "30d": "30 дней",
    "current_month": "Текущий месяц",
    "3m": "3 месяца",
    "all": "Всё время",
}


class UnknownPeriodError(ValueError):
    pass


def resolve_report_period(
    period_code: str, local_today: date
) -> tuple[date, date]:
    """Возвращает (date_from, date_to) включительно. date_to всегда = local_today.

    Правила:
      - '7d'            : последние 7 дней (date_to - 6, date_to);
      - '30d'           : последние 30 дней (date_to - 29, date_to);
      - 'current_month' : с 1-го числа текущего месяца по date_to;
      - '3m'            : последние ~90 дней (date_to - 89, date_to) — нам важна
                          предсказуемая длина, не календарные кварталы;
      - 'all'           : ограничено ALL_PERIOD_HARD_LIMIT_DAYS, иначе PDF
                          разорвётся на огромное число страниц.
    """
    if period_code == "7d":
        return local_today - timedelta(days=6), local_today
    if period_code == "30d":
        return local_today - timedelta(days=29), local_today
    if period_code == "current_month":
        return local_today.replace(day=1), local_today
    if period_code == "3m":
        return local_today - timedelta(days=89), local_today
    if period_code == "all":
        return local_today - timedelta(days=ALL_PERIOD_HARD_LIMIT_DAYS - 1), local_today
    raise UnknownPeriodError(f"Unknown period code: {period_code}")
