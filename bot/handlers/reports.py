"""Handler раздела «📄 Отчёт».

Меню Отчёт содержит три формата:
  - PDF — компактный документ с обложкой, графиками и сводной таблицей.
  - Excel — сырые данные за период.
  - Полный отчёт — все графики отдельными сообщениями (бывший stats:full).

`/export` остаётся как алиас и сразу открывает это меню.

PDF-flow:
  1. report:pdf → клавиатура выбора периода.
  2. report:period:<code> → собрать данные, отрендерить PDF, отправить.
  3. finally: удалить временные PNG и PDF.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time as _time

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from bot.config import config
from bot.database import session_scope
from bot.keyboards.report_keyboards import (
    report_menu_keyboard,
    report_period_keyboard,
)
from bot.keyboards.stats_keyboards import period_keyboard
from bot.services import (
    pdf_report_builder,
    report_data_service,
    survey_service,
)
from bot.services.notification_sender import safe_send_document
from bot.services.report_charts import cleanup_paths
from bot.utils.date_periods import (
    PERIOD_CODES,
    PERIOD_LABELS,
    resolve_report_period,
)
from bot.utils.time_utils import user_local_date

logger = logging.getLogger(__name__)

REPORT_MENU_TEXT = (
    "📄 Отчёт\n\nВыберите формат:"
)
REPORT_PDF_PERIOD_TEXT = (
    "📄 PDF-отчёт\n\nЗа какой период сформировать отчёт?"
)
REPORT_EXCEL_PERIOD_TEXT = (
    "📊 Excel-выгрузка\n\nЗа какой период выгрузить данные?"
)
REPORT_FULL_PERIOD_TEXT = (
    "📦 Полный отчёт в чат\n\nЗа какой период показать все графики?"
)
GENERATING_TEXT = "Формирую PDF-отчёт. Это может занять немного времени."
NO_DATA_TEXT = (
    "За выбранный период недостаточно данных для PDF-отчёта.\n"
    "Попробуйте выбрать другой период или пройти несколько опросов."
)
GENERIC_ERROR_TEXT = (
    "Не удалось сформировать PDF-отчёт. Попробуйте позже."
)


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


async def report_open_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Открыть корневое меню «📄 Отчёт». Используется как entry point из
    /export, reply-кнопки и inline-кнопки menu:report."""
    if update.callback_query is not None:
        await update.callback_query.answer()
    logger.info("report_menu_opened tg=%s", update.effective_user.id)
    await _show(update, REPORT_MENU_TEXT, report_menu_keyboard())


async def report_router(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "report:menu":
        await _show(update, REPORT_MENU_TEXT, report_menu_keyboard())
        return

    if data == "report:close":
        # Закрываем экран. Старое сообщение остаётся, но без клавиатуры —
        # пользователь возвращается в основной чат с reply-меню.
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            pass
        return

    if data == "report:pdf":
        logger.info("pdf_report_requested tg=%s", update.effective_user.id)
        await _show(update, REPORT_PDF_PERIOD_TEXT, report_period_keyboard())
        return

    if data == "report:excel":
        # Делегируем существующему export-flow: показываем выбор периода.
        await _show(
            update, REPORT_EXCEL_PERIOD_TEXT,
            period_keyboard("export", include_all=True),
        )
        return

    if data == "report:full":
        # Делегируем существующему stats:full-flow: те же 7/14/30 дней,
        # обработчик stats_period_callback увидит prefix stfull.
        await _show(
            update, REPORT_FULL_PERIOD_TEXT, period_keyboard("stfull"),
        )
        return

    if data.startswith("report:period:"):
        period_code = data.split(":", 2)[2]
        if period_code not in PERIOD_CODES:
            await _show(update, "Неизвестный период.", report_period_keyboard())
            return
        await _generate_and_send(update, context, period_code)
        return


async def _generate_and_send(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    period_code: str,
) -> None:
    tg_id = update.effective_user.id
    logger.info(
        "pdf_report_period_selected tg=%s period=%s", tg_id, period_code
    )

    # Сразу показываем "формирую..." — это и UX-сигнал, и одновременно
    # пользователь видит, что callback принят.
    try:
        await update.callback_query.edit_message_text(GENERATING_TEXT)
    except BadRequest:
        pass

    started = _time.monotonic()

    # 1. Собираем данные.
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_today = user_local_date(user.timezone)
            date_from, date_to = resolve_report_period(period_code, local_today)
            logger.info(
                "pdf_report_data_collection_started tg=%s from=%s to=%s",
                tg_id, date_from, date_to,
            )
            report_data = report_data_service.collect_report_data(
                session, user, date_from, date_to
            )
            logger.info(
                "pdf_report_data_collection_finished tg=%s surveys=%s days=%s",
                tg_id, report_data.total_surveys, report_data.days_with_data,
            )
    except Exception:
        logger.exception("pdf_report_data_failed tg=%s", tg_id)
        await context.bot.send_message(chat_id=tg_id, text=GENERIC_ERROR_TEXT)
        return

    # 2. Если данных нет — отдельный путь.
    if not report_data.has_meaningful_data and not report_data.cycle_summary:
        await context.bot.send_message(chat_id=tg_id, text=NO_DATA_TEXT)
        return

    # 3. Генерируем PDF в отдельной временной директории — потом всю удалим.
    tmp_dir = tempfile.mkdtemp(prefix="mood_report_")
    pdf_path: str | None = None
    chart_paths: list[str] = []
    try:
        logger.info("pdf_report_build_started tg=%s", tg_id)
        pdf_path, chart_paths = pdf_report_builder.build_pdf_report(
            report_data, output_dir=tmp_dir, period_code=period_code,
        )
        pdf_size = os.path.getsize(pdf_path)

        filename = (
            f"state_report_{report_data.date_from.isoformat()}_"
            f"{report_data.date_to.isoformat()}.pdf"
        )
        with open(pdf_path, "rb") as fobj:
            sent = await safe_send_document(
                context.bot,
                telegram_user_id=tg_id,
                document=fobj,
                filename=filename,
                caption=(
                    f"PDF-отчёт за {PERIOD_LABELS.get(period_code, period_code)}"
                ),
                notification_type="pdf_report",
            )
        if sent:
            duration_ms = int((_time.monotonic() - started) * 1000)
            logger.info(
                "pdf_report_sent tg=%s period=%s size=%s duration_ms=%s",
                tg_id, period_code, pdf_size, duration_ms,
            )
        else:
            # safe_send_document уже залогировал и/или деактивировал юзера.
            logger.info(
                "pdf_report_send_failed tg=%s period=%s", tg_id, period_code
            )
    except Exception:
        logger.exception(
            "pdf_report_failed tg=%s period=%s", tg_id, period_code
        )
        try:
            await context.bot.send_message(
                chat_id=tg_id, text=GENERIC_ERROR_TEXT
            )
        except Exception:
            # уже терялся канал — больше ничего не сделаем
            pass
    finally:
        # Удаляем всё, что могли создать: PDF + PNG-чарты + директорию.
        try:
            cleanup_paths(chart_paths)
        except Exception:
            logger.exception("Не удалось почистить PNG отчёта")
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.unlink(pdf_path)
            except OSError:
                logger.warning("Не удалось удалить PDF %s", pdf_path)
        try:
            os.rmdir(tmp_dir)
        except OSError:
            # каталог не пуст — это значит что-то ещё внутри. Удалим всё подряд.
            for root, dirs, files in os.walk(tmp_dir, topdown=False):
                for name in files:
                    try:
                        os.unlink(os.path.join(root, name))
                    except OSError:
                        pass
                for name in dirs:
                    try:
                        os.rmdir(os.path.join(root, name))
                    except OSError:
                        pass
            try:
                os.rmdir(tmp_dir)
            except OSError:
                logger.warning("Не удалось удалить tmp_dir %s", tmp_dir)


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/export по-прежнему открывает меню «📄 Отчёт»."""
    await report_open_menu(update, context)


async def menu_report_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Inline-меню (menu:report) — открыть меню «Отчёт»."""
    await report_open_menu(update, context)


def build_report_handlers() -> list:
    return [
        # /export — оставляем как команду-алиас, чтобы пользователи по привычке
        # могли попасть в меню отчётов.
        CommandHandler("export", report_command),
        CallbackQueryHandler(menu_report_callback, pattern=r"^menu:report$"),
        CallbackQueryHandler(
            report_router,
            pattern=(
                r"^report:("
                r"menu|close|pdf|excel|full|"
                r"period:(7d|30d|current_month|3m|all)"
                r")$"
            ),
        ),
    ]
