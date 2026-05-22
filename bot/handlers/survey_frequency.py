"""Экран '📅 Частота опроса' и FSM ввода 'Каждые N дней'.

Callback префикс: freq2 (старый freq:N — кол-во опросов в день — оставляем
без изменений). Подменюшная навигация — через nav_service.safe_edit;
кнопка ⬅️ Назад в корне меню частоты возвращает в экран /settings;
кнопка ⬅️ Назад/Отмена в FSM сбрасывает state и возвращает в меню частоты.
"""
from __future__ import annotations

import logging

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
from bot.database import session_scope
from bot.keyboards.survey_frequency_keyboards import (
    survey_frequency_cancel_keyboard,
    survey_frequency_keyboard,
)
from bot.services import nav_service, scheduler_service, survey_service
from bot.services.survey_frequency_service import (
    CUSTOM_DAYS_MAX,
    CUSTOM_DAYS_MIN,
    FREQ_BIWEEKLY,
    FREQ_CUSTOM,
    FREQ_DAILY,
    FREQ_WEEKLY,
    VALID_FREQUENCY_TYPES,
    format_survey_frequency,
    validate_custom_days,
)

logger = logging.getLogger(__name__)

# FSM state.
AWAIT_CUSTOM_DAYS = 0

MENU_TEXT_TEMPLATE = (
    "📅 Частота опроса\n\n"
    "Как часто присылать опрос?\n\n"
    "Текущая настройка: {current}."
)

CUSTOM_PROMPT = (
    "Введите, через сколько дней присылать опрос.\n\n"
    "Например:\n"
    f"{CUSTOM_DAYS_MIN} — раз в {CUSTOM_DAYS_MIN} дня\n"
    "3 — раз в 3 дня\n"
    "10 — раз в 10 дней\n\n"
    f"Минимум {CUSTOM_DAYS_MIN}, максимум {CUSTOM_DAYS_MAX}."
)

CUSTOM_INVALID = (
    f"Нужно целое число от {CUSTOM_DAYS_MIN} до {CUSTOM_DAYS_MAX}. "
    "Попробуйте ещё раз или нажмите «Назад»."
)

CUSTOM_CANCELLED = "Настройка отменена."


# ---------- helpers ----------

def _read_current_frequency(tg_id: int) -> tuple[str, int | None]:
    """Возвращает (type, days). Если settings не нашлись — defaults."""
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            settings = survey_service.get_settings(session, user.id)
            if settings is None:
                return FREQ_DAILY, None
            return settings.survey_frequency_type, settings.survey_frequency_days
    except Exception:
        logger.exception("Не удалось прочитать частоту опроса tg=%s", tg_id)
        return FREQ_DAILY, None


async def _render_menu(update: Update) -> None:
    tg_id = update.effective_user.id
    ftype, fdays = _read_current_frequency(tg_id)
    text = MENU_TEXT_TEMPLATE.format(
        current=format_survey_frequency(ftype, fdays)
    )
    await nav_service.safe_edit(
        update, text, survey_frequency_keyboard(ftype)
    )


# ---------- entry: открыть меню частоты ----------

async def open_frequency_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Callback 'freq2:menu' — открыть экран частоты опроса."""
    query = update.callback_query
    await nav_service.answer_silently(query)
    logger.info("Открыты настройки частоты опроса tg=%s", update.effective_user.id)
    await _render_menu(update)


# ---------- router: set / back ----------

async def frequency_router(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Роутер для freq2:set:<type> и freq2:back. Без FSM."""
    query = update.callback_query
    await nav_service.answer_silently(query)
    data = query.data
    tg_id = update.effective_user.id

    if data == "freq2:menu":
        await _render_menu(update)
        return

    if data == "freq2:back":
        # Кнопка Назад в корне меню частоты — закрываем inline-меню.
        await nav_service.close_menu(update, context)
        return

    if data.startswith("freq2:set:"):
        ftype = data.split(":", 2)[2]
        if ftype not in VALID_FREQUENCY_TYPES or ftype == FREQ_CUSTOM:
            # custom_days приходит через freq2:custom -> FSM, не через set.
            await _render_menu(update)
            return
        await _apply_frequency(update, context, tg_id, ftype, None)
        return


async def _apply_frequency(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tg_id: int,
    ftype: str,
    fdays: int | None,
) -> None:
    """Сохраняет частоту и перерисовывает экран. Также пересобирает расписание
    (notification_times и slot-индексация не зависят от частоты, но безопасно)."""
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            settings = survey_service.update_survey_frequency(
                session, user.id, ftype, fdays
            )
    except Exception:
        logger.exception("Ошибка сохранения частоты опроса tg=%s", tg_id)
        await nav_service.safe_edit(
            update,
            "Не удалось сохранить настройку. Попробуйте ещё раз.",
            survey_frequency_keyboard(FREQ_DAILY),
        )
        return

    logger.info(
        "Частота опроса сохранена tg=%s type=%s days=%s",
        tg_id, ftype, fdays,
    )

    # Расписание JobQueue зависит только от frequency_per_day/start/end,
    # но настройка last_survey_notification_date может уже потребовать
    # пересобрать политики. Достаточно просто пересобрать.
    if settings is not None:
        try:
            scheduler_service.schedule_user(context.application, user, settings)
        except Exception:
            logger.exception("Не удалось пересобрать расписание после смены частоты")

    await _render_menu(update)


# ---------- FSM: custom N days ----------

async def custom_days_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Entry point для freq2:custom — спрашиваем число."""
    query = update.callback_query
    await nav_service.answer_silently(query)
    logger.info(
        "Начата настройка custom_days tg=%s", update.effective_user.id
    )
    await nav_service.safe_edit(
        update, CUSTOM_PROMPT, survey_frequency_cancel_keyboard()
    )
    return AWAIT_CUSTOM_DAYS


async def custom_days_receive(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Принимаем текстовое сообщение с числом N."""
    text = (update.message.text or "").strip()
    n = validate_custom_days(text)
    tg_id = update.effective_user.id
    if n is None:
        logger.info("Невалидное custom_days tg=%s value=%r", tg_id, text)
        await update.message.reply_text(
            CUSTOM_INVALID, reply_markup=survey_frequency_cancel_keyboard()
        )
        return AWAIT_CUSTOM_DAYS

    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            settings = survey_service.update_survey_frequency(
                session, user.id, FREQ_CUSTOM, n
            )
    except Exception:
        logger.exception("Ошибка сохранения custom_days tg=%s", tg_id)
        await update.message.reply_text(
            "Не удалось сохранить настройку. Попробуйте позже."
        )
        return ConversationHandler.END

    if settings is not None:
        try:
            scheduler_service.schedule_user(
                context.application, user, settings
            )
        except Exception:
            logger.exception("Не удалось пересобрать расписание после custom_days")

    logger.info("Сохранено custom_days tg=%s days=%s", tg_id, n)
    await update.message.reply_text(
        f"Готово. Опрос будет приходить {format_survey_frequency(FREQ_CUSTOM, n)}."
    )
    return ConversationHandler.END


async def custom_days_cancel_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """freq2:cancel внутри FSM — сбросить state и вернуть на экран частоты."""
    query = update.callback_query
    await nav_service.answer_silently(query)
    logger.info(
        "Отмена custom_days tg=%s", update.effective_user.id
    )
    await _render_menu(update)
    return ConversationHandler.END


async def custom_days_cancel_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.message.reply_text(CUSTOM_CANCELLED)
    return ConversationHandler.END


def build_custom_days_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(custom_days_start, pattern=r"^freq2:custom$"),
        ],
        states={
            AWAIT_CUSTOM_DAYS: [
                CallbackQueryHandler(
                    custom_days_cancel_callback, pattern=r"^freq2:cancel$"
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, custom_days_receive
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", custom_days_cancel_cmd)],
        name="survey_frequency_custom_conversation",
        persistent=False,
    )


def build_frequency_open_handler() -> CallbackQueryHandler:
    """Открыть меню частоты из settings (callback freq2:menu)."""
    return CallbackQueryHandler(open_frequency_menu, pattern=r"^freq2:menu$")


def build_frequency_router() -> CallbackQueryHandler:
    """Роутер для freq2:set:<type>, freq2:back. (freq2:custom и freq2:cancel
    обрабатывает ConversationHandler.)"""
    return CallbackQueryHandler(
        frequency_router,
        pattern=r"^freq2:(back|set:(daily|weekly|biweekly))$",
    )
