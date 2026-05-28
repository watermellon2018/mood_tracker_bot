"""Менструальный цикл: feature flag, периоды, расчёты, прогнозы.

Все операции синхронные, используются вместе с session_scope(), как остальные
сервисы. Привязка к users.id (внутренний user_id), не к telegram_user_id.

Главные операции:
  - enable / disable / is_enabled
  - get_settings, update_notification_settings
  - create_period_start, set_period_end, get_open_period, get_latest_period
  - get_current_cycle_day, median_cycle_length, median_period_length
  - predict_next_period_start, predict_period_end, refresh_prediction
  - get_cycle_summary (для UI + статистики)

Все даты — date (локальные у пользователя). Время сервера / UTC не используется
в расчётах cycle_day.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from bot.models import (
    MenstrualCyclePredictionState,
    MenstrualCycleSettings,
    MenstrualPeriod,
)

logger = logging.getLogger(__name__)


DEFAULT_CYCLE_LENGTH_DAYS = 28
DEFAULT_PERIOD_LENGTH_DAYS = 5
MEDIAN_WINDOW = 6           # сколько последних значений берём в медиану
MAX_PERIOD_LENGTH_DAYS = 14  # выше — нужен confirm/предупреждение
MAX_PERIOD_AGE_YEARS = 2     # дата начала старше 2 лет — рискованно


class CycleValidationError(ValueError):
    pass


# ============================================================
#                      settings (feature flag)
# ============================================================

def get_settings(
    session: Session, user_id: int
) -> MenstrualCycleSettings | None:
    return session.get(MenstrualCycleSettings, user_id)


def is_enabled(session: Session, user_id: int) -> bool:
    s = get_settings(session, user_id)
    return bool(s and s.is_enabled)


def enable(session: Session, user_id: int) -> MenstrualCycleSettings:
    s = get_settings(session, user_id)
    if s is None:
        s = MenstrualCycleSettings(user_id=user_id, is_enabled=True)
        session.add(s)
    else:
        s.is_enabled = True
    session.flush()
    logger.info("cycle_tracking_enabled user_id=%s", user_id)
    return s


def disable(session: Session, user_id: int) -> None:
    s = get_settings(session, user_id)
    if s is not None:
        s.is_enabled = False
        session.flush()
    # Состояние прогноза тоже гасим — иначе scheduler может сработать после
    # повторного включения по устаревшим датам.
    state = session.get(MenstrualCyclePredictionState, user_id)
    if state is not None:
        state.start_confirmation_active = False
        state.end_confirmation_active = False
        session.flush()
    logger.info("cycle_tracking_disabled user_id=%s", user_id)


def update_notification_settings(
    session: Session,
    user_id: int,
    *,
    notify_before_predicted_start: bool | None = None,
    notify_on_predicted_start: bool | None = None,
    ask_period_end: bool | None = None,
    notify_days_before: int | None = None,
) -> MenstrualCycleSettings | None:
    s = get_settings(session, user_id)
    if s is None:
        return None
    if notify_before_predicted_start is not None:
        s.notify_before_predicted_start = notify_before_predicted_start
    if notify_on_predicted_start is not None:
        s.notify_on_predicted_start = notify_on_predicted_start
    if ask_period_end is not None:
        s.ask_period_end = ask_period_end
    if notify_days_before is not None:
        if not (0 <= notify_days_before <= 7):
            raise CycleValidationError("notify_days_before должно быть 0..7.")
        s.notify_days_before = notify_days_before
    session.flush()
    return s


# ============================================================
#                            queries
# ============================================================

def _active_periods_q(user_id: int):
    return select(MenstrualPeriod).where(
        and_(
            MenstrualPeriod.user_id == user_id,
            MenstrualPeriod.status != "archived",
        )
    )


def get_open_period(
    session: Session, user_id: int
) -> MenstrualPeriod | None:
    return session.scalar(
        _active_periods_q(user_id)
        .where(MenstrualPeriod.period_end_date.is_(None))
        .order_by(desc(MenstrualPeriod.period_start_date))
        .limit(1)
    )


def get_latest_period(
    session: Session, user_id: int
) -> MenstrualPeriod | None:
    return session.scalar(
        _active_periods_q(user_id)
        .order_by(desc(MenstrualPeriod.period_start_date))
        .limit(1)
    )


def get_recent_starts(
    session: Session, user_id: int, limit: int = MEDIAN_WINDOW
) -> list[date]:
    rows = session.scalars(
        _active_periods_q(user_id)
        .order_by(desc(MenstrualPeriod.period_start_date))
        .limit(limit)
    ).all()
    return [p.period_start_date for p in rows]


def get_recent_closed_periods(
    session: Session, user_id: int, limit: int = MEDIAN_WINDOW
) -> list[MenstrualPeriod]:
    return list(
        session.scalars(
            _active_periods_q(user_id)
            .where(MenstrualPeriod.period_end_date.is_not(None))
            .order_by(desc(MenstrualPeriod.period_start_date))
            .limit(limit)
        )
    )


def find_period_containing(
    session: Session, user_id: int, target: date
) -> MenstrualPeriod | None:
    """Возвращает период, который содержит target (start <= target <= end или
    end IS NULL и start <= target)."""
    return session.scalar(
        _active_periods_q(user_id)
        .where(
            and_(
                MenstrualPeriod.period_start_date <= target,
                # NULL end — открытый, считаем "содержит".
                (
                    MenstrualPeriod.period_end_date.is_(None)
                    | (MenstrualPeriod.period_end_date >= target)
                ),
            )
        )
        .limit(1)
    )


# ============================================================
#                         mutations
# ============================================================

def _validate_start_date(
    period_start_date: date, local_today: date
) -> None:
    if period_start_date > local_today:
        raise CycleValidationError("Дата начала не может быть в будущем.")
    if (local_today - period_start_date).days > MAX_PERIOD_AGE_YEARS * 366:
        raise CycleValidationError(
            f"Дата выглядит слишком старой (старше {MAX_PERIOD_AGE_YEARS} лет)."
        )


def create_period_start(
    session: Session,
    user_id: int,
    period_start_date: date,
    local_today: date,
    *,
    source: str = "manual",
    close_open_period_before: bool = True,
) -> MenstrualPeriod:
    """Создаёт новый период с заданной датой начала.

    - Валидирует дату относительно local_today (TZ юзера).
    - Если внутри другого активного периода — отказ с CycleValidationError.
    - Если есть открытый предыдущий период (period_end_date IS NULL):
        * при close_open_period_before=True — закроем его днём до нового старта;
        * иначе бросим CycleValidationError (вызывающий handler решит UX).
    - source: 'manual' | 'prediction_confirmed' | 'imported'.
    """
    _validate_start_date(period_start_date, local_today)

    inside = find_period_containing(session, user_id, period_start_date)
    if inside is not None and inside.period_start_date != period_start_date:
        raise CycleValidationError(
            "Эта дата уже входит в другой отмеченный период. "
            "Сначала проверьте существующие записи."
        )
    # Дубль точно того же старта.
    dup = session.scalar(
        _active_periods_q(user_id)
        .where(MenstrualPeriod.period_start_date == period_start_date)
        .limit(1)
    )
    if dup is not None:
        raise CycleValidationError(
            "Период с такой датой начала уже отмечен."
        )

    open_p = get_open_period(session, user_id)
    if open_p is not None and open_p.period_start_date < period_start_date:
        if not close_open_period_before:
            raise CycleValidationError(
                "Предыдущий период ещё открыт. Сначала отметьте его окончание."
            )
        # Закрываем днём до нового начала.
        candidate_end = period_start_date - timedelta(days=1)
        if candidate_end < open_p.period_start_date:
            # Старый старт совпадает с днём перед новым — закроем в тот же день.
            candidate_end = open_p.period_start_date
        open_p.period_end_date = candidate_end
        open_p.status = "confirmed"
        session.flush()

    status = "open" if source == "prediction_confirmed" else "confirmed"
    # Если у нас тот же день старта = сегодня и end не задан — это open.
    # Для простоты делаем статус 'open' пока end IS NULL; при set_period_end
    # переключим на 'confirmed'.
    status = "open"
    p = MenstrualPeriod(
        user_id=user_id,
        period_start_date=period_start_date,
        period_end_date=None,
        source=source,
        status=status,
    )
    session.add(p)
    session.flush()
    logger.info(
        "period_start_created user_id=%s start=%s source=%s id=%s",
        user_id, period_start_date, source, p.id,
    )
    return p


def set_period_end(
    session: Session,
    user_id: int,
    period_end_date: date,
    local_today: date,
    *,
    allow_long_period: bool = False,
) -> MenstrualPeriod:
    """Закрывает последний открытый период. Бросает CycleValidationError.

    - period_end_date >= period_start_date;
    - не в будущем;
    - длительность <= MAX_PERIOD_LENGTH_DAYS, кроме allow_long_period=True.
    """
    p = get_open_period(session, user_id)
    if p is None:
        raise CycleValidationError(
            "Сейчас нет открытого периода. Сначала отметьте начало месячных."
        )
    if period_end_date > local_today:
        raise CycleValidationError("Дата окончания не может быть в будущем.")
    if period_end_date < p.period_start_date:
        raise CycleValidationError(
            "Дата окончания не может быть раньше даты начала."
        )
    duration = (period_end_date - p.period_start_date).days + 1
    if duration > MAX_PERIOD_LENGTH_DAYS and not allow_long_period:
        raise CycleValidationError(
            f"Длительность {duration} дней выглядит большой. "
            "Если это правда — подтвердите."
        )

    p.period_end_date = period_end_date
    p.status = "confirmed"
    session.flush()
    logger.info(
        "period_end_set user_id=%s id=%s end=%s duration=%s",
        user_id, p.id, period_end_date, duration,
    )
    return p


# ============================================================
#                       calculations
# ============================================================

def get_current_cycle_day(
    session: Session, user_id: int, local_today: date
) -> int | None:
    """День цикла = (local_today - последний_start).days + 1. None — нет данных."""
    latest = get_latest_period(session, user_id)
    if latest is None:
        return None
    if local_today < latest.period_start_date:
        logger.warning(
            "cycle_day local_today<period_start user_id=%s today=%s start=%s",
            user_id, local_today, latest.period_start_date,
        )
        return None
    return (local_today - latest.period_start_date).days + 1


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) // 2


def median_cycle_length(period_start_dates: list[date]) -> int | None:
    """period_start_dates — отсортированный по убыванию список последних стартов.
    Возвращает медиану длины цикла (соседние пары), либо None.
    """
    if len(period_start_dates) < 2:
        return None
    sorted_asc = sorted(period_start_dates)
    deltas = [
        (sorted_asc[i + 1] - sorted_asc[i]).days
        for i in range(len(sorted_asc) - 1)
    ]
    return _median(deltas)


def median_period_length(closed_periods: list[MenstrualPeriod]) -> int | None:
    """Медиана длительности закрытых периодов."""
    lens: list[int] = []
    for p in closed_periods:
        if p.period_end_date is None:
            continue
        lens.append((p.period_end_date - p.period_start_date).days + 1)
    if not lens:
        return None
    return _median(lens)


def predict_next_period_start(
    session: Session, user_id: int
) -> tuple[date | None, bool]:
    """Возвращает (predicted_date, low_confidence). low_confidence=True если
    данных мало (использован DEFAULT_CYCLE_LENGTH_DAYS)."""
    starts = get_recent_starts(session, user_id)
    if not starts:
        return None, True
    latest = starts[0]
    mc = median_cycle_length(starts)
    if mc is None:
        return latest + timedelta(days=DEFAULT_CYCLE_LENGTH_DAYS), True
    return latest + timedelta(days=mc), False


def predict_period_end(
    session: Session, user_id: int, period_start_date: date
) -> tuple[date, bool]:
    closed = get_recent_closed_periods(session, user_id)
    mp = median_period_length(closed)
    if mp is None:
        return (
            period_start_date + timedelta(days=DEFAULT_PERIOD_LENGTH_DAYS - 1),
            True,
        )
    return period_start_date + timedelta(days=mp - 1), False


# ============================================================
#                       prediction state
# ============================================================

def _get_or_create_state(
    session: Session, user_id: int
) -> MenstrualCyclePredictionState:
    state = session.get(MenstrualCyclePredictionState, user_id)
    if state is None:
        state = MenstrualCyclePredictionState(user_id=user_id)
        session.add(state)
        session.flush()
    return state


def refresh_prediction(
    session: Session, user_id: int
) -> MenstrualCyclePredictionState:
    """Пересчитывает predicted_next_start_date и predicted_period_end_date
    исходя из текущих данных. Не трогает last_*_date (анти-спам)."""
    state = _get_or_create_state(session, user_id)
    next_start, _ = predict_next_period_start(session, user_id)
    state.predicted_next_start_date = next_start
    open_p = get_open_period(session, user_id)
    if open_p is not None:
        end_pred, _ = predict_period_end(session, user_id, open_p.period_start_date)
        state.predicted_period_end_date = end_pred
    else:
        state.predicted_period_end_date = None
    session.flush()
    logger.info(
        "cycle_prediction_calculated user_id=%s next_start=%s end=%s",
        user_id, state.predicted_next_start_date, state.predicted_period_end_date,
    )
    return state


def mark_before_start_notified(
    session: Session, user_id: int, local_today: date
) -> None:
    state = _get_or_create_state(session, user_id)
    state.last_before_start_notification_date = local_today
    session.flush()


def mark_start_check_sent(
    session: Session, user_id: int, local_today: date
) -> None:
    state = _get_or_create_state(session, user_id)
    state.last_start_check_date = local_today
    state.start_confirmation_active = True
    session.flush()


def clear_start_check(session: Session, user_id: int) -> None:
    state = session.get(MenstrualCyclePredictionState, user_id)
    if state is None:
        return
    state.start_confirmation_active = False
    session.flush()


def mark_end_check_sent(
    session: Session, user_id: int, local_today: date
) -> None:
    state = _get_or_create_state(session, user_id)
    state.last_end_check_date = local_today
    state.end_confirmation_active = True
    session.flush()


def clear_end_check(session: Session, user_id: int) -> None:
    state = session.get(MenstrualCyclePredictionState, user_id)
    if state is None:
        return
    state.end_confirmation_active = False
    session.flush()


def get_state(
    session: Session, user_id: int
) -> MenstrualCyclePredictionState | None:
    return session.get(MenstrualCyclePredictionState, user_id)


# ============================================================
#                          summary
# ============================================================

def get_cycle_summary(
    session: Session, user_id: int, local_today: date
) -> dict[str, Any]:
    """Возвращает данные для UI / статистики. Все поля nullable; UI решает,
    что показать.
    """
    latest = get_latest_period(session, user_id)
    open_p = get_open_period(session, user_id)
    starts = get_recent_starts(session, user_id)
    closed = get_recent_closed_periods(session, user_id)
    cycle_day = get_current_cycle_day(session, user_id, local_today)
    mc = median_cycle_length(starts)
    mp = median_period_length(closed)
    next_start, low_conf = predict_next_period_start(session, user_id)
    state = get_state(session, user_id)
    return {
        "is_enabled": is_enabled(session, user_id),
        "latest_period_start": latest.period_start_date if latest else None,
        "latest_period_end": latest.period_end_date if latest else None,
        "has_open_period": open_p is not None,
        "cycle_day": cycle_day,
        "median_cycle_length": mc,
        "median_period_length": mp,
        "predicted_next_start": next_start,
        "low_confidence": low_conf,
        "predicted_period_end": (
            state.predicted_period_end_date if state else None
        ),
    }
