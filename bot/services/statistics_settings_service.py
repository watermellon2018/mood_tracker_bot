"""Сервис настроек блоков статистики.

Семантика:
- Если у пользователя в user_statistics_blocks нет записи для block_code —
  считаем включённым только если он в STATISTICS_DEFAULTS.
- При toggle первая запись для блока создаётся явно.
- При reset_to_default — стираем все записи пользователя. После этого
  поведение возвращается к дефолту.
"""
import logging

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from bot.constants_statistics import (
    STATISTICS_BLOCK_CODES_SET,
    STATISTICS_DEFAULTS,
)
from bot.models import UserStatisticsBlock

logger = logging.getLogger(__name__)


def get_enabled_blocks(session: Session, user_id: int) -> list[str]:
    """Возвращает список включённых block_code в каноничном порядке STATISTICS_BLOCKS.
    Включает defaults для блоков, у которых нет записей."""
    rows = list(
        session.scalars(
            select(UserStatisticsBlock).where(
                UserStatisticsBlock.user_id == user_id
            )
        )
    )
    user_state = {r.block_code: r.is_enabled for r in rows}

    enabled: set[str] = set()
    for code in STATISTICS_BLOCK_CODES_SET:
        if code in user_state:
            if user_state[code]:
                enabled.add(code)
        elif code in STATISTICS_DEFAULTS:
            enabled.add(code)
    # Сохраняем каноничный порядок (по STATISTICS_BLOCKS).
    from bot.constants_statistics import STATISTICS_BLOCK_CODES
    return [c for c in STATISTICS_BLOCK_CODES if c in enabled]


def is_block_enabled(session: Session, user_id: int, block_code: str) -> bool:
    if block_code not in STATISTICS_BLOCK_CODES_SET:
        return False
    row = session.get(UserStatisticsBlock, (user_id, block_code))
    if row is not None:
        return row.is_enabled
    return block_code in STATISTICS_DEFAULTS


def set_block(session: Session, user_id: int, block_code: str, is_enabled: bool) -> bool:
    if block_code not in STATISTICS_BLOCK_CODES_SET:
        logger.warning("Unknown statistics block_code: %s", block_code)
        return False
    row = session.get(UserStatisticsBlock, (user_id, block_code))
    if row is None:
        session.add(UserStatisticsBlock(
            user_id=user_id, block_code=block_code, is_enabled=is_enabled
        ))
    else:
        row.is_enabled = is_enabled
    session.flush()
    logger.info(
        "Statistics block %s user_id=%s -> %s", block_code, user_id, is_enabled
    )
    return is_enabled


def toggle_block(session: Session, user_id: int, block_code: str) -> bool | None:
    if block_code not in STATISTICS_BLOCK_CODES_SET:
        return None
    current = is_block_enabled(session, user_id, block_code)
    return set_block(session, user_id, block_code, not current)


def reset_to_default(session: Session, user_id: int) -> None:
    """Удаляем все пользовательские записи — поведение возвращается к дефолту."""
    session.query(UserStatisticsBlock).filter(
        UserStatisticsBlock.user_id == user_id
    ).delete(synchronize_session=False)
    logger.info("Statistics blocks reset to default user_id=%s", user_id)
