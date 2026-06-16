"""Перечисления значений, хранимых в БД, и их человекочитаемые подписи."""

# Источник записи
SOURCE_SCHEDULED = "scheduled"
SOURCE_MANUAL = "manual"
SOURCE_REMINDER = "reminder"

# Статусы pending_surveys
PENDING_STATUS = "pending"
REMINDER_SENT_STATUS = "reminder_sent"
COMPLETED_STATUS = "completed"
EXPIRED_STATUS = "expired"
# Опрос был перезапущен кнопкой напоминания, пока старый не завершился.
# Снимает старый pending из активных, чтобы его reminder-джоба не сработала
# повторно. Колонка status — String(16) без CHECK, миграция не нужна.
ABANDONED_STATUS = "abandoned"

# Длительность сна
SLEEP_DURATION_CATEGORIES = [
    ("no_sleep", "Не спал(а)"),
    ("less_3h", "Меньше 3 часов"),
    ("3_5h", "3–5 часов"),
    ("5_7h", "5–7 часов"),
    ("7_9h", "7–9 часов"),
    ("more_9h", "Больше 9 часов"),
]
SLEEP_DURATION_LABELS = dict(SLEEP_DURATION_CATEGORIES)
SLEEP_DURATION_LABELS["skipped"] = "—"
SLEEP_DURATION_TO_HOURS = {
    "no_sleep": 0,
    "less_3h": 2,
    "3_5h": 4,
    "5_7h": 6,
    "7_9h": 8,
    "more_9h": 10,
    "skipped": 0,
}

# Качество сна
SLEEP_QUALITY_CATEGORIES = [
    ("terrible", "Ужасный"),
    ("bad", "Плохой"),
    ("normal", "Нормальный"),
    ("good", "Хороший"),
    ("deep", "Крепкий"),
]
SLEEP_QUALITY_LABELS = dict(SLEEP_QUALITY_CATEGORIES)
SLEEP_QUALITY_LABELS["skipped"] = "—"
SLEEP_QUALITY_TO_SCORE = {
    "terrible": 1,
    "bad": 2,
    "normal": 3,
    "good": 4,
    "deep": 5,
    "skipped": 0,
}

# Проблемы сна
SLEEP_PROBLEMS = [
    ("hard_to_fall_asleep", "Долго не мог(ла) уснуть"),
    ("early_wakeup", "Проснулся/проснулась слишком рано"),
    ("frequent_wakeups", "Часто просыпался/просыпалась"),
    ("little_sleep_but_feel_good", "Спал(а) мало, но чувствую себя отлично"),
    ("long_sleep_not_restored", "Спал(а) много, но не восстановился/восстановилась"),
]
SLEEP_PROBLEM_LABELS = dict(SLEEP_PROBLEMS)

# Прием лекарств
MEDICATION_OPTIONS = [
    ("yes", "Да"),
    ("no", "Нет"),
    ("partial", "Частично"),
    ("not_applicable", "Не назначены / не принимаю"),
    ("skipped", "Пропустить"),
]
MEDICATION_LABELS = dict(MEDICATION_OPTIONS)

# Шкалы
MOOD_DESCRIPTIONS = {
    0: "тяжелая депрессия",
    1: "очень низкое настроение",
    2: "очень низкое настроение",
    3: "сниженное настроение",
    4: "сниженное настроение",
    5: "нейтральное состояние",
    6: "хорошее / приподнятое",
    7: "хорошее / приподнятое",
    8: "сверхприподнятое / разогнанное",
    9: "сверхприподнятое / разогнанное",
    10: "сверхприподнятое / разогнанное",
}

ANXIETY_DESCRIPTIONS = {
    0: "нет тревоги",
    1: "слабая",
    2: "умеренная",
    3: "заметная",
    4: "сильная",
    5: "очень сильная / паника",
}

ENERGY_DESCRIPTIONS = {
    0: "нет сил",
    1: "очень мало",
    2: "сниженная",
    3: "обычная",
    4: "повышенная",
    5: "очень много / сложно усидеть",
}

IRRITABILITY_DESCRIPTIONS = {
    0: "нет",
    1: "легкая",
    2: "умеренная",
    3: "заметная",
    4: "сильная",
    5: "очень сильная",
}

IMPULSIVITY_DESCRIPTIONS = {
    0: "нет",
    1: "немного",
    2: "умеренно",
    3: "заметно",
    4: "сильно",
    5: "очень сильно",
}

MAX_COMMENT_LENGTH = 1000
