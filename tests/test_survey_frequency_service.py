"""Тесты для bot.services.survey_frequency_service.

Покрывают баг с пропуском поздних слотов в дне (PR
claude/fix-survey-frequency-skip) и базовое поведение всех частот.
"""
from datetime import date

import pytest

from bot.services.survey_frequency_service import (
    CUSTOM_DAYS_MAX,
    CUSTOM_DAYS_MIN,
    FREQ_BIWEEKLY,
    FREQ_CUSTOM,
    FREQ_DAILY,
    FREQ_WEEKLY,
    format_survey_frequency,
    is_valid_frequency_type,
    required_gap_days,
    should_send_survey_today,
    validate_custom_days,
)


TODAY = date(2026, 5, 23)
YESTERDAY = date(2026, 5, 22)


# ---------- should_send_survey_today ----------

class TestShouldSendSurveyTodayDaily:
    """daily: каждый день — день опроса. Все слоты любого дня должны проходить."""

    def test_first_ever_send_returns_true(self):
        assert should_send_survey_today(FREQ_DAILY, None, None, TODAY) is True

    def test_same_day_repeated_slot_returns_true(self):
        """Регрессионный тест на баг: после первого слота
        last_date == local_today; последующие слоты не должны глохнуть."""
        assert should_send_survey_today(
            FREQ_DAILY, None, TODAY, TODAY
        ) is True

    def test_next_day_returns_true(self):
        assert should_send_survey_today(
            FREQ_DAILY, None, YESTERDAY, TODAY
        ) is True

    def test_after_long_gap_returns_true(self):
        assert should_send_survey_today(
            FREQ_DAILY, None, date(2026, 5, 1), TODAY
        ) is True

    def test_tz_shift_backwards_returns_false(self):
        """last_date в будущем относительно today — не дублируем (защита от
        смены TZ назад или ручной правки БД)."""
        tomorrow = date(2026, 5, 24)
        assert should_send_survey_today(
            FREQ_DAILY, None, tomorrow, TODAY
        ) is False


class TestShouldSendSurveyTodayWeekly:
    """weekly: gap = 7 дней."""

    def test_first_ever_send_returns_true(self):
        assert should_send_survey_today(FREQ_WEEKLY, None, None, TODAY) is True

    def test_same_day_repeated_slot_returns_true(self):
        assert should_send_survey_today(
            FREQ_WEEKLY, None, TODAY, TODAY
        ) is True

    def test_one_day_passed_returns_false(self):
        assert should_send_survey_today(
            FREQ_WEEKLY, None, YESTERDAY, TODAY
        ) is False

    def test_six_days_passed_returns_false(self):
        assert should_send_survey_today(
            FREQ_WEEKLY, None, date(2026, 5, 17), TODAY
        ) is False

    def test_exactly_seven_days_passed_returns_true(self):
        assert should_send_survey_today(
            FREQ_WEEKLY, None, date(2026, 5, 16), TODAY
        ) is True

    def test_more_than_seven_days_passed_returns_true(self):
        assert should_send_survey_today(
            FREQ_WEEKLY, None, date(2026, 5, 10), TODAY
        ) is True


class TestShouldSendSurveyTodayBiweekly:
    """biweekly: gap = 14 дней."""

    def test_same_day_repeated_slot_returns_true(self):
        assert should_send_survey_today(
            FREQ_BIWEEKLY, None, TODAY, TODAY
        ) is True

    def test_thirteen_days_passed_returns_false(self):
        assert should_send_survey_today(
            FREQ_BIWEEKLY, None, date(2026, 5, 10), TODAY
        ) is False

    def test_exactly_fourteen_days_passed_returns_true(self):
        assert should_send_survey_today(
            FREQ_BIWEEKLY, None, date(2026, 5, 9), TODAY
        ) is True


class TestShouldSendSurveyTodayCustom:
    """custom_days: gap = frequency_days."""

    def test_same_day_repeated_slot_returns_true(self):
        assert should_send_survey_today(
            FREQ_CUSTOM, 3, TODAY, TODAY
        ) is True

    def test_gap_not_reached_returns_false(self):
        # gap=3, прошло 2 дня
        assert should_send_survey_today(
            FREQ_CUSTOM, 3, date(2026, 5, 21), TODAY
        ) is False

    def test_gap_reached_exactly_returns_true(self):
        # gap=3, прошло ровно 3 дня
        assert should_send_survey_today(
            FREQ_CUSTOM, 3, date(2026, 5, 20), TODAY
        ) is True

    def test_custom_days_max_boundary(self):
        # gap=30 (CUSTOM_DAYS_MAX): 29 дней — нельзя, 30 — можно
        assert should_send_survey_today(
            FREQ_CUSTOM, 30, date(2026, 4, 24), TODAY
        ) is False
        assert should_send_survey_today(
            FREQ_CUSTOM, 30, date(2026, 4, 23), TODAY
        ) is True


class TestShouldSendSurveyTodayBugRegression:
    """Конкретный сценарий из issue: 3 слота daily 11:00 / 17:00 / 23:00.

    После первого слота last_date обновляется на сегодня. 17:00 и 23:00
    должны проходить гейт. До фикса они получали False по `days_passed <= 0`.
    """

    def test_three_slots_first_day_all_pass(self):
        # До первого пуша last_date is None.
        assert should_send_survey_today(FREQ_DAILY, None, None, TODAY) is True
        # После первого пуша last_date := TODAY. Остальные слоты должны
        # проходить гейт.
        assert should_send_survey_today(FREQ_DAILY, None, TODAY, TODAY) is True
        # 23:00 — то же.
        assert should_send_survey_today(FREQ_DAILY, None, TODAY, TODAY) is True

    def test_next_day_all_slots_pass(self):
        # На следующий день первый слот видит last_date = вчера → пройдёт.
        assert should_send_survey_today(
            FREQ_DAILY, None, YESTERDAY, TODAY
        ) is True
        # Дальше тот же путь: last_date := TODAY → остальные слоты проходят.
        assert should_send_survey_today(FREQ_DAILY, None, TODAY, TODAY) is True


# ---------- required_gap_days ----------

class TestRequiredGapDays:
    def test_daily(self):
        assert required_gap_days(FREQ_DAILY, None) == 1

    def test_weekly(self):
        assert required_gap_days(FREQ_WEEKLY, None) == 7

    def test_biweekly(self):
        assert required_gap_days(FREQ_BIWEEKLY, None) == 14

    def test_custom_with_days(self):
        assert required_gap_days(FREQ_CUSTOM, 5) == 5
        assert required_gap_days(FREQ_CUSTOM, CUSTOM_DAYS_MIN) == CUSTOM_DAYS_MIN
        assert required_gap_days(FREQ_CUSTOM, CUSTOM_DAYS_MAX) == CUSTOM_DAYS_MAX

    def test_custom_without_days_fallbacks_to_one(self):
        # Без явного числа дней деградируем к daily-поведению (gap=1).
        assert required_gap_days(FREQ_CUSTOM, None) == 1

    def test_unknown_type_fallbacks_to_one(self):
        assert required_gap_days("garbage", None) == 1


# ---------- validate_custom_days ----------

class TestValidateCustomDays:
    @pytest.mark.parametrize("value", ["2", "3", "10", "30"])
    def test_valid(self, value):
        assert validate_custom_days(value) == int(value)

    @pytest.mark.parametrize("value", ["1", "0", "31", "100", "-3"])
    def test_out_of_range(self, value):
        assert validate_custom_days(value) is None

    @pytest.mark.parametrize("value", ["", "  ", "abc", "3.5", "1e2", "2 days", "??"])
    def test_garbage(self, value):
        assert validate_custom_days(value) is None

    def test_strips_whitespace(self):
        assert validate_custom_days("  5  ") == 5

    def test_none_safe(self):
        # validate_custom_days делает (value or "").strip(), так что None ок.
        assert validate_custom_days(None) is None


# ---------- format_survey_frequency ----------

class TestFormatSurveyFrequency:
    def test_daily(self):
        assert format_survey_frequency(FREQ_DAILY, None) == "каждый день"

    def test_weekly(self):
        assert format_survey_frequency(FREQ_WEEKLY, None) == "раз в неделю"

    def test_biweekly(self):
        assert format_survey_frequency(FREQ_BIWEEKLY, None) == "раз в 2 недели"

    def test_custom_without_days(self):
        assert format_survey_frequency(FREQ_CUSTOM, None) == "каждые N дней"

    @pytest.mark.parametrize("n, expected", [
        (2, "каждые 2 дня"),
        (3, "каждые 3 дня"),
        (4, "каждые 4 дня"),
        (5, "каждые 5 дней"),
        (10, "каждые 10 дней"),
        (11, "каждые 11 дней"),  # 11..14 — "дней" (исключение из правила «1»)
        (12, "каждые 12 дней"),
        (13, "каждые 13 дней"),
        (14, "каждые 14 дней"),
        (21, "каждые 21 день"),  # 21 — снова "день"
        (22, "каждые 22 дня"),
        (25, "каждые 25 дней"),
    ])
    def test_custom_days_plural_forms(self, n, expected):
        assert format_survey_frequency(FREQ_CUSTOM, n) == expected

    def test_unknown_type_fallbacks_to_daily(self):
        assert format_survey_frequency("garbage", None) == "каждый день"


# ---------- is_valid_frequency_type ----------

class TestIsValidFrequencyType:
    @pytest.mark.parametrize("value", [FREQ_DAILY, FREQ_WEEKLY, FREQ_BIWEEKLY, FREQ_CUSTOM])
    def test_valid(self, value):
        assert is_valid_frequency_type(value) is True

    @pytest.mark.parametrize("value", ["", "DAILY", "monthly", "everyday", " daily "])
    def test_invalid(self, value):
        assert is_valid_frequency_type(value) is False
