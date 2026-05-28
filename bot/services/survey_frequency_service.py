"""Логика частоты прохождения опроса.

Чистые функции, не зависят от сессии БД:
- format_survey_frequency(type, days) -> human-readable str;
- should_send_survey_today(...) -> bool, нужно ли сегодня отправлять опрос;
- validate_custom_days(value) -> int | None;

Также модуль хранит коды частоты в одном месте.
"""
from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)

FREQ_DAILY = "daily"
FREQ_WEEKLY = "weekly"
FREQ_BIWEEKLY = "biweekly"
FREQ_CUSTOM = "custom_days"

VALID_FREQUENCY_TYPES = frozenset({FREQ_DAILY, FREQ_WEEKLY, FREQ_BIWEEKLY, FREQ_CUSTOM})

CUSTOM_DAYS_MIN = 2
CUSTOM_DAYS_MAX = 30


def is_valid_frequency_type(value: str) -> bool:
    return value in VALID_FREQUENCY_TYPES


def validate_custom_days(value: str) -> int | None:
    """Парсит и валидирует строку с N днями. None — невалид."""
    value = (value or "").strip()
    if not value:
        return None
    # Запрещаем дробные/научную нотацию: только digits.
    if not value.isdigit():
        return None
    try:
        n = int(value)
    except ValueError:
        return None
    if n < CUSTOM_DAYS_MIN or n > CUSTOM_DAYS_MAX:
        return None
    return n


def _days_word(n: int) -> str:
    """Простое склонение 'день'."""
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "дня"
    return "дней"


def format_survey_frequency(frequency_type: str, frequency_days: int | None) -> str:
    if frequency_type == FREQ_DAILY:
        return "каждый день"
    if frequency_type == FREQ_WEEKLY:
        return "раз в неделю"
    if frequency_type == FREQ_BIWEEKLY:
        return "раз в 2 недели"
    if frequency_type == FREQ_CUSTOM:
        if frequency_days is None:
            return "каждые N дней"
        return f"каждые {frequency_days} {_days_word(frequency_days)}"
    return "каждый день"


def required_gap_days(frequency_type: str, frequency_days: int | None) -> int:
    """Минимальное число дней между двумя плановыми опросами."""
    if frequency_type == FREQ_WEEKLY:
        return 7
    if frequency_type == FREQ_BIWEEKLY:
        return 14
    if frequency_type == FREQ_CUSTOM and frequency_days is not None:
        return frequency_days
    return 1  # daily / fallback


def should_send_survey_today(
    frequency_type: str,
    frequency_days: int | None,
    last_survey_notification_date: date | None,
    local_today: date,
) -> bool:
    """Нужно ли сегодня отправлять плановый опрос пользователю.

    Правила:
    - если ещё ни разу не отправляли (last is None) — отправляем;
    - если last == local_today — сегодня уже «день опроса», остальные
      слоты этого же дня тоже разрешены (frequency_per_day может быть > 1);
    - daily: интервал >= 1 (т.е. каждый день);
    - weekly/biweekly/custom_days: проверяем (local_today - last).days >= gap.

    Сравнение идёт в локальной дате пользователя — её должен посчитать
    вызывающий через bot.utils.time_utils.user_local_date(user.timezone).
    """
    if last_survey_notification_date is None:
        return True
    # Сегодня уже зафиксировано как «день опроса» — пропускаем все
    # оставшиеся слоты этого дня (frequency_per_day может быть > 1).
    if last_survey_notification_date == local_today:
        return True
    days_passed = (local_today - last_survey_notification_date).days
    # Защита от сдвига локальной даты назад (смена TZ, ручная правка БД):
    # last в будущем относительно today — не шлём.
    if days_passed < 0:
        return False
    gap = required_gap_days(frequency_type, frequency_days)
    return days_passed >= gap
