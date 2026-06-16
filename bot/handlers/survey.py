"""Пошаговый опрос на ConversationHandler.

Учитывает политики показа вопросов (см. bot.services.question_policy_service):
- сборка опционального плана делается через build_daily_survey_steps;
- late_phone/physical_activity/stress_events/spending имеют свои option_codes
  и сохраняются сразу после ответа (чтобы повторный опрос в тот же день
  корректно увидел, что ответ уже есть);
- physical_activity — двухшаговый: «Да/Нет» -> длительность, итог JSON.
"""

import json
import logging
import re

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.config import config
from bot.constants import (
    MAX_COMMENT_LENGTH,
    MEDICATION_LABELS,
    SLEEP_DURATION_LABELS,
    SLEEP_PROBLEM_LABELS,
    SLEEP_QUALITY_LABELS,
    SOURCE_MANUAL,
    SOURCE_REMINDER,
    SOURCE_SCHEDULED,
)
from bot.constants_questions import (
    CRISIS_MESSAGE,
    PHYSICAL_ACTIVITY_DURATION_LABELS,
    PHYSICAL_ACTIVITY_DURATION_QUESTION,
    QUESTION_DEFINITIONS,
    SUICIDAL_HIGH_RISK_INDEX,
    SURVEY_SLOT_MANUAL,
    SURVEY_SLOT_SINGLE,
    option_codes_for,
    options_for,
)
from bot.database import session_scope
from bot.keyboards.custom_question_keyboards import (
    cq_boolean_keyboard,
    cq_scale_0_5_keyboard,
)
from bot.keyboards.survey_keyboards import (
    anxiety_keyboard,
    comment_skip_keyboard,
    energy_keyboard,
    medication_keyboard,
    mood_keyboard,
    optional_question_keyboard,
    physical_activity_duration_keyboard,
    sleep_duration_keyboard,
    sleep_problems_keyboard,
    sleep_quality_keyboard,
    unfinished_survey_keyboard,
)
from sqlalchemy.exc import IntegrityError

from bot.services import (
    custom_question_service,
    question_policy_service,
    question_settings_service,
    reminder_service,
    survey_service,
)
from bot.texts import (
    ERR_COMMENT_TOO_LONG,
    ERR_DB,
    Q_ANXIETY,
    Q_COMMENT,
    Q_ENERGY,
    Q_MEDICATION,
    Q_MOOD,
    Q_SLEEP_DURATION,
    Q_SLEEP_PROBLEMS,
    Q_SLEEP_QUALITY,
    SAVED,
    SKIP_MEDICATION_TODAY,
    SKIP_SLEEP_TODAY,
    SURVEY_INTRO,
    UNFINISHED_SURVEY,
)
from bot.utils.time_utils import (
    DEFAULT_SLEEP_ASK_TIME,
    can_ask_sleep_question,
    user_local_date,
    user_local_now,
)

logger = logging.getLogger(__name__)

(
    MOOD,
    ANXIETY,
    ENERGY,
    SLEEP_DURATION,
    SLEEP_QUALITY,
    SLEEP_PROBLEMS,
    MEDICATION,
    OPTIONAL_Q,
    PHYS_ACT_DURATION,
    CUSTOM_Q,
    COMMENT,
) = range(11)


# ---------- helpers ----------

def _is_active_survey(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.user_data.get("survey"))


# Коды, у которых есть отдельный базовый шаг в опросе — их не нужно дублировать
# через опциональный механизм, даже если пользователь включил их в настройках.
# irritability/impulsivity больше не имеют базовых шагов — задаются как опциональные.
# menstrual_cycle вынесен в отдельный домен (bot/services/menstrual_cycle_service.py)
# и не задаётся в ежедневном опросе, даже если пользователь когда-то включил его
# в user_question_settings.
_HANDLED_AS_BASE = {"medications", "menstrual_cycle"}


def _init_survey(
    context: ContextTypes.DEFAULT_TYPE, source: str, tg_id: int, survey_slot: str
) -> None:
    """Инициализирует state опроса. Определяет:
    - survey_slot (first/regular/last/single/manual) — влияет на политики;
    - заполнены ли сон и лекарства за локальную дату (для скипа базовых блоков);
    - список включенных опциональных вопросов и порядок их прохождения;
    - какие custom-вопросы подходят по частоте показа для текущего опроса.
    """
    has_sleep = False
    has_med = False
    local_date = None
    optional_codes: list[str] = []
    custom_qs: list[dict] = []
    # Дефолты на случай сбоя БД внутри try: иначе except (ниже) не задаёт
    # skip_sleep_block/plan_serialized, и сборка survey-state упала бы с
    # NameError — а survey_start_callback к этому моменту уже сбросил старый
    # state (pop), оставив пользователя совсем без опроса.
    skip_sleep_block = True  # безопасно: просто пропустить блок сна
    plan_serialized: list[dict] = []  # без опциональных шагов
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_now = user_local_now(user.timezone)
            local_date = local_now.date()
            has_sleep = survey_service.has_main_sleep_for_date(
                session, user.id, local_date
            )
            has_med = survey_service.has_medication_for_date(
                session, user.id, local_date
            )

            # Решаем, можно ли сейчас задавать блок сна. После полуночи
            # локальная дата уже сменилась, но пользователь мог ещё не лечь —
            # тогда «как спал?» не имеет смысла. Берём порог = min(start_time,
            # DEFAULT_SLEEP_ASK_TIME=10:00). first_survey_time = start_time
            # пользователя (расписание уведомлений всегда начинается с него,
            # см. compute_schedule в bot/utils/time_utils.py).
            user_settings = survey_service.get_settings(session, user.id)
            first_survey_time = (
                user_settings.start_time if user_settings is not None else None
            )
            sleep_allowed = can_ask_sleep_question(
                local_now=local_now,
                first_survey_time=first_survey_time,
                has_main_sleep_today=has_sleep,
            )
            # skip_sleep объединяет "уже есть запись" и "слишком рано спрашивать".
            skip_sleep_block = not sleep_allowed
            threshold = (
                min(first_survey_time, DEFAULT_SLEEP_ASK_TIME)
                if first_survey_time is not None else DEFAULT_SLEEP_ASK_TIME
            )
            if has_sleep:
                logger.info(
                    "sleep skipped because already exists for date "
                    "tg=%s date=%s", tg_id, local_date,
                )
            elif not sleep_allowed:
                logger.info(
                    "sleep skipped because before sleep_question_start_time "
                    "tg=%s tz=%s local_now=%s threshold=%s",
                    tg_id, user.timezone,
                    local_now.strftime("%Y-%m-%d %H:%M"),
                    threshold.strftime("%H:%M"),
                )
            else:
                logger.info(
                    "sleep asked after sleep_question_start_time "
                    "tg=%s tz=%s local_now=%s threshold=%s",
                    tg_id, user.timezone,
                    local_now.strftime("%Y-%m-%d %H:%M"),
                    threshold.strftime("%H:%M"),
                )
            enabled = question_settings_service.enabled_optional_codes(
                session, user.id
            )
            # _HANDLED_AS_BASE (medications) исключаем — у них отдельный
            # базовый шаг. Остальное прокидываем в политики.
            policy_input = {c for c in enabled if c not in _HANDLED_AS_BASE}
            plan = question_policy_service.build_daily_survey_steps(
                session=session,
                user_id=user.id,
                enabled_codes=policy_input,
                survey_slot=survey_slot,
                local_today=local_date,
                # Время открытия опроса — для last_or_after_noon (порог 12:00).
                local_now=local_now.time(),
            )
            plan_serialized = [
                {
                    "code": step.code,
                    "target_date": step.target_date.isoformat(),
                    "ask_policy": step.ask_policy,
                }
                for step in plan
            ]
            # Индекс текущего опроса в локальный день и признак "последний".
            already_today = survey_service.count_main_entries_for_date(
                session, user.id, local_date
            )
            today_survey_index = already_today + 1
            settings_obj = survey_service.get_settings(session, user.id)
            freq_per_day = settings_obj.frequency_per_day if settings_obj else 1
            # Последний — если этот опрос исчерпывает дневное расписание
            # (или превышает его, что бывает при ручных опросах сверх плана).
            is_last_today = today_survey_index >= max(freq_per_day, 1)

            # Custom-вопросы: фильтруем по частоте.
            enabled_customs = custom_question_service.get_enabled(session, user.id)
            for q in enabled_customs:
                if not custom_question_service.should_ask(
                    q, local_date, today_survey_index, is_last_today,
                    freq_per_day=freq_per_day,
                ):
                    continue
                custom_qs.append({
                    "id": q.id,
                    "text": q.question_text,
                    "type": q.answer_type,
                })
            # Сразу отмечаем, что эти вопросы показаны сегодня — даже если опрос
            # не дойдёт до конца. Это совпадает с уточнением "по дате последнего
            # показа в опросе", а не "по дате ответа".
            if custom_qs:
                custom_question_service.mark_asked(
                    session, [c["id"] for c in custom_qs], local_date
                )
    except Exception:
        logger.exception("Не удалось определить состояние блоков сна/лекарств")
        today_survey_index = 1
        is_last_today = False

    context.user_data["survey"] = {
        "source": source,
        "survey_slot": survey_slot,
        "sleep_problems": set(),
        # skip_sleep теперь = "уже записан за сегодня" ИЛИ "слишком рано
        # спрашивать (до sleep_question_start_time)". См. _init_survey выше.
        "skip_sleep": skip_sleep_block,
        "skip_medication": has_med,
        "local_date": local_date,
        # План шагов: list[dict(code, target_date_iso, ask_policy)]. Сохраняем
        # сериализованным, чтобы не таскать SurveyStep по user_data.
        "optional_plan": plan_serialized,
        "optional_idx": 0,
        # Список выполненных шагов (для итогового summary).
        # dict(code, target_date_iso, display, persisted=True|False)
        "optional_answers": [],
        # Промежуточное состояние для двухшагового physical_activity.
        # None или {"code": "physical_activity", "target_date_iso": "..."}.
        "pa_pending": None,
        "custom_questions": custom_qs,
        "custom_idx": 0,
        "custom_answers": [],
        "high_risk_triggered": False,
    }
    if plan_serialized:
        logger.info(
            "Опрос tg=%s slot=%s: %d опциональных шагов: %s",
            tg_id, survey_slot, len(plan_serialized),
            ", ".join(step["code"] for step in plan_serialized),
        )
    else:
        logger.info(
            "Опрос tg=%s slot=%s: опциональных шагов нет",
            tg_id, survey_slot,
        )
    if custom_qs:
        logger.info(
            "Опрос tg=%s: подключены custom-вопросы (%d шт, опрос дня #%d, last=%s)",
            tg_id, len(custom_qs), today_survey_index, is_last_today,
        )


async def _send_question(update: Update, text: str, markup) -> None:
    """Шлет вопрос как новое сообщение независимо от типа update."""
    if update.callback_query is not None:
        await update.callback_query.message.reply_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


# ---------- entry points ----------

def _parse_slot_from_callback(data: str) -> str:
    """Из 'survey:start' или 'survey:start:<slot>' возвращает slot.
    Старый формат без слота -> SURVEY_SLOT_SINGLE (безопасный fallback)."""
    from bot.constants_questions import ALL_SURVEY_SLOTS

    parts = data.split(":")
    if len(parts) >= 3 and parts[2] in ALL_SURVEY_SLOTS:
        return parts[2]
    return SURVEY_SLOT_SINGLE


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if _is_active_survey(context):
        await update.message.reply_text(
            UNFINISHED_SURVEY, reply_markup=unfinished_survey_keyboard()
        )
        return ConversationHandler.END
    _init_survey(
        context, SOURCE_MANUAL, update.effective_user.id, SURVEY_SLOT_MANUAL
    )
    await update.message.reply_text(SURVEY_INTRO)
    await update.message.reply_text(Q_MOOD, reply_markup=mood_keyboard())
    return MOOD


async def survey_start_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Запуск опроса по кнопке из планового уведомления.

    Кнопка из напоминания всегда начинает новый опрос: если пользователь
    застрял в незавершённом диалоге (бросил прошлый опрос на полушаге), мы
    молча прерываем его и стартуем заново. Раньше при allow_reentry=False
    застрявший пользователь не мог запустить опрос вовсе — кнопка «не
    работала». _init_survey пересоздаёт survey-state с нуля, так что сбросить
    старый безопасно. Защита _is_active_survey остаётся на ручном /add.
    """
    query = update.callback_query
    await query.answer()
    if _is_active_survey(context):
        logger.info(
            "Кнопка опроса из напоминания: прерываю незавершённый диалог tg=%s",
            update.effective_user.id,
        )
        context.user_data.pop("survey", None)
    survey_slot = _parse_slot_from_callback(query.data)
    # Источник: если есть pending в статусе reminder_sent — это reminder.
    source = SOURCE_SCHEDULED
    try:
        with session_scope() as session:
            user = survey_service.get_user_by_tg(session, update.effective_user.id)
            if user is not None:
                pending = survey_service.latest_pending(session, user.id)
                if pending is not None and pending.status == "reminder_sent":
                    source = SOURCE_REMINDER
    except Exception:
        logger.exception("Ошибка определения source при запуске опроса")
    _init_survey(context, source, update.effective_user.id, survey_slot)
    await query.message.reply_text(Q_MOOD, reply_markup=mood_keyboard())
    return MOOD


async def unfinished_choice_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]
    if choice == "resume":
        # Просто покажем текущий шаг — для простоты MVP начинаем сначала.
        # Состояния шага мы не сохраняем явно; перезапускаем с настроения,
        # сохраняя уже введенные значения.
        await query.message.reply_text(
            "Продолжаем. Ответь на следующий вопрос."
        )
        await query.message.reply_text(Q_MOOD, reply_markup=mood_keyboard())
        return MOOD
    else:
        context.user_data.pop("survey", None)
        _init_survey(
            context, SOURCE_MANUAL, update.effective_user.id, SURVEY_SLOT_MANUAL
        )
        await query.message.reply_text(Q_MOOD, reply_markup=mood_keyboard())
        return MOOD


# ---------- steps ----------

async def mood_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    value = int(query.data.split(":")[1])
    context.user_data["survey"]["mood"] = value
    await query.edit_message_text(f"{Q_MOOD}\n\nВыбрано: {value}")
    await query.message.reply_text(Q_ANXIETY, reply_markup=anxiety_keyboard())
    return ANXIETY


async def anxiety_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    value = int(query.data.split(":")[1])
    context.user_data["survey"]["anxiety"] = value
    await query.edit_message_text(f"{Q_ANXIETY}\n\nВыбрано: {value}")
    await query.message.reply_text(Q_ENERGY, reply_markup=energy_keyboard())
    return ENERGY


async def energy_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    value = int(query.data.split(":")[1])
    context.user_data["survey"]["energy"] = value
    await query.edit_message_text(f"{Q_ENERGY}\n\nВыбрано: {value}")
    # irritability/impulsivity — теперь опциональные (см. QUESTION_DEFINITIONS).
    # После базовых шкал сразу идём к блоку сна (или к опциональным/комменту,
    # если сон/лекарства уже заполнены за сегодня).
    return await _after_base_scales(update, context)


async def _after_base_scales(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Решает, какой следующий шаг показать после блока шкал — с учётом скипов."""
    survey = context.user_data["survey"]
    target = update.callback_query.message if update.callback_query else update.message

    if survey.get("skip_sleep"):
        logger.info(
            "Скипаем блок сна (уже есть main за %s)", survey.get("local_date")
        )
        await target.reply_text(SKIP_SLEEP_TODAY)
        return await _ask_medication_or_skip(update, context)

    await target.reply_text(Q_SLEEP_DURATION, reply_markup=sleep_duration_keyboard())
    return SLEEP_DURATION


async def _ask_medication_or_skip(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Запрашивает блок лекарств или скипает его, переходя дальше."""
    survey = context.user_data["survey"]
    target = update.callback_query.message if update.callback_query else update.message

    if survey.get("skip_medication"):
        logger.info(
            "Скипаем блок лекарств (уже есть запись за %s)", survey.get("local_date")
        )
        await target.reply_text(SKIP_MEDICATION_TODAY)
        return await _next_optional_or_comment(update, context)

    await target.reply_text(Q_MEDICATION, reply_markup=medication_keyboard())
    return MEDICATION


async def _next_optional_or_comment(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """После базового блока — задаём следующий опциональный или переходим к custom/комменту."""
    survey = context.user_data["survey"]
    target = update.callback_query.message if update.callback_query else update.message

    plan: list[dict] = survey.get("optional_plan", [])
    idx: int = survey.get("optional_idx", 0)

    if idx >= len(plan):
        return await _next_custom_or_comment(update, context)

    step = plan[idx]
    code = step["code"]
    title = QUESTION_DEFINITIONS.get(code, {}).get("question_text", code)
    question_text, options = options_for(code, title)
    await target.reply_text(
        question_text, reply_markup=optional_question_keyboard(options)
    )
    return OPTIONAL_Q


async def _next_custom_or_comment(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Задаёт следующий пользовательский вопрос. Когда custom закончились — комментарий."""
    survey = context.user_data["survey"]
    target = update.callback_query.message if update.callback_query else update.message

    customs: list[dict] = survey.get("custom_questions", [])
    idx: int = survey.get("custom_idx", 0)

    if idx >= len(customs):
        await target.reply_text(Q_COMMENT, reply_markup=comment_skip_keyboard())
        return COMMENT

    q = customs[idx]
    text = q["text"]
    qtype = q["type"]

    if qtype == "scale_0_5":
        await target.reply_text(
            f"{text}\n\nВыберите значение от 0 до 5.",
            reply_markup=cq_scale_0_5_keyboard(),
        )
    elif qtype == "boolean":
        await target.reply_text(text, reply_markup=cq_boolean_keyboard())
    elif qtype == "text":
        await target.reply_text(f"Опишите коротко:\n«{text}»")
    else:
        # неизвестный тип — пропускаем
        logger.warning("Unknown custom answer_type: %s, skip", qtype)
        survey["custom_idx"] = idx + 1
        return await _next_custom_or_comment(update, context)
    return CUSTOM_Q


async def custom_question_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Обработка ответа на пользовательский вопрос.

    Принимает три варианта callback_data:
    - cqa:scale:N  (0..5)
    - cqa:bool:0|1
    Или текстовое сообщение для вопросов типа text.
    """
    survey = context.user_data["survey"]
    customs: list[dict] = survey.get("custom_questions", [])
    idx: int = survey.get("custom_idx", 0)

    if idx >= len(customs):
        # Гонка — просто переходим к комментарию.
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text(Q_COMMENT, reply_markup=comment_skip_keyboard())
        return COMMENT

    q = customs[idx]
    qtype = q["type"]

    if update.callback_query is not None:
        query = update.callback_query
        await query.answer()
        data = query.data
        if qtype == "scale_0_5" and data.startswith("cqa:scale:"):
            try:
                value = int(data.split(":")[2])
            except (ValueError, IndexError):
                return CUSTOM_Q
            if not (0 <= value <= 5):
                return CUSTOM_Q
            display = str(value)
            survey["custom_answers"].append({
                "id": q["id"], "type": qtype, "value": value, "display": display,
            })
            try:
                await query.edit_message_text(
                    f"{q['text']}\n\nВыбрано: {display}"
                )
            except Exception:
                pass
        elif qtype == "boolean" and data.startswith("cqa:bool:"):
            try:
                value = bool(int(data.split(":")[2]))
            except (ValueError, IndexError):
                return CUSTOM_Q
            display = "Да" if value else "Нет"
            survey["custom_answers"].append({
                "id": q["id"], "type": qtype, "value": value, "display": display,
            })
            try:
                await query.edit_message_text(f"{q['text']}\n\nОтвет: {display}")
            except Exception:
                pass
        else:
            # callback не подходит к типу текущего вопроса — игнорируем.
            return CUSTOM_Q
    else:
        # Текстовый ответ для qtype == 'text'.
        if qtype != "text":
            return CUSTOM_Q
        text = (update.message.text or "").strip()
        if not text:
            await update.message.reply_text("Текст пустой. Попробуйте ещё раз:")
            return CUSTOM_Q
        if len(text) > custom_question_service.MAX_TEXT_ANSWER_LEN:
            await update.message.reply_text(
                f"Слишком длинно (макс. {custom_question_service.MAX_TEXT_ANSWER_LEN} симв). "
                "Сократите:"
            )
            return CUSTOM_Q
        survey["custom_answers"].append({
            "id": q["id"], "type": qtype, "value": text,
            "display": text if len(text) <= 60 else text[:57] + "…",
        })

    survey["custom_idx"] = idx + 1
    return await _next_custom_or_comment(update, context)


async def optional_question_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Обработка ответа на опциональный вопрос.

    Спец-обработка:
    - physical_activity: при "Да" уходим в PHYS_ACT_DURATION; при "Нет"
      записываем JSON-ответ {done: false, duration: null} и идём дальше.
    - вопросы с option_codes (late_phone/stress_events/spending) сохраняются
      с answer_value = код варианта.
    - остальные — старая логика (answer_value = текст, answer_numeric = idx).

    Сохранение в БД делается в _finish_survey — но с правильным log_date,
    взятым из плана опроса (для late_phone это previous_day).
    """
    query = update.callback_query
    await query.answer()
    try:
        choice_idx = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return OPTIONAL_Q

    survey = context.user_data["survey"]
    idx: int = survey.get("optional_idx", 0)
    plan: list[dict] = survey.get("optional_plan", [])
    if idx >= len(plan):
        # Из-за гонок — просто переходим к комментарию.
        await query.message.reply_text(Q_COMMENT, reply_markup=comment_skip_keyboard())
        return COMMENT

    step = plan[idx]
    code = step["code"]
    target_date_iso = step["target_date"]
    _, options = options_for(code)
    if not (0 <= choice_idx < len(options)):
        return OPTIONAL_Q
    answer_text = options[choice_idx]
    question_text = QUESTION_DEFINITIONS.get(code, {}).get("question_text", code)

    # --- physical_activity: первый шаг "Да/Нет" ---
    if code == "physical_activity":
        if choice_idx == 0:
            # "Да" — спросим длительность, ничего пока не записываем в state.
            survey["pa_pending"] = {
                "code": code,
                "target_date_iso": target_date_iso,
            }
            try:
                await query.edit_message_text(
                    f"{question_text}\n\nВыбрано: {answer_text}"
                )
            except Exception:
                pass
            await query.message.reply_text(
                PHYSICAL_ACTIVITY_DURATION_QUESTION,
                reply_markup=physical_activity_duration_keyboard(),
            )
            return PHYS_ACT_DURATION
        else:
            # "Нет" — записываем JSON и идём дальше.
            payload = json.dumps({"done": False, "duration": None})
            survey["optional_answers"].append({
                "code": code,
                "answer_value": payload,
                "answer_index": None,
                "target_date_iso": target_date_iso,
                "display": "Нет",
            })
            survey["optional_idx"] = idx + 1
            try:
                await query.edit_message_text(
                    f"{question_text}\n\nВыбрано: {answer_text}"
                )
            except Exception:
                pass
            return await _next_optional_or_comment(update, context)

    # --- Вопросы с option_codes (late_phone, stress_events, spending) ---
    codes_list = option_codes_for(code)
    if codes_list is not None:
        answer_value = codes_list[choice_idx]
    else:
        answer_value = answer_text

    survey["optional_answers"].append({
        "code": code,
        "answer_value": answer_value,
        "answer_index": choice_idx,
        "target_date_iso": target_date_iso,
        "display": answer_text,
    })
    survey["optional_idx"] = idx + 1

    try:
        await query.edit_message_text(f"{question_text}\n\nВыбрано: {answer_text}")
    except Exception:
        pass

    # Hook: suicidal high-risk — поставим флаг, сообщение покажем после finish.
    if code == "suicidal_thoughts" and choice_idx == SUICIDAL_HIGH_RISK_INDEX:
        survey["high_risk_triggered"] = True
        logger.warning(
            "Suicidal high-risk ответ tg=%s — будет показано кризисное сообщение",
            update.effective_user.id,
        )

    return await _next_optional_or_comment(update, context)


async def physical_activity_duration_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Второй шаг physical_activity: выбор длительности. Записывает JSON
    и продолжает опрос."""
    query = update.callback_query
    await query.answer()
    survey = context.user_data["survey"]
    pending = survey.get("pa_pending")
    if not pending:
        logger.warning("pa_pending пуст при ответе на длительность активности")
        return await _next_optional_or_comment(update, context)

    try:
        duration_key = query.data.split(":", 1)[1]
    except IndexError:
        return PHYS_ACT_DURATION
    if duration_key not in PHYSICAL_ACTIVITY_DURATION_LABELS:
        return PHYS_ACT_DURATION

    code = pending["code"]
    target_date_iso = pending["target_date_iso"]
    duration_label = PHYSICAL_ACTIVITY_DURATION_LABELS[duration_key]
    payload = json.dumps({"done": True, "duration": duration_key})

    survey["optional_answers"].append({
        "code": code,
        "answer_value": payload,
        "answer_index": None,
        "target_date_iso": target_date_iso,
        "display": f"Да, {duration_label.lower()}",
    })
    survey["pa_pending"] = None
    survey["optional_idx"] = survey.get("optional_idx", 0) + 1
    try:
        await query.edit_message_text(
            f"{PHYSICAL_ACTIVITY_DURATION_QUESTION}\n\nВыбрано: {duration_label}"
        )
    except Exception:
        pass
    return await _next_optional_or_comment(update, context)


async def sleep_duration_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    context.user_data["survey"]["sleep_duration_category"] = key
    await query.edit_message_text(
        f"{Q_SLEEP_DURATION}\n\nВыбрано: {SLEEP_DURATION_LABELS.get(key, key)}"
    )
    await query.message.reply_text(
        Q_SLEEP_QUALITY, reply_markup=sleep_quality_keyboard()
    )
    return SLEEP_QUALITY


async def sleep_quality_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    context.user_data["survey"]["sleep_quality"] = key
    await query.edit_message_text(
        f"{Q_SLEEP_QUALITY}\n\nВыбрано: {SLEEP_QUALITY_LABELS.get(key, key)}"
    )
    selected: set[str] = context.user_data["survey"]["sleep_problems"]
    await query.message.reply_text(
        Q_SLEEP_PROBLEMS, reply_markup=sleep_problems_keyboard(selected)
    )
    return SLEEP_PROBLEMS


async def sleep_problems_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    selected: set[str] = context.user_data["survey"]["sleep_problems"]

    if key == "__none__":
        selected.clear()
        await query.edit_message_text(f"{Q_SLEEP_PROBLEMS}\n\nВыбрано: нет")
        return await _ask_medication_or_skip(update, context)

    if key == "__done__":
        if selected:
            chosen = ", ".join(SLEEP_PROBLEM_LABELS[k] for k in selected)
        else:
            chosen = "нет"
        await query.edit_message_text(f"{Q_SLEEP_PROBLEMS}\n\nВыбрано: {chosen}")
        return await _ask_medication_or_skip(update, context)

    # toggle
    if key in selected:
        selected.remove(key)
    else:
        selected.add(key)
    await query.edit_message_reply_markup(reply_markup=sleep_problems_keyboard(selected))
    return SLEEP_PROBLEMS


async def medication_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    context.user_data["survey"]["medication_taken"] = key
    await query.edit_message_text(
        f"{Q_MEDICATION}\n\nВыбрано: {MEDICATION_LABELS.get(key, key)}"
    )
    return await _next_optional_or_comment(update, context)


async def comment_text_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    text = (update.message.text or "").strip()
    if len(text) > MAX_COMMENT_LENGTH:
        await update.message.reply_text(ERR_COMMENT_TOO_LONG)
        return COMMENT
    context.user_data["survey"]["comment"] = text or None
    return await _finish_survey(update, context)


async def comment_skip_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["survey"]["comment"] = None
    await query.edit_message_text(f"{Q_COMMENT}\n\nПропущено.")
    return await _finish_survey(update, context)


async def _finish_survey(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    from datetime import date as _date

    data = context.user_data.get("survey", {})
    # Разворачиваем sleep_problems в булевы поля
    problems: set[str] = data.pop("sleep_problems", set())
    for key in (
        "hard_to_fall_asleep",
        "early_wakeup",
        "frequent_wakeups",
        "little_sleep_but_feel_good",
        "long_sleep_not_restored",
    ):
        data[key] = key in problems

    skip_sleep = data.pop("skip_sleep", False)
    skip_medication = data.pop("skip_medication", False)
    local_date = data.pop("local_date", None)
    optional_answers = data.pop("optional_answers", [])
    custom_answers = data.pop("custom_answers", [])
    high_risk_triggered = data.pop("high_risk_triggered", False)
    # Ключи, не нужные в save_entry.
    data.pop("survey_slot", None)
    data.pop("optional_plan", None)
    data.pop("optional_idx", None)
    data.pop("pa_pending", None)
    data.pop("custom_questions", None)
    data.pop("custom_idx", None)

    # Маркируем тип записи. Если сон скипнули — sleep_type='none', поля сна
    # фактически отсутствуют (save_entry проставит дефолты 'skipped').
    # Если лекарства скипнули — medication_filled=false, medication_taken
    # остаётся 'not_applicable' (save_entry проставит).
    data["sleep_type"] = "none" if skip_sleep else "main"
    data["medication_filled"] = not skip_medication

    tg_id = update.effective_user.id

    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            if local_date is None:
                local_date = user_local_date(user.timezone)
            pending = survey_service.latest_pending(session, user.id)
            pending_id = pending.id if pending is not None else None
            # Двойная проверка: между _init_survey и сейчас могла появиться
            # запись (другой опрос/доп. сон). Если main уже есть — пишем 'none',
            # чтобы не упасть на уникальном индексе.
            if data["sleep_type"] == "main" and survey_service.has_main_sleep_for_date(
                session, user.id, local_date
            ):
                logger.info("Гонка: main-сон уже есть, пишем sleep_type='none'")
                data["sleep_type"] = "none"
                data["sleep_duration_category"] = "skipped"
                data["sleep_quality"] = "skipped"
            if data["medication_filled"] and survey_service.has_medication_for_date(
                session, user.id, local_date
            ):
                logger.info("Гонка: лекарства уже есть, пишем medication_filled=false")
                data["medication_filled"] = False
                data["medication_taken"] = "not_applicable"
            entry = survey_service.save_entry(session, user.id, data, local_date)
            # Сохраняем опциональные ответы. Идемпотентно: если параллельный
            # опрос уже сохранил ответ за target_date — пропускаем (важно для
            # once_per_day / last_of_day, чтобы не плодить дубли).
            for ans in optional_answers:
                code = ans["code"]
                target_date = _date.fromisoformat(ans["target_date_iso"])
                if question_policy_service.has_answer_for_question_date(
                    session, user.id, code, target_date
                ):
                    logger.info(
                        "skip save code=%s: уже есть ответ за %s",
                        code, target_date,
                    )
                    continue
                survey_service.save_optional_answer(
                    session,
                    entry_id=entry.id,
                    question_code=code,
                    answer_text=ans["answer_value"],
                    answer_index=ans["answer_index"],
                    log_date=target_date,
                )
            for ans in custom_answers:
                try:
                    custom_question_service.save_answer(
                        session,
                        entry_id=entry.id,
                        custom_question_id=ans["id"],
                        answer_type=ans["type"],
                        value=ans["value"],
                    )
                except Exception:
                    logger.exception(
                        "Не удалось сохранить ответ на custom_question id=%s",
                        ans["id"],
                    )
            if pending is not None:
                survey_service.mark_pending_completed(session, user.id)
    except IntegrityError:
        logger.exception("IntegrityError при сохранении опроса (вероятно гонка)")
        target = (
            update.callback_query.message if update.callback_query else update.message
        )
        await target.reply_text(
            "Запись уже была сохранена раньше. Дубль не создан."
        )
        context.user_data.pop("survey", None)
        return ConversationHandler.END
    except Exception:
        logger.exception("Ошибка сохранения опроса")
        target = (
            update.callback_query.message if update.callback_query else update.message
        )
        await target.reply_text(ERR_DB)
        context.user_data.pop("survey", None)
        return ConversationHandler.END

    if pending_id is not None:
        reminder_service.cancel_reminder_for_pending(context.application, pending_id)

    summary_lines = [
        SAVED,
        "",
        f"Настроение: {data['mood']}",
        f"Тревога: {data['anxiety']}",
        f"Энергия: {data['energy']}",
    ]
    if not skip_sleep:
        summary_lines.append(
            f"Сон: {SLEEP_DURATION_LABELS.get(data['sleep_duration_category'], '')}, "
            f"качество: {SLEEP_QUALITY_LABELS.get(data['sleep_quality'], '')}"
        )
    if not skip_medication:
        summary_lines.append(
            f"Лекарства: {MEDICATION_LABELS.get(data['medication_taken'], '')}"
        )
    if optional_answers:
        summary_lines.append("")
        summary_lines.append("Дополнительно:")
        for ans in optional_answers:
            title = QUESTION_DEFINITIONS.get(ans["code"], {}).get(
                "question_text", ans["code"]
            )
            summary_lines.append(
                f"• {title.rstrip('?')}: {ans.get('display', '')}"
            )
    if custom_answers:
        summary_lines.append("")
        summary_lines.append("Свои вопросы:")
        # Заголовки берём из custom_questions снимка, который уже извлечен.
        # Сделаем lookup на лету по id из survey state — но он уже очищен.
        # Поэтому в custom_answers удобнее иметь и текст. Пока есть только id.
        # Чтобы не делать лишний запрос, выводим краткое значение.
        for ans in custom_answers:
            summary_lines.append(f"• {ans['display']}")
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text("\n".join(summary_lines))

    if high_risk_triggered:
        await target.reply_text(CRISIS_MESSAGE)

    context.user_data.pop("survey", None)
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("survey", None)
    await update.message.reply_text("Опрос отменен.")
    return ConversationHandler.END


def build_survey_conversation() -> ConversationHandler:
    from bot.keyboards.main_menu import BTN_ADD

    # Принимаем и старый формат 'survey:start' (без слота), и новый
    # 'survey:start:<slot>'. Парсинг слота — в _parse_slot_from_callback.
    return ConversationHandler(
        entry_points=[
            CommandHandler("add", add_command),
            CallbackQueryHandler(
                survey_start_callback,
                pattern=r"^survey:start(:[a-z_]+)?$",
            ),
            MessageHandler(filters.Regex(rf"^{re.escape(BTN_ADD)}$"), add_command),
        ],
        states={
            MOOD: [CallbackQueryHandler(mood_step, pattern=r"^mood:\d+$")],
            ANXIETY: [CallbackQueryHandler(anxiety_step, pattern=r"^anxiety:\d+$")],
            ENERGY: [CallbackQueryHandler(energy_step, pattern=r"^energy:\d+$")],
            SLEEP_DURATION: [
                CallbackQueryHandler(sleep_duration_step, pattern=r"^sleep_dur:")
            ],
            SLEEP_QUALITY: [
                CallbackQueryHandler(sleep_quality_step, pattern=r"^sleep_q:")
            ],
            SLEEP_PROBLEMS: [
                CallbackQueryHandler(sleep_problems_step, pattern=r"^sleep_p:")
            ],
            MEDICATION: [
                CallbackQueryHandler(medication_step, pattern=r"^med:")
            ],
            OPTIONAL_Q: [
                CallbackQueryHandler(optional_question_step, pattern=r"^opt:\d+$")
            ],
            PHYS_ACT_DURATION: [
                CallbackQueryHandler(
                    physical_activity_duration_step, pattern=r"^pa_dur:[a-z0-9_]+$"
                )
            ],
            CUSTOM_Q: [
                CallbackQueryHandler(
                    custom_question_step,
                    pattern=r"^cqa:(scale:\d+|bool:[01])$",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, custom_question_step),
            ],
            COMMENT: [
                CallbackQueryHandler(comment_skip_step, pattern=r"^comment:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, comment_text_step),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        name="survey_conversation",
        persistent=False,
        # allow_reentry=True: кнопка «Заполнить опрос» из планового напоминания
        # должна срабатывать, даже если пользователь застрял в незавершённом
        # диалоге. С False entry_points игнорировались, пока пользователь «внутри»
        # conversation, и кнопка молча не реагировала (см. survey_start_callback).
        allow_reentry=True,
    )
