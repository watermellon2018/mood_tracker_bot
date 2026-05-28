"""Inline-клавиатуры для меню «📄 Отчёт»."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def report_menu_keyboard() -> InlineKeyboardMarkup:
    """Корневое меню Отчёт: PDF / Excel / Полный отчёт в чат."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📄 PDF-отчёт", callback_data="report:pdf"
        )],
        [InlineKeyboardButton(
            "📊 Excel-выгрузка", callback_data="report:excel"
        )],
        [InlineKeyboardButton(
            "📦 Полный отчёт в чат (все графики)",
            callback_data="report:full",
        )],
        [InlineKeyboardButton("⬅️ Назад", callback_data="report:close")],
    ])


def report_period_keyboard() -> InlineKeyboardMarkup:
    """Выбор периода для PDF-отчёта."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("7 дней", callback_data="report:period:7d")],
        [InlineKeyboardButton("30 дней", callback_data="report:period:30d")],
        [InlineKeyboardButton(
            "Текущий месяц", callback_data="report:period:current_month"
        )],
        [InlineKeyboardButton("3 месяца", callback_data="report:period:3m")],
        [InlineKeyboardButton("Всё время", callback_data="report:period:all")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="report:menu")],
    ])
