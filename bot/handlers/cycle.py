"""Handlers и FSM для функции «Менструальный цикл».

UI-блоки:
- `cycle:menu` — корневой экран (включён / выключен).
- Включение + onboarding (старт даты, опционально дата окончания / «ещё идут»).
- Отметить начало / окончание (Сегодня / Вчера / Другая дата).
- Подтверждение прогнозного начала / окончания (от scheduler).
- Настройки уведомлений (3 тогла).
- Disable c подтверждением.

Один общий ConversationHandler ловит ВЕСЬ ввод custom-даты: контекст
держит флаг (`cycle_pending_op`), чтобы понять, какая операция в ходу.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from telegram import Update
from telegram.error import BadRequest
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
from bot.keyboards.cycle_keyboards import (
    cycle_before_start_keyboard,
    cycle_disable_confirm_keyboard,
    cycle_end_pick_keyboard,
    cycle_long_period_confirm_keyboard,
    cycle_notif_keyboard,
    cycle_onboarding_end_keyboard,
    cycle_predicted_end_keyboard,
    cycle_predicted_start_keyboard,
    cycle_root_disabled_keyboard,
    cycle_root_enabled_keyboard,
    cycle_start_pick_keyboard,
)
from bot.services import menstrual_cycle_service as mcs
from bot.services import survey_service
from bot.services.cycle_scheduler import (
    CYCLE_JOB_PREFIX,
    schedule_user_cycle,
)
from bot.services.menstrual_cycle_service import CycleValidationError
from bot.utils.date_parsing import parse_user_date
from bot.utils.time_utils import user_local_date

logger = logging.getLogger(__name__)


# FSM: ожидание ввода даты текстом. Одно состояние на все операции.
AWAIT_DATE = 0

# Идентификаторы операций, чтобы знать, что делать с введённой датой.
OP_ONBOARD_START = "onb_start"
OP_ONBOARD_END = "onb_end"
OP_MARK_START = "mark_start"
OP_MARK_END = "mark_end"
OP_PRED_START_CUSTOM = "pred_start_custom"

DISABLED_TEXT = (
    "🌙 Менструальный цикл\n\n"
    "Эта функция помогает считать дни цикла и напоминать о возможном начале "
    "месячных.\n\n"
    "Бот не ставит диагнозы и не заменяет врача. Расчёты являются примерными."
)

ASK_START_DATE_TEXT = (
    "Укажите дату начала последних месячных.\n\n"
    "Например:\n"
    "12.05.2026\n"
    "12.05\n"
    "сегодня\n"
    "вчера"
)
ASK_END_DATE_TEXT = (
    "Укажите дату окончания месячных, если они уже закончились.\n"
    "Если они ещё идут, можно отметить окончание позже."
)
ASK_CUSTOM_DATE_TEXT = (
    "Введите дату в формате 12.05.2026, 12.05, ‘сегодня’ или ‘вчера’."
)


# ---------- low-level helpers ----------

async def _send(update: Update, text: str, markup=None) -> None:
    query = update.callback_query
    if query is not None:
        try:
            await query.edit_message_text(text, reply_markup=markup)
            return
        except BadRequest:
            await query.message.reply_text(text, reply_markup=markup)
            return
    await update.message.reply_text(text, reply_markup=markup)


def _fmt_date(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else "—"


def _get_user_id_and_tz(tg_id: int) -> tuple[int, str, date]:
    with session_scope() as session:
        user = survey_service.get_or_create_user(
            session, tg_id, config.DEFAULT_TIMEZONE
        )
        return user.id, user.timezone, user_local_date(user.timezone)


def _build_root_text(summary: dict) -> str:
    if not summary["is_enabled"]:
        return DISABLED_TEXT
    lines = ["🌙 Менструальный цикл", "", "Функция включена.", ""]
    lines.append(f"Последнее начало: {_fmt_date(summary['latest_period_start'])}")
    if summary["latest_period_end"]:
        lines.append(f"Последнее окончание: {_fmt_date(summary['latest_period_end'])}")
    elif summary["has_open_period"]:
        lines.append("Период открыт (окончание ещё не отмечено).")
    cd = summary["cycle_day"]
    if cd is not None:
        lines.append(f"Текущий день цикла: {cd}")
    pred = summary["predicted_next_start"]
    if pred:
        prefix = "Примерное"
        if summary["low_confidence"]:
            prefix = "По стандартному циклу 28 дн. — примерное"
        lines.append(f"{prefix} следующее начало: {_fmt_date(pred)}")
    return "\n".join(lines)


# ---------- root screens ----------

async def _show_root(update: Update, tg_id: int) -> None:
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_today = user_local_date(user.timezone)
            summary = mcs.get_cycle_summary(session, user.id, local_today)
    except Exception:
        logger.exception("Ошибка чтения cycle summary")
        await _send(update, "Не удалось загрузить экран цикла.")
        return
    text = _build_root_text(summary)
    if summary["is_enabled"]:
        markup = cycle_root_enabled_keyboard(
            has_open_period=summary["has_open_period"]
        )
    else:
        markup = cycle_root_disabled_keyboard()
    await _send(update, text, markup)


async def cycle_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry-point из qs:menu (callback qs:cycle)."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    await _show_root(update, update.effective_user.id)


async def cycle_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Главный роутер cycle:*, не относящийся к FSM."""
    query = update.callback_query
    await query.answer()
    data = query.data
    tg_id = update.effective_user.id

    if data == "cycle:menu":
        await _show_root(update, tg_id)
        return

    if data == "cycle:disable":
        await _send(
            update,
            "Выключить отслеживание цикла?\n\n"
            "Данные о ваших периодах сохранятся — функцию можно будет включить "
            "снова.",
            cycle_disable_confirm_keyboard(),
        )
        return

    if data == "cycle:disable_ok":
        try:
            with session_scope() as session:
                user = survey_service.get_or_create_user(
                    session, tg_id, config.DEFAULT_TIMEZONE
                )
                mcs.disable(session, user.id)
            # Снимаем daily job — больше уведомлений не приходит.
            jq = context.application.job_queue
            if jq is not None:
                for job in jq.get_jobs_by_name(f"{CYCLE_JOB_PREFIX}{tg_id}"):
                    job.schedule_removal()
        except Exception:
            logger.exception("Ошибка disable cycle")
        await _show_root(update, tg_id)
        return

    if data == "cycle:day":
        await _show_day(update, tg_id)
        return

    if data == "cycle:notif":
        await _show_notif(update, tg_id)
        return

    if data.startswith("cycle:toggle:"):
        await _handle_notif_toggle(update, tg_id, data.split(":")[2])
        return

    # start / end через пресеты "сегодня / вчера" (custom уходит во FSM).
    if data in (
        "cycle:start:today",
        "cycle:start:yesterday",
        "cycle:end:today",
        "cycle:end:yesterday",
    ):
        await _handle_quick_date(update, tg_id, data)
        return

    if data == "cycle:end:long_ok":
        await _handle_long_end_confirm(update, tg_id)
        return

    if data == "cycle:pred:before_ack":
        # пользователь подтвердил, что услышал предупреждение — больше делать
        # нечего, состояние и так уже отмечено в last_before_start_notification_date
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            pass
        return

    if data == "cycle:pred:start:no":
        # переносим follow-up на завтра. Сейчас никаких UI-изменений не нужно.
        try:
            with session_scope() as session:
                user = survey_service.get_or_create_user(
                    session, tg_id, config.DEFAULT_TIMEZONE
                )
                mcs.clear_start_check(session, user.id)
            logger.info("cycle_start_denied user_id=%s", user.id)
            await _send(
                update,
                "Хорошо. Я спрошу снова завтра, если не наступит сегодня.",
            )
        except Exception:
            logger.exception("Ошибка обработки 'нет' для прогноза начала")
        return

    if data in ("cycle:pred:start:today", "cycle:pred:start:yesterday"):
        await _handle_prediction_start(update, tg_id, data)
        return

    if data in (
        "cycle:pred:end:today",
        "cycle:pred:end:yesterday",
        "cycle:pred:end:no",
    ):
        await _handle_prediction_end(update, tg_id, data)
        return


# ---------- quick date ops (sego/vchera) ----------

async def _handle_quick_date(update: Update, tg_id: int, data: str) -> None:
    op, when = data.split(":")[1], data.split(":")[2]
    # op = 'start' | 'end', when = 'today' | 'yesterday'
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_today = user_local_date(user.timezone)
            target = (
                local_today if when == "today"
                else local_today - timedelta(days=1)
            )
            if op == "start":
                _commit_start(session, user.id, target, local_today, source="manual")
                text = f"Начало месячных отмечено: {_fmt_date(target)}."
            else:
                mcs.set_period_end(session, user.id, target, local_today)
                mcs.refresh_prediction(session, user.id)
                text = f"Окончание месячных отмечено: {_fmt_date(target)}."
    except CycleValidationError as e:
        logger.info("cycle_validation_failed: %s", e)
        await _send(update, str(e))
        return
    except Exception:
        logger.exception("Ошибка отметки %s/%s", op, when)
        await _send(update, "Не удалось сохранить. Попробуйте позже.")
        return
    await _send(update, text)
    await _show_root(update, tg_id)


async def _handle_long_end_confirm(update: Update, tg_id: int) -> None:
    """Подтверждение длинного периода (>14 дней). Закрываем сегодняшним числом
    с allow_long_period=True. В контексте используем local_today как
    целевую дату; для более точного UX можно хранить дату в user_data, но
    в текущем флоу пользователь дошёл сюда из быстрой кнопки и подтверждает
    именно сегодняшнюю дату."""
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_today = user_local_date(user.timezone)
            mcs.set_period_end(
                session, user.id, local_today, local_today, allow_long_period=True
            )
            mcs.refresh_prediction(session, user.id)
    except CycleValidationError as e:
        await _send(update, str(e))
        return
    except Exception:
        logger.exception("Ошибка long_ok end")
        await _send(update, "Не удалось сохранить. Попробуйте позже.")
        return
    await _send(update, f"Окончание месячных отмечено: {_fmt_date(local_today)}.")
    await _show_root(update, tg_id)


def _commit_start(
    session,
    user_id: int,
    target: date,
    local_today: date,
    *,
    source: str,
) -> None:
    mcs.create_period_start(
        session, user_id, target, local_today, source=source,
        close_open_period_before=True,
    )
    mcs.refresh_prediction(session, user_id)


# ---------- prediction confirmations ----------

async def _handle_prediction_start(update: Update, tg_id: int, data: str) -> None:
    when = data.split(":")[3]  # today | yesterday
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_today = user_local_date(user.timezone)
            target = (
                local_today if when == "today" else local_today - timedelta(days=1)
            )
            _commit_start(
                session, user.id, target, local_today, source="prediction_confirmed"
            )
            mcs.clear_start_check(session, user.id)
            logger.info(
                "cycle_start_confirmed user_id=%s date=%s", user.id, target
            )
    except CycleValidationError as e:
        await _send(update, str(e))
        return
    except Exception:
        logger.exception("Ошибка подтверждения начала из прогноза")
        await _send(update, "Не удалось сохранить. Попробуйте позже.")
        return
    await _send(update, f"Принято. Начало месячных: {_fmt_date(target)}.")


async def _handle_prediction_end(update: Update, tg_id: int, data: str) -> None:
    choice = data.split(":")[3]
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_today = user_local_date(user.timezone)
            if choice == "no":
                mcs.clear_end_check(session, user.id)
                await _send(update, "Хорошо. Спрошу снова позже.")
                return
            target = (
                local_today if choice == "today" else local_today - timedelta(days=1)
            )
            try:
                mcs.set_period_end(session, user.id, target, local_today)
            except CycleValidationError as e:
                if "выглядит большой" in str(e):
                    await _send(
                        update,
                        f"{e}\n\nЕсли это правда, подтвердите.",
                        cycle_long_period_confirm_keyboard(),
                    )
                    return
                raise
            mcs.clear_end_check(session, user.id)
            mcs.refresh_prediction(session, user.id)
            logger.info(
                "cycle_end_confirmed user_id=%s date=%s", user.id, target
            )
    except CycleValidationError as e:
        await _send(update, str(e))
        return
    except Exception:
        logger.exception("Ошибка подтверждения окончания из прогноза")
        await _send(update, "Не удалось сохранить. Попробуйте позже.")
        return
    await _send(update, f"Окончание месячных отмечено: {_fmt_date(target)}.")


# ---------- day screen ----------

async def _show_day(update: Update, tg_id: int) -> None:
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_today = user_local_date(user.timezone)
            summary = mcs.get_cycle_summary(session, user.id, local_today)
    except Exception:
        logger.exception("Ошибка _show_day")
        await _send(update, "Не удалось получить день цикла.")
        return
    if summary["cycle_day"] is None:
        text = (
            "Пока не хватает данных, чтобы посчитать день цикла. "
            "Отметьте начало месячных, и я начну считать."
        )
    else:
        text = (
            f"📅 Сегодня день цикла: {summary['cycle_day']}\n\n"
            f"Последнее начало: {_fmt_date(summary['latest_period_start'])}\n"
        )
        if summary["predicted_next_start"]:
            text += (
                f"Примерное следующее начало: "
                f"{_fmt_date(summary['predicted_next_start'])}"
            )
    await _send(
        update, text,
        cycle_root_enabled_keyboard(has_open_period=summary["has_open_period"]),
    )


# ---------- notifications ----------

async def _show_notif(update: Update, tg_id: int) -> None:
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            s = mcs.get_settings(session, user.id)
            if s is None or not s.is_enabled:
                await _show_root(update, tg_id)
                return
            data = (
                s.notify_before_predicted_start,
                s.notify_on_predicted_start,
                s.ask_period_end,
            )
    except Exception:
        logger.exception("Ошибка чтения notif settings")
        await _send(update, "Не удалось загрузить настройки.")
        return
    await _send(
        update,
        "🔔 Уведомления о цикле\n\nВыберите, какие напоминания вам нужны.",
        cycle_notif_keyboard(*data),
    )


async def _handle_notif_toggle(update: Update, tg_id: int, which: str) -> None:
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            s = mcs.get_settings(session, user.id)
            if s is None:
                return
            if which == "before":
                mcs.update_notification_settings(
                    session, user.id,
                    notify_before_predicted_start=not s.notify_before_predicted_start,
                )
            elif which == "start":
                mcs.update_notification_settings(
                    session, user.id,
                    notify_on_predicted_start=not s.notify_on_predicted_start,
                )
            elif which == "end":
                mcs.update_notification_settings(
                    session, user.id,
                    ask_period_end=not s.ask_period_end,
                )
    except Exception:
        logger.exception("Ошибка переключения notif")
    await _show_notif(update, tg_id)


# ============================================================
#                FSM: ввод даты текстом
# ============================================================

async def cycle_enable_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """callback cycle:enable. Включает функцию и запускает onboarding."""
    query = update.callback_query
    await query.answer()
    tg_id = update.effective_user.id
    user_snapshot = None
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            mcs.enable(session, user.id)
            user_snapshot = (user.id, user.telegram_user_id, user.timezone)
    except Exception:
        logger.exception("Ошибка enable cycle")
        await _send(update, "Не удалось включить функцию. Попробуйте позже.")
        return ConversationHandler.END
    # Запускаем ежедневный job уведомлений. SimpleNamespace, чтобы не дёргать
    # БД снова — schedule_user_cycle читает только id/telegram_user_id/timezone.
    if user_snapshot is not None:
        from types import SimpleNamespace
        u_id, u_tg, u_tz = user_snapshot
        schedule_user_cycle(
            context.application,
            SimpleNamespace(id=u_id, telegram_user_id=u_tg, timezone=u_tz),
        )
    context.user_data["cycle_pending_op"] = OP_ONBOARD_START
    await _send(update, ASK_START_DATE_TEXT)
    return AWAIT_DATE


async def cycle_start_custom_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["cycle_pending_op"] = OP_MARK_START
    await _send(update, ASK_CUSTOM_DATE_TEXT)
    return AWAIT_DATE


async def cycle_end_custom_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["cycle_pending_op"] = OP_MARK_END
    await _send(update, ASK_CUSTOM_DATE_TEXT)
    return AWAIT_DATE


async def cycle_onb_end_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["cycle_pending_op"] = OP_ONBOARD_END
    await _send(update, ASK_CUSTOM_DATE_TEXT)
    return AWAIT_DATE


async def cycle_onb_still(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Пользователь нажал «Ещё идут» — оставляем период открытым."""
    query = update.callback_query
    await query.answer()
    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            mcs.refresh_prediction(session, user.id)
    except Exception:
        logger.exception("Ошибка refresh_prediction после onb_still")
    context.user_data.pop("cycle_pending_op", None)
    await _send(
        update,
        "Готово. Я включил отслеживание цикла.\n\n"
        "Теперь я буду считать день цикла автоматически и смогу напоминать "
        "о возможном начале следующих месячных.",
    )
    await _show_root(update, tg_id)
    return ConversationHandler.END


async def cycle_pred_start_custom_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["cycle_pending_op"] = OP_PRED_START_CUSTOM
    await _send(update, ASK_CUSTOM_DATE_TEXT)
    return AWAIT_DATE


async def cycle_receive_date(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    raw = (update.message.text or "").strip()
    tg_id = update.effective_user.id
    op = context.user_data.get("cycle_pending_op")
    if not op:
        await update.message.reply_text("Действие истекло. Откройте меню снова.")
        return ConversationHandler.END

    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            local_today = user_local_date(user.timezone)
            parsed = parse_user_date(raw, local_today)
            if parsed is None:
                logger.info(
                    "cycle_date_parse_failed user_id=%s raw=%r", user.id, raw
                )
                await update.message.reply_text(
                    "Не понял дату. Попробуйте 12.05.2026, 12.05, "
                    "‘сегодня’ или ‘вчера’."
                )
                return AWAIT_DATE

            try:
                if op == OP_ONBOARD_START:
                    _commit_start(
                        session, user.id, parsed, local_today, source="manual"
                    )
                    # после onboarding-старта спросим про окончание
                    context.user_data["cycle_pending_op"] = OP_ONBOARD_END
                    await update.message.reply_text(
                        f"Принято. Начало: {_fmt_date(parsed)}.\n\n"
                        + ASK_END_DATE_TEXT,
                        reply_markup=cycle_onboarding_end_keyboard(),
                    )
                    return AWAIT_DATE
                if op == OP_ONBOARD_END:
                    mcs.set_period_end(session, user.id, parsed, local_today)
                    mcs.refresh_prediction(session, user.id)
                    context.user_data.pop("cycle_pending_op", None)
                    await update.message.reply_text(
                        "Готово. Я включил отслеживание цикла.\n\n"
                        "Теперь я буду считать день цикла автоматически и смогу "
                        "напоминать о возможном начале следующих месячных."
                    )
                    await _show_root(update, tg_id)
                    return ConversationHandler.END
                if op == OP_MARK_START:
                    _commit_start(
                        session, user.id, parsed, local_today, source="manual"
                    )
                    await update.message.reply_text(
                        f"Начало месячных отмечено: {_fmt_date(parsed)}."
                    )
                elif op == OP_MARK_END:
                    mcs.set_period_end(session, user.id, parsed, local_today)
                    mcs.refresh_prediction(session, user.id)
                    await update.message.reply_text(
                        f"Окончание месячных отмечено: {_fmt_date(parsed)}."
                    )
                elif op == OP_PRED_START_CUSTOM:
                    _commit_start(
                        session, user.id, parsed, local_today,
                        source="prediction_confirmed",
                    )
                    mcs.clear_start_check(session, user.id)
                    await update.message.reply_text(
                        f"Принято. Начало месячных: {_fmt_date(parsed)}."
                    )
            except CycleValidationError as e:
                logger.info("cycle_validation_failed: %s", e)
                await update.message.reply_text(str(e))
                return AWAIT_DATE
    except Exception:
        logger.exception("Ошибка cycle_receive_date op=%s", op)
        await update.message.reply_text(
            "Не удалось сохранить. Попробуйте позже."
        )

    context.user_data.pop("cycle_pending_op", None)
    await _show_root(update, tg_id)
    return ConversationHandler.END


async def cycle_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("cycle_pending_op", None)
    if update.callback_query is not None:
        await update.callback_query.answer()
    await _send(update, "Отменено.")
    await _show_root(update, update.effective_user.id)
    return ConversationHandler.END


async def cycle_cancel_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("cycle_pending_op", None)
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


# ============================================================
#                       handlers builders
# ============================================================

def build_cycle_conversation() -> ConversationHandler:
    """ConversationHandler с одним состоянием AWAIT_DATE и несколькими
    entry-callback-ами, ведущими в это состояние."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cycle_enable_start, pattern=r"^cycle:enable$"),
            CallbackQueryHandler(
                cycle_start_custom_entry, pattern=r"^cycle:start:custom$"
            ),
            CallbackQueryHandler(
                cycle_end_custom_entry, pattern=r"^cycle:end:custom$"
            ),
            CallbackQueryHandler(
                cycle_onb_end_entry, pattern=r"^cycle:onb:end_custom$"
            ),
            CallbackQueryHandler(
                cycle_onb_still, pattern=r"^cycle:onb:still$"
            ),
            CallbackQueryHandler(
                cycle_pred_start_custom_entry,
                pattern=r"^cycle:pred:start:custom$",
            ),
        ],
        states={
            AWAIT_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cycle_receive_date),
                CallbackQueryHandler(
                    cycle_onb_end_entry, pattern=r"^cycle:onb:end_custom$"
                ),
                CallbackQueryHandler(
                    cycle_onb_still, pattern=r"^cycle:onb:still$"
                ),
                CallbackQueryHandler(cycle_cancel, pattern=r"^cycle:menu$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cycle_cancel_cmd)],
        name="cycle_conversation",
        persistent=False,
        allow_reentry=True,
    )


def build_cycle_router() -> CallbackQueryHandler:
    """Прочие cycle:* — кроме того, что обрабатывает ConversationHandler."""
    return CallbackQueryHandler(
        cycle_router,
        pattern=(
            r"^cycle:("
            r"menu|disable|disable_ok|day|notif|toggle:[a-z]+|"
            r"start:(today|yesterday)|"
            r"end:(today|yesterday|long_ok)|"
            r"pred:before_ack|"
            r"pred:start:(today|yesterday|no)|"
            r"pred:end:(today|yesterday|no)"
            r")$"
        ),
    )


def build_cycle_open_handler() -> CallbackQueryHandler:
    """Вход в раздел из qs:menu (callback qs:cycle)."""
    return CallbackQueryHandler(cycle_open, pattern=r"^qs:cycle$")
