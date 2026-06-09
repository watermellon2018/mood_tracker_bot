"""Пресеты и UI-маппинг для настройки вопросов опроса.

Список самих вопросов — в БД (question_catalog, см. миграцию 0004).
Здесь только то, что относится к UI и Python: пресеты и короткие коды
для callback_data.
"""

# Короткие callback-коды для категорий (длинные не влезают в callback_data
# с учётом префикса qs:cat:). Полная категория — справа.
CATEGORY_SHORT_TO_FULL = {
    "depr": "depression",
    "anx":  "anxiety",
    "hypo": "hypomania",
    "life": "lifestyle",
    "hlth": "health",
}
CATEGORY_FULL_TO_SHORT = {v: k for k, v in CATEGORY_SHORT_TO_FULL.items()}

CATEGORY_LABELS = {
    "depression": "🧠 Настроение и депрессивные симптомы",
    "anxiety":    "😰 Тревога",
    "hypomania":  "⚡ Подъем / гипомания",
    "lifestyle":  "🏃 Поведение и образ жизни",
    "health":     "💊 Здоровье и лечение",
}

# Пресеты: replace semantics — включить именно эти, остальные опциональные
# выключить. Базовые вопросы пресеты не трогают.
PRESETS: dict[str, dict] = {
    "depr": {
        "label": "🌧 Сниженное настроение",
        "codes": [
            "anhedonia", "self_esteem_guilt", "appetite", "concentration",
            "productivity", "social_activity", "physical_activity",
            "medications", "therapy",
        ],
    },
    "anx": {
        "label": "😰 Тревога",
        "codes": [
            "panic_attacks", "obsessive_thoughts", "avoidance",
            "somatic_anxiety", "caffeine", "stress_events", "late_phone",
            "medications", "therapy",
        ],
    },
    "mood": {
        "label": "⚡ Перепады настроения",
        "codes": [
            "hypomania", "thought_speech_speed", "irritability",
            "impulsivity", "libido", "risky_behavior", "spending",
            "aggression_conflicts", "medications", "substances",
        ],
    },
    "sleep": {
        "label": "🌙 Сон и режим",
        "codes": [
            "caffeine", "late_phone", "physical_activity", "substances",
            "stress_events",
        ],
    },
    "all": {
        # Заполняется динамически из question_catalog в сервисе.
        "label": "🧩 Всё расширенное",
        "codes": None,
    },
}

PRESET_ORDER = ["depr", "anx", "mood", "sleep", "all"]


# Порядок опциональных вопросов в опросе. Если код есть в этом списке и в
# enabled_codes пользователя — он будет включен в шаги опроса именно в этом
# порядке. Базовые вопросы (mood/anxiety/sleep/energy/comment) идут отдельно
# в фиксированных местах flow.
OPTIONAL_QUESTION_ORDER = [
    "medications",
    "anhedonia",
    "self_esteem_guilt",
    "appetite",
    "concentration",
    "productivity",
    "social_activity",
    "panic_attacks",
    "obsessive_thoughts",
    "avoidance",
    "somatic_anxiety",
    "hypomania",
    "thought_speech_speed",
    "irritability",
    "impulsivity",
    "libido",
    "risky_behavior",
    "spending",
    "physical_activity",
    "substances",
    "caffeine",
    "late_phone",
    "stress_events",
    "aggression_conflicts",
    "therapy",
    "menstrual_cycle",
    "suicidal_thoughts",
]

# Универсальные подписи для шкалы 0..4. Если вопрос не переопределён в
# QUESTION_DEFINITIONS — используем эти как fallback.
DEFAULT_SCALE_OPTIONS = [
    "Совсем нет",
    "Почти нет",
    "Немного",
    "Нормально",
    "Да, хорошо",
]

# Конфиг текста вопроса и подписей кнопок. Если кода нет в этой карте —
# берём title из question_catalog и DEFAULT_SCALE_OPTIONS.
QUESTION_DEFINITIONS: dict[str, dict] = {
    "anhedonia": {
        "question_text": "Получалось ли сегодня получать удовольствие от чего-то?",
        "options": DEFAULT_SCALE_OPTIONS,
    },
    "self_esteem_guilt": {
        "question_text": "Были ли мысли о собственной никчёмности или вине?",
        "options": ["Нет", "Редкие", "Иногда", "Часто", "Постоянно"],
    },
    "appetite": {
        "question_text": "Как с аппетитом?",
        "options": ["Не было", "Снижен", "Обычный", "Повышен", "Очень повышен"],
    },
    "concentration": {
        "question_text": "Оцени уровень концентрации?",
        "options": ["Совсем нет", "С трудом", "Иногда", "Нормально", "Хорошо"],
    },
    "productivity": {
        "question_text": "Насколько ты продуктивен?",
        "options": ["Ничего", "Мало", "Средне", "Много", "Очень много"],
    },
    "social_activity": {
        "question_text": "Было ли сегодня общение с другими людьми?",
        "options": ["Не было", "Минимум", "Немного", "Обычно", "Много"],
    },
    "panic_attacks": {
        "question_text": "Были ли сегодня панические атаки?",
        "options": ["Нет", "Близко к атаке", "Была одна", "Несколько", "Сильные"],
    },
    "obsessive_thoughts": {
        "question_text": "Есть ли навязчивые мысли?",
        "options": ["Нет", "Редкие", "Иногда", "Часто", "Постоянно"],
    },
    "avoidance": {
        "question_text": "Избегание каких-то ситуаций из-за тревоги?",
        "options": ["Нет", "Немного", "Заметно", "Сильно", "Очень сильно"],
    },
    "somatic_anxiety": {
        "question_text": "Были ли телесные симптомы тревоги (сердцебиение, дрожь, ком в горле)?",
        "options": ["Нет", "Слабые", "Умеренные", "Сильные", "Очень сильные"],
    },
    "hypomania": {
        "question_text": "Замечены ли признаки гипомании?",
        "options": ["Нет", "Намёк", "Заметно", "Сильно", "Очень сильно"],
    },
    "thought_speech_speed": {
        "question_text": "Как сегодня скорость мыслей и речи?",
        "options": ["Замедленно", "Сниженно", "Обычно", "Ускоренно", "Очень быстро"],
    },
    "irritability": {
        "question_text": "Уровень раздражительности?",
        "options": ["Нет", "Лёгкая", "Умеренная", "Сильная", "Очень сильная"],
    },
    "impulsivity": {
        "question_text": "Насколько сегодня ты импульсивен?",
        "options": ["Нет", "Немного", "Умеренно", "Заметно", "Сильно"],
    },
    "libido": {
        "question_text": "Какой сегодня уровень либидо?",
        "options": ["Снижен", "Низкий", "Обычный", "Повышен", "Очень повышен"],
    },
    "risky_behavior": {
        "question_text": "Было ли сегодня рискованное поведение?",
        "options": ["Нет", "Лёгкое", "Заметно", "Сильно", "Очень сильно"],
    },
    "spending": {
        "question_text": (
            "Были ли сегодня импульсивные траты или сильное желание тратить деньги?"
        ),
        # 4 варианта — кнопки рисуются ровно по options.
        "options": [
            "Нет",
            "Было желание, но не тратила",
            "Да, небольшие траты",
            "Да, заметные траты",
        ],
        "option_codes": [
            "none",
            "urge_no_spending",
            "small_spending",
            "significant_spending",
        ],
    },
    "physical_activity": {
        # Спец-вопрос: вместо одной шкалы — двухшаговый поток
        # (done? -> duration?). См. PHYSICAL_ACTIVITY_*.
        "question_text": "Была ли физ нагрузка?",
        "options": ["Да", "Нет"],
        "option_codes": ["yes", "no"],
    },
    "substances": {
        "question_text": "Были ли сегодня алкоголь или другие вещества?",
        "options": ["Нет", "Немного", "Умеренно", "Много", "Очень много"],
    },
    "caffeine": {
        "question_text": "Сколько кофеина было сегодня?",
        # Новые варианты — в кружках. Старые ответы в БД ("Мало"/"Умеренно"/...)
        # остаются как legacy: answer_numeric (0..4) совместим — индексы те же,
        # так что аналитика на answer_numeric не ломается. В renderer-е, если
        # понадобится показать текст, идём через answer_value (там старые
        # подписи) — это и есть fallback.
        "options": [
            "Не было",
            "1 кружка",
            "2 кружки",
            "3–5 кружек",
            "5+ кружек",
        ],
        "option_codes": [
            "none",
            "one_cup",
            "two_cups",
            "three_to_five_cups",
            "five_plus_cups",
        ],
    },
    "late_phone": {
        "question_text": (
            "Сколько времени вы провели в телефоне или за экраном перед сном вчера?"
        ),
        "options": [
            "Не было",
            "До 15 минут",
            "15–30 минут",
            "30–60 минут",
            "Больше часа",
        ],
        "option_codes": [
            "none",
            "lt_15_min",
            "min_15_30",
            "min_30_60",
            "gt_60_min",
        ],
    },
    "stress_events": {
        "question_text": "Были ли сегодня заметные стрессовые события?",
        "options": [
            "Нет",
            "Да, одно",
            "Да, несколько",
            "День был очень стрессовый",
        ],
        "option_codes": ["none", "one", "several", "very_stressful_day"],
    },
    "aggression_conflicts": {
        "question_text": "Были ли сегодня агрессия или конфликты?",
        "options": ["Нет", "Лёгкие", "Заметные", "Сильные", "Очень сильные"],
    },
    "medications": {
        "question_text": "Сегодня по приёму лекарств?",
        "options": ["Принял(а) всё", "Частично", "Пропустил(а)", "Не назначены", "Пропустить"],
    },
    "therapy": {
        "question_text": "Была ли сегодня сессия с психотерапевтом или работа по технике?",
        "options": ["Нет", "Кратко сам(а)", "Сам(а)", "Сессия", "Сессия + работа"],
    },
    "menstrual_cycle": {
        "question_text": "Текущий день цикла как себя проявляет?",
        "options": ["Не применимо", "Без особенностей", "ПМС/начало", "Менструация", "Овуляция"],
    },
    "suicidal_thoughts": {
        "question_text": (
            "Были ли сегодня мысли о самоповреждении или о том, что не хочется жить?"
        ),
        "options": [
            "Нет",
            "Были мимолётные мысли",
            "Были навязчивые мысли",
            "Думал(а) о способах",
            "Есть риск, что могу навредить себе",
        ],
    },
}

# Индекс варианта, который считается high-risk для suicidal_thoughts.
# При выборе этого варианта показываем кризисное сообщение.
SUICIDAL_HIGH_RISK_INDEX = 4

CRISIS_MESSAGE = (
    "Если сейчас плохо и есть мысли о том, чтобы навредить себе — пожалуйста, "
    "обратись за срочной помощью: к близкому человеку, врачу, в экстренную службу "
    "или местную кризисную линию. Я не заменяю помощь специалиста."
)


def options_for(code: str, fallback_title: str = "") -> tuple[str, list[str]]:
    """Возвращает (текст_вопроса, варианты) для опционального вопроса."""
    defn = QUESTION_DEFINITIONS.get(code)
    if defn is None:
        return (fallback_title or code, DEFAULT_SCALE_OPTIONS)
    return (defn["question_text"], defn["options"])


def option_codes_for(code: str) -> list[str] | None:
    """Если у вопроса есть свои коды вариантов (enum-подобный ответ),
    возвращает их. Иначе None — значит варианты пишутся как текст из options.
    """
    defn = QUESTION_DEFINITIONS.get(code)
    if defn is None:
        return None
    return defn.get("option_codes")


# ---------- Политики показа и привязки даты ответа ----------
#
# Эти словари — единый источник правды для Python-кода. БД хранит их же значения
# (миграция 0009) для отчётности и фильтров через SQL.
#
# Возможные значения ask_policy:
#   'per_survey'                  — спрашивать в каждом опросе;
#   'once_per_day'                — один раз за локальный день;
#   'first_survey_until_answered' — задавать в первом опросе дня; пока ответа
#                                   нет — повторять в каждом следующем опросе
#                                   ТОГО ЖЕ дня; на следующий день не переносим;
#   'last_survey_of_day'          — только в последнем опросе дня;
#   'last_or_after_noon'          — в последнем (last/single) опросе ИЛИ в любом
#                                   опросе, открытом не раньше NOON_HOUR (12:00).
#                                   Для вопросов-итогов, которые утром задавать
#                                   рано, но к середине дня уже осмысленны.
#
# Возможные значения answer_target_date_policy:
#   'current_day'  — ответ относится к сегодняшнему локальному дню;
#   'previous_day' — ответ относится к вчерашнему локальному дню (late_phone).

ASK_POLICY_PER_SURVEY = "per_survey"
ASK_POLICY_ONCE_PER_DAY = "once_per_day"
ASK_POLICY_FIRST_UNTIL_ANSWERED = "first_survey_until_answered"
ASK_POLICY_LAST_OF_DAY = "last_survey_of_day"
ASK_POLICY_LAST_OR_AFTER_NOON = "last_or_after_noon"

# Порог «дня» для ASK_POLICY_LAST_OR_AFTER_NOON: опрос, открытый в этот час
# или позже по локальному времени пользователя, считается «не утренним», и
# вопросы-итоги в нём задаются даже если слот не последний. Час, не time(),
# чтобы не тянуть datetime в этот UI-модуль — сравнение делает
# question_policy_service.
NOON_HOUR = 12

TARGET_DATE_CURRENT = "current_day"
TARGET_DATE_PREVIOUS = "previous_day"

# Слоты опроса. single = и первый, и последний; manual — ручной запуск.
SURVEY_SLOT_FIRST = "first"
SURVEY_SLOT_REGULAR = "regular"
SURVEY_SLOT_LAST = "last"
SURVEY_SLOT_SINGLE = "single"
SURVEY_SLOT_MANUAL = "manual"

ALL_SURVEY_SLOTS = {
    SURVEY_SLOT_FIRST,
    SURVEY_SLOT_REGULAR,
    SURVEY_SLOT_LAST,
    SURVEY_SLOT_SINGLE,
    SURVEY_SLOT_MANUAL,
}

# Политики по кодам. Если кода нет в карте — по умолчанию (per_survey/current_day).
#
# В per_survey остаются вопросы про "состояние сейчас":
#   mood, anxiety, energy, irritability, self_esteem_guilt, avoidance,
#   somatic_anxiety, thought_speech_speed, libido, panic_attacks, appetite,
#   comment — они нужны в каждом срезе дня.
#
# Вопросы про ИТОГ дня ("сегодня", "за день", "прошёл день") — last_survey_of_day:
# они формулируются как сводка и должны задаваться только в last/single слоте.
QUESTION_POLICIES: dict[str, dict[str, str]] = {
    # once_per_day — про режим, разово фиксируем за день и не пересматриваем.
    "sleep":           {"ask": ASK_POLICY_ONCE_PER_DAY,        "target": TARGET_DATE_CURRENT},
    "medications":     {"ask": ASK_POLICY_ONCE_PER_DAY,        "target": TARGET_DATE_CURRENT},
    # first_survey_until_answered — про "вчера", пока не ответили.
    "late_phone":      {"ask": ASK_POLICY_FIRST_UNTIL_ANSWERED, "target": TARGET_DATE_PREVIOUS},
    # last_or_after_noon — итоги, осмысленные с середины дня: задаются в
    # последнем опросе ИЛИ в любом опросе, открытом не раньше NOON_HOUR.
    "productivity":        {"ask": ASK_POLICY_LAST_OR_AFTER_NOON, "target": TARGET_DATE_CURRENT},
    "concentration":       {"ask": ASK_POLICY_LAST_OR_AFTER_NOON, "target": TARGET_DATE_CURRENT},
    "hypomania":           {"ask": ASK_POLICY_LAST_OR_AFTER_NOON, "target": TARGET_DATE_CURRENT},
    "physical_activity":   {"ask": ASK_POLICY_LAST_OR_AFTER_NOON, "target": TARGET_DATE_CURRENT},
    # per_survey — состояние «сейчас», валидно и утром. Указан явно (хотя это
    # и default), чтобы зафиксировать осознанный выбор против last_of_day.
    "obsessive_thoughts":  {"ask": ASK_POLICY_PER_SURVEY, "target": TARGET_DATE_CURRENT},
    # last_survey_of_day — дневные итоги. Задаются только в last/single слоте.
    "anhedonia":           {"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
    "social_activity":     {"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
    "impulsivity":         {"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
    "risky_behavior":      {"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
    "spending":            {"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
    "substances":          {"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
    "caffeine":            {"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
    "stress_events":       {"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
    "aggression_conflicts":{"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
    "therapy":             {"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
    "menstrual_cycle":     {"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
    "suicidal_thoughts":   {"ask": ASK_POLICY_LAST_OF_DAY, "target": TARGET_DATE_CURRENT},
}


def get_ask_policy(code: str) -> str:
    return QUESTION_POLICIES.get(code, {}).get("ask", ASK_POLICY_PER_SURVEY)


def get_target_date_policy(code: str) -> str:
    return QUESTION_POLICIES.get(code, {}).get("target", TARGET_DATE_CURRENT)


# ---------- Physical activity (двухшаговый ответ) ----------

PHYSICAL_ACTIVITY_QUESTION = "Была ли физ нагрузка?"
PHYSICAL_ACTIVITY_DURATION_QUESTION = "Сколько примерно по времени?"

PHYSICAL_ACTIVITY_DURATION_OPTIONS = [
    ("lt_15_min", "До 15 минут"),
    ("min_15_30", "15–30 минут"),
    ("min_30_60", "30–60 минут"),
    ("h_1_2",     "1–2 часа"),
    ("gt_2_h",    "Больше 2 часов"),
]
PHYSICAL_ACTIVITY_DURATION_LABELS = dict(PHYSICAL_ACTIVITY_DURATION_OPTIONS)
