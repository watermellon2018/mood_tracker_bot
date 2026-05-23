"""Меню статистики, режимы brief/selected/full, экран настроек блоков.

Архитектура:
- /stats -> меню (выбор режима) — без периода. Период спрашивается на следующем шаге.
- Каждый режим имеет свой префикс period_keyboard, чтобы знать, что было выбрано:
  * stbrief / stsel / stfull
- После выбора периода вызывается единый _send_report(mode, days).
"""
import logging
import os
from datetime import datetime, timezone, timedelta

from telegram import InputMediaPhoto, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from bot.config import config
from bot.constants_statistics import (
    STATISTICS_BLOCK_LABELS,
    STATISTICS_BRIEF,
    short_to_block,
)
from bot.database import session_scope
from bot.keyboards.statistics_keyboards import (
    stats_menu_keyboard,
    stats_settings_keyboard,
)
from bot.keyboards.stats_keyboards import period_keyboard
from bot.services import (
    nav_service,
    statistics_renderer,
    statistics_settings_service,
    stats_service,
    survey_service,
)
from bot.services.statistics_renderer import SUMMARY_SENTINEL
from bot.texts import (
    DISCLAIMER_FOOTER,
    ERR_GENERIC,
    ERR_NO_DATA,
)

logger = logging.getLogger(__name__)

STATS_MENU_TEXT = "📊 Статистика\n\nЧто показать?"
SETTINGS_HEADER = (
    "⚙️ Настройки статистики\n\n"
    'Выберите, какие блоки включать в отчёт «Выбранные блоки».\n'
    "Изменения сохраняются автоматически."
)
CHOOSE_PERIOD = "За какой период показать?"


# ---------- helpers ----------

async def _show(update: Update, text: str, markup) -> None:
    query = update.callback_query
    if query is not None:
        try:
            await query.edit_message_text(text, reply_markup=markup)
            return
        except BadRequest:
            pass
        target = query.message
    else:
        target = update.message
    await target.reply_text(text, reply_markup=markup)


def _get_enabled_blocks_set(user_id: int) -> set[str]:
    try:
        with session_scope() as session:
            return set(
                statistics_settings_service.get_enabled_blocks(session, user_id)
            )
    except Exception:
        logger.exception("Ошибка чтения настроек блоков статистики")
        return set(STATISTICS_BRIEF)


# ---------- entry: /stats ----------

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Открыто меню статистики tg=%s", update.effective_user.id)
    await update.message.reply_text(STATS_MENU_TEXT, reply_markup=stats_menu_keyboard())


async def stats_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Роутер для stats:* (кроме stats:tgl: и stats:<digits>:)."""
    query = update.callback_query
    await query.answer()
    data = query.data
    tg_id = update.effective_user.id

    if data == "stats:menu":
        await _show(update, STATS_MENU_TEXT, stats_menu_keyboard())
        return

    if data == "stats:back":
        # Закрываем меню статистики — удаляем сообщение или редактируем
        # на короткое подтверждение, чтобы оно не висело без кнопок.
        await nav_service.close_menu(update, context)
        return

    if data == "stats:brief":
        logger.info("stats mode=brief tg=%s", tg_id)
        await _show(update, CHOOSE_PERIOD, period_keyboard("stbrief"))
        return

    if data == "stats:selected":
        logger.info("stats mode=selected tg=%s", tg_id)
        await _show(update, CHOOSE_PERIOD, period_keyboard("stsel"))
        return

    if data == "stats:full":
        logger.info("stats mode=full tg=%s", tg_id)
        await _show(update, CHOOSE_PERIOD, period_keyboard("stfull"))
        return

    if data == "stats:excel":
        # Делегируем существующему /export flow: показываем выбор периода.
        from bot.texts import EXPORT_CHOOSE_PERIOD
        await _show(
            update, EXPORT_CHOOSE_PERIOD,
            period_keyboard("export", include_all=True),
        )
        return

    if data == "stats:settings":
        enabled = _get_enabled_blocks_set(_get_user_id(tg_id))
        await _show(update, SETTINGS_HEADER, stats_settings_keyboard(enabled))
        return

    if data == "stats:reset":
        try:
            with session_scope() as session:
                user = survey_service.get_or_create_user(
                    session, tg_id, config.DEFAULT_TIMEZONE
                )
                statistics_settings_service.reset_to_default(session, user.id)
        except Exception:
            logger.exception("Ошибка сброса настроек статистики")
        enabled = _get_enabled_blocks_set(_get_user_id(tg_id))
        await _show(update, SETTINGS_HEADER, stats_settings_keyboard(enabled))
        return

    if data.startswith("stats:tgl:"):
        short = data.split(":", 2)[2]
        long_code = short_to_block(short)
        if long_code is None:
            return
        try:
            with session_scope() as session:
                user = survey_service.get_or_create_user(
                    session, tg_id, config.DEFAULT_TIMEZONE
                )
                statistics_settings_service.toggle_block(
                    session, user.id, long_code
                )
        except Exception:
            logger.exception("Ошибка toggle блока %s", long_code)
        enabled = _get_enabled_blocks_set(_get_user_id(tg_id))
        await _show(update, SETTINGS_HEADER, stats_settings_keyboard(enabled))
        return


def _get_user_id(tg_id: int) -> int:
    """Достаёт users.id по telegram_user_id. Используется для краткости."""
    with session_scope() as session:
        user = survey_service.get_or_create_user(
            session, tg_id, config.DEFAULT_TIMEZONE
        )
        return user.id


# ---------- period callbacks: stbrief/stsel/stfull ----------

async def stats_period_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обрабатывает stbrief:N / stsel:N / stfull:N."""
    query = update.callback_query
    await query.answer()
    try:
        prefix, days_str = query.data.split(":", 1)
        days = int(days_str)
    except (ValueError, IndexError):
        return

    mode_map = {"stbrief": "brief", "stsel": "selected", "stfull": "full"}
    mode = mode_map.get(prefix)
    if mode is None:
        return

    tg_id = update.effective_user.id
    await _send_report(update, context, tg_id, mode, days)


async def _send_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tg_id: int,
    mode: str,
    days: int,
) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # 1. Подгружаем данные одним заходом.
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            entries = stats_service.fetch_entries(session, user.id, since)
            user_tz = user.timezone
            user_id = user.id
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
            entry_dt = {e.id: e.created_at for e in entries}
            entry_local_date = {e.id: e.local_date for e in entries}
            answers_rows: list[dict] = []
            for entry_id, alist in answers_by_entry.items():
                for a in alist:
                    answers_rows.append({
                        "created_at": entry_dt[entry_id],
                        # log_date — локальная дата, к которой относится ответ.
                        # Для late_phone это previous_day, для остальных
                        # совпадает с entry.local_date. Используется в
                        # дневной агрегации графиков.
                        "log_date": a.log_date,
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
                        # У custom-ответов своего log_date нет — берём
                        # entry.local_date (это и есть локальная дата
                        # пользователя на момент сохранения опроса).
                        "log_date": entry_local_date[entry_id],
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
            custom_q_snapshot = {
                qid: (q.question_text, q.answer_type, q.is_active)
                for qid, q in custom_q_map.items()
            }
            # Список блоков для выбранного режима.
            if mode == "brief":
                blocks = list(STATISTICS_BRIEF)
            elif mode == "selected":
                blocks = statistics_settings_service.get_enabled_blocks(
                    session, user.id
                )
            else:  # full
                # full — все блоки в порядке каталога. Рендерер сам отсеет
                # те, по которым нет данных.
                from bot.constants_statistics import STATISTICS_BLOCK_CODES
                blocks = list(STATISTICS_BLOCK_CODES)
    except Exception:
        logger.exception("Ошибка чтения данных для статистики")
        await context.bot.send_message(chat_id=tg_id, text=ERR_GENERIC)
        return

    if not entries:
        await context.bot.send_message(chat_id=tg_id, text=ERR_NO_DATA)
        return

    ctx = {
        "entries": entries,
        "user_tz": user_tz,
        "days": days,
        "answers_rows": answers_rows,
        "custom_rows": custom_rows,
        "custom_q_snapshot": custom_q_snapshot,
    }

    # 2. Идём по блокам, собираем выходы.
    summary_sent = False
    plot_paths: list[str] = []
    skipped_no_data: list[str] = []
    skipped_no_renderer: list[str] = []

    try:
        for block in blocks:
            out = statistics_renderer.render_block(block, ctx)
            if not out:
                # Пусто — отличаем «нет рендера» от «нет данных» по логам ренденера.
                # Но снаружи всё равно покажем общий итог. Для пользователя — пропуск.
                skipped_no_data.append(block)
                continue
            for item in out:
                if item == SUMMARY_SENTINEL:
                    if summary_sent:
                        continue
                    summary_text = stats_service.build_summary(
                        ctx["entries"], days, user_tz
                    ) + DISCLAIMER_FOOTER
                    await context.bot.send_message(
                        chat_id=tg_id, text=summary_text
                    )
                    summary_sent = True
                else:
                    plot_paths.append(item)

        # 3. Отправляем графики чанками по 10 (Telegram media group limit).
        for chunk_start in range(0, len(plot_paths), 10):
            chunk = plot_paths[chunk_start : chunk_start + 10]
            opened = [open(p, "rb") for p in chunk]
            try:
                media = [InputMediaPhoto(media=fobj) for fobj in opened]
                await context.bot.send_media_group(chat_id=tg_id, media=media)
            finally:
                for fobj in opened:
                    fobj.close()

        # 4. Итоговое сообщение про пропущенные блоки. Только если их много
        # и пользователь явно выбирал блоки (selected): в full и brief это
        # ожидаемое поведение.
        if mode == "selected" and skipped_no_data:
            names = ", ".join(
                STATISTICS_BLOCK_LABELS.get(b, b)
                for b in skipped_no_data
                if b in STATISTICS_BLOCK_LABELS
            )
            if names:
                await context.bot.send_message(
                    chat_id=tg_id,
                    text=(
                        "По части выбранных блоков пока недостаточно данных: "
                        f"{names}."
                    ),
                )

        logger.info(
            "stats report mode=%s tg=%s blocks=%d plots=%d skipped=%d",
            mode, tg_id, len(blocks), len(plot_paths), len(skipped_no_data),
        )
    finally:
        for p in plot_paths:
            try:
                os.unlink(p)
            except OSError:
                pass


def stats_handlers():
    return [
        CommandHandler("stats", stats_command),
        # Меню и настройки.
        CallbackQueryHandler(
            stats_menu_callback,
            pattern=(
                r"^stats:("
                r"menu|back|brief|selected|full|excel|settings|reset|tgl:[a-zA-Z0-9_]+"
                r")$"
            ),
        ),
        # Период для каждого режима.
        CallbackQueryHandler(stats_period_callback, pattern=r"^stbrief:\d+$"),
        CallbackQueryHandler(stats_period_callback, pattern=r"^stsel:\d+$"),
        CallbackQueryHandler(stats_period_callback, pattern=r"^stfull:\d+$"),
    ]
