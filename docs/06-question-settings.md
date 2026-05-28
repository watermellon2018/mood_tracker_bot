# 06. Настройка вопросов опроса

Раздел «Вопросы опроса» (вызывается из `/settings` → «Вопросы опроса») позволяет пользователю настраивать набор опциональных вопросов, которые попадают в ежедневный опрос.

Handler: [`bot/handlers/question_settings.py`](../bot/handlers/question_settings.py), callback префикс `qs:`.

## Структура каталога вопросов

Сами вопросы — в БД (`question_catalog`), плюс UI-данные в [`bot/constants_questions.py`](../bot/constants_questions.py).

Поля `QuestionCatalog`:

| Поле | Описание |
|------|----------|
| `code` | PK, короткий код (`anhedonia`, `caffeine`, ...) |
| `title` | Подпись в UI |
| `description` | Длинное описание (опционально) |
| `category` | `base` / `depression` / `anxiety` / `hypomania` / `lifestyle` / `health` |
| `is_required` | Базовый вопрос — нельзя выключить |
| `is_default_enabled` | Включён по умолчанию для новых пользователей |
| `is_active` | Soft-disable на уровне каталога (выводится из обращения) |
| `sort_order` | Порядок |
| `ask_policy` | См. [05-question-policies.md](05-question-policies.md) |
| `answer_target_date_policy` | См. там же |

Активные базовые: `mood`, `anxiety`, `sleep`, `energy`, `comment` (всегда включены, нельзя выключить).

## Состояние пользователя

`user_question_settings(user_id, question_code, is_enabled)`.

- Если строки нет — вопрос выключен.
- Базовые вопросы НЕ хранятся в этой таблице. `enabled_codes_for_user = required_codes ∪ enabled_optional_codes`.
- `is_enabled=True` означает: вопрос будет задаваться, если разрешает `ask_policy` + нет ответа за `target_date`.

Сервис: [`bot/services/question_settings_service.py`](../bot/services/question_settings_service.py).

## UI-структура

Корневой экран (`qs:menu`):

```
🌧 Готовые наборы          → qs:presets
🛠 Настроить вручную        → qs:manual
➕ Свой вопрос              → cq:add (FSM создания)
📝 Мои вопросы              → qs:cq_list
🔄 Сбросить к базовому набору → qs:reset
⬅️ Назад                     → qs:back (close_menu)
```

### Готовые наборы (`qs:presets`)

5 пресетов (см. `PRESETS` в [`bot/constants_questions.py`](../bot/constants_questions.py)):

| Код | Лейбл | Включает |
|-----|-------|----------|
| `depr` | 🌧 Сниженное настроение | anhedonia, self_esteem_guilt, appetite, concentration, productivity, social_activity, physical_activity, medications, therapy |
| `anx` | 😰 Тревога | panic_attacks, obsessive_thoughts, avoidance, somatic_anxiety, caffeine, stress_events, late_phone, medications, therapy |
| `mood` | ⚡ Перепады настроения | hypomania, thought_speech_speed, irritability, impulsivity, libido, risky_behavior, spending, aggression_conflicts, medications, substances |
| `sleep` | 🌙 Сон и режим | caffeine, late_phone, physical_activity, substances, stress_events |
| `all` | 🧩 Всё расширенное | все опциональные, кроме `suicidal_thoughts` |

**Replace-семантика**: применение пресета сбрасывает все опциональные вопросы и включает только те, что входят в пресет. Базовые не трогаются. `suicidal_thoughts` никогда не включается через пресеты (требует явного подтверждения).

Реализация: `question_settings_service.apply_preset(session, user_id, preset_code)`:

1. Если `codes is None` (для `all`) — берёт все опциональные из `question_catalog`.
2. Исключает `SUICIDAL_CODE`.
3. `UPDATE user_question_settings SET is_enabled=False WHERE question_code NOT IN target`.
4. Upsert `is_enabled=True` для всех target.

### Настроить вручную (`qs:manual`)

Показывает 5 категорий (`qs:cat:<short>`). Короткие коды через `CATEGORY_SHORT_TO_FULL`: `depr` / `anx` / `hypo` / `life` / `hlth`.

После выбора категории — список опциональных вопросов с галочками (✅/⬜) и кнопкой «⬅️ К категориям». Тап по вопросу → toggle (`qs:tgl:<code>`).

Реализация toggle: `question_settings_service.toggle_question(session, user_id, code)`:
- Возвращает False для базовых / unknown / inactive.
- Если код = `suicidal_thoughts` и пытается включить — отказ (нужно идти через `set_suicidal_after_confirm`).
- Иначе upsert новое значение `not current`.

### Suicide warning

Если пользователь пытается включить `suicidal_thoughts`, handler перехватывает (см. `_handle_toggle`):

1. Проверяет текущее состояние. Если уже включено — toggle off без подтверждения.
2. Если выключено — показывает текст `SUICIDE_WARNING` и кнопки «✅ Включить» / «Отмена».
3. На `qs:suicide_confirm` — `set_suicidal_after_confirm(session, user_id)` (специальный путь, минующий защиту в `set_question_enabled`).

Это единственный способ включить `suicidal_thoughts`. Пресеты, `set_question_enabled`, обычный `toggle` — все откажут.

### Сброс (`qs:reset`)

`question_settings_service.reset_optional(session, user_id)` — `UPDATE user_question_settings SET is_enabled=False`. После сброса опрос состоит только из базовых вопросов.

### «Мои вопросы» (`qs:cq_list`)

Открывает экран custom-вопросов. См. [07-custom-questions.md](07-custom-questions.md).

## Категории и эмодзи

```python
CATEGORY_LABELS = {
    "depression": "🧠 Настроение и депрессивные симптомы",
    "anxiety":    "😰 Тревога",
    "hypomania":  "⚡ Подъем / гипомания",
    "lifestyle":  "🏃 Поведение и образ жизни",
    "health":     "💊 Здоровье и лечение",
}
```

## Защита от длинного callback_data

`CATEGORY_SHORT_TO_FULL` сокращает категории до 4 символов:
- `depr` ↔ `depression`
- `anx` ↔ `anxiety`
- `hypo` ↔ `hypomania`
- `life` ↔ `lifestyle`
- `hlth` ↔ `health`

Это нужно, потому что callback `qs:cat:depression` уже близок к лимиту 64 байта вместе с кириллицей в текстах (UTF-8 умножает на 2 байта).

## Текст вариантов опционального вопроса

Берётся через `options_for(code, fallback_title)` из `QUESTION_DEFINITIONS` или дефолтом `DEFAULT_SCALE_OPTIONS`:

```python
DEFAULT_SCALE_OPTIONS = ["Совсем нет", "Почти нет", "Немного", "Нормально", "Да, хорошо"]
```

Для каждого кода в `QUESTION_DEFINITIONS` определены:
- `question_text` — текст вопроса (отображается перед клавиатурой).
- `options` — список лейблов кнопок.
- `option_codes` — опционально, коды вариантов (для `late_phone`, `stress_events`, `spending`, `caffeine`, `physical_activity`).

Если у вопроса есть `option_codes` — `answer_value` сохраняется как код, не как текст. Это позволяет аналитике различать «1 кружка» и «5+ кружек» по коду, а не по строке.

## Связанные документы

- [05-question-policies.md](05-question-policies.md) — как настройки превращаются в шаги опроса.
- [07-custom-questions.md](07-custom-questions.md) — свои вопросы.
- [15-safety-and-crisis.md](15-safety-and-crisis.md) — `suicidal_thoughts`.
