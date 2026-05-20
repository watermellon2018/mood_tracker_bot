import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.texts import ERR_GENERIC

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Необработанная ошибка", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message is not None:
        try:
            await update.effective_message.reply_text(ERR_GENERIC)
        except Exception:
            pass
