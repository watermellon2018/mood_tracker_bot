from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def period_keyboard(prefix: str, include_all: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("7 дней", callback_data=f"{prefix}:7"),
            InlineKeyboardButton("14 дней", callback_data=f"{prefix}:14"),
            InlineKeyboardButton("30 дней", callback_data=f"{prefix}:30"),
        ]
    ]
    if include_all:
        rows.append(
            [InlineKeyboardButton("Все данные", callback_data=f"{prefix}:all")]
        )
    return InlineKeyboardMarkup(rows)
