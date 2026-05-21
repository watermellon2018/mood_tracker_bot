"""Сервис настроек опционных вопросов опроса.

База:
- question_catalog содержит все вопросы (базовые + опциональные).
- user_question_settings хранит только переключатели опциональных вопросов.
- Базовые (is_required=True) всегда считаются включенными — записей для них нет.
- Список enabled = required-вопросы ∪ опциональные с is_enabled=True.
"""
import logging
from typing import Iterable

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from bot.constants_questions import PRESETS
from bot.models import QuestionCatalog, UserQuestionSettings

logger = logging.getLogger(__name__)

SUICIDAL_CODE = "suicidal_thoughts"


# ---------- catalog ----------

def all_active_questions(session: Session) -> list[QuestionCatalog]:
    return list(
        session.scalars(
            select(QuestionCatalog)
            .where(QuestionCatalog.is_active.is_(True))
            .order_by(QuestionCatalog.sort_order.asc())
        )
    )


def required_codes(session: Session) -> set[str]:
    return set(
        session.scalars(
            select(QuestionCatalog.code).where(
                and_(
                    QuestionCatalog.is_required.is_(True),
                    QuestionCatalog.is_active.is_(True),
                )
            )
        )
    )


def optional_questions_by_category(
    session: Session, category: str
) -> list[QuestionCatalog]:
    return list(
        session.scalars(
            select(QuestionCatalog)
            .where(
                and_(
                    QuestionCatalog.category == category,
                    QuestionCatalog.is_active.is_(True),
                    QuestionCatalog.is_required.is_(False),
                )
            )
            .order_by(QuestionCatalog.sort_order.asc())
        )
    )


def all_optional_codes(session: Session) -> list[str]:
    return list(
        session.scalars(
            select(QuestionCatalog.code)
            .where(
                and_(
                    QuestionCatalog.is_active.is_(True),
                    QuestionCatalog.is_required.is_(False),
                )
            )
            .order_by(QuestionCatalog.sort_order.asc())
        )
    )


# ---------- user state ----------

def enabled_optional_codes(session: Session, user_id: int) -> set[str]:
    return set(
        session.scalars(
            select(UserQuestionSettings.question_code).where(
                and_(
                    UserQuestionSettings.user_id == user_id,
                    UserQuestionSettings.is_enabled.is_(True),
                )
            )
        )
    )


def enabled_codes_for_user(session: Session, user_id: int) -> set[str]:
    """Все включенные вопросы (required + опциональные пользователя)."""
    return required_codes(session) | enabled_optional_codes(session, user_id)


def set_question_enabled(
    session: Session, user_id: int, code: str, is_enabled: bool
) -> bool:
    """Устанавливает is_enabled для конкретного вопроса. Возвращает фактическое
    значение после операции. Игнорирует базовые и неизвестные вопросы.

    Особая защита: включить SUICIDAL_CODE можно только через явный путь —
    эта функция отказывается включать его (нужно подтверждение в UI).
    Если is_enabled=False — разрешено.
    """
    q = session.get(QuestionCatalog, code)
    if q is None or not q.is_active or q.is_required:
        return False
    if code == SUICIDAL_CODE and is_enabled:
        # Принудительный путь — выставлять только через set_suicidal_after_confirm.
        logger.warning(
            "Попытка прямого включения suicidal_thoughts user_id=%s — отказано",
            user_id,
        )
        return False

    return _upsert(session, user_id, code, is_enabled)


def set_suicidal_after_confirm(session: Session, user_id: int) -> bool:
    """Явный путь для включения suicidal_thoughts после подтверждения пользователя."""
    return _upsert(session, user_id, SUICIDAL_CODE, True)


def toggle_question(session: Session, user_id: int, code: str) -> bool:
    """Переключает состояние. Возвращает новое is_enabled. Для базовых/inactive — False."""
    q = session.get(QuestionCatalog, code)
    if q is None or not q.is_active or q.is_required:
        return False
    current = session.get(UserQuestionSettings, (user_id, code))
    new_value = not (current.is_enabled if current else False)
    # SUICIDAL — toggle разрешён только через отдельный путь (включение —
    # с подтверждением, выключение — свободно).
    if code == SUICIDAL_CODE and new_value:
        return False
    return _upsert(session, user_id, code, new_value)


def apply_preset(session: Session, user_id: int, preset_code: str) -> int:
    """Заменяет текущие опциональные настройки на пресет. SUICIDAL никогда
    не включается через пресеты. Возвращает кол-во включенных вопросов."""
    preset = PRESETS.get(preset_code)
    if preset is None:
        return 0
    codes = preset["codes"]
    if codes is None:  # 'all'
        codes = all_optional_codes(session)
    codes = [c for c in codes if c != SUICIDAL_CODE]

    optional = set(all_optional_codes(session))
    target = set(codes) & optional

    # 1) выключить всё, что не в target
    session.query(UserQuestionSettings).filter(
        UserQuestionSettings.user_id == user_id,
        UserQuestionSettings.question_code.notin_(target),
    ).update({"is_enabled": False}, synchronize_session=False)

    # 2) включить target (upsert)
    for code in target:
        _upsert(session, user_id, code, True)

    logger.info(
        "Применён пресет %s user_id=%s: %d вопросов включено",
        preset_code, user_id, len(target),
    )
    return len(target)


def reset_optional(session: Session, user_id: int) -> int:
    """Выключает все опциональные. Возвращает кол-во отключенных."""
    n = session.query(UserQuestionSettings).filter(
        UserQuestionSettings.user_id == user_id,
        UserQuestionSettings.is_enabled.is_(True),
    ).update({"is_enabled": False}, synchronize_session=False)
    logger.info("Сброс опциональных вопросов user_id=%s, выключено=%d", user_id, n)
    return n


# ---------- internal ----------

def _upsert(session: Session, user_id: int, code: str, is_enabled: bool) -> bool:
    """INSERT ... ON CONFLICT для user_question_settings.
    Простая реализация: получить запись, обновить или создать.
    """
    existing = session.get(UserQuestionSettings, (user_id, code))
    if existing is None:
        session.add(
            UserQuestionSettings(
                user_id=user_id, question_code=code, is_enabled=is_enabled
            )
        )
    else:
        existing.is_enabled = is_enabled
    session.flush()
    logger.info(
        "Вопрос %s user_id=%s -> is_enabled=%s", code, user_id, is_enabled
    )
    return is_enabled
