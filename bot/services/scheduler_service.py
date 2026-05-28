"""Планирование плановых опросов и повторных напоминаний через PTB JobQueue."""

import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from telegram.ext import Application, ContextTypes

from bot.config import config
from bot.constants import PENDING_STATUS, SOURCE_SCHEDULED
from bot.database import session_scope
from bot.models import User, UserSettings
from bot.services import survey_service
from bot.utils.time_utils import compute_schedule, get_tz

logger = logging.getLogger(__name__)

SCHEDULED_JOB_PREFIX = "scheduled:"
REMINDER_JOB_PREFIX = "reminder:"
CLEANUP_JOB_NAME = "cleanup_expired_pendings"


def schedule_user(application: Application, user: User, settings: UserSettings) -> None:
    """Удаляет старые задачи пользователя и ставит новые согласно настройкам."""
    job_queue = application.job_queue
    if job_queue is None:
        logger.warning("JobQueue не инициализирована")
        return

    name = f"{SCHEDULED_JOB_PREFIX}{user.telegram_user_id}"
    for job in job_queue.get_jobs_by_name(name):
        job.schedule_removal()

    if not settings.notifications_enabled:
        logger.info(
            "Уведомления выключены для tg=%s, расписание не ставится",
            user.telegram_user_id,
        )
        return

    schedule = compute_schedule(
        settings.frequency_per_day, settings.start_time, settings.end_time
    )
    tz = get_tz(user.timezone)
    for slot in schedule:
        job_queue.run_daily(
            send_scheduled_survey,
            time=time(slot.hour, slot.minute, tzinfo=tz),
            name=name,
            data={"telegram_user_id": user.telegram_user_id},
        )
    logger.info(
        "Расписание пересобрано для tg=%s: %s слотов",
        user.telegram_user_id,
        len(schedule),
    )


def reschedule_all(application: Application) -> None:
    with session_scope() as session:
        users = session.scalars(
            select(User).where(User.is_active.is_(True))
        ).all()
        for user in users:
            settings = survey_service.get_settings(session, user.id)
            if settings is None:
                continue
            schedule_user(application, user, settings)


def schedule_cleanup(application: Application) -> None:
    job_queue = application.job_queue
    if job_queue is None:
        return
    for job in job_queue.get_jobs_by_name(CLEANUP_JOB_NAME):
        job.schedule_removal()
    # Раз в час чистим устаревшие pending.
    job_queue.run_repeating(
        cleanup_expired_pendings,
        interval=timedelta(hours=1),
        first=timedelta(minutes=5),
        name=CLEANUP_JOB_NAME,
    )


async def send_scheduled_survey(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Шлет плановое уведомление с кнопкой и создает pending запись."""
    from bot.keyboards.survey_keyboards import start_survey_keyboard
    from bot.texts import SURVEY_SCHEDULED_INTRO
    from bot.services.notification_sender import safe_send_message

    data = context.job.data or {}
    telegram_user_id = data.get("telegram_user_id")
    if telegram_user_id is None:
        return

    try:
        with session_scope() as session:
            user = survey_service.get_user_by_tg(session, telegram_user_id)
            if user is None:
                return
            if not user.is_active:
                logger.info(
                    "notification_skipped_inactive_user tg=%s type=scheduled",
                    telegram_user_id,
                )
                # Снимаем jobs пользователя на ближайшее время — больше не
                # нужно дёргать send_scheduled_survey/send_reminder для него.
                _remove_user_jobs(context, telegram_user_id)
                return
            settings = survey_service.get_settings(session, user.id)
            if settings is None or not settings.notifications_enabled:
                return
            reminder_enabled = settings.reminder_enabled
            reminder_delay = settings.reminder_delay_minutes
    except Exception:
        logger.exception("Ошибка БД при отправке планового опроса")
        return

    # 1. Сначала пытаемся отправить — и только при успехе создаём pending.
    sent = await safe_send_message(
        context.bot,
        telegram_user_id,
        SURVEY_SCHEDULED_INTRO,
        reply_markup=start_survey_keyboard(),
        notification_type="scheduled_survey",
    )
    if not sent:
        # safe_send_message сам деактивировал пользователя при Forbidden /
        # chat-gone. Pending не создаём, чтобы он не оставался висеть.
        return

    # 2. Pending после успешной отправки.
    try:
        with session_scope() as session:
            user = survey_service.get_user_by_tg(session, telegram_user_id)
            if user is None or not user.is_active:
                return
            pending = survey_service.create_pending(
                session, user.id, datetime.now(timezone.utc)
            )
            pending_id = pending.id
    except Exception:
        logger.exception(
            "Ошибка создания pending после отправки tg=%s", telegram_user_id
        )
        return

    logger.info(
        "scheduled_notification_sent tg=%s pending=%s", telegram_user_id, pending_id
    )

    if reminder_enabled:
        context.job_queue.run_once(
            send_reminder,
            when=timedelta(minutes=reminder_delay),
            name=f"{REMINDER_JOB_PREFIX}{pending_id}",
            data={
                "telegram_user_id": telegram_user_id,
                "pending_id": pending_id,
            },
        )


async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.keyboards.survey_keyboards import start_survey_keyboard
    from bot.texts import SURVEY_REMINDER
    from bot.services.notification_sender import safe_send_message

    data = context.job.data or {}
    telegram_user_id = data.get("telegram_user_id")
    pending_id = data.get("pending_id")
    if telegram_user_id is None or pending_id is None:
        return

    try:
        with session_scope() as session:
            from bot.models import PendingSurvey

            user = survey_service.get_user_by_tg(session, telegram_user_id)
            if user is None or not user.is_active:
                logger.info(
                    "notification_skipped_inactive_user tg=%s type=reminder",
                    telegram_user_id,
                )
                _remove_user_jobs(context, telegram_user_id)
                return
            pending = session.get(PendingSurvey, pending_id)
            if pending is None or pending.status != PENDING_STATUS:
                # Уже завершен или истек — ничего не делаем.
                return
    except Exception:
        logger.exception("Ошибка БД при отправке напоминания")
        return

    sent = await safe_send_message(
        context.bot,
        telegram_user_id,
        SURVEY_REMINDER,
        reply_markup=start_survey_keyboard(),
        notification_type="reminder",
    )
    if not sent:
        # Не помечаем pending как reminder_sent — попробуем в следующий цикл.
        return

    try:
        with session_scope() as session:
            survey_service.mark_pending_reminder_sent(session, pending_id)
    except Exception:
        logger.exception(
            "Ошибка пометки pending=%s reminder_sent после успешной отправки",
            pending_id,
        )
        return

    logger.info(
        "reminder_notification_sent tg=%s pending=%s",
        telegram_user_id, pending_id,
    )


def _remove_user_jobs(
    context: ContextTypes.DEFAULT_TYPE, telegram_user_id: int
) -> None:
    """Снимает все pending jobs пользователя: расписание + cycle daily.
    Используется когда мы знаем, что пользователь стал inactive, чтобы
    лишние job не дёргали send_scheduled_survey / cycle_daily_check.
    """
    from bot.services.cycle_scheduler import CYCLE_JOB_PREFIX

    jq = context.job_queue
    if jq is None:
        return
    name = f"{SCHEDULED_JOB_PREFIX}{telegram_user_id}"
    for job in jq.get_jobs_by_name(name):
        job.schedule_removal()
    cycle_name = f"{CYCLE_JOB_PREFIX}{telegram_user_id}"
    for job in jq.get_jobs_by_name(cycle_name):
        job.schedule_removal()


async def cleanup_expired_pendings(context: ContextTypes.DEFAULT_TYPE) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.PENDING_EXPIRE_HOURS)
    try:
        with session_scope() as session:
            n = survey_service.expire_old_pendings(session, cutoff)
            if n:
                logger.info("Помечено как expired: %s записей", n)
    except Exception:
        logger.exception("Ошибка при очистке pending_surveys")
