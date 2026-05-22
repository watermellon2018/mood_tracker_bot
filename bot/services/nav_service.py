"""Единый набор хелперов для inline-навигации.

Цели:
- safe_edit  — отредактировать текущее inline-сообщение, без падений на
  устаревших/неизмененных сообщениях; fallback на новое сообщение.
- close_menu — закрыть inline-меню: попытаться удалить сообщение (лучший UX
  на мобильнике), иначе заменить на короткое подтверждение без клавиатуры.
- clear_state_and_close — то же + сброс FSM user_data ключей.

Все функции глотают ожидаемые ошибки Telegram API (`BadRequest`, `Forbidden`)
и логируют их на debug уровне — повторное нажатие кнопки не должно ронять бота.
"""
from __future__ import annotations

import logging
from typing import Iterable

from telegram import CallbackQuery, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

CLOSE_FALLBACK_TEXT = "Меню закрыто."


async def safe_edit(
    update: Update,
    text: str,
    markup: InlineKeyboardMarkup | None,
) -> None:
    """Отредактировать текущее сообщение (callback-кейс) или прислать новое.

    Подавляет:
    - 'message is not modified' — не паникуем, считаем успехом;
    - 'message to edit not found' / 'message can't be edited' — фолбэк на
      новое сообщение;
    - прочие BadRequest — логируем warning, фолбэк на новое сообщение.
    """
    query = update.callback_query
    if query is not None:
        try:
            await query.edit_message_text(text, reply_markup=markup)
            return
        except BadRequest as exc:
            msg = str(exc).lower()
            if "not modified" in msg:
                return
            logger.debug("safe_edit fallback: %s", exc)
            target = query.message
        except TelegramError as exc:
            logger.warning("safe_edit telegram error: %s", exc)
            target = query.message
    else:
        target = update.message
    if target is None:
        return
    try:
        await target.reply_text(text, reply_markup=markup)
    except TelegramError as exc:
        logger.warning("safe_edit reply fallback failed: %s", exc)


async def close_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    fallback_text: str = CLOSE_FALLBACK_TEXT,
) -> None:
    """Закрыть inline-меню. Сначала пробуем удалить сообщение (чище для UX
    на телефоне), при неудаче — редактируем на короткий текст без клавиатуры.

    Безопасно при повторном нажатии (сообщение могло уже быть удалено).
    """
    query = update.callback_query
    message = query.message if query is not None else update.message
    if message is None:
        return

    # Сначала пытаемся удалить.
    try:
        await message.delete()
        return
    except BadRequest as exc:
        msg = str(exc).lower()
        # 'message to delete not found' / 'message can't be deleted' — это ок,
        # делаем фолбэк на редактирование.
        logger.debug("close_menu: delete failed (%s), fallback to edit", exc)
    except Forbidden as exc:
        logger.debug("close_menu: delete forbidden (%s), fallback to edit", exc)
    except TelegramError as exc:
        logger.warning("close_menu: unexpected delete error: %s", exc)

    # Фолбэк: редактируем сообщение, чтобы убрать клавиатуру.
    if query is not None:
        try:
            await query.edit_message_text(fallback_text, reply_markup=None)
            return
        except BadRequest as exc:
            if "not modified" in str(exc).lower():
                return
            logger.debug("close_menu: edit failed (%s), sending new message", exc)
        except TelegramError as exc:
            logger.warning("close_menu: edit telegram error: %s", exc)
    # Последний рубеж — прислать новое сообщение.
    try:
        await message.reply_text(fallback_text)
    except TelegramError as exc:
        logger.warning("close_menu: final reply failed: %s", exc)


def clear_state_keys(
    context: ContextTypes.DEFAULT_TYPE, keys: Iterable[str]
) -> None:
    """Удаляет FSM-связанные ключи из context.user_data. Безопасно при отсутствии."""
    if context is None or context.user_data is None:
        return
    for key in keys:
        context.user_data.pop(key, None)


async def clear_state_and_close(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_keys: Iterable[str] = (),
    fallback_text: str = CLOSE_FALLBACK_TEXT,
) -> None:
    """Сбросить FSM-state ключи И закрыть меню. Используется в обработчиках
    кнопки '⬅️ Назад' / '❌ Отмена', находящихся внутри FSM."""
    clear_state_keys(context, state_keys)
    await close_menu(update, context, fallback_text=fallback_text)


async def answer_silently(query: CallbackQuery | None) -> None:
    """query.answer() с подавлением ошибок устаревшего callback."""
    if query is None:
        return
    try:
        await query.answer()
    except BadRequest as exc:
        logger.debug("callback.answer fallback: %s", exc)
    except TelegramError as exc:
        logger.debug("callback.answer telegram error: %s", exc)
