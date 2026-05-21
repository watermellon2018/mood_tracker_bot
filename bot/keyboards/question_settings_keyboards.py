"""Inline-клавиатуры для экрана 'Вопросы опроса'."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.constants_questions import (
    CATEGORY_FULL_TO_SHORT,
    CATEGORY_LABELS,
    PRESET_ORDER,
    PRESETS,
)
from bot.models import QuestionCatalog


def qs_root_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🌧 Готовые наборы", callback_data="qs:presets")],
            [InlineKeyboardButton("🛠 Настроить вручную", callback_data="qs:manual")],
            [InlineKeyboardButton("🔄 Сбросить к базовому набору", callback_data="qs:reset")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="qs:back")],
        ]
    )


def qs_presets_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(PRESETS[code]["label"], callback_data=f"qs:preset:{code}")]
        for code in PRESET_ORDER
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="qs:menu")])
    return InlineKeyboardMarkup(rows)


def qs_preset_applied_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛠 Настроить вручную", callback_data="qs:manual")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="qs:menu")],
        ]
    )


def qs_categories_keyboard() -> InlineKeyboardMarkup:
    rows = []
    # Используем тот же порядок, что в CATEGORY_LABELS (Python dict сохраняет порядок).
    for full, label in CATEGORY_LABELS.items():
        short = CATEGORY_FULL_TO_SHORT[full]
        rows.append([InlineKeyboardButton(label, callback_data=f"qs:cat:{short}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="qs:menu")])
    return InlineKeyboardMarkup(rows)


def qs_category_questions_keyboard(
    questions: list[QuestionCatalog],
    enabled_codes: set[str],
) -> InlineKeyboardMarkup:
    rows = []
    for q in questions:
        prefix = "✅" if q.code in enabled_codes else "⬜"
        # Для suicidal_thoughts при включении показывается warning,
        # это решается на handler-уровне (callback тот же).
        rows.append(
            [InlineKeyboardButton(f"{prefix} {q.title}", callback_data=f"qs:tgl:{q.code}")]
        )
    rows.append([InlineKeyboardButton("⬅️ К категориям", callback_data="qs:manual")])
    return InlineKeyboardMarkup(rows)


def qs_suicide_warning_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Включить", callback_data="qs:suicide_confirm"),
                InlineKeyboardButton("Отмена", callback_data="qs:suicide_cancel"),
            ]
        ]
    )
