"""Клавиатуры для раздела 'Свой вопрос' / 'Мои вопросы'."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.models import CustomQuestion

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
