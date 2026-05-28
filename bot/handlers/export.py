import logging
import os
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.config import config
from bot.database import session_scope
from bot.keyboards.stats_keyboards import period_keyboard
from bot.services import export_service, stats_service, survey_service
from bot.texts import ERR_GENERIC, ERR_NO_DATA, EXPORT_CHOOSE_PERIOD, EXPORT_PREPARING

logger = logging.getLogger(__name__)


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        EXPORT_CHOOSE_PERIOD,
        reply_markup=period_keyboard("export", include_all=True),
    )


async def export_period_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    period = query.data.split(":")[1]
    tg_id = update.effective_user.id

    if period == "all":
        since = None
        label = "Все данные"
    else:
        days = int(period)
        since = datetime.now(timezone.utc) - timedelta(days=days)
        label = f"{days} дней"

    await query.message.reply_text(EXPORT_PREPARING)

    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            entries = stats_service.fetch_entries(session, user.id, since)
            user_tz = user.timezone
            entry_ids = [e.id for e in entries]
            answers_by_entry = stats_service.fetch_optional_answers(
                session, entry_ids
            )
            custom_by_entry = stats_service.fetch_custom_answers(
                session, entry_ids
            )
            custom_q_map = stats_service.fetch_user_custom_questions(
                session, user.id
            )
            custom_q_snapshot = {
                qid: q.question_text for qid, q in custom_q_map.items()
            }
            # Сериализуем в простые dict, чтобы не зависеть от сессии.
            answers_rows = []
            custom_rows = []
            for e in entries:
                for a in answers_by_entry.get(e.id, []):
                    answers_rows.append({
                        "entry_id": e.id,
                        "created_at": e.created_at,
                        "question_code": a.question_code,
                        "answer_value": a.answer_value,
                        "answer_numeric": float(a.answer_numeric) if a.answer_numeric is not None else None,
                    })
                for a in custom_by_entry.get(e.id, []):
                    custom_rows.append({
                        "entry_id": e.id,
                        "created_at": e.created_at,
                        "custom_question_id": a.custom_question_id,
                        "answer_type": a.answer_type,
                        "answer_text": a.answer_text,
                        "answer_numeric": float(a.answer_numeric) if a.answer_numeric is not None else None,
                        "answer_bool": a.answer_bool,
                    })
    except Exception:
        logger.exception("Ошибка чтения данных для экспорта")
        await query.message.reply_text(ERR_GENERIC)
        return

    if not entries:
        await query.message.reply_text(ERR_NO_DATA)
        return

    try:
        path = export_service.build_excel(
            entries, label, user_tz, answers_rows,
            custom_answers=custom_rows,
            custom_questions_map=custom_q_snapshot,
        )
    except Exception:
        logger.exception("Ошибка генерации Excel")
        await query.message.reply_text(ERR_GENERIC)
        return

    try:
        with open(path, "rb") as f:
            await context.bot.send_document(
                chat_id=tg_id,
                document=f,
                filename=f"mood_export_{period}.xlsx",
            )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def export_handlers():
    # /export-команда переехала в bot/handlers/reports.py (она открывает
    # общее меню «📄 Отчёт»). Здесь оставляем только callback на выбор
    # периода — он по-прежнему выполняет реальную Excel-выгрузку.
    return [
        CallbackQueryHandler(export_period_callback, pattern=r"^export:(7|14|30|all)$"),
    ]
