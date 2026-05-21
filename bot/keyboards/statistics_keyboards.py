"""Inline-клавиатуры для меню статистики."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.constants_statistics import (
    STATISTICS_BLOCKS,
    block_to_short,
)


def stats_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Кратко", callback_data="stats:brief")],
        [InlineKeyboardButton("🎛 Выбранные блоки", callback_data="stats:selected")],
        [InlineKeyboardButton("📦 Полный отчет", callback_data="stats:full")],
        [InlineKeyboardButton("📄 Excel-отчет", callback_data="stats:excel")],
        [InlineKeyboardButton("⚙️ Настроить статистику", callback_data="stats:settings")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="stats:back")],
    ])


def stats_settings_keyboard(enabled: set[str]) -> InlineKeyboardMarkup:
    """Чекбоксы по всем блокам каталога. Один ряд = одна кнопка (тексты длинные).
    Сохраняем порядок из STATISTICS_BLOCKS."""
    rows = []
    for code, label, _cat in STATISTICS_BLOCKS:
        prefix = "✅" if code in enabled else "⬜"
        short = block_to_short(code)
        rows.append([InlineKeyboardButton(
            f"{prefix} {label}", callback_data=f"stats:tgl:{short}"
        )])
    rows.append([InlineKeyboardButton(
        "🔄 Сбросить к базовым", callback_data="stats:reset"
    )])
    rows.append([InlineKeyboardButton(
        "⬅️ Назад", callback_data="stats:menu"
    )])
    return InlineKeyboardMarkup(rows)
