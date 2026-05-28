import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from bot.constants import (
    COMPLETED_STATUS,
    PENDING_STATUS,
    REMINDER_SENT_STATUS,
)
from bot.models import PendingSurvey, SurveyAnswer, SurveyEntry, User, UserSettings

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


def count_main_entries_for_date(
    session: Session, user_id: int, target_date: date
) -> int:
    """Сколько уже сохранённых survey_entries за локальный день.

    Считаем только sleep_type IN ('main','none') — те, что создаются полным
    опросом. 'additional' — дополнительный сон, не опрос.
    """
    return int(
        session.scalar(
            select(func.count(SurveyEntry.id)).where(
                and_(
                    SurveyEntry.user_id == user_id,
                    SurveyEntry.local_date == target_date,
                    SurveyEntry.sleep_type.in_(("main", "none")),
                )
            )
        )
        or 0
    )


def has_main_sleep_for_date(
    session: Session, user_id: int, target_date: date
) -> bool:
    return session.scalar(
        select(SurveyEntry.id).where(
            and_(
                SurveyEntry.user_id == user_id,
                SurveyEntry.local_date == target_date,
                SurveyEntry.sleep_type == "main",
            )
        ).limit(1)
    ) is not None


def has_medication_for_date(
    session: Session, user_id: int, target_date: date
) -> bool:
    return session.scalar(
        select(SurveyEntry.id).where(
            and_(
                SurveyEntry.user_id == user_id,
                SurveyEntry.local_date == target_date,
                SurveyEntry.medication_filled.is_(True),
            )
        ).limit(1)
    ) is not None


def get_medication_entry_for_date(
    session: Session, user_id: int, target_date: date
) -> SurveyEntry | None:
    return session.scalar(
        select(SurveyEntry).where(
            and_(
                SurveyEntry.user_id == user_id,
                SurveyEntry.local_date == target_date,
                SurveyEntry.medication_filled.is_(True),
            )
        ).order_by(SurveyEntry.created_at.desc()).limit(1)
    )


def save_entry(
    session: Session, user_id: int, data: dict[str, Any], local_date: date
) -> SurveyEntry:
    """Сохраняет основную запись опроса.

    `data` может содержать sleep_type ('main'|'none') и medication_filled (bool).
    Если sleep_type='none', поля сна заполняются дефолтами (категория из БД nullable=False,
    поэтому подставляем 'unknown'/'none' маркеры — см. ниже).
    """
    sleep_type = data.get("sleep_type", "main")
    medication_filled = data.get("medication_filled", True)
    entry = SurveyEntry(
        user_id=user_id,
        local_date=local_date,
        sleep_type=sleep_type,
        medication_filled=medication_filled,
        mood=data["mood"],
        anxiety=data["anxiety"],
        energy=data["energy"],
        # irritability/impulsivity теперь опциональные и пишутся в survey_answers.
        # Колонки сохраняются NULL.
        irritability=data.get("irritability"),
        impulsivity=data.get("impulsivity"),
        sleep_duration_category=data.get("sleep_duration_category", "skipped"),
        sleep_quality=data.get("sleep_quality", "skipped"),
        hard_to_fall_asleep=data.get("hard_to_fall_asleep", False),
        early_wakeup=data.get("early_wakeup", False),
        frequent_wakeups=data.get("frequent_wakeups", False),
        little_sleep_but_feel_good=data.get("little_sleep_but_feel_good", False),
        long_sleep_not_restored=data.get("long_sleep_not_restored", False),
        medication_taken=data.get("medication_taken", "not_applicable"),
        comment=data.get("comment"),
        source=data["source"],
    )
    session.add(entry)
    session.flush()
    logger.info(
        "Сохранена запись id=%s user_id=%s source=%s sleep_type=%s med_filled=%s",
        entry.id, user_id, entry.source, sleep_type, medication_filled,
    )
    return entry


def save_additional_sleep(
    session: Session,
    user_id: int,
    local_date: date,
    sleep_duration_category: str,
    sleep_quality: str,
    source: str,
) -> SurveyEntry:
    """Создаёт запись с sleep_type='additional' без вопросов настроения и т.п.
    Числовые шкалы заполняются нейтральными нулями — статистика игнорирует
    additional через фильтр sleep_type."""
    entry = SurveyEntry(
        user_id=user_id,
        local_date=local_date,
        sleep_type="additional",
        medication_filled=False,
        mood=0, anxiety=0, energy=0,
        irritability=None, impulsivity=None,
        sleep_duration_category=sleep_duration_category,
        sleep_quality=sleep_quality,
        hard_to_fall_asleep=False,
        early_wakeup=False,
        frequent_wakeups=False,
        little_sleep_but_feel_good=False,
        long_sleep_not_restored=False,
        medication_taken="not_applicable",
        comment=None,
        source=source,
    )
    session.add(entry)
    session.flush()
    logger.info(
        "Добавлен дополнительный сон id=%s user_id=%s date=%s", entry.id, user_id, local_date
    )
    return entry


def save_optional_answer(
    session: Session,
    entry_id: int,
    question_code: str,
    answer_text: str,
    answer_index: int,
) -> SurveyAnswer:
    """Записывает ответ на опциональный вопрос в EAV-таблицу."""
    a = SurveyAnswer(
        entry_id=entry_id,
        question_code=question_code,
        answer_value=answer_text,
        answer_numeric=answer_index,
    )
    session.add(a)
    session.flush()
    return a


def update_medication(
    session: Session, user_id: int, local_date: date, new_value: str
) -> SurveyEntry | None:
    """UPDATE сегодняшней записи с medication_filled=true. Возвращает её или None."""
    entry = get_medication_entry_for_date(session, user_id, local_date)
    if entry is None:
        return None
    entry.medication_taken = new_value
    session.flush()
    logger.info(
        "Обновлены лекарства id=%s user_id=%s -> %s", entry.id, user_id, new_value
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
