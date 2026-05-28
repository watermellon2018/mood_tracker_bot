"""Клавиатуры для раздела 'Свой вопрос' / 'Мои вопросы'."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.models import CustomQuestion
from bot.services.custom_question_service import (
    EVERY_N_DAYS_MAX,
    EVERY_N_DAYS_MIN,
    FREQUENCY_BIWEEKLY,
    FREQUENCY_EVERY_N_DAYS,
    FREQUENCY_EVERY_SURVEY,
    FREQUENCY_NTH_SURVEY,
    FREQUENCY_WEEKLY,
    SLOT_EVENING,
    SLOT_MIDDAY,
    SLOT_MORNING,
)

# Сокращения для отображения текста вопроса на кнопках.
MAX_BTN_TEXT = 45


def _truncate(text: str, limit: int = MAX_BTN_TEXT) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def cq_list_keyboard(questions: list[CustomQuestion]) -> InlineKeyboardMarkup:
    rows = []
    for q in questions:
        prefix = "✅" if q.is_enabled else "⬜"
        rows.append([
            InlineKeyboardButton(
                f"{prefix} {_truncate(q.question_text)}",
                callback_data=f"cq:view:{q.id}",
            )
        ])
    rows.append([InlineKeyboardButton("➕ Добавить вопрос", callback_data="cq:add")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="qs:menu")])
    return InlineKeyboardMarkup(rows)


def cq_empty_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить вопрос", callback_data="cq:add")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="qs:menu")],
    ])


def cq_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 Шкала 0–5", callback_data="cq:type:scale_0_5")],
        [InlineKeyboardButton("✅ Да / Нет", callback_data="cq:type:boolean")],
        [InlineKeyboardButton("📝 Текст", callback_data="cq:type:text")],
        [InlineKeyboardButton("⬅️ Отмена", callback_data="cq:cancel")],
    ])


def cq_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Добавить", callback_data="cq:confirm")],
        [InlineKeyboardButton("✏️ Изменить текст", callback_data="cq:edit_text")],
        [InlineKeyboardButton("🔄 Изменить формат", callback_data="cq:edit_type")],
        [InlineKeyboardButton("🔁 Изменить частоту", callback_data="cq:edit_freq")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cq:cancel")],
    ])


def cq_created_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Мои вопросы", callback_data="cq:list")],
        [InlineKeyboardButton("➕ Добавить ещё вопрос", callback_data="cq:add")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="qs:menu")],
    ])


def cq_view_keyboard(q: CustomQuestion) -> InlineKeyboardMarkup:
    toggle_label = "⬜ Выключить" if q.is_enabled else "✅ Включить"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"cq:toggle:{q.id}")],
        [InlineKeyboardButton("✏️ Переименовать", callback_data=f"cq:rename:{q.id}")],
        [InlineKeyboardButton(
            "🔁 Изменить частоту", callback_data=f"cq:freq:{q.id}"
        )],
        [InlineKeyboardButton("🗑 Архивировать", callback_data=f"cq:archive:{q.id}")],
        [InlineKeyboardButton("⬅️ К моим вопросам", callback_data="cq:list")],
    ])


def cq_archive_confirm_keyboard(question_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Архивировать", callback_data=f"cq:archive_ok:{question_id}"
        )],
        [InlineKeyboardButton(
            "❌ Отмена", callback_data=f"cq:view:{question_id}"
        )],
    ])


# ---------- частота показа ----------

def cq_frequency_keyboard(cancel_data: str = "cq:cancel") -> InlineKeyboardMarkup:
    """Клавиатура выбора типа частоты. Используется и в FSM создания, и в
    смене частоты у существующего вопроса. callback: cq:freq_set:<type>."""
    rows = [
        [InlineKeyboardButton(
            "📋 В каждом опросе",
            callback_data=f"cq:freq_set:{FREQUENCY_EVERY_SURVEY}",
        )],
        [InlineKeyboardButton(
            "🕐 В определённое время дня",
            callback_data=f"cq:freq_set:{FREQUENCY_NTH_SURVEY}",
        )],
        [InlineKeyboardButton(
            "📅 Раз в N дней (вечером)",
            callback_data=f"cq:freq_set:{FREQUENCY_EVERY_N_DAYS}",
        )],
        [InlineKeyboardButton(
            "🗓 Раз в неделю (вечером)",
            callback_data=f"cq:freq_set:{FREQUENCY_WEEKLY}",
        )],
        [InlineKeyboardButton(
            "🗓 Раз в две недели (вечером)",
            callback_data=f"cq:freq_set:{FREQUENCY_BIWEEKLY}",
        )],
        [InlineKeyboardButton("⬅️ Отмена", callback_data=cancel_data)],
    ]
    return InlineKeyboardMarkup(rows)


def cq_nth_survey_keyboard(cancel_data: str = "cq:cancel") -> InlineKeyboardMarkup:
    """Выбор слота опроса дня: утром / в середине дня / вечером."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🌅 Утром (первый опрос дня)",
            callback_data=f"cq:freq_n:{SLOT_MORNING}",
        )],
        [InlineKeyboardButton(
            "☀️ В середине дня",
            callback_data=f"cq:freq_n:{SLOT_MIDDAY}",
        )],
        [InlineKeyboardButton(
            "🌙 Вечером (последний опрос дня)",
            callback_data=f"cq:freq_n:{SLOT_EVENING}",
        )],
        [InlineKeyboardButton("⬅️ Назад", callback_data="cq:freq_back")],
        [InlineKeyboardButton("❌ Отмена", callback_data=cancel_data)],
    ])


def cq_every_n_days_keyboard(
    cancel_data: str = "cq:cancel",
) -> InlineKeyboardMarkup:
    """Выбор числа дней (EVERY_N_DAYS_MIN..EVERY_N_DAYS_MAX). Раскладка 5 в ряд."""
    buttons = [
        InlineKeyboardButton(str(i), callback_data=f"cq:freq_n:{i}")
        for i in range(EVERY_N_DAYS_MIN, EVERY_N_DAYS_MAX + 1)
    ]
    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="cq:freq_back")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data=cancel_data)])
    return InlineKeyboardMarkup(rows)


# ---------- ответы в опросе ----------

def cq_scale_0_5_keyboard() -> InlineKeyboardMarkup:
    """Кнопки 0..5 для scale_0_5 ответа. Префикс cqa: (custom question answer)."""
    buttons = [
        InlineKeyboardButton(str(i), callback_data=f"cqa:scale:{i}")
        for i in range(6)
    ]
    return InlineKeyboardMarkup([buttons])


def cq_boolean_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Да", callback_data="cqa:bool:1"),
            InlineKeyboardButton("Нет", callback_data="cqa:bool:0"),
        ],
    ])
