"""Каталог блоков статистики + UI-маппинг.

`STATISTICS_BLOCKS` — список всех известных блоков: код, лейбл, категория.
Категория используется только для упорядочивания на экране настроек.

`STATISTICS_DEFAULTS` — что включено для нового пользователя.

`BLOCK_CALLBACK_SHORTS` — короткие коды для callback_data, т.к. некоторые
блоки имеют длинные имена (self_esteem_guilt, thought_speech_speed и т.п.)
и не вмещаются в 64-байтовый callback_data вместе с префиксом stats:tgl:.
"""

# (code, label, category)
STATISTICS_BLOCKS: list[tuple[str, str, str]] = [
    # Базовые
    ("summary",                "Краткое саммари",                       "base"),
    ("mood",                   "Настроение",                            "base"),
    ("anxiety",                "Тревога",                               "base"),
    ("sleep",                  "Сон",                                   "base"),
    ("energy",                 "Энергия",                               "base"),
    # Уже хранятся в SurveyEntry колонках
    ("mood_energy",            "Настроение × энергия",                  "base"),
    ("mood_spread",            "Разброс настроения",                    "base"),
    ("sleep_problems",         "Проблемы сна",                          "base"),
    # Опциональные (system optional)
    ("medications",            "Прием лекарств",                        "health"),
    ("therapy",                "Психотерапия",                          "health"),
    ("menstrual_cycle",        "Менструальный цикл",                    "health"),
    ("suicidal_thoughts",      "Суицидальные мысли",                    "health"),
    ("hypomania",              "Гипомания / признаки подъема",          "hypomania"),
    ("irritability",           "Раздражительность",                     "hypomania"),
    ("impulsivity",            "Импульсивность",                        "hypomania"),
    ("thought_speech_speed",   "Скорость мыслей и речи",                "hypomania"),
    ("libido",                 "Либидо",                                "hypomania"),
    ("risky_behavior",         "Рискованное поведение",                 "hypomania"),
    ("spending",               "Траты",                                 "hypomania"),
    ("panic_attacks",          "Панические атаки",                      "anxiety"),
    ("obsessive_thoughts",     "Навязчивые мысли",                      "anxiety"),
    ("avoidance",              "Избегание",                             "anxiety"),
    ("somatic_anxiety",        "Телесные симптомы тревоги",             "anxiety"),
    ("anhedonia",              "Ангедония",                             "depression"),
    ("self_esteem_guilt",      "Самооценка и чувство вины",             "depression"),
    ("appetite",               "Аппетит",                               "depression"),
    ("concentration",          "Концентрация",                          "depression"),
    ("productivity",           "Продуктивность",                        "depression"),
    ("social_activity",        "Социальная активность",                 "depression"),
    ("physical_activity",      "Физическая активность",                 "lifestyle"),
    ("substances",             "Алкоголь / вещества",                   "lifestyle"),
    ("caffeine",               "Кофеин",                                "lifestyle"),
    ("late_phone",             "Телефон перед сном",                    "lifestyle"),
    ("stress_events",          "Стрессовые события",                    "lifestyle"),
    ("aggression_conflicts",   "Агрессия / конфликты",                  "lifestyle"),
    # Пользовательские
    ("custom_questions",       "Пользовательские вопросы",              "custom"),
]

STATISTICS_BLOCK_LABELS: dict[str, str] = {code: label for code, label, _ in STATISTICS_BLOCKS}
STATISTICS_BLOCK_CATEGORIES: dict[str, str] = {code: cat for code, _, cat in STATISTICS_BLOCKS}
STATISTICS_BLOCK_CODES: list[str] = [code for code, _, _ in STATISTICS_BLOCKS]
STATISTICS_BLOCK_CODES_SET: set[str] = set(STATISTICS_BLOCK_CODES)

# Что включено для нового пользователя (если в БД ничего нет).
STATISTICS_DEFAULTS: set[str] = {"summary", "mood", "anxiety", "sleep", "energy"}

# Brief-режим — фиксированный набор. Не зависит от настроек пользователя.
STATISTICS_BRIEF: list[str] = ["summary", "mood", "anxiety", "sleep", "energy"]


# --- callback shorts ---
# Telegram callback_data ограничен 64 байтами. Префикс "stats:tgl:" уже
# занимает 10. Некоторые коды длиннее ~50 символов в utf-8 не бывают,
# но на всякий случай используем короткие алиасы для самых длинных.
BLOCK_CALLBACK_SHORTS: dict[str, str] = {
    "thought_speech_speed":  "tss",
    "self_esteem_guilt":     "seg",
    "somatic_anxiety":       "som",
    "obsessive_thoughts":    "obs",
    "aggression_conflicts":  "agc",
    "physical_activity":     "pha",
    "social_activity":       "soc",
    "stress_events":         "str",
    "menstrual_cycle":       "men",
    "suicidal_thoughts":     "sui",
    "panic_attacks":         "pan",
    "risky_behavior":        "rsk",
    "custom_questions":      "cst",
    "sleep_problems":        "slp",
    "mood_energy":           "mne",
    "mood_spread":           "msp",
}
# Обратный маппинг: short -> long.
BLOCK_CALLBACK_LONG: dict[str, str] = {v: k for k, v in BLOCK_CALLBACK_SHORTS.items()}


def block_to_short(code: str) -> str:
    """Превращает long block_code в короткий для callback_data.
    Если в маппинге нет — возвращает оригинал (он короткий)."""
    return BLOCK_CALLBACK_SHORTS.get(code, code)


def short_to_block(short: str) -> str | None:
    """Обратное превращение. None — если такого блока нет в каталоге."""
    long = BLOCK_CALLBACK_LONG.get(short, short)
    return long if long in STATISTICS_BLOCK_CODES_SET else None
