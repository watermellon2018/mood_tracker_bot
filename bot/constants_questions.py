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
        "question_text": "Получалось ли сегодня сосредоточиться на задачах?",
        "options": ["Совсем нет", "С трудом", "Иногда", "Нормально", "Хорошо"],
    },
    "productivity": {
        "question_text": "Насколько продуктивно прошёл день?",
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
        "question_text": "Сегодня были ли навязчивые мысли?",
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
        "question_text": "Были ли сегодня признаки подъёма / гипомании?",
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
        "question_text": "Насколько сегодня была импульсивность?",
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
        "question_text": "Были ли импульсивные траты сегодня?",
        "options": ["Нет", "Мелкие", "Заметные", "Крупные", "Очень крупные"],
    },
    "physical_activity": {
        "question_text": "Была ли сегодня физическая активность?",
        "options": ["Не было", "Минимум", "Немного", "Обычно", "Много"],
    },
    "substances": {
        "question_text": "Были ли сегодня алкоголь или другие вещества?",
        "options": ["Нет", "Немного", "Умеренно", "Много", "Очень много"],
    },
    "caffeine": {
        "question_text": "Сколько кофеина было сегодня?",
        "options": ["Не было", "Мало", "Умеренно", "Много", "Очень много"],
    },
    "late_phone": {
        "question_text": "Был ли телефон/экран перед сном?",
        "options": ["Нет", "Чуть-чуть", "Умеренно", "Много", "До поздна"],
    },
    "stress_events": {
        "question_text": "Стрессовые события?",
        "options": ["Нет", "Лёгкие", "Заметные", "Сильные", "Очень сильные"],
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
