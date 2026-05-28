"""Сервис пользовательских вопросов: CRUD, валидация, защита от чужого id."""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from bot.models import CustomQuestion, CustomQuestionAnswer

logger = logging.getLogger(__name__)

MAX_TEXT_LEN = 150
MAX_ACTIVE_PER_USER = 10
ANSWER_TYPES = ("scale_0_5", "boolean", "text")
MAX_TEXT_ANSWER_LEN = 1000

# Типы частоты показа custom-вопроса в опросе. См. миграцию 0009.
FREQUENCY_EVERY_SURVEY = "every_survey"
FREQUENCY_NTH_SURVEY = "nth_survey"
FREQUENCY_EVERY_N_DAYS = "every_n_days"
FREQUENCY_WEEKLY = "weekly"
FREQUENCY_BIWEEKLY = "biweekly"
FREQUENCY_TYPES = (
    FREQUENCY_EVERY_SURVEY,
    FREQUENCY_NTH_SURVEY,
    FREQUENCY_EVERY_N_DAYS,
    FREQUENCY_WEEKLY,
    FREQUENCY_BIWEEKLY,
)

NTH_SURVEY_MIN = 1
# Для nth_survey ask_every_n хранит фиксированный слот дня:
#   1 = утро (первый опрос дня),
#   2 = середина дня (≈середина расписания),
#   3 = вечер (последний опрос дня).
# 1..3 укладывается в существующий CHECK (1..13 в миграции 0009) — схема
# не меняется.
NTH_SURVEY_MAX = 3
SLOT_MORNING = 1
SLOT_MIDDAY = 2
SLOT_EVENING = 3
EVERY_N_DAYS_MIN = 2
EVERY_N_DAYS_MAX = 30

_PERIODIC_FREQUENCIES = {
    FREQUENCY_EVERY_N_DAYS,
    FREQUENCY_WEEKLY,
    FREQUENCY_BIWEEKLY,
}


class ValidationError(ValueError):
    pass


def validate_frequency(
    frequency_type: str, every_n: int | None
) -> tuple[str, int | None]:
    """Проверяет тип частоты и значение N. Возвращает нормализованную пару.

    Для типов, не использующих N, every_n принудительно становится None
    (чтобы CHECK-констрейнт не упал даже если в FSM кто-то прокинул мусор)."""
    if frequency_type not in FREQUENCY_TYPES:
        raise ValidationError(f"Неизвестный тип частоты: {frequency_type}")
    if frequency_type == FREQUENCY_NTH_SURVEY:
        if every_n not in (SLOT_MORNING, SLOT_MIDDAY, SLOT_EVENING):
            raise ValidationError(
                "Выберите слот: утром, в середине дня или вечером."
            )
        return frequency_type, every_n
    if frequency_type == FREQUENCY_EVERY_N_DAYS:
        if not isinstance(every_n, int) or not (
            EVERY_N_DAYS_MIN <= every_n <= EVERY_N_DAYS_MAX
        ):
            raise ValidationError(
                f"Период в днях должен быть от {EVERY_N_DAYS_MIN} до "
                f"{EVERY_N_DAYS_MAX}."
            )
        return frequency_type, every_n
    return frequency_type, None


def should_ask(
    q: CustomQuestion,
    today: date,
    today_survey_index: int,
    is_last_survey_of_day: bool,
    *,
    freq_per_day: int = 1,
) -> bool:
    """Решает, нужно ли задать вопрос q в текущем опросе.

    today_survey_index — порядковый номер этого опроса в локальный день
    (1 = первый запланированный/ручной опрос дня и т.д.).
    is_last_survey_of_day — True, если текущий опрос — последний по расписанию.
    freq_per_day — пользовательская частота опросов в день (для слота 'midday').
    """
    ftype = q.ask_frequency_type or FREQUENCY_EVERY_SURVEY
    if ftype == FREQUENCY_EVERY_SURVEY:
        return True
    if ftype == FREQUENCY_NTH_SURVEY:
        slot = q.ask_every_n or 0
        if slot == SLOT_MORNING:
            return today_survey_index == 1
        if slot == SLOT_EVENING:
            return is_last_survey_of_day
        if slot == SLOT_MIDDAY:
            # «Середина дня» = округлённый middle расписания; для 1 опроса
            # — он же; для 2 — первый; для 3 — второй; для 4 — второй и т.д.
            target = max(1, (max(freq_per_day, 1) + 1) // 2)
            return today_survey_index == target
        # Старые значения (4..13) от прежней версии — не показываем, пока
        # пользователь не выберет новый слот.
        logger.warning(
            "Legacy nth_survey slot=%s on custom_question id=%s — пропускаем",
            slot, q.id,
        )
        return False
    if ftype in _PERIODIC_FREQUENCIES:
        if not is_last_survey_of_day:
            return False
        period_days = _period_days_for(ftype, q.ask_every_n)
        if period_days is None:
            return False
        last = q.last_asked_local_date
        if last is None:
            return True
        return (today - last) >= timedelta(days=period_days)
    # Неизвестный тип — на всякий случай показываем (back-compat).
    logger.warning("Unknown ask_frequency_type=%s on custom_question id=%s", ftype, q.id)
    return True


def _period_days_for(frequency_type: str, every_n: int | None) -> int | None:
    if frequency_type == FREQUENCY_EVERY_N_DAYS:
        return every_n if isinstance(every_n, int) and every_n >= 1 else None
    if frequency_type == FREQUENCY_WEEKLY:
        return 7
    if frequency_type == FREQUENCY_BIWEEKLY:
        return 14
    return None


def mark_asked(
    session: Session, question_ids: list[int], local_date: date
) -> None:
    """Обновляет last_asked_local_date пакетно. Вызывать после реального показа."""
    if not question_ids:
        return
    session.execute(
        CustomQuestion.__table__.update()
        .where(CustomQuestion.id.in_(question_ids))
        .values(last_asked_local_date=local_date)
    )


# ---------- queries ----------

def get_active(session: Session, user_id: int) -> list[CustomQuestion]:
    return list(
        session.scalars(
            select(CustomQuestion)
            .where(
                and_(
                    CustomQuestion.user_id == user_id,
                    CustomQuestion.is_active.is_(True),
                )
            )
            .order_by(CustomQuestion.sort_order.asc(), CustomQuestion.id.asc())
        )
    )


def get_enabled(session: Session, user_id: int) -> list[CustomQuestion]:
    return list(
        session.scalars(
            select(CustomQuestion)
            .where(
                and_(
                    CustomQuestion.user_id == user_id,
                    CustomQuestion.is_active.is_(True),
                    CustomQuestion.is_enabled.is_(True),
                )
            )
            .order_by(CustomQuestion.sort_order.asc(), CustomQuestion.id.asc())
        )
    )


def get_owned(
    session: Session, user_id: int, question_id: int
) -> CustomQuestion | None:
    """Возвращает вопрос ТОЛЬКО если он принадлежит пользователю.
    Защита от попыток обратиться к чужому id через callback."""
    q = session.get(CustomQuestion, question_id)
    if q is None or q.user_id != user_id:
        if q is not None:
            logger.warning(
                "Попытка доступа к чужому custom_question_id=%s от user_id=%s (owner=%s)",
                question_id, user_id, q.user_id,
            )
        return None
    return q


def count_active(session: Session, user_id: int) -> int:
    return int(
        session.scalar(
            select(func.count(CustomQuestion.id)).where(
                and_(
                    CustomQuestion.user_id == user_id,
                    CustomQuestion.is_active.is_(True),
                )
            )
        )
        or 0
    )


# ---------- validation ----------

def _normalize_text(text: str) -> str:
    return (text or "").strip()


def _validate_text(text: str) -> str:
    t = _normalize_text(text)
    if not t:
        raise ValidationError("Текст вопроса не может быть пустым.")
    if len(t) > MAX_TEXT_LEN:
        raise ValidationError(
            f"Слишком длинный текст (макс. {MAX_TEXT_LEN} символов)."
        )
    return t


def _is_duplicate(
    session: Session, user_id: int, normalized_text: str, exclude_id: int | None = None
) -> bool:
    stmt = select(CustomQuestion.id).where(
        and_(
            CustomQuestion.user_id == user_id,
            CustomQuestion.is_active.is_(True),
            func.lower(func.trim(CustomQuestion.question_text)) == normalized_text.lower(),
        )
    ).limit(1)
    if exclude_id is not None:
        stmt = stmt.where(CustomQuestion.id != exclude_id)
    return session.scalar(stmt) is not None


# ---------- mutations ----------

def create(
    session: Session,
    user_id: int,
    text: str,
    answer_type: str,
    ask_frequency_type: str = FREQUENCY_EVERY_SURVEY,
    ask_every_n: int | None = None,
) -> CustomQuestion:
    if answer_type not in ANSWER_TYPES:
        raise ValidationError(f"Неизвестный формат ответа: {answer_type}")
    normalized = _validate_text(text)
    ftype, n = validate_frequency(ask_frequency_type, ask_every_n)

    if count_active(session, user_id) >= MAX_ACTIVE_PER_USER:
        raise ValidationError(
            f"Пока можно добавить до {MAX_ACTIVE_PER_USER} своих вопросов. "
            "Чтобы добавить новый, архивируйте один из старых."
        )

    if _is_duplicate(session, user_id, normalized):
        raise ValidationError("У вас уже есть активный вопрос с таким текстом.")

    q = CustomQuestion(
        user_id=user_id,
        question_text=normalized,
        answer_type=answer_type,
        is_enabled=True,
        is_active=True,
        ask_frequency_type=ftype,
        ask_every_n=n,
    )
    session.add(q)
    session.flush()
    logger.info(
        "Создан custom_question id=%s user_id=%s type=%s freq=%s n=%s",
        q.id, user_id, answer_type, ftype, n,
    )
    return q


def update_frequency(
    session: Session,
    user_id: int,
    question_id: int,
    ask_frequency_type: str,
    ask_every_n: int | None,
) -> CustomQuestion | None:
    q = get_owned(session, user_id, question_id)
    if q is None or not q.is_active:
        return None
    ftype, n = validate_frequency(ask_frequency_type, ask_every_n)
    q.ask_frequency_type = ftype
    q.ask_every_n = n
    # При смене частоты сбрасываем "последнюю дату", чтобы новый период начал
    # отсчёт с ближайшего показа, а не от старой даты другого режима.
    q.last_asked_local_date = None
    session.flush()
    logger.info(
        "Обновлена частота custom_question id=%s user_id=%s -> %s n=%s",
        q.id, user_id, ftype, n,
    )
    return q


def toggle(
    session: Session, user_id: int, question_id: int
) -> bool | None:
    """Переключает is_enabled. Возвращает новое значение или None если вопрос
    не принадлежит пользователю / не существует / не активен."""
    q = get_owned(session, user_id, question_id)
    if q is None or not q.is_active:
        return None
    q.is_enabled = not q.is_enabled
    session.flush()
    logger.info(
        "Toggle custom_question id=%s user_id=%s -> is_enabled=%s",
        q.id, user_id, q.is_enabled,
    )
    return q.is_enabled


def rename(
    session: Session, user_id: int, question_id: int, new_text: str
) -> CustomQuestion | None:
    q = get_owned(session, user_id, question_id)
    if q is None or not q.is_active:
        return None
    normalized = _validate_text(new_text)
    if _is_duplicate(session, user_id, normalized, exclude_id=q.id):
        raise ValidationError("У вас уже есть активный вопрос с таким текстом.")
    q.question_text = normalized
    session.flush()
    logger.info("Переименован custom_question id=%s user_id=%s", q.id, user_id)
    return q


def archive(
    session: Session, user_id: int, question_id: int
) -> CustomQuestion | None:
    q = get_owned(session, user_id, question_id)
    if q is None or not q.is_active:
        return None
    q.is_active = False
    q.is_enabled = False
    session.flush()
    logger.info("Архивирован custom_question id=%s user_id=%s", q.id, user_id)
    return q


# ---------- answer persistence ----------

def save_answer(
    session: Session,
    entry_id: int,
    custom_question_id: int,
    answer_type: str,
    value: Any,
) -> CustomQuestionAnswer:
    """Сохраняет ответ. value трактуется по answer_type:
    - scale_0_5:  int 0..5 -> answer_numeric;
    - boolean:   bool       -> answer_bool;
    - text:      str        -> answer_text.
    Уникальный индекс (entry_id, custom_question_id) защищает от дублей.
    """
    answer_text = None
    answer_numeric: Decimal | None = None
    answer_bool = None

    if answer_type == "scale_0_5":
        if not isinstance(value, int) or not (0 <= value <= 5):
            raise ValidationError("scale_0_5: ожидается число 0..5")
        answer_numeric = Decimal(value)
    elif answer_type == "boolean":
        if not isinstance(value, bool):
            raise ValidationError("boolean: ожидается True/False")
        answer_bool = value
    elif answer_type == "text":
        if not isinstance(value, str):
            raise ValidationError("text: ожидается строка")
        v = value.strip()
        if not v:
            raise ValidationError("Текст ответа пустой.")
        if len(v) > MAX_TEXT_ANSWER_LEN:
            raise ValidationError(
                f"Слишком длинный ответ (макс. {MAX_TEXT_ANSWER_LEN} символов)."
            )
        answer_text = v
    else:
        raise ValidationError(f"Неизвестный формат ответа: {answer_type}")

    a = CustomQuestionAnswer(
        entry_id=entry_id,
        custom_question_id=custom_question_id,
        answer_type=answer_type,
        answer_text=answer_text,
        answer_numeric=answer_numeric,
        answer_bool=answer_bool,
    )
    session.add(a)
    session.flush()
    return a
