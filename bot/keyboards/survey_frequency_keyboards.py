"""Клавиатуры для экрана '📅 Частота опроса'."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.survey_frequency_service import (
    FREQ_BIWEEKLY,
    FREQ_CUSTOM,
    FREQ_DAILY,
    FREQ_WEEKLY,
)


def _mark(is_active: bool) -> str:
    return "✅ " if is_active else ""


def survey_frequency_keyboard(current_type: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            f"{_mark(current_type == FREQ_DAILY)}Каждый день",
            callback_data=f"freq2:set:{FREQ_DAILY}",
        )],
        [InlineKeyboardButton(
            f"{_mark(current_type == FREQ_WEEKLY)}Раз в неделю",
            callback_data=f"freq2:set:{FREQ_WEEKLY}",
        )],
        [InlineKeyboardButton(
            f"{_mark(current_type == FREQ_BIWEEKLY)}Раз в 2 недели",
            callback_data=f"freq2:set:{FREQ_BIWEEKLY}",
        )],
        [InlineKeyboardButton(
            f"{_mark(current_type == FREQ_CUSTOM)}Каждые N дней",
            callback_data="freq2:custom",
        )],
        [InlineKeyboardButton("⬅️ Назад", callback_data="freq2:back")],
    ]
    return InlineKeyboardMarkup(rows)


def survey_frequency_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой Отмена под промптом ввода N дней."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="freq2:cancel")],
    ])
