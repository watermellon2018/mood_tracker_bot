"""Клавиатуры для функции «Менструальный цикл»."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def cycle_root_disabled_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Включить", callback_data="cycle:enable")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="qs:menu")],
    ])


def cycle_root_enabled_keyboard(
    *, has_open_period: bool
) -> InlineKeyboardMarkup:
    """Главное меню цикла. Если есть открытый период (period_end_date IS NULL),
    показываем только «Отметить окончание». Если открытого периода нет —
    только «Отметить начало». Две одновременные кнопки сбивали с толку.
    """
    if has_open_period:
        action_row = [InlineKeyboardButton(
            "✅ Отметить окончание месячных", callback_data="cycle:end"
        )]
    else:
        action_row = [InlineKeyboardButton(
            "🩸 Отметить начало месячных", callback_data="cycle:start"
        )]
    return InlineKeyboardMarkup([
        action_row,
        [InlineKeyboardButton(
            "📅 Посмотреть текущий день цикла", callback_data="cycle:day"
        )],
        [InlineKeyboardButton(
            "🔔 Настройки уведомлений", callback_data="cycle:notif"
        )],
        [InlineKeyboardButton(
            "❌ Выключить функцию", callback_data="cycle:disable"
        )],
        [InlineKeyboardButton("⬅️ Назад", callback_data="qs:menu")],
    ])


def cycle_disable_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "❌ Выключить", callback_data="cycle:disable_ok"
        )],
        [InlineKeyboardButton("⬅️ Отмена", callback_data="cycle:menu")],
    ])


# ---------- onboarding ----------

def cycle_onboarding_end_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📅 Ввести дату окончания", callback_data="cycle:onb:end_custom"
        )],
        [InlineKeyboardButton(
            "⏳ Ещё идут", callback_data="cycle:onb:still"
        )],
        [InlineKeyboardButton("⬅️ Отмена", callback_data="cycle:menu")],
    ])


# ---------- mark start ----------

def cycle_start_pick_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Сегодня", callback_data="cycle:start:today")],
        [InlineKeyboardButton("Вчера", callback_data="cycle:start:yesterday")],
        [InlineKeyboardButton("Другая дата", callback_data="cycle:start:custom")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="cycle:menu")],
    ])


# ---------- mark end ----------

def cycle_end_pick_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Сегодня", callback_data="cycle:end:today")],
        [InlineKeyboardButton("Вчера", callback_data="cycle:end:yesterday")],
        [InlineKeyboardButton("Другая дата", callback_data="cycle:end:custom")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="cycle:menu")],
    ])


def cycle_long_period_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Подтвердить длинный период", callback_data="cycle:end:long_ok"
        )],
        [InlineKeyboardButton("⬅️ Отмена", callback_data="cycle:menu")],
    ])


# ---------- prediction confirmation ----------

def cycle_before_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🩸 Начались уже", callback_data="cycle:pred:start:today"
        )],
        [InlineKeyboardButton(
            "👌 Понятно", callback_data="cycle:pred:before_ack"
        )],
    ])


def cycle_predicted_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Да, сегодня", callback_data="cycle:pred:start:today"
        )],
        [InlineKeyboardButton(
            "Да, вчера", callback_data="cycle:pred:start:yesterday"
        )],
        [InlineKeyboardButton("Нет", callback_data="cycle:pred:start:no")],
        [InlineKeyboardButton(
            "Другая дата", callback_data="cycle:pred:start:custom"
        )],
    ])


def cycle_predicted_end_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Да, сегодня", callback_data="cycle:pred:end:today"
        )],
        [InlineKeyboardButton(
            "Да, вчера", callback_data="cycle:pred:end:yesterday"
        )],
        [InlineKeyboardButton(
            "Нет, ещё идут", callback_data="cycle:pred:end:no"
        )],
    ])


# ---------- notifications settings ----------

def cycle_notif_keyboard(
    notify_before: bool,
    notify_on: bool,
    ask_end: bool,
) -> InlineKeyboardMarkup:
    def mark(v: bool) -> str:
        return "✅" if v else "⬜"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{mark(notify_before)} Напоминать за 2 дня до возможного начала",
            callback_data="cycle:toggle:before",
        )],
        [InlineKeyboardButton(
            f"{mark(notify_on)} Спрашивать в день возможного начала",
            callback_data="cycle:toggle:start",
        )],
        [InlineKeyboardButton(
            f"{mark(ask_end)} Спрашивать окончание месячных",
            callback_data="cycle:toggle:end",
        )],
        [InlineKeyboardButton("⬅️ Назад", callback_data="cycle:menu")],
    ])
