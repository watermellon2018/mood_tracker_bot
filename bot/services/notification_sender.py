"""Безопасная отправка Telegram-сообщений в фоновых задачах.

Использовать ВЕЗДЕ, где сообщение может уйти к юзеру, который заблокировал
бота или удалил чат: scheduler-уведомления, daily-jobs, follow-up. Для
обычных reply на user action (handlers по нажатию кнопки) wrap не нужен —
пользователь точно может получить сообщение, иначе не нажал бы.

Возвращает bool: True — отправлено, False — не отправлено. False с
deactivate=True означает, что пользователь был помечен inactive.

PTB 21 exception map:
  - telegram.error.Forbidden — бот заблокирован пользователем
    (включая 'Forbidden: bot was blocked by the user').
  - telegram.error.BadRequest — "chat not found" / "user is deactivated"
    означают, что чат недоступен; прочие BadRequest — наш баг или вход.
  - telegram.error.TimedOut / NetworkError / RetryAfter — временные,
    не деактивируем.
"""
from __future__ import annotations

import logging
from typing import Any

from telegram import Bot
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from bot.database import session_scope
from bot.services import user_service

logger = logging.getLogger(__name__)

# Подстроки, по которым отличаем BadRequest «адресат недоступен» от прочих.
_CHAT_GONE_PHRASES = (
    "chat not found",
    "user is deactivated",
    "peer_id_invalid",
)


def _is_chat_gone(error_text: str) -> str | None:
    lowered = error_text.lower()
    if "user is deactivated" in lowered:
        return "user_deactivated"
    if "chat not found" in lowered:
        return "chat_not_found"
    if "peer_id_invalid" in lowered:
        return "chat_not_found"
    return None


def _deactivate(telegram_user_id: int, reason: str, error: Exception) -> None:
    try:
        with session_scope() as session:
            user_service.mark_user_blocked_bot(
                session, telegram_user_id, reason=reason
            )
    except Exception:
        # Деактивация не должна ломать send-цикл — логируем и идём дальше.
        logger.exception(
            "user_deactivation_failed tg=%s reason=%s", telegram_user_id, reason
        )
    logger.info(
        "notification_send_failed_%s tg=%s error=%s",
        reason, telegram_user_id, error,
    )


async def safe_send_message(
    bot: Bot,
    telegram_user_id: int,
    text: str,
    *,
    notification_type: str | None = None,
    **kwargs: Any,
) -> bool:
    try:
        await bot.send_message(chat_id=telegram_user_id, text=text, **kwargs)
        return True
    except Forbidden as e:
        _deactivate(telegram_user_id, "bot_blocked", e)
        return False
    except BadRequest as e:
        reason = _is_chat_gone(str(e))
        if reason is not None:
            _deactivate(telegram_user_id, reason, e)
            return False
        logger.warning(
            "telegram_bad_request_send_failed tg=%s type=%s error=%s",
            telegram_user_id, notification_type, e,
        )
        return False
    except RetryAfter as e:
        logger.warning(
            "telegram_rate_limit tg=%s retry_after=%s",
            telegram_user_id, getattr(e, "retry_after", None),
        )
        return False
    except (TimedOut, NetworkError) as e:
        logger.warning(
            "telegram_transient_error tg=%s error=%s", telegram_user_id, e
        )
        return False
    except Exception:
        logger.exception(
            "telegram_send_failed_unexpected tg=%s type=%s",
            telegram_user_id, notification_type,
        )
        return False


async def safe_send_document(
    bot: Bot,
    telegram_user_id: int,
    document: Any,
    *,
    filename: str | None = None,
    caption: str | None = None,
    notification_type: str | None = None,
    **kwargs: Any,
) -> bool:
    try:
        await bot.send_document(
            chat_id=telegram_user_id,
            document=document,
            filename=filename,
            caption=caption,
            **kwargs,
        )
        return True
    except Forbidden as e:
        _deactivate(telegram_user_id, "bot_blocked", e)
        return False
    except BadRequest as e:
        reason = _is_chat_gone(str(e))
        if reason is not None:
            _deactivate(telegram_user_id, reason, e)
            return False
        logger.warning(
            "telegram_bad_request_send_failed tg=%s type=%s error=%s",
            telegram_user_id, notification_type, e,
        )
        return False
    except (TimedOut, NetworkError, RetryAfter) as e:
        logger.warning("telegram_transient_error tg=%s error=%s", telegram_user_id, e)
        return False
    except Exception:
        logger.exception("telegram_send_failed_unexpected tg=%s", telegram_user_id)
        return False


async def safe_send_photo(
    bot: Bot,
    telegram_user_id: int,
    photo: Any,
    *,
    notification_type: str | None = None,
    **kwargs: Any,
) -> bool:
    try:
        await bot.send_photo(chat_id=telegram_user_id, photo=photo, **kwargs)
        return True
    except Forbidden as e:
        _deactivate(telegram_user_id, "bot_blocked", e)
        return False
    except BadRequest as e:
        reason = _is_chat_gone(str(e))
        if reason is not None:
            _deactivate(telegram_user_id, reason, e)
            return False
        logger.warning(
            "telegram_bad_request_send_failed tg=%s type=%s error=%s",
            telegram_user_id, notification_type, e,
        )
        return False
    except (TimedOut, NetworkError, RetryAfter) as e:
        logger.warning("telegram_transient_error tg=%s error=%s", telegram_user_id, e)
        return False
    except Exception:
        logger.exception("telegram_send_failed_unexpected tg=%s", telegram_user_id)
        return False
