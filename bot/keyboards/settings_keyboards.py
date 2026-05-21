from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def settings_menu_keyboard(
    notifications_enabled: bool, reminder_enabled: bool
) -> InlineKeyboardMarkup:
    notif_label = (
        "Выключить уведомления" if notifications_enabled else "Включить уведомления"
    )
    rem_label = (
        "Выключить повторное напоминание"
        if reminder_enabled
        else "Включить повторное напоминание"
    )
    rows = [
        [   InlineKeyboardButton("Частота опросов", callback_data="set:freq"),
            InlineKeyboardButton("Время начала", callback_data="set:start"),
            InlineKeyboardButton("Время окончания", callback_data="set:end")],
        [   InlineKeyboardButton("Часовой пояс", callback_data="set:tz"),
            InlineKeyboardButton(notif_label, callback_data="set:toggle_notif")],
        [InlineKeyboardButton(rem_label, callback_data="set:toggle_rem")],
        [InlineKeyboardButton("Вопросы опроса", callback_data="qs:menu")],
    ]
    return InlineKeyboardMarkup(rows)


def frequency_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(str(i), callback_data=f"freq:{i}")
        for i in range(1, 14)
    ]
    rows = [buttons[i : i + 7] for i in range(0, len(buttons), 7)]
    return InlineKeyboardMarkup(rows)
