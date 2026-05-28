"""User lifecycle: soft delete (mark_user_blocked_bot) и реактивация.

Используется из safe_send-обёртки и /start handler-а. Sync (как остальные
сервисы), используется внутри `session_scope()`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.models import User

logger = logging.getLogger(__name__)


VALID_REASONS = {
    "bot_blocked",
    "user_deactivated",
    "chat_not_found",
    "manual_delete",
}


def get_user_by_tg(
    session: Session, telegram_user_id: int
) -> User | None:
    return session.scalar(
        select(User).where(User.telegram_user_id == telegram_user_id)
    )


def is_active(session: Session, telegram_user_id: int) -> bool:
    """Активен ли пользователь. None в БД считается inactive (защитнее)."""
    u = get_user_by_tg(session, telegram_user_id)
    return bool(u and u.is_active)


def mark_user_blocked_bot(
    session: Session,
    telegram_user_id: int,
    reason: str = "bot_blocked",
) -> User | None:
    """Soft-delete пользователя. Возвращает обновлённого User или None,
    если пользователя не существует.

    Идемпотентно: повторный вызов не падает, дату не перезаписывает у уже
    деактивированного.
    """
    if reason not in VALID_REASONS:
        # Защита от попытки вписать произвольное reason — CHECK всё равно
        # бы отбил, но лучше fail-fast.
        raise ValueError(f"Unknown deactivation reason: {reason}")

    user = get_user_by_tg(session, telegram_user_id)
    if user is None:
        logger.info(
            "user_deactivate_skipped_not_found tg=%s reason=%s",
            telegram_user_id, reason,
        )
        return None
    if not user.is_active:
        # Уже деактивирован — не трогаем deleted_at/blocked_bot_at, чтобы не
        # стирать историю.
        return user

    now = datetime.now(timezone.utc)
    user.is_active = False
    user.blocked_bot_at = now if reason == "bot_blocked" else user.blocked_bot_at
    user.deleted_at = now
    user.deactivation_reason = reason
    session.flush()
    logger.info(
        "user_deactivated tg=%s reason=%s", telegram_user_id, reason
    )
    return user


def reactivate_user(
    session: Session, telegram_user_id: int
) -> User | None:
    """Делает пользователя is_active=True и очищает deleted_at/blocked_bot_at/
    deactivation_reason. Возвращает (User, was_reactivated)."""
    user = get_user_by_tg(session, telegram_user_id)
    if user is None:
        return None
    if user.is_active:
        return user
    user.is_active = True
    user.blocked_bot_at = None
    user.deleted_at = None
    user.deactivation_reason = None
    session.flush()
    logger.info("user_reactivated_by_start tg=%s", telegram_user_id)
    return user
