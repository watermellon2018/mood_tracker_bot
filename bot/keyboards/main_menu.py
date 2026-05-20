from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Подписи кнопок reply-клавиатуры. Используются и для рендера, и для роутинга
# в MessageHandler (см. bot/handlers/start.py::reply_menu_router).
BTN_ADD = "📝 Добавить запись"
BTN_STATS = "📊 Статистика"
BTN_EXPORT = "📤 Экспорт"
BTN_SETTINGS = "⚙️ Настройки"
BTN_PAUSE = "⏸ Пауза"
BTN_RESUME = "▶️ Возобновить"
BTN_HELP = "❓ Помощь"


def main_menu_keyboard(notifications_enabled: bool = True) -> ReplyKeyboardMarkup:
    """Закрепленная reply-клавиатура у поля ввода."""
    pause_btn = BTN_PAUSE if notifications_enabled else BTN_RESUME
    rows = [
        [KeyboardButton(BTN_ADD), KeyboardButton(pause_btn)],
        [KeyboardButton(BTN_STATS), KeyboardButton(BTN_EXPORT), KeyboardButton(BTN_SETTINGS)],
        # [KeyboardButton(BTN_HELP)],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def main_menu_inline_keyboard(notifications_enabled: bool = True) -> InlineKeyboardMarkup:
    """Inline-вариант (если где-то понадобится прикрепить под сообщение)."""
    pause_label = "⏸ Пауза" if notifications_enabled else "▶️ Возобновить"
    pause_data = "menu:pause" if notifications_enabled else "menu:resume"

    rows = [
        [InlineKeyboardButton("📝 Добавить запись", callback_data="survey:start")],
        [
            InlineKeyboardButton("📊 Статистика", callback_data="menu:stats"),
            InlineKeyboardButton("📤 Экспорт", callback_data="menu:export"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data="menu:settings"),
            InlineKeyboardButton(pause_label, callback_data=pause_data),
        ],
        [InlineKeyboardButton("❓ Помощь", callback_data="menu:help")],
    ]
    return InlineKeyboardMarkup(rows)
