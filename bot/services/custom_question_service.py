"""Сервис пользовательских вопросов: CRUD, валидация, защита от чужого id."""

import logging
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


class ValidationError(ValueError):
    pass


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
) -> CustomQuestion:
    if answer_type not in ANSWER_TYPES:
        raise ValidationError(f"Неизвестный формат ответа: {answer_type}")
    normalized = _validate_text(text)

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
    )
    session.add(q)
    session.flush()
    logger.info(
        "Создан custom_question id=%s user_id=%s type=%s", q.id, user_id, answer_type
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
