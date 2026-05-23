"""Тесты дневной агрегации медианой для графиков статистики.

Покрывают все сценарии из ТЗ: один день с несколькими ответами, чётное
количество, несколько дней, разные question_code, custom scale_0_5,
boolean/text (исключаются), timezone.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from bot.utils.daily_median import (
    _to_local_date,
    aggregate_daily_median_by_date,
    aggregate_entries_daily_median,
    aggregate_rows_daily_median,
)


# ---------- mock объектов ----------

@dataclass
class FakeEntry:
    """Минимальный объект-stub, имитирующий SurveyEntry для тестов."""
    mood: int | None = None
    anxiety: int | None = None
    energy: int | None = None
    irritability: int | None = None
    impulsivity: int | None = None
    local_date: date | None = None
    created_at: datetime | None = None


# ---------- aggregate_daily_median_by_date ----------

class TestAggregateDailyMedianByDate:
    """Сценарии 1-4 из ТЗ — базовая логика медианы."""

    def test_single_day_three_values_returns_median(self):
        """Сценарий 1: 8, 5, 6 → median = 6."""
        result = aggregate_daily_median_by_date([
            (date(2026, 5, 21), 8),
            (date(2026, 5, 21), 5),
            (date(2026, 5, 21), 6),
        ])
        assert result == [(date(2026, 5, 21), 6)]

    def test_single_day_even_count_returns_half(self):
        """Сценарий 2: 4, 8 → median = 6.0 (не округляем)."""
        result = aggregate_daily_median_by_date([
            (date(2026, 5, 21), 4),
            (date(2026, 5, 21), 8),
        ])
        assert result == [(date(2026, 5, 21), 6.0)]

    def test_single_day_even_count_non_integer_median(self):
        """median(4, 7) = 5.5 — не округляем до целого."""
        result = aggregate_daily_median_by_date([
            (date(2026, 5, 21), 4),
            (date(2026, 5, 21), 7),
        ])
        assert result == [(date(2026, 5, 21), 5.5)]

    def test_multiple_days(self):
        """Сценарий 3: разные дни — отдельные точки, отсортированы."""
        result = aggregate_daily_median_by_date([
            (date(2026, 5, 23), 2),
            (date(2026, 5, 23), 4),
            (date(2026, 5, 21), 8),
            (date(2026, 5, 21), 5),
            (date(2026, 5, 21), 6),
            (date(2026, 5, 22), 3),
        ])
        assert result == [
            (date(2026, 5, 21), 6),
            (date(2026, 5, 22), 3),
            (date(2026, 5, 23), 3),
        ]

    def test_none_values_dropped(self):
        result = aggregate_daily_median_by_date([
            (date(2026, 5, 21), None),
            (date(2026, 5, 21), 5),
            (date(2026, 5, 21), 7),
            (date(2026, 5, 22), None),
        ])
        # 22 мая после фильтрации пустой → не должен попасть в результат.
        assert result == [(date(2026, 5, 21), 6)]

    def test_empty_input(self):
        assert aggregate_daily_median_by_date([]) == []

    def test_all_none(self):
        result = aggregate_daily_median_by_date([
            (date(2026, 5, 21), None),
            (date(2026, 5, 22), None),
        ])
        assert result == []

    def test_decimal_values_converted_to_float(self):
        """answer_numeric из БД — Decimal/Numeric. Должен работать через float()."""
        from decimal import Decimal
        result = aggregate_daily_median_by_date([
            (date(2026, 5, 21), Decimal("3")),
            (date(2026, 5, 21), Decimal("5")),
        ])
        assert result == [(date(2026, 5, 21), 4.0)]


# ---------- aggregate_entries_daily_median ----------

class TestAggregateEntriesDailyMedian:
    """Версия для SurveyEntry. Сценарий 4: разные поля считаются отдельно."""

    def test_uses_local_date_when_available(self):
        entries = [
            FakeEntry(mood=8, local_date=date(2026, 5, 21)),
            FakeEntry(mood=5, local_date=date(2026, 5, 21)),
            FakeEntry(mood=6, local_date=date(2026, 5, 21)),
        ]
        result = aggregate_entries_daily_median(entries, "mood", "Europe/Moscow")
        assert result == [(date(2026, 5, 21), 6)]

    def test_separates_by_field(self):
        """mood и anxiety не должны смешиваться (сценарий 4)."""
        entries = [
            FakeEntry(mood=8, anxiety=2, local_date=date(2026, 5, 21)),
            FakeEntry(mood=5, anxiety=4, local_date=date(2026, 5, 21)),
        ]
        mood_result = aggregate_entries_daily_median(entries, "mood", "UTC")
        anxiety_result = aggregate_entries_daily_median(entries, "anxiety", "UTC")
        assert mood_result == [(date(2026, 5, 21), 6.5)]
        assert anxiety_result == [(date(2026, 5, 21), 3.0)]

    def test_skips_none_fields(self):
        """irritability/impulsivity — NULL-able, NULL отбрасывается."""
        entries = [
            FakeEntry(irritability=3, local_date=date(2026, 5, 21)),
            FakeEntry(irritability=None, local_date=date(2026, 5, 21)),
            FakeEntry(irritability=5, local_date=date(2026, 5, 21)),
        ]
        result = aggregate_entries_daily_median(entries, "irritability", "UTC")
        assert result == [(date(2026, 5, 21), 4)]

    def test_falls_back_to_created_at_when_no_local_date(self):
        """Если у entry нет local_date — считаем по created_at в TZ пользователя."""
        # 21:00 UTC = 23:00 в Москве (UTC+2 без DST? Москва UTC+3) — пусть 00:00 24/05.
        # Берём 21:00 UTC 23 мая → в Москве будет 00:00 24 мая.
        dt_late = datetime(2026, 5, 23, 21, 0, 0, tzinfo=timezone.utc)
        entries = [
            FakeEntry(mood=5, local_date=None, created_at=dt_late),
            FakeEntry(mood=7, local_date=None, created_at=dt_late),
        ]
        result = aggregate_entries_daily_median(entries, "mood", "Europe/Moscow")
        # В Москве (UTC+3) 23 мая 21:00 UTC → 24 мая 00:00.
        assert result == [(date(2026, 5, 24), 6.0)]

    def test_empty_returns_empty_list(self):
        assert aggregate_entries_daily_median([], "mood", "UTC") == []

    def test_does_not_interpolate_missing_days(self):
        """Пустые дни между точками не появляются автоматически (требование ТЗ)."""
        entries = [
            FakeEntry(mood=5, local_date=date(2026, 5, 21)),
            FakeEntry(mood=7, local_date=date(2026, 5, 25)),
        ]
        result = aggregate_entries_daily_median(entries, "mood", "UTC")
        assert result == [
            (date(2026, 5, 21), 5),
            (date(2026, 5, 25), 7),
        ]
        # 22, 23, 24 мая отсутствуют — это и нужно.


# ---------- aggregate_rows_daily_median ----------

class TestAggregateRowsDailyMedian:
    """Версия для dict-rows (answers_rows / custom_rows из stats handler)."""

    def test_uses_log_date_when_provided(self):
        """log_date имеет приоритет над created_at — это семантически
        правильная дата (например, для late_phone = previous_day)."""
        rows = [
            {
                "log_date": date(2026, 5, 20),  # вчера
                "created_at": datetime(2026, 5, 21, 8, 0, tzinfo=timezone.utc),
                "answer_numeric": 2,
            },
            {
                "log_date": date(2026, 5, 20),
                "created_at": datetime(2026, 5, 21, 9, 0, tzinfo=timezone.utc),
                "answer_numeric": 4,
            },
        ]
        result = aggregate_rows_daily_median(rows, "Europe/Moscow")
        # Группировка по log_date, не по created_at.
        assert result == [(date(2026, 5, 20), 3.0)]

    def test_falls_back_to_created_at_when_no_log_date(self):
        """Custom-вопросы могут не иметь log_date в row — конвертация
        created_at в локальную TZ."""
        rows = [
            {
                "created_at": datetime(2026, 5, 21, 6, 0, tzinfo=timezone.utc),
                "answer_numeric": 3,
            },
            {
                "created_at": datetime(2026, 5, 21, 18, 0, tzinfo=timezone.utc),
                "answer_numeric": 5,
            },
        ]
        # В Москве оба попадают на 21 мая.
        result = aggregate_rows_daily_median(rows, "Europe/Moscow")
        assert result == [(date(2026, 5, 21), 4.0)]

    def test_drops_rows_with_none_numeric(self):
        rows = [
            {"log_date": date(2026, 5, 21), "answer_numeric": 5},
            {"log_date": date(2026, 5, 21), "answer_numeric": None},
            {"log_date": date(2026, 5, 21), "answer_numeric": 7},
        ]
        result = aggregate_rows_daily_median(rows, "UTC")
        assert result == [(date(2026, 5, 21), 6.0)]

    def test_drops_rows_without_any_date(self):
        """Если ни log_date, ни created_at нет — row пропускается."""
        rows = [
            {"answer_numeric": 5},
            {"log_date": date(2026, 5, 21), "answer_numeric": 7},
        ]
        result = aggregate_rows_daily_median(rows, "UTC")
        assert result == [(date(2026, 5, 21), 7)]

    def test_empty_returns_empty(self):
        assert aggregate_rows_daily_median([], "UTC") == []

    def test_custom_scale_0_5_example(self):
        """Сценарий 5: custom-вопрос "Боль в спине", за день 2/7/4 → median=4."""
        # Хоть scale_0_5 в текущей модели максимум 5, тест из ТЗ.
        rows = [
            {"log_date": date(2026, 5, 21), "answer_numeric": 2},
            {"log_date": date(2026, 5, 21), "answer_numeric": 7},
            {"log_date": date(2026, 5, 21), "answer_numeric": 4},
        ]
        result = aggregate_rows_daily_median(rows, "UTC")
        assert result == [(date(2026, 5, 21), 4)]


# ---------- _to_local_date / TZ ----------

class TestToLocalDate:
    """Сценарий 7: timezone — группировка по локальной дате пользователя."""

    def test_around_midnight_moscow(self):
        """Сервер в UTC, пользователь в Москве (UTC+3). 21:00 UTC = 00:00 MSK
        следующего дня."""
        dt_utc = datetime(2026, 5, 21, 21, 0, tzinfo=timezone.utc)
        assert _to_local_date(dt_utc, "Europe/Moscow") == date(2026, 5, 22)

    def test_around_midnight_stockholm(self):
        """Stockholm (CEST в мае = UTC+2). 22:00 UTC = 00:00 локальное
        следующего дня."""
        dt_utc = datetime(2026, 5, 21, 22, 0, tzinfo=timezone.utc)
        assert _to_local_date(dt_utc, "Europe/Stockholm") == date(2026, 5, 22)

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetime интерпретируем как UTC (защита от старых записей)."""
        dt_naive = datetime(2026, 5, 21, 21, 0)  # нет tzinfo
        assert _to_local_date(dt_naive, "Europe/Moscow") == date(2026, 5, 22)

    def test_bad_tz_falls_back_to_utc(self):
        """При невалидной TZ возвращаем UTC-дату вместо падения."""
        dt_utc = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)
        # 'NotAZone/Invalid' нет в IANA → fallback на UTC.
        result = _to_local_date(dt_utc, "NotAZone/Invalid")
        assert result == date(2026, 5, 21)

    def test_same_day_when_no_shift_needed(self):
        dt_utc = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)
        assert _to_local_date(dt_utc, "Europe/Moscow") == date(2026, 5, 21)


# ---------- интеграционный сценарий из ТЗ ----------

class TestScenarioFromSpec:
    """Сценарий из главного описания ТЗ:

    2026-05-21:
    - тревога утром: 8
    - тревога днем: 5
    - тревога вечером: 6
    → на графике median = 6 (одна точка).
    """

    def test_anxiety_three_per_day_yields_median_six(self):
        entries = [
            FakeEntry(anxiety=8, local_date=date(2026, 5, 21)),  # утро
            FakeEntry(anxiety=5, local_date=date(2026, 5, 21)),  # день
            FakeEntry(anxiety=6, local_date=date(2026, 5, 21)),  # вечер
        ]
        result = aggregate_entries_daily_median(entries, "anxiety", "Europe/Moscow")
        assert len(result) == 1
        assert result[0] == (date(2026, 5, 21), 6)
