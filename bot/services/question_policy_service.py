"""Политики показа вопросов и привязки даты ответа.

Содержит чистые функции для:
- определения слота опроса (first / regular / last / single / manual);
- расчёта target_date по политике (current_day / previous_day);
- проверки, нужно ли задавать вопрос в данном слоте (ask_policy);
- проверки, есть ли уже ответ за target_date (БД-зависимая часть);
- сборки финального списка опциональных шагов опроса с учётом всех политик.

Все даты считаются по локальной TZ пользователя — функции принимают
local_today/local_now извне, чтобы было удобно тестировать.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Sequence

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from bot.constants_questions import (
    ASK_POLICY_FIRST_UNTIL_ANSWERED,
    ASK_POLICY_LAST_OF_DAY,
    ASK_POLICY_ONCE_PER_DAY,
    ASK_POLICY_PER_SURVEY,
    OPTIONAL_QUESTION_ORDER,
    SURVEY_SLOT_FIRST,
    SURVEY_SLOT_LAST,
    SURVEY_SLOT_MANUAL,
    SURVEY_SLOT_REGULAR,
    SURVEY_SLOT_SINGLE,
    TARGET_DATE_CURRENT,
    TARGET_DATE_PREVIOUS,
    get_ask_policy,
    get_target_date_policy,
)
from bot.models import SurveyAnswer, SurveyEntry
from bot.services import survey_service

logger = logging.getLogger(__name__)


# ---------- Survey slot ----------

def compute_survey_slot(
    schedule_times: Sequence[time], current_time: time | None
) -> str:
    """Определяет слот опроса по расписанию уведомлений и текущему времени.

    schedule_times — отсортированные локальные времена расписания пользователя.
    current_time — локальное время отправки уведомления (момент,
    когда планировщик решил отправить пуш). Может быть None для ручного
    запуска — тогда вызывайте этот хелпер только из scheduler, а ручные
    запуски обрабатывайте через SURVEY_SLOT_MANUAL.

    Правила:
      - 1 слот в день -> single;
      - первый слот в дне -> first;
      - последний слот в дне -> last;
      - всё, что между -> regular.
    """
    if not schedule_times:
        # На всякий случай: нет расписания — считаем single, чтобы пройти
        # last_survey вопросы тоже (по сути ручной режим = single).
        return SURVEY_SLOT_SINGLE
    if len(schedule_times) == 1:
        return SURVEY_SLOT_SINGLE

    sorted_times = sorted(schedule_times)
    if current_time is None:
        # Без точного времени нельзя определить — возвращаем regular как
        # консервативный выбор (last-вопросы не зададим случайно).
        return SURVEY_SLOT_REGULAR

    if _times_equal_minute(current_time, sorted_times[0]):
        return SURVEY_SLOT_FIRST
    if _times_equal_minute(current_time, sorted_times[-1]):
        return SURVEY_SLOT_LAST
    return SURVEY_SLOT_REGULAR


def slot_for_index(total_slots: int, idx: int) -> str:
    """То же, но по индексу слота, если планировщик уже знает позицию.
    Используется при постановке расписания: каждому job-у назначаем slot."""
    if total_slots <= 0:
        return SURVEY_SLOT_SINGLE
    if total_slots == 1:
        return SURVEY_SLOT_SINGLE
    if idx == 0:
        return SURVEY_SLOT_FIRST
    if idx == total_slots - 1:
        return SURVEY_SLOT_LAST
    return SURVEY_SLOT_REGULAR


def _times_equal_minute(a: time, b: time) -> bool:
    return a.hour == b.hour and a.minute == b.minute


# ---------- target date ----------

def get_target_date_for_question(local_today: date, target_policy: str) -> date:
    """Возвращает дату, к которой относится ответ."""
    if target_policy == TARGET_DATE_PREVIOUS:
        return local_today - timedelta(days=1)
    return local_today


# ---------- should ask ----------

# Слоты, в которых разрешено задавать first_survey_until_answered.
# Включает regular и manual, чтобы повторные попытки в течение того же дня
# работали, а пользователь, запустивший опрос вручную, тоже мог ответить.
_FIRST_ALLOWED_SLOTS = frozenset({
    SURVEY_SLOT_FIRST,
    SURVEY_SLOT_REGULAR,
    SURVEY_SLOT_SINGLE,
    SURVEY_SLOT_MANUAL,
})

# Слоты, в которых разрешено задавать last_survey_of_day.
# manual в эти слоты НЕ входит — иначе нельзя надёжно определить «вечерний»
# слот ручного запуска.
_LAST_ALLOWED_SLOTS = frozenset({SURVEY_SLOT_LAST, SURVEY_SLOT_SINGLE})


def should_ask_question_in_slot(ask_policy: str, survey_slot: str) -> bool:
    """Можно ли в данном слоте задавать вопрос с этой политикой.
    Игнорирует наличие ответа — это отдельная проверка.
    """
    if ask_policy == ASK_POLICY_PER_SURVEY:
        return True
    if ask_policy == ASK_POLICY_ONCE_PER_DAY:
        return True
    if ask_policy == ASK_POLICY_FIRST_UNTIL_ANSWERED:
        return survey_slot in _FIRST_ALLOWED_SLOTS
    if ask_policy == ASK_POLICY_LAST_OF_DAY:
        return survey_slot in _LAST_ALLOWED_SLOTS
    # Неизвестная политика — на всякий случай не задаём, чтобы не дёргать
    # пользователя зря.
    logger.warning("Unknown ask_policy=%s — skip", ask_policy)
    return False


# ---------- has answer ----------

def has_answer_for_question_date(
    session: Session, user_id: int, question_code: str, target_date: date
) -> bool:
    """Есть ли у пользователя ответ на вопрос за target_date.

    Различает источник хранения:
    - sleep      -> SurveyEntry с sleep_type='main' за target_date;
    - medications-> SurveyEntry с medication_filled=true за target_date;
    - остальные  -> SurveyAnswer с (question_code, log_date=target_date).
    """
    if question_code == "sleep":
        return survey_service.has_main_sleep_for_date(
            session, user_id, target_date
        )
    if question_code == "medications":
        return survey_service.has_medication_for_date(
            session, user_id, target_date
        )

    row = session.scalar(
        select(SurveyAnswer.id)
        .join(SurveyEntry, SurveyEntry.id == SurveyAnswer.entry_id)
        .where(
            and_(
                SurveyEntry.user_id == user_id,
                SurveyAnswer.question_code == question_code,
                SurveyAnswer.log_date == target_date,
            )
        )
        .limit(1)
    )
    return row is not None


# ---------- step plan ----------

@dataclass(frozen=True)
class SurveyStep:
    """Один опциональный шаг опроса (после расчёта политик).

    code           — код вопроса из question_catalog;
    target_date    — дата, к которой относится ответ (для last_phone — вчера);
    ask_policy     — для логов/диагностики;
    """
    code: str
    target_date: date
    ask_policy: str


def build_daily_survey_steps(
    session: Session,
    user_id: int,
    enabled_codes: set[str],
    survey_slot: str,
    local_today: date,
) -> list[SurveyStep]:
    """Собирает список опциональных шагов для текущего запуска опроса.

    Учитывает:
      - порядок из OPTIONAL_QUESTION_ORDER;
      - ask_policy (через should_ask_question_in_slot);
      - наличие ответа за target_date для once_per_day /
        first_survey_until_answered / last_survey_of_day.

    enabled_codes — включённые пользователем опциональные коды.
    """
    plan: list[SurveyStep] = []
    for code in OPTIONAL_QUESTION_ORDER:
        if code not in enabled_codes:
            continue

        ask_policy = get_ask_policy(code)
        if not should_ask_question_in_slot(ask_policy, survey_slot):
            logger.info(
                "skip code=%s: ask_policy=%s не подходит для slot=%s",
                code, ask_policy, survey_slot,
            )
            continue

        target_policy = get_target_date_policy(code)
        target_date = get_target_date_for_question(local_today, target_policy)

        # Для политик, привязанных к дате, не дёргаем повторно если ответ уже есть.
        if ask_policy in (
            ASK_POLICY_ONCE_PER_DAY,
            ASK_POLICY_FIRST_UNTIL_ANSWERED,
            ASK_POLICY_LAST_OF_DAY,
        ):
            if has_answer_for_question_date(
                session, user_id, code, target_date
            ):
                logger.info(
                    "skip code=%s: уже есть ответ за %s",
                    code, target_date,
                )
                continue

        plan.append(
            SurveyStep(code=code, target_date=target_date, ask_policy=ask_policy)
        )
    return plan
