"""Scheduler для уведомлений менструального цикла.

Один daily-job на пользователя, запускается в 10:00 локального времени.
Каждый запуск:
  1. Если функция выключена — выйти.
  2. Обновить prediction state.
  3. Проверить, нужно ли:
     - отправить «за N дней до возможного начала» (не чаще 1 раза в день);
     - спросить «начались сегодня?» (если predicted_next_start_date <= today
       и start_confirmation_active или ещё не запрошено сегодня) — окно N дней;
     - спросить «закончились?» если есть открытый период и наступила
       predicted_period_end_date — окно до 14 дней от старта.

Анти-спам: даты последних уведомлений хранятся в
menstrual_cycle_prediction_state.last_*. Один и тот же день — один запрос.
"""
from __future__ import annotations

import logging
from datetime import time, timedelta

from sqlalchemy import select
from telegram.ext import Application, ContextTypes

from bot.database import session_scope
from bot.keyboards.cycle_keyboards import (
    cycle_before_start_keyboard,
    cycle_predicted_end_keyboard,
    cycle_predicted_start_keyboard,
)
from bot.models import MenstrualCycleSettings, User
from bot.services import menstrual_cycle_service as mcs
from bot.utils.time_utils import get_tz, user_local_date

logger = logging.getLogger(__name__)

CYCLE_JOB_PREFIX = "cycle_daily:"
DEFAULT_CHECK_HOUR = 10  # 10:00 локально у пользователя

# Окна follow-up.
START_FOLLOWUP_DAYS = 7    # сколько дней спрашивать «начались?» после прогноза
END_FOLLOWUP_DAYS = 14     # сколько дней спрашивать «закончились?» от старта


def schedule_user_cycle(application: Application, user: User) -> None:
    job_queue = application.job_queue
    if job_queue is None:
        logger.warning("JobQueue не инициализирована")
        return
    name = f"{CYCLE_JOB_PREFIX}{user.telegram_user_id}"
    for job in job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    tz = get_tz(user.timezone)
    job_queue.run_daily(
        cycle_daily_check,
        time=time(DEFAULT_CHECK_HOUR, 0, tzinfo=tz),
        name=name,
        data={"telegram_user_id": user.telegram_user_id, "user_id": user.id},
    )
    logger.debug(
        "Запланирован cycle_daily для tg=%s в 10:00 (%s)",
        user.telegram_user_id, user.timezone,
    )


def reschedule_all_cycles(application: Application) -> None:
    """Перестраивает все daily-jobs цикла. Только для пользователей с
    включённой функцией и is_active=true."""
    with session_scope() as session:
        users = session.scalars(
            select(User).join(
                MenstrualCycleSettings,
                MenstrualCycleSettings.user_id == User.id,
            ).where(
                MenstrualCycleSettings.is_enabled.is_(True),
                User.is_active.is_(True),
            )
        ).all()
        for user in users:
            schedule_user_cycle(application, user)
        logger.info("cycle scheduler пересобран: %d пользователей", len(users))


# ============================================================
#                  daily check (job callback)
# ============================================================

def _mark_cycle_action_sent(user_id: int, action: str, local_today) -> None:
    """Помечает анти-спам state ПОСЛЕ успешной отправки. Если запись в БД
    падает — повторим уведомление завтра, это безопасно (пользователь
    получит дубль не чаще, чем 1 раз в день)."""
    try:
        with session_scope() as session:
            if action == "before_start":
                mcs.mark_before_start_notified(session, user_id, local_today)
            elif action == "start_check":
                mcs.mark_start_check_sent(session, user_id, local_today)
            elif action == "end_check":
                mcs.mark_end_check_sent(session, user_id, local_today)
    except Exception:
        logger.exception(
            "Не удалось пометить cycle action как отправленное user_id=%s action=%s",
            user_id, action,
        )


async def cycle_daily_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    telegram_user_id = data.get("telegram_user_id")
    user_id = data.get("user_id")
    if telegram_user_id is None or user_id is None:
        return

    # Готовим план уведомлений в БД (синхронно), сами message.send делаем
    # после выхода из session_scope().
    actions: list[tuple[str, dict]] = []
    try:
        with session_scope() as session:
            settings = mcs.get_settings(session, user_id)
            if settings is None or not settings.is_enabled:
                return
            # Уточняем TZ — может смениться.
            from bot.models import User as _User  # локально, избегаем циклов
            user = session.get(_User, user_id)
            if user is None:
                return
            if not user.is_active:
                logger.info(
                    "notification_skipped_inactive_user tg=%s type=cycle_daily",
                    telegram_user_id,
                )
                # Снимаем cycle job — пользователь больше не получит уведомлений.
                jq = context.job_queue
                if jq is not None:
                    for job in jq.get_jobs_by_name(
                        f"{CYCLE_JOB_PREFIX}{telegram_user_id}"
                    ):
                        job.schedule_removal()
                return
            local_today = user_local_date(user.timezone)
            mcs.refresh_prediction(session, user_id)
            state = mcs.get_state(session, user_id)
            if state is None:
                return

            pred = state.predicted_next_start_date

            # 1) За notify_days_before до прогноза.
            if (
                settings.notify_before_predicted_start
                and pred is not None
                and state.last_before_start_notification_date != local_today
            ):
                delta = (pred - local_today).days
                if delta == settings.notify_days_before:
                    actions.append(("before_start", {"days": delta, "pred": pred}))

            # 2) В день прогноза и далее, пока не подтвердят / не пройдёт окно.
            open_p = mcs.get_open_period(session, user_id)
            if (
                settings.notify_on_predicted_start
                and pred is not None
                and open_p is None  # уже подтверждён — спрашивать незачем
                and state.last_start_check_date != local_today
            ):
                if 0 <= (local_today - pred).days <= START_FOLLOWUP_DAYS:
                    actions.append(("start_check", {"pred": pred}))

            # 3) Спросить об окончании, если открыт период и прошёл прогноз окончания
            # либо общая длительность близка к лимиту.
            if (
                settings.ask_period_end
                and open_p is not None
                and state.last_end_check_date != local_today
            ):
                pred_end = state.predicted_period_end_date
                days_since_start = (
                    local_today - open_p.period_start_date
                ).days
                should_ask = False
                if pred_end is not None and local_today >= pred_end:
                    should_ask = True
                if 0 < days_since_start <= END_FOLLOWUP_DAYS and should_ask:
                    actions.append(("end_check", {}))
    except Exception:
        logger.exception("Ошибка cycle_daily_check user_id=%s", user_id)
        return

    # Отправка сообщений через safe_send_message. Помечаем как отправленное
    # только при success — иначе при временной ошибке потеряем уведомление,
    # а при Forbidden пользователь уже стал inactive и помечать смысла нет.
    from bot.services.notification_sender import safe_send_message

    for action, payload in actions:
        sent = False
        if action == "before_start":
            pred = payload["pred"]
            sent = await safe_send_message(
                context.bot,
                telegram_user_id,
                (
                    f"🌙 Возможное начало цикла примерно "
                    f"{pred.strftime('%d.%m.%Y')}.\n\n"
                    "Я напомню снова в день прогноза. Это примерный расчёт."
                ),
                reply_markup=cycle_before_start_keyboard(),
                notification_type="cycle_before_start",
            )
            if sent:
                _mark_cycle_action_sent(user_id, action, local_today)
                logger.info(
                    "cycle_before_start_notification_sent tg=%s pred=%s",
                    telegram_user_id, pred,
                )
        elif action == "start_check":
            sent = await safe_send_message(
                context.bot,
                telegram_user_id,
                "Сегодня начались месячные?",
                reply_markup=cycle_predicted_start_keyboard(),
                notification_type="cycle_start_check",
            )
            if sent:
                _mark_cycle_action_sent(user_id, action, local_today)
                logger.info(
                    "cycle_start_confirmation_sent tg=%s", telegram_user_id
                )
        elif action == "end_check":
            sent = await safe_send_message(
                context.bot,
                telegram_user_id,
                "Месячные закончились?",
                reply_markup=cycle_predicted_end_keyboard(),
                notification_type="cycle_end_check",
            )
            if sent:
                _mark_cycle_action_sent(user_id, action, local_today)
                logger.info(
                    "cycle_end_confirmation_sent tg=%s", telegram_user_id
                )
