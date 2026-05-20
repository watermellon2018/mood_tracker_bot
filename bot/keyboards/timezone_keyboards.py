from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.utils.timezones import TIMEZONE_CALLBACK_MAP, TZ_PAGE_MAIN, TZ_PAGE_MORE


def _rows_from_keys(keys: list[str], cols: int = 2) -> list[list[InlineKeyboardButton]]:
    buttons = [
        InlineKeyboardButton(
            TIMEZONE_CALLBACK_MAP[k]["label"],
            callback_data=k,
        )
        for k in keys
    ]
    return [buttons[i : i + cols] for i in range(0, len(buttons), cols)]


def timezone_main_keyboard() -> InlineKeyboardMarkup:
    rows = _rows_from_keys(TZ_PAGE_MAIN, cols=2)
    rows.append([InlineKeyboardButton("Другое", callback_data="tz:more")])
    rows.append([InlineKeyboardButton("Отмена", callback_data="tz:cancel")])
    return InlineKeyboardMarkup(rows)


def timezone_more_keyboard() -> InlineKeyboardMarkup:
    rows = _rows_from_keys(TZ_PAGE_MORE, cols=2)
    rows.append(
        [
            InlineKeyboardButton("Назад", callback_data="tz:back"),
            InlineKeyboardButton("Отмена", callback_data="tz:cancel"),
        ]
    )
    return InlineKeyboardMarkup(rows)
