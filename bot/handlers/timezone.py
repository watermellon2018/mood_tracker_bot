"""Onboarding и редактирование таймзоны пользователя."""

import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.config import config
from bot.database import session_scope
from bot.keyboards.timezone_keyboards import (
    timezone_main_keyboard,
    timezone_more_keyboard,
)
from bot.services import scheduler_service, survey_service
from bot.utils.timezones import (
    TIMEZONE_CALLBACK_MAP,
    is_valid_iana_timezone,
)

logger = logging.getLogger(__name__)

PROMPT_CHOOSE_TZ = (
    "Чтобы я мог отправлять уведомления в правильное время, "
    "выбери часовой пояс."
)
PROMPT_MORE_TZ = "Выбери город:"
TZ_CANCELLED = "Отменено. Часовой пояс не изменён."
TZ_ERROR_UNKNOWN = "Не удалось распознать этот вариант. Попробуй ещё раз."
TZ_ERROR_SAVE = "Не удалось сохранить часовой пояс. Попробуй позже."


def needs_timezone_setup(telegram_user_id: int) -> bool:
    """True, если пользователь ещё не выбирал TZ явно."""
    with session_scope() as session:
        user = survey_service.get_user_by_tg(session, telegram_user_id)
        if user is None:
            return True
        return not user.timezone_set


async def prompt_timezone_choice(update: Update) -> None:
    """Отправляет сообщение с inline-клавиатурой выбора TZ."""
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(PROMPT_CHOOSE_TZ, reply_markup=timezone_main_keyboard())


async def timezone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Единый callback для всех tz:* кнопок."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # Навигация и отмена.
    if data == "tz:more":
        await _safe_edit(query, PROMPT_MORE_TZ, timezone_more_keyboard())
        return
    if data == "tz:back":
        await _safe_edit(query, PROMPT_CHOOSE_TZ, timezone_main_keyboard())
        return
    if data == "tz:cancel":
        await _safe_edit(query, TZ_CANCELLED, None)
        return

    entry = TIMEZONE_CALLBACK_MAP.get(data)
    if entry is None:
        # устаревшая или незнакомая кнопка
        await _safe_edit(query, TZ_ERROR_UNKNOWN, timezone_main_keyboard())
        return

    tz_name = entry["timezone"]
    label = entry["label"]

    if not is_valid_iana_timezone(tz_name):
        # Сюда не должны попадать, если константы корректны. Логируем как баг.
        logger.error("В TIMEZONE_CALLBACK_MAP невалидная IANA-зона: %s", tz_name)
        await _safe_edit(query, TZ_ERROR_SAVE, None)
        return

    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            survey_service.set_user_timezone(session, tg_id, tz_name)
            settings = survey_service.get_settings(session, user.id)
    except Exception:
        logger.exception("Не удалось сохранить timezone tg=%s", tg_id)
        await _safe_edit(query, TZ_ERROR_SAVE, None)
        return

    # Пересобираем расписание в новой TZ. user/settings уже доступны после
    # выхода из сессии благодаря expire_on_commit=False.
    if settings is not None:
        try:
            scheduler_service.schedule_user(context.application, user, settings)
        except Exception:
            logger.exception("Не удалось пересобрать расписание после смены TZ")

    text = (
        f"Готово. Твой часовой пояс: {label} ({tz_name}). "
        f"Уведомления будут приходить по твоему местному времени."
    )
    await _safe_edit(query, text, None)


async def _safe_edit(query, text, markup) -> None:
    """Редактирует сообщение, если возможно. Если нельзя (например, нет
    изменений или сообщение слишком старое) — отправляет новое."""
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except BadRequest as e:
        # 'message is not modified' и подобное — просто шлём новое сообщение.
        logger.debug("edit_message_text fallback: %s", e)
        await query.message.reply_text(text, reply_markup=markup)


def build_timezone_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(timezone_callback, pattern=r"^tz:")
