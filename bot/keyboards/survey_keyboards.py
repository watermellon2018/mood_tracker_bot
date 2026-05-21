from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.constants import (
    MEDICATION_OPTIONS,
    SLEEP_DURATION_CATEGORIES,
    SLEEP_PROBLEMS,
    SLEEP_QUALITY_CATEGORIES,
)


def scale_keyboard(prefix: str, max_value: int) -> InlineKeyboardMarkup:
    """Кнопки 0..max_value, по 6 в ряд."""
    buttons = [
        InlineKeyboardButton(str(i), callback_data=f"{prefix}:{i}")
        for i in range(max_value + 1)
    ]
    rows = [buttons[i : i + 6] for i in range(0, len(buttons), 6)]
    return InlineKeyboardMarkup(rows)


def mood_keyboard() -> InlineKeyboardMarkup:
    return scale_keyboard("mood", 10)


def anxiety_keyboard() -> InlineKeyboardMarkup:
    return scale_keyboard("anxiety", 5)


def energy_keyboard() -> InlineKeyboardMarkup:
    return scale_keyboard("energy", 5)


def irritability_keyboard() -> InlineKeyboardMarkup:
    return scale_keyboard("irritability", 5)


def impulsivity_keyboard() -> InlineKeyboardMarkup:
    return scale_keyboard("impulsivity", 5)


def sleep_duration_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"sleep_dur:{key}")]
        for key, label in SLEEP_DURATION_CATEGORIES
    ]
    return InlineKeyboardMarkup(rows)


def sleep_quality_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"sleep_q:{key}")]
        for key, label in SLEEP_QUALITY_CATEGORIES
    ]
    return InlineKeyboardMarkup(rows)


def sleep_problems_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    rows = []
    # Опция "Нет" сразу завершает шаг.
    rows.append(
        [InlineKeyboardButton("Нет", callback_data="sleep_p:__none__")]
    )
    for key, label in SLEEP_PROBLEMS:
        mark = "✓ " if key in selected else ""
        rows.append(
            [InlineKeyboardButton(f"{mark}{label}", callback_data=f"sleep_p:{key}")]
        )
    rows.append([InlineKeyboardButton("Готово", callback_data="sleep_p:__done__")])
    return InlineKeyboardMarkup(rows)


def medication_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"med:{key}")]
        for key, label in MEDICATION_OPTIONS
    ]
    return InlineKeyboardMarkup(rows)


def comment_skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Пропустить", callback_data="comment:skip")]]
    )


def unfinished_survey_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Продолжить", callback_data="unfinished:resume"),
                InlineKeyboardButton("Начать заново", callback_data="unfinished:restart"),
            ]
        ]
    )


def start_survey_keyboard() -> InlineKeyboardMarkup:
    """Кнопка для запуска планового опроса из уведомления."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Заполнить опрос", callback_data="survey:start")]]
    )


def optional_question_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    """5 кнопок по числу вариантов опционального вопроса. callback_data — индекс 0..N-1.

    Кнопки идут по одной в ряд — подписи у некоторых вопросов длинные.
    """
    rows = [
        [InlineKeyboardButton(label, callback_data=f"opt:{idx}")]
        for idx, label in enumerate(options)
    ]
    return InlineKeyboardMarkup(rows)
