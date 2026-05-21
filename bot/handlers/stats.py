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
            # Сериализуем в простые dict — нужно после выхода из сессии.
            entry_dt = {e.id: e.created_at for e in entries}
            answers_rows: list[dict] = []
            for entry_id, alist in answers_by_entry.items():
                for a in alist:
                    answers_rows.append({
                        "created_at": entry_dt[entry_id],
                        "question_code": a.question_code,
                        "answer_numeric": (
                            float(a.answer_numeric)
                            if a.answer_numeric is not None
                            else None
                        ),
                        "answer_value": a.answer_value,
                    })
            custom_rows: list[dict] = []
            for entry_id, alist in custom_by_entry.items():
                for a in alist:
                    custom_rows.append({
                        "created_at": entry_dt[entry_id],
                        "custom_question_id": a.custom_question_id,
                        "answer_type": a.answer_type,
                        "answer_text": a.answer_text,
                        "answer_numeric": (
                            float(a.answer_numeric)
                            if a.answer_numeric is not None
                            else None
                        ),
                        "answer_bool": a.answer_bool,
                    })
            # Снимок custom-вопросов: {id: (text, answer_type, is_active)}
            custom_q_snapshot = {
                qid: (q.question_text, q.answer_type, q.is_active)
                for qid, q in custom_q_map.items()
            }
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
        # Базовые графики (SurveyEntry колонки).
        for fn in (
            plotting.plot_mood,
            plotting.plot_anxiety,
            plotting.plot_energy,
            plotting.plot_irritability,
            plotting.plot_impulsivity,
            plotting.plot_mood_energy,
            plotting.plot_sleep,             # объединённый длительность+качество
            plotting.plot_sleep_problems,
            plotting.plot_mood_spread,
        ):
            try:
                path = fn(entries, user_tz)
                if path:
                    plot_paths.append(path)
            except Exception:
                logger.exception("Ошибка построения графика %s", fn.__name__)

        # Графики по опциональным вопросам: только те, по которым есть ответы.
        present_codes: list[str] = []
        seen: set[str] = set()
        for a in answers_rows:
            code = a["question_code"]
            if code not in seen:
                seen.add(code)
                present_codes.append(code)
        for code in present_codes:
            try:
                path = plotting.plot_optional_question(answers_rows, code, user_tz)
                if path:
                    plot_paths.append(path)
            except Exception:
                logger.exception("Ошибка построения графика по %s", code)

        # Графики по пользовательским вопросам. Только те, у которых есть ответы.
        present_custom_ids: list[int] = []
        seen_ids: set[int] = set()
        for a in custom_rows:
            qid = a["custom_question_id"]
            if qid not in seen_ids:
                seen_ids.add(qid)
                present_custom_ids.append(qid)
        for qid in present_custom_ids:
            meta = custom_q_snapshot.get(qid)
            if meta is None:
                continue
            qtext, qtype, _is_active = meta
            try:
                path = plotting.plot_custom_question(
                    custom_rows, qid, qtext, qtype, user_tz
                )
                if path:
                    plot_paths.append(path)
            except Exception:
                logger.exception("Ошибка построения графика по custom id=%s", qid)

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
