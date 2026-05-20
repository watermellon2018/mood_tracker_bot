import logging
import os
from datetime import datetime, timezone, timedelta

from telegram import InputMediaPhoto, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from bot.config import config
from bot.database import session_scope
from bot.keyboards.stats_keyboards import period_keyboard
from bot.services import stats_service, survey_service
from bot.texts import (
    DISCLAIMER_FOOTER,
    ERR_GENERIC,
    ERR_NO_DATA,
    STATS_CHOOSE_PERIOD,
)
from bot.utils import plotting

logger = logging.getLogger(__name__)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        STATS_CHOOSE_PERIOD, reply_markup=period_keyboard("stats")
    )


async def stats_period_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    try:
        days = int(query.data.split(":")[1])
    except ValueError:
        return
    tg_id = update.effective_user.id
    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            entries = stats_service.fetch_entries(session, user.id, since)
            user_tz = user.timezone
    except Exception:
        logger.exception("Ошибка чтения данных для статистики")
        await query.message.reply_text(ERR_GENERIC)
        return

    if not entries:
        await query.message.reply_text(ERR_NO_DATA)
        return

    summary = stats_service.build_summary(entries, days, user_tz) + DISCLAIMER_FOOTER
    await query.message.reply_text(summary)

    plot_paths: list[str] = []
    try:
        for fn in (
            plotting.plot_mood,
            plotting.plot_anxiety,
            plotting.plot_energy,
            plotting.plot_irritability,
            plotting.plot_impulsivity,
            plotting.plot_mood_energy,
            plotting.plot_sleep_duration,
            plotting.plot_sleep_quality,
            plotting.plot_sleep_problems,
            plotting.plot_mood_spread,
            plotting.plot_medication,
        ):
            try:
                path = fn(entries, user_tz)
                if path:
                    plot_paths.append(path)
            except Exception:
                logger.exception("Ошибка построения графика %s", fn.__name__)

        # Telegram media group: до 10 элементов за раз.
        for chunk_start in range(0, len(plot_paths), 10):
            chunk = plot_paths[chunk_start : chunk_start + 10]
            opened = [open(p, "rb") for p in chunk]
            try:
                media = [InputMediaPhoto(media=fobj) for fobj in opened]
                await context.bot.send_media_group(
                    chat_id=tg_id, media=media
                )
            finally:
                for fobj in opened:
                    fobj.close()
    finally:
        for p in plot_paths:
            try:
                os.unlink(p)
            except OSError:
                pass


def stats_handlers():
    return [
        CommandHandler("stats", stats_command),
        CallbackQueryHandler(stats_period_callback, pattern=r"^stats:\d+$"),
    ]
