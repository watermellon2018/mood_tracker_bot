import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.constants import (
    COMPLETED_STATUS,
    PENDING_STATUS,
    REMINDER_SENT_STATUS,
)
from bot.models import PendingSurvey, SurveyEntry, User, UserSettings

logger = logging.getLogger(__name__)


def get_or_create_user(session: Session, telegram_user_id: int, default_tz: str) -> User:
    user = session.scalar(
        select(User).where(User.telegram_user_id == telegram_user_id)
    )
    if user is not None:
        return user
    user = User(telegram_user_id=telegram_user_id, timezone=default_tz)
    session.add(user)
    session.flush()
    settings = UserSettings(user_id=user.id)
    session.add(settings)
    session.flush()
    logger.info("Создан пользователь telegram_user_id=%s", telegram_user_id)
    return user


def get_user_by_tg(session: Session, telegram_user_id: int) -> User | None:
    return session.scalar(
        select(User).where(User.telegram_user_id == telegram_user_id)
    )


def set_user_timezone(session: Session, telegram_user_id: int, tz_name: str) -> User | None:
    """Сохраняет timezone пользователю и взводит флаг timezone_set.

    Вызывающий должен предварительно валидировать tz_name через
    bot.utils.timezones.is_valid_iana_timezone.
    """
    user = session.scalar(
        select(User).where(User.telegram_user_id == telegram_user_id)
    )
    if user is None:
        return None
    user.timezone = tz_name
    user.timezone_set = True
    session.flush()
    logger.info(
        "Обновлен timezone tg=%s -> %s", telegram_user_id, tz_name
    )
    return user


def get_settings(session: Session, user_id: int) -> UserSettings | None:
    return session.scalar(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )


def save_entry(session: Session, user_id: int, data: dict[str, Any]) -> SurveyEntry:
    entry = SurveyEntry(
        user_id=user_id,
        mood=data["mood"],
        anxiety=data["anxiety"],
        energy=data["energy"],
        irritability=data["irritability"],
        impulsivity=data["impulsivity"],
        sleep_duration_category=data["sleep_duration_category"],
        sleep_quality=data["sleep_quality"],
        hard_to_fall_asleep=data.get("hard_to_fall_asleep", False),
        early_wakeup=data.get("early_wakeup", False),
        frequent_wakeups=data.get("frequent_wakeups", False),
        little_sleep_but_feel_good=data.get("little_sleep_but_feel_good", False),
        long_sleep_not_restored=data.get("long_sleep_not_restored", False),
        medication_taken=data["medication_taken"],
        comment=data.get("comment"),
        source=data["source"],
    )
    session.add(entry)
    session.flush()
    logger.info(
        "Сохранена запись id=%s user_id=%s source=%s", entry.id, user_id, entry.source
    )
    return entry


def create_pending(session: Session, user_id: int, sent_at: datetime) -> PendingSurvey:
    pending = PendingSurvey(
        user_id=user_id, sent_at=sent_at, status=PENDING_STATUS
    )
    session.add(pending)
    session.flush()
    return pending


def latest_pending(session: Session, user_id: int) -> PendingSurvey | None:
    return session.scalar(
        select(PendingSurvey)
        .where(
            PendingSurvey.user_id == user_id,
            PendingSurvey.status.in_([PENDING_STATUS, REMINDER_SENT_STATUS]),
        )
        .order_by(PendingSurvey.sent_at.desc())
        .limit(1)
    )


def mark_pending_completed(session: Session, user_id: int) -> None:
    pending = latest_pending(session, user_id)
    if pending is not None:
        pending.status = COMPLETED_STATUS


def mark_pending_reminder_sent(session: Session, pending_id: int) -> None:
    pending = session.get(PendingSurvey, pending_id)
    if pending is not None and pending.status == PENDING_STATUS:
        pending.status = REMINDER_SENT_STATUS
        pending.reminder_sent_at = datetime.now(timezone.utc)


def expire_old_pendings(session: Session, older_than: datetime) -> int:
    pendings = session.scalars(
        select(PendingSurvey).where(
            PendingSurvey.status.in_([PENDING_STATUS, REMINDER_SENT_STATUS]),
            PendingSurvey.sent_at < older_than,
        )
    ).all()
    for p in pendings:
        p.status = "expired"
    return len(pendings)
