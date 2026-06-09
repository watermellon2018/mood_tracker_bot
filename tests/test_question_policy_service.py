"""Тесты политик показа вопросов (bot.services.question_policy_service).

Покрывают чистые функции, не зависящие от БД:
- should_ask_question_in_slot для всех ask_policy, включая новый
  last_or_after_noon с порогом NOON_HOUR (12:00) по времени открытия опроса;
- slot_for_index и compute_survey_slot (назначение слота).

Регрессия на баг: утренний (first) опрос не должен задавать вопросы-итоги
(last_survey_of_day), а last_or_after_noon — только начиная с 12:00.
"""
from datetime import time

import pytest

from bot.constants_questions import (
    ASK_POLICY_FIRST_UNTIL_ANSWERED,
    ASK_POLICY_LAST_OF_DAY,
    ASK_POLICY_LAST_OR_AFTER_NOON,
    ASK_POLICY_ONCE_PER_DAY,
    ASK_POLICY_PER_SURVEY,
    NOON_HOUR,
    SURVEY_SLOT_FIRST,
    SURVEY_SLOT_LAST,
    SURVEY_SLOT_MANUAL,
    SURVEY_SLOT_REGULAR,
    SURVEY_SLOT_SINGLE,
)
from bot.services.question_policy_service import (
    compute_survey_slot,
    should_ask_question_in_slot,
    slot_for_index,
)


ALL_SLOTS = [
    SURVEY_SLOT_FIRST,
    SURVEY_SLOT_REGULAR,
    SURVEY_SLOT_LAST,
    SURVEY_SLOT_SINGLE,
    SURVEY_SLOT_MANUAL,
]


# ---------- should_ask_question_in_slot: per_survey / once_per_day ----------

class TestShouldAskAlwaysOn:
    """per_survey и once_per_day задаются в любом слоте и в любое время."""

    @pytest.mark.parametrize("policy", [ASK_POLICY_PER_SURVEY, ASK_POLICY_ONCE_PER_DAY])
    @pytest.mark.parametrize("slot", ALL_SLOTS)
    def test_allowed_in_every_slot(self, policy, slot):
        assert should_ask_question_in_slot(policy, slot, time(9, 0)) is True

    @pytest.mark.parametrize("policy", [ASK_POLICY_PER_SURVEY, ASK_POLICY_ONCE_PER_DAY])
    def test_allowed_without_time(self, policy):
        assert should_ask_question_in_slot(policy, SURVEY_SLOT_FIRST, None) is True


# ---------- should_ask_question_in_slot: first_until_answered ----------

class TestShouldAskFirstUntilAnswered:
    """Разрешён в first/regular/single/manual; в last-only — нет."""

    @pytest.mark.parametrize("slot", [
        SURVEY_SLOT_FIRST, SURVEY_SLOT_REGULAR, SURVEY_SLOT_SINGLE, SURVEY_SLOT_MANUAL,
    ])
    def test_allowed_slots(self, slot):
        assert should_ask_question_in_slot(
            ASK_POLICY_FIRST_UNTIL_ANSWERED, slot, time(9, 0)
        ) is True

    def test_not_in_last_only_slot(self):
        assert should_ask_question_in_slot(
            ASK_POLICY_FIRST_UNTIL_ANSWERED, SURVEY_SLOT_LAST, time(9, 0)
        ) is False


# ---------- should_ask_question_in_slot: last_of_day ----------

class TestShouldAskLastOfDay:
    """Только last и single. Время не влияет."""

    @pytest.mark.parametrize("slot", [SURVEY_SLOT_LAST, SURVEY_SLOT_SINGLE])
    def test_allowed_slots(self, slot):
        assert should_ask_question_in_slot(
            ASK_POLICY_LAST_OF_DAY, slot, time(23, 0)
        ) is True

    @pytest.mark.parametrize("slot", [
        SURVEY_SLOT_FIRST, SURVEY_SLOT_REGULAR, SURVEY_SLOT_MANUAL,
    ])
    def test_blocked_slots(self, slot):
        # Даже поздним вечером — last_of_day строго по позиции слота.
        assert should_ask_question_in_slot(
            ASK_POLICY_LAST_OF_DAY, slot, time(23, 0)
        ) is False

    def test_morning_first_blocked_regression(self):
        """Регрессия исходного бага: утренний first НЕ задаёт last-вопросы."""
        assert should_ask_question_in_slot(
            ASK_POLICY_LAST_OF_DAY, SURVEY_SLOT_FIRST, time(9, 0)
        ) is False


# ---------- should_ask_question_in_slot: last_or_after_noon ----------

class TestShouldAskLastOrAfterNoon:
    """last/single всегда; иначе — только если local_now >= NOON_HOUR."""

    P = ASK_POLICY_LAST_OR_AFTER_NOON

    @pytest.mark.parametrize("slot", [SURVEY_SLOT_LAST, SURVEY_SLOT_SINGLE])
    def test_last_and_single_always_allowed(self, slot):
        # Даже рано утром — потому что это последний/единственный опрос дня.
        assert should_ask_question_in_slot(self.P, slot, time(7, 0)) is True

    @pytest.mark.parametrize("slot", [
        SURVEY_SLOT_FIRST, SURVEY_SLOT_REGULAR, SURVEY_SLOT_MANUAL,
    ])
    def test_before_noon_blocked(self, slot):
        assert should_ask_question_in_slot(self.P, slot, time(11, 59)) is False

    @pytest.mark.parametrize("slot", [
        SURVEY_SLOT_FIRST, SURVEY_SLOT_REGULAR, SURVEY_SLOT_MANUAL,
    ])
    def test_at_noon_allowed(self, slot):
        # Граница включительна: ровно 12:00 уже проходит.
        assert should_ask_question_in_slot(self.P, slot, time(NOON_HOUR, 0)) is True

    @pytest.mark.parametrize("slot", [
        SURVEY_SLOT_FIRST, SURVEY_SLOT_REGULAR, SURVEY_SLOT_MANUAL,
    ])
    def test_after_noon_allowed(self, slot):
        assert should_ask_question_in_slot(self.P, slot, time(15, 30)) is True

    def test_morning_first_blocked_regression(self):
        """Утренний first в 9:00 — productivity/concentration/hypomania НЕ задаём."""
        assert should_ask_question_in_slot(self.P, SURVEY_SLOT_FIRST, time(9, 0)) is False

    def test_no_time_degrades_to_last_only(self):
        # Без времени — консервативно: не утренний вопрос, кроме last/single.
        assert should_ask_question_in_slot(self.P, SURVEY_SLOT_FIRST, None) is False
        assert should_ask_question_in_slot(self.P, SURVEY_SLOT_LAST, None) is True
        assert should_ask_question_in_slot(self.P, SURVEY_SLOT_SINGLE, None) is True


# ---------- should_ask_question_in_slot: unknown ----------

class TestShouldAskUnknownPolicy:
    def test_unknown_policy_skipped(self):
        assert should_ask_question_in_slot("garbage", SURVEY_SLOT_SINGLE, time(12, 0)) is False


# ---------- slot_for_index ----------

class TestSlotForIndex:
    def test_zero_or_negative_total(self):
        assert slot_for_index(0, 0) == SURVEY_SLOT_SINGLE
        assert slot_for_index(-1, 0) == SURVEY_SLOT_SINGLE

    def test_single_slot(self):
        assert slot_for_index(1, 0) == SURVEY_SLOT_SINGLE

    def test_two_slots(self):
        assert slot_for_index(2, 0) == SURVEY_SLOT_FIRST
        assert slot_for_index(2, 1) == SURVEY_SLOT_LAST

    def test_three_slots(self):
        assert slot_for_index(3, 0) == SURVEY_SLOT_FIRST
        assert slot_for_index(3, 1) == SURVEY_SLOT_REGULAR
        assert slot_for_index(3, 2) == SURVEY_SLOT_LAST


# ---------- compute_survey_slot ----------

class TestComputeSurveySlot:
    def test_empty_schedule_is_single(self):
        assert compute_survey_slot([], time(9, 0)) == SURVEY_SLOT_SINGLE

    def test_one_time_is_single(self):
        assert compute_survey_slot([time(9, 0)], time(9, 0)) == SURVEY_SLOT_SINGLE

    def test_none_current_time_is_regular(self):
        # Без точного времени — консервативный regular (last не зададим случайно).
        assert compute_survey_slot(
            [time(9, 0), time(21, 0)], None
        ) == SURVEY_SLOT_REGULAR

    def test_first_slot(self):
        assert compute_survey_slot(
            [time(9, 0), time(15, 0), time(21, 0)], time(9, 0)
        ) == SURVEY_SLOT_FIRST

    def test_last_slot(self):
        assert compute_survey_slot(
            [time(9, 0), time(15, 0), time(21, 0)], time(21, 0)
        ) == SURVEY_SLOT_LAST

    def test_middle_slot_is_regular(self):
        assert compute_survey_slot(
            [time(9, 0), time(15, 0), time(21, 0)], time(15, 0)
        ) == SURVEY_SLOT_REGULAR

    def test_unsorted_schedule_still_resolves(self):
        # На вход дали неотсортированное расписание — функция сортирует сама.
        assert compute_survey_slot(
            [time(21, 0), time(9, 0)], time(9, 0)
        ) == SURVEY_SLOT_FIRST
        assert compute_survey_slot(
            [time(21, 0), time(9, 0)], time(21, 0)
        ) == SURVEY_SLOT_LAST
