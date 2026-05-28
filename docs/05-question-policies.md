# 05. Политики показа вопросов

Политики — это правила, по которым опционные вопросы попадают в конкретный экземпляр опроса. Они работают поверх «включено/выключено пользователем». Источник правды — `bot/constants_questions.py::QUESTION_POLICIES`; БД хранит те же значения в `question_catalog.ask_policy` и `question_catalog.answer_target_date_policy` для SQL-фильтрации.

## ask_policy — когда задавать

| Код | Семантика |
|-----|-----------|
| `per_survey` | В каждом опросе. Default для вопросов «состояние сейчас» |
| `once_per_day` | Один раз в локальный день. Если ответ уже есть — скип |
| `first_survey_until_answered` | В первом опросе дня; если не ответили — в каждом последующем опросе того же дня; на следующий день не переносим |
| `last_survey_of_day` | Только в последнем (`last`) или единственном (`single`) опросе дня |

Реализация: [`bot/services/question_policy_service.py::should_ask_question_in_slot`](../bot/services/question_policy_service.py).

### Разрешённые слоты

```python
_FIRST_ALLOWED_SLOTS = {first, regular, single, manual}
_LAST_ALLOWED_SLOTS  = {last, single}
```

`per_survey` и `once_per_day` разрешены во всех слотах. `first_survey_until_answered` в `last`-only слоте не задаётся (потому что это «утренний» вопрос). `last_survey_of_day` в `manual` не задаётся: иначе нельзя надёжно определить, что ручной запуск — «вечерний».

## answer_target_date_policy — к какому дню относится ответ

| Код | Семантика |
|-----|-----------|
| `current_day` | Ответ за текущий локальный день (default) |
| `previous_day` | Ответ за вчерашний день (`local_today - 1`) |

Применяется в `get_target_date_for_question(local_today, target_policy)`.

Используется для:
- `late_phone` — про вчерашний вечер (телефон перед сном).

`log_date` в `survey_answers` фиксирует именно `target_date`, а не `entry.local_date`. Это позволяет аналитике корректно соотнести «телефон вчера» с конкретным днём.

## Слоты опроса (`survey_slot`)

Определены в `bot/constants_questions.py`:

```python
SURVEY_SLOT_FIRST    = "first"
SURVEY_SLOT_REGULAR  = "regular"
SURVEY_SLOT_LAST     = "last"
SURVEY_SLOT_SINGLE   = "single"
SURVEY_SLOT_MANUAL   = "manual"
```

### Откуда берётся слот

1. **Плановый опрос**: `scheduler_service.schedule_user` ставит N jobs (по числу слотов в день) и каждому передаёт `survey_slot` в `data`, посчитанный через `question_policy_service.slot_for_index(total_slots, idx)`:
   - 1 слот → `single`.
   - Иначе: idx=0 → `first`, idx=N-1 → `last`, иначе `regular`.
2. **При нажатии «Заполнить опрос»**: `survey_slot` уезжает в callback_data (`survey:start:<slot>`). FSM парсит через `_parse_slot_from_callback`.
3. **Ручной `/add`**: `SURVEY_SLOT_MANUAL`.
4. **Reminder**: тот же `survey_slot`, что в pending. Передаётся через job data.

## Таблица политик по кодам

| Код | ask_policy | target | Где спрашивается |
|-----|------------|--------|------------------|
| (default) | `per_survey` | `current_day` | в каждом опросе |
| `sleep` | `once_per_day` | `current_day` | один раз в день |
| `medications` | `once_per_day` | `current_day` | один раз в день |
| `late_phone` | `first_survey_until_answered` | `previous_day` | утром, пока не ответили |
| `anhedonia` | `last_of_day` | `current_day` | вечером |
| `concentration` | `last_of_day` | `current_day` | вечером |
| `productivity` | `last_of_day` | `current_day` | вечером |
| `social_activity` | `last_of_day` | `current_day` | вечером |
| `obsessive_thoughts` | `last_of_day` | `current_day` | вечером |
| `hypomania` | `last_of_day` | `current_day` | вечером |
| `impulsivity` | `last_of_day` | `current_day` | вечером |
| `risky_behavior` | `last_of_day` | `current_day` | вечером |
| `spending` | `last_of_day` | `current_day` | вечером |
| `physical_activity` | `last_of_day` | `current_day` | вечером |
| `substances` | `last_of_day` | `current_day` | вечером |
| `caffeine` | `last_of_day` | `current_day` | вечером |
| `stress_events` | `last_of_day` | `current_day` | вечером |
| `aggression_conflicts` | `last_of_day` | `current_day` | вечером |
| `therapy` | `last_of_day` | `current_day` | вечером |
| `menstrual_cycle` | `last_of_day` | `current_day` | вечером |
| `suicidal_thoughts` | `last_of_day` | `current_day` | вечером |

Перевод в `last_of_day` для большой группы вопросов произошёл в миграции 0011 (см. [13-database-schema.md](13-database-schema.md)).

Остальные опциональные коды (`self_esteem_guilt`, `avoidance`, `somatic_anxiety`, `thought_speech_speed`, `libido`, `panic_attacks`, `appetite`) — `per_survey` (default), потому что формулировка «состояние сейчас», а не «итог дня».

## Двойная проверка наличия ответа

Когда планируется задавать вопрос с политикой `once_per_day` / `first_until_answered` / `last_of_day`, перед добавлением шага в план FSM делает SQL-запрос `has_answer_for_question_date(user, code, target_date)`:

```python
if question_code == "sleep":
    return has_main_sleep_for_date(...)
if question_code == "medications":
    return has_medication_for_date(...)
# else:
return EXISTS(survey_answers WHERE question_code=? AND log_date=? AND entry.user_id=?)
```

При сохранении ответа (`_finish_survey`) проверка делается ещё раз — на случай гонки между параллельными опросами (например, бот отправил два уведомления, пользователь нажал на оба).

## Сборка плана опроса

Функция: `question_policy_service.build_daily_survey_steps(session, user_id, enabled_codes, survey_slot, local_today)`.

```python
plan: list[SurveyStep] = []
for code in OPTIONAL_QUESTION_ORDER:
    if code not in enabled_codes:
        continue
    ask_policy = get_ask_policy(code)
    if not should_ask_question_in_slot(ask_policy, survey_slot):
        continue
    target_date = get_target_date_for_question(local_today, get_target_date_policy(code))
    if ask_policy in (once_per_day, first_until_answered, last_of_day):
        if has_answer_for_question_date(session, user_id, code, target_date):
            continue
    plan.append(SurveyStep(code=code, target_date=target_date, ask_policy=ask_policy))
return plan
```

`OPTIONAL_QUESTION_ORDER` — фиксированный порядок 27 опциональных кодов (см. константу в файле). Это и порядок UI в опросе, и порядок «дисциплины» (medications в начале, suicidal в конце).

## Пример: вечерний `last` слот

Допустим:
- Пользователь включил `anhedonia` + `caffeine` + `late_phone` + `medications`.
- Слот — `last`.
- За день уже задан `late_phone` (утром ответили).

План:
1. `medications` (per `_HANDLED_AS_BASE` исключен из опциональных — задаётся как базовый шаг).
2. `late_phone` — не задаётся: `last_of_day` для last-only вопросов, late_phone не в их числе; `first_survey_until_answered` в `_LAST_ALLOWED_SLOTS={last, single}` тоже разрешён (см. `_FIRST_ALLOWED_SLOTS`). НО проверка `has_answer_for_question_date` → ответ уже есть, скип.
3. `anhedonia` — `last_of_day` ∈ `_LAST_ALLOWED_SLOTS`, ответа за сегодня нет → задаётся.
4. `caffeine` — `last_of_day`, аналогично.

## Пример: единственный опрос (single) ранним вечером

`survey_slot = single` — это и first, и last одновременно. Поэтому работают все политики (`first_until_answered` и `last_of_day` оба разрешены).

## Связанные документы

- [04-survey-flow.md](04-survey-flow.md) — где именно политики применяются в FSM.
- [13-database-schema.md](13-database-schema.md) — `survey_answers.log_date`, `question_catalog.ask_policy`.
