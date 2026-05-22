# 04. Flow опроса

Опрос реализован как `ConversationHandler` (PTB) с FSM-состояниями. Файл: [`bot/handlers/survey.py`](../bot/handlers/survey.py).

## Состояния FSM

```python
(
    MOOD,              # 0
    ANXIETY,           # 1
    ENERGY,            # 2
    SLEEP_DURATION,    # 3
    SLEEP_QUALITY,     # 4
    SLEEP_PROBLEMS,    # 5
    MEDICATION,        # 6
    OPTIONAL_Q,        # 7   (общее состояние для всех опциональных)
    PHYS_ACT_DURATION, # 8   (второй шаг physical_activity)
    CUSTOM_Q,          # 9   (общее состояние для всех custom-вопросов)
    COMMENT,           # 10
) = range(11)
```

## Entry-points

1. `CommandHandler("add", add_command)` — `/add`.
2. `CallbackQueryHandler(survey_start_callback, pattern=r"^survey:start(:[a-z_]+)?$")` — кнопка из планового пуша.
3. `MessageHandler(filters.Regex(f"^{BTN_ADD}$"), add_command)` — reply-кнопка «📝 Добавить запись».

`survey:start:<slot>` — новый формат с явным слотом. `survey:start` без слота → fallback `single`.

## Инициализация `_init_survey`

При старте опроса заполняется `context.user_data["survey"]`:

```python
{
    "source": "manual" | "scheduled" | "reminder",
    "survey_slot": "first" | "regular" | "last" | "single" | "manual",
    "sleep_problems": set(),
    "skip_sleep": bool,        # уже есть main за дату ИЛИ слишком рано
    "skip_medication": bool,   # уже есть запись с medication_filled=true
    "local_date": date,
    "optional_plan": [{"code": ..., "target_date": "ISO", "ask_policy": ...}, ...],
    "optional_idx": 0,
    "optional_answers": [],    # для итогового summary
    "pa_pending": None,        # промежуточное для physical_activity
    "custom_questions": [{"id": ..., "text": ..., "type": ...}, ...],
    "custom_idx": 0,
    "custom_answers": [],
    "high_risk_triggered": False,  # выставится при выборе suicidal high-risk
}
```

### skip_sleep — две причины

`skip_sleep = True`, если:
1. За локальную дату уже есть запись с `sleep_type='main'`.
2. Или текущее локальное время раньше `sleep_question_start_time = min(start_time пользователя, 10:00)`. Это защита от ситуации «после полуночи новый локальный день, но пользователь ещё не ложился» — спросить «как спал?» в 00:30 нет смысла.

Реализация: `bot/utils/time_utils.py::can_ask_sleep_question`.

### skip_medication

`skip_medication = True`, если за локальную дату уже есть запись с `medication_filled=True`.

### План опциональных шагов

Строится через `bot/services/question_policy_service.py::build_daily_survey_steps`:

1. Берёт `OPTIONAL_QUESTION_ORDER` (фиксированный порядок).
2. Фильтрует по `enabled_codes` пользователя.
3. Для каждого кода проверяет `should_ask_question_in_slot(ask_policy, survey_slot)`.
4. Считает `target_date` (current_day / previous_day).
5. Для политик, привязанных к дате (`once_per_day`, `first_until_answered`, `last_of_day`) — пропускает, если ответ за `target_date` уже есть (`has_answer_for_question_date`).

`medications` исключен из опциональных шагов в `_HANDLED_AS_BASE`, потому что у него отдельный базовый шаг.

Подробно: [05-question-policies.md](05-question-policies.md).

## Линейный сценарий

```
MOOD → ANXIETY → ENERGY
     → (если не skip_sleep) SLEEP_DURATION → SLEEP_QUALITY → SLEEP_PROBLEMS
     → (если не skip_medication) MEDICATION
     → OPTIONAL_Q* (для каждого пункта optional_plan)
     → CUSTOM_Q* (для каждого custom-вопроса)
     → COMMENT
     → _finish_survey
```

Звёздочка = состояние циклится до тех пор, пока `idx < len(plan)`. Переход дальше — внутри хендлера через `_next_optional_or_comment` / `_next_custom_or_comment`.

## Шаги в деталях

### 1. mood (`mood_step`)

callback `mood:0..10`. Кнопки 0..10 (по 6 в ряд через `scale_keyboard("mood", 10)`).

### 2. anxiety (`anxiety_step`)

callback `anxiety:0..5`.

### 3. energy (`energy_step`)

callback `energy:0..5`. После — `_after_base_scales`.

### 4. _after_base_scales

Решает: спрашивать ли блок сна. Если `skip_sleep` — сообщение `SKIP_SLEEP_TODAY` → `_ask_medication_or_skip`.

### 5. Блок сна (3 шага)

**sleep_duration** — список из `SLEEP_DURATION_CATEGORIES`:
- `no_sleep`, `less_3h`, `3_5h`, `5_7h`, `7_9h`, `more_9h`.

**sleep_quality** — `SLEEP_QUALITY_CATEGORIES`:
- `terrible`, `bad`, `normal`, `good`, `deep`.

**sleep_problems** — мульти-выбор `SLEEP_PROBLEMS`:
- `hard_to_fall_asleep`, `early_wakeup`, `frequent_wakeups`, `little_sleep_but_feel_good`, `long_sleep_not_restored`.
- Кнопка `__none__` сразу очищает выбор и завершает шаг.
- Кнопка `__done__` фиксирует выбранное.
- Остальные — toggle (накапливаются в `set`).

### 6. medication (`medication_step`)

callback `med:<key>`. Опции `MEDICATION_OPTIONS`:
- `yes`, `no`, `partial`, `not_applicable`, `skipped`.

### 7. optional_question_step (циклит)

callback `opt:<choice_idx>`. Логика зависит от кода вопроса:

#### a) `physical_activity` — двухшаговый

Шаг 1: «Да/Нет?» (2 кнопки).
- Если «Нет» — сохраняет JSON `{"done": false, "duration": null}` и идёт дальше.
- Если «Да» — кладёт `pa_pending`, переход в `PHYS_ACT_DURATION`.

Шаг 2 (`physical_activity_duration_step`): callback `pa_dur:<duration_key>` (5 вариантов: lt_15_min, min_15_30, min_30_60, h_1_2, gt_2_h). Записывает JSON `{"done": true, "duration": duration_key}`.

#### b) Вопросы с `option_codes` (late_phone, stress_events, spending, caffeine)

Сохраняет `answer_value = codes_list[choice_idx]` — конкретный код варианта (например, `none`, `one_cup`, `lt_15_min`...). Это позволяет аналитике различать выборы по семантике, а не по тексту.

#### c) `suicidal_thoughts` high-risk

При `choice_idx == SUICIDAL_HIGH_RISK_INDEX (=4)` — выставляется флаг `high_risk_triggered=True`. Сообщение `CRISIS_MESSAGE` показывается в конце опроса, не прерывая поток.

#### d) Обычные

Сохраняет `answer_value = options[choice_idx]` (текст) и `answer_index = choice_idx`.

### 8. custom_question_step (циклит)

Тип ответа зависит от `q.answer_type`:

- `scale_0_5` → клавиатура 0..5, callback `cqa:scale:N`. Сохраняется `answer_numeric`.
- `boolean` → две кнопки «Да/Нет», callback `cqa:bool:1|0`. Сохраняется `answer_bool`.
- `text` → ожидает текстовое сообщение, валидируется по `MAX_TEXT_ANSWER_LEN=1000`. Сохраняется `answer_text`.

### 9. comment

- callback `comment:skip` → `comment=None`.
- Любой текст → проверка `len <= MAX_COMMENT_LENGTH (1000)` → `comment=text`.

Затем `_finish_survey`.

## Финальный шаг `_finish_survey`

1. Распаковывает `sleep_problems` в булевы поля.
2. Снимает служебные ключи из `data` (survey_slot, optional_plan, optional_idx, pa_pending, custom_questions, custom_idx).
3. `sleep_type = 'none' if skip_sleep else 'main'`.
4. `medication_filled = not skip_medication`.
5. **Двойная проверка на гонку** перед сохранением:
   - Если sleep_type='main' и main уже появился в БД между init и сейчас → переключает на `'none'` (sleep поля → 'skipped').
   - Если medication_filled=True и запись с лекарствами уже есть → `medication_filled=False`, `medication_taken='not_applicable'`.
6. `survey_service.save_entry(...)` — INSERT SurveyEntry.
7. Для каждого опционального ответа:
   - Проверяет `has_answer_for_question_date(...)` — если за `target_date` уже есть ответ (параллельный опрос), скип.
   - Иначе `save_optional_answer(...)` в `survey_answers`.
8. Для каждого custom-ответа: `save_answer(...)` в `custom_question_answers`.
9. Если есть pending для пользователя → `mark_pending_completed`.
10. Отменяет reminder job: `reminder_service.cancel_reminder_for_pending(pending_id)`.
11. Шлёт текстовый summary (что было сохранено).
12. Если `high_risk_triggered` — отдельно шлёт `CRISIS_MESSAGE`.
13. `context.user_data.pop("survey")`, конец FSM.

## Обработка ошибок

- `IntegrityError` (например, гонка по уникальному индексу): «Запись уже была сохранена раньше. Дубль не создан.»
- Прочие исключения: `ERR_DB` («Не удалось обратиться к базе. Попробуй позже.»).
- При ошибке `context.user_data["survey"]` всё равно очищается.

## Связанные документы

- [05-question-policies.md](05-question-policies.md) — детальная семантика политик.
- [06-question-settings.md](06-question-settings.md) — как пользователь меняет набор вопросов.
- [07-custom-questions.md](07-custom-questions.md) — custom-вопросы.
- [15-safety-and-crisis.md](15-safety-and-crisis.md) — кризисный сценарий.
