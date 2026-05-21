"""Пошаговый опрос на ConversationHandler."""

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
    OPTIONAL_QUESTION_ORDER,
    QUESTION_DEFINITIONS,
    SUICIDAL_HIGH_RISK_INDEX,
    options_for,
)
from bot.database import session_scope
from bot.keyboards.survey_keyboards import (
    anxiety_keyboard,
    comment_skip_keyboard,
    energy_keyboard,
    medication_keyboard,
    mood_keyboard,
    optional_question_keyboard,
    sleep_duration_keyboard,
    sleep_problems_keyboard,
    sleep_quality_keyboard,
    unfinished_survey_keyboard,
)
from sqlalchemy.exc import IntegrityError

from bot.services import (
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
from bot.utils.time_utils import user_local_date

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
    COMMENT,
) = range(9)


# ---------- helpers ----------

def _is_active_survey(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.user_data.get("survey"))


# Коды, у которых есть отдельный базовый шаг в опросе — их не нужно дублировать
# через опциональный механизм, даже если пользователь включил их в настройках.
# irritability/impulsivity больше не имеют базовых шагов — задаются как опциональные.
_HANDLED_AS_BASE = {"medications"}


def _init_survey(
    context: ContextTypes.DEFAULT_TYPE, source: str, tg_id: int
) -> None:
    """Инициализирует state опроса. Определяет:
    - заполнены ли сон и лекарства за локальную дату (для скипа базовых блоков);
    - список включенных опциональных вопросов и порядок их прохождения.
    """
    has_sleep = False
    has_med = False
    local_date = None
    optional_codes: list[str] = []
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_date = user_local_date(user.timezone)
            has_sleep = survey_service.has_main_sleep_for_date(
                session, user.id, local_date
            )
            has_med = survey_service.has_medication_for_date(
                session, user.id, local_date
            )
            enabled = question_settings_service.enabled_optional_codes(
                session, user.id
            )
            # фильтруем и упорядочиваем
            optional_codes = [
                c for c in OPTIONAL_QUESTION_ORDER
                if c in enabled and c not in _HANDLED_AS_BASE
            ]
    except Exception:
        logger.exception("Не удалось определить состояние блоков сна/лекарств")

    context.user_data["survey"] = {
        "source": source,
        "sleep_problems": set(),
        "skip_sleep": has_sleep,
        "skip_medication": has_med,
        "local_date": local_date,
        "optional_codes": optional_codes,
        "optional_idx": 0,
        "optional_answers": [],  # list[dict(code, text, index)]
        "high_risk_triggered": False,
    }
    if optional_codes:
        logger.info(
            "Опрос tg=%s: подключены опциональные вопросы (%d шт): %s",
            tg_id, len(optional_codes), ", ".join(optional_codes),
        )


async def _send_question(update: Update, text: str, markup) -> None:
    """Шлет вопрос как новое сообщение независимо от типа update."""
    if update.callback_query is not None:
        await update.callback_query.message.reply_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


# ---------- entry points ----------

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if _is_active_survey(context):
        await update.message.reply_text(
            UNFINISHED_SURVEY, reply_markup=unfinished_survey_keyboard()
        )
        return ConversationHandler.END
    _init_survey(context, SOURCE_MANUAL, update.effective_user.id)
    await update.message.reply_text(SURVEY_INTRO)
    await update.message.reply_text(Q_MOOD, reply_markup=mood_keyboard())
    return MOOD


async def survey_start_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Запуск опроса по кнопке из планового уведомления."""
    query = update.callback_query
    await query.answer()
    if _is_active_survey(context):
        await query.message.reply_text(
            UNFINISHED_SURVEY, reply_markup=unfinished_survey_keyboard()
        )
        return ConversationHandler.END
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
    _init_survey(context, source, update.effective_user.id)
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
        _init_survey(context, SOURCE_MANUAL, update.effective_user.id)
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
    """После базового блока — задаём следующий опциональный или переходим к комментарию."""
    survey = context.user_data["survey"]
    target = update.callback_query.message if update.callback_query else update.message

    codes: list[str] = survey.get("optional_codes", [])
    idx: int = survey.get("optional_idx", 0)

    if idx >= len(codes):
        await target.reply_text(Q_COMMENT, reply_markup=comment_skip_keyboard())
        return COMMENT

    code = codes[idx]
    title = QUESTION_DEFINITIONS.get(code, {}).get("question_text", code)
    question_text, options = options_for(code, title)
    await target.reply_text(
        question_text, reply_markup=optional_question_keyboard(options)
    )
    return OPTIONAL_Q


async def optional_question_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Обработка ответа на опциональный вопрос. Сохраняет в state и переходит дальше."""
    query = update.callback_query
    await query.answer()
    try:
        choice_idx = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return OPTIONAL_Q

    survey = context.user_data["survey"]
    idx: int = survey.get("optional_idx", 0)
    codes: list[str] = survey.get("optional_codes", [])
    if idx >= len(codes):
        # Из-за гонок — просто переходим к комментарию.
        await query.message.reply_text(Q_COMMENT, reply_markup=comment_skip_keyboard())
        return COMMENT

    code = codes[idx]
    _, options = options_for(code)
    if not (0 <= choice_idx < len(options)):
        return OPTIONAL_Q
    answer_text = options[choice_idx]

    survey["optional_answers"].append(
        {"code": code, "text": answer_text, "index": choice_idx}
    )
    survey["optional_idx"] = idx + 1

    # Подсветим выбранный вариант в исходном сообщении.
    question_text = QUESTION_DEFINITIONS.get(code, {}).get("question_text", code)
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
    high_risk_triggered = data.pop("high_risk_triggered", False)
    # Эти ключи уже не нужны после извлечения ответов.
    data.pop("optional_codes", None)
    data.pop("optional_idx", None)

    # Маркируем тип записи. Если сон скипнули — sleep_type='none', поля сна
    # фактически отсутствуют (save_entry проставит дефолты 'skipped').
    # Если лекарства скипнули — medication_filled=false, medication_taken остаётся
    # 'not_applicable' (save_entry проставит).
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
            # Двойная проверка: между _init_survey и сейчас могла появиться запись
            # (другой опрос/доп. сон). Если main уже есть — пишем 'none', чтобы не
            # упасть на уникальном индексе.
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
            for ans in optional_answers:
                survey_service.save_optional_answer(
                    session,
                    entry_id=entry.id,
                    question_code=ans["code"],
                    answer_text=ans["text"],
                    answer_index=ans["index"],
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
            summary_lines.append(f"• {title.rstrip('?')}: {ans['text']}")
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

    return ConversationHandler(
        entry_points=[
            CommandHandler("add", add_command),
            CallbackQueryHandler(survey_start_callback, pattern=r"^survey:start$"),
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
            COMMENT: [
                CallbackQueryHandler(comment_skip_step, pattern=r"^comment:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, comment_text_step),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        name="survey_conversation",
        persistent=False,
        allow_reentry=False,
    )
