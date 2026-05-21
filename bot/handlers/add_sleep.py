"""Команда /add_sleep — добавление дополнительного сна (sleep_type='additional').

Доп. сон не зависит от того, заполнен ли уже основной сон за день: на БД-уровне
уникальный индекс работает только для sleep_type='main'.
"""

import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from bot.config import config
from bot.constants import (
    SLEEP_DURATION_LABELS,
    SLEEP_QUALITY_LABELS,
    SOURCE_MANUAL,
)
from bot.database import session_scope
from bot.keyboards.survey_keyboards import (
    sleep_duration_keyboard,
    sleep_quality_keyboard,
)
from bot.services import survey_service
from bot.texts import ERR_DB, Q_SLEEP_DURATION, Q_SLEEP_QUALITY
from bot.utils.time_utils import user_local_date

logger = logging.getLogger(__name__)

ADD_SLEEP_DURATION, ADD_SLEEP_QUALITY = range(2)


async def add_sleep_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data["add_sleep"] = {}
    await update.message.reply_text(
        Q_SLEEP_DURATION, reply_markup=sleep_duration_keyboard()
    )
    return ADD_SLEEP_DURATION


async def add_sleep_duration_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    context.user_data["add_sleep"]["sleep_duration_category"] = key
    await query.edit_message_text(
        f"{Q_SLEEP_DURATION}\n\nВыбрано: {SLEEP_DURATION_LABELS.get(key, key)}"
    )
    await query.message.reply_text(
        Q_SLEEP_QUALITY, reply_markup=sleep_quality_keyboard()
    )
    return ADD_SLEEP_QUALITY


async def add_sleep_quality_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    duration = context.user_data["add_sleep"]["sleep_duration_category"]
    quality = key

    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_date = user_local_date(user.timezone)
            survey_service.save_additional_sleep(
                session,
                user.id,
                local_date,
                duration,
                quality,
                SOURCE_MANUAL,
            )
    except Exception:
        logger.exception("Ошибка сохранения дополнительного сна")
        await query.message.reply_text(ERR_DB)
        context.user_data.pop("add_sleep", None)
        return ConversationHandler.END

    await query.edit_message_text(
        f"{Q_SLEEP_QUALITY}\n\nВыбрано: {SLEEP_QUALITY_LABELS.get(quality, quality)}"
    )
    await query.message.reply_text("Дополнительный сон записан.")
    context.user_data.pop("add_sleep", None)
    return ConversationHandler.END


async def _cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("add_sleep", None)
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


def build_add_sleep_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("add_sleep", add_sleep_command)],
        states={
            ADD_SLEEP_DURATION: [
                CallbackQueryHandler(
                    add_sleep_duration_step, pattern=r"^sleep_dur:"
                )
            ],
            ADD_SLEEP_QUALITY: [
                CallbackQueryHandler(
                    add_sleep_quality_step, pattern=r"^sleep_q:"
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", _cancel)],
        name="add_sleep_conversation",
        persistent=False,
    )
