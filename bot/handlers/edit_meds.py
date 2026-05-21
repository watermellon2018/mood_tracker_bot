"""Команда /edit_meds — изменить запись о приеме лекарств за сегодня.

Использует UPDATE, а не INSERT. Если записи нет — предлагает пройти обычный опрос.
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
from bot.constants import MEDICATION_LABELS
from bot.database import session_scope
from bot.keyboards.survey_keyboards import medication_keyboard
from bot.services import survey_service
from bot.texts import ERR_DB
from bot.utils.time_utils import user_local_date

logger = logging.getLogger(__name__)

EDIT_MEDS_PICK = 0


async def edit_meds_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_date = user_local_date(user.timezone)
            entry = survey_service.get_medication_entry_for_date(
                session, user.id, local_date
            )
            current = entry.medication_taken if entry is not None else None
    except Exception:
        logger.exception("Ошибка чтения записи лекарств")
        await update.message.reply_text(ERR_DB)
        return ConversationHandler.END

    if current is None:
        await update.message.reply_text(
            "Сегодня по лекарствам ещё ничего не записано. "
            "Запиши через /add — это создаст полноценную запись опроса."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"Сейчас записано: {MEDICATION_LABELS.get(current, current)}.\n"
        f"Выбери новое значение:",
        reply_markup=medication_keyboard(),
    )
    return EDIT_MEDS_PICK


async def edit_meds_pick(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]

    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_date = user_local_date(user.timezone)
            entry = survey_service.update_medication(
                session, user.id, local_date, key
            )
    except Exception:
        logger.exception("Ошибка обновления лекарств")
        await query.message.reply_text(ERR_DB)
        return ConversationHandler.END

    if entry is None:
        await query.edit_message_text("Запись не найдена.")
        return ConversationHandler.END

    await query.edit_message_text(
        f"Прием лекарств обновлён: {MEDICATION_LABELS.get(key, key)}."
    )
    return ConversationHandler.END


async def _cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


def build_edit_meds_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("edit_meds", edit_meds_command)],
        states={
            EDIT_MEDS_PICK: [
                CallbackQueryHandler(edit_meds_pick, pattern=r"^med:")
            ],
        },
        fallbacks=[CommandHandler("cancel", _cancel)],
        name="edit_meds_conversation",
        persistent=False,
    )
