# 17. Глоссарий

Краткий справочник ключевых терминов и кодов, встречающихся в коде и документации.

## Концепции

| Термин | Значение |
|--------|----------|
| **Опрос** (survey) | Один сеанс заполнения шкал и вопросов. Запускается по расписанию, по reminder'у или вручную (`/add`). Сохраняется как одна запись `survey_entries`. |
| **Слот** (survey_slot) | Тип опроса в течение дня: first / regular / last / single / manual. Влияет на политики показа вопросов |
| **Pending** | Запись `pending_surveys` — отправленный, но не пройденный плановый опрос. Жизненный цикл: pending → reminder_sent → completed/expired |
| **Reminder** | Повторное напоминание пользователю через `reminder_delay_minutes` после планового пуша |
| **Базовый вопрос** | `is_required=True` в каталоге. mood/anxiety/sleep/energy/comment. Нельзя выключить |
| **Опциональный вопрос** (system optional) | Из `question_catalog`, `is_required=False`. Пользователь выбирает, какие включить |
| **Custom-вопрос** | Создан пользователем (`custom_questions`). До 10 активных. Типы: scale_0_5 / boolean / text |
| **EAV** | Entity-Attribute-Value таблица `survey_answers` — универсальное хранилище ответов на опциональные вопросы |
| **Локальная дата** | Дата в TZ пользователя. В отличие от UTC-времени created_at, local_date фиксируется на момент сохранения и не меняется |
| **Sleep type** | `main` (основной сон в день, уникален), `additional` (доп. сон через /add_sleep), `none` (запись опроса без сна) |

## Политики (ask_policy)

| Код | Когда задаём |
|-----|--------------|
| `per_survey` | В каждом опросе |
| `once_per_day` | Один раз в локальный день, если ответ ещё не записан |
| `first_survey_until_answered` | В первом опросе дня; пока не ответили — повторяем в каждом последующем; на следующий день не переносим |
| `last_survey_of_day` | Только в последнем (или единственном) опросе дня |

## Target date (answer_target_date_policy)

| Код | К какому дню относится ответ |
|-----|------------------------------|
| `current_day` | Сегодня (default) |
| `previous_day` | Вчера (только `late_phone`) |

## Слоты (survey_slot)

| Код | Описание |
|-----|----------|
| `first` | Первый плановый опрос в дне |
| `regular` | Промежуточный |
| `last` | Последний плановый опрос в дне |
| `single` | Единственный опрос в дне (1 слот) |
| `manual` | Ручной запуск через `/add` |

## Источник записи (source)

| Код | Описание |
|-----|----------|
| `scheduled` | Плановый опрос |
| `manual` | Ручной (`/add` или кнопка) |
| `reminder` | После повторного напоминания |

## Статус pending (PendingSurvey.status)

| Код |
|-----|
| `pending` |
| `reminder_sent` |
| `completed` |
| `expired` |

## Тип ответа custom-вопроса (answer_type)

| Код | Хранение |
|-----|----------|
| `scale_0_5` | `answer_numeric` (Numeric 0..5) |
| `boolean` | `answer_bool` |
| `text` | `answer_text` |

## Категории вопросов

| Код | Эмодзи / Label |
|-----|---------------|
| `base` | Базовые (всегда включены) |
| `depression` | 🧠 Настроение и депрессивные симптомы |
| `anxiety` | 😰 Тревога |
| `hypomania` | ⚡ Подъем / гипомания |
| `lifestyle` | 🏃 Поведение и образ жизни |
| `health` | 💊 Здоровье и лечение |

## Категории сна (sleep_duration_category)

| Код | Label | ≈ Часов |
|-----|-------|---------|
| `no_sleep` | Не спал(а) | 0 |
| `less_3h` | Меньше 3 часов | 2 |
| `3_5h` | 3–5 часов | 4 |
| `5_7h` | 5–7 часов | 6 |
| `7_9h` | 7–9 часов | 8 |
| `more_9h` | Больше 9 часов | 10 |
| `skipped` | — | 0 |

## Качество сна (sleep_quality)

| Код | Label | Балл |
|-----|-------|------|
| `terrible` | Ужасный | 1 |
| `bad` | Плохой | 2 |
| `normal` | Нормальный | 3 |
| `good` | Хороший | 4 |
| `deep` | Крепкий | 5 |
| `skipped` | — | 0 |

## Проблемы сна (sleep_problems, мульти-выбор)

| Код | Label |
|-----|-------|
| `hard_to_fall_asleep` | Долго не мог(ла) уснуть |
| `early_wakeup` | Проснулся/проснулась слишком рано |
| `frequent_wakeups` | Часто просыпался/просыпалась |
| `little_sleep_but_feel_good` | Спал(а) мало, но чувствую себя отлично |
| `long_sleep_not_restored` | Спал(а) много, но не восстановился/восстановилась |

## Лекарства (medication_taken)

| Код | Label |
|-----|-------|
| `yes` | Да |
| `no` | Нет |
| `partial` | Частично |
| `not_applicable` | Не назначены / не принимаю |
| `skipped` | Пропустить |

## Шкалы

| Поле | Диапазон | CHECK в БД |
|------|----------|------------|
| mood | 0..10 | ✓ |
| anxiety | 0..5 | ✓ |
| energy | 0..5 | ✓ |
| irritability | 0..5 (nullable, EAV) | дроп в 0005 |
| impulsivity | 0..5 (nullable, EAV) | дроп в 0005 |

## Пресеты вопросов

| Код | Лейбл | Эмодзи |
|-----|-------|--------|
| `depr` | Сниженное настроение | 🌧 |
| `anx` | Тревога | 😰 |
| `mood` | Перепады настроения | ⚡ |
| `sleep` | Сон и режим | 🌙 |
| `all` | Всё расширенное | 🧩 |

## Режимы статистики

| Код | Описание |
|-----|----------|
| `brief` | summary + mood + anxiety + sleep + energy |
| `selected` | Включенные пользователем блоки (default = STATISTICS_DEFAULTS) |
| `full` | Все блоки каталога |

## Префиксы callback_data

| Префикс | Назначение |
|---------|-----------|
| `survey:` | Запуск опроса |
| `unfinished:` | Resume/restart незавершенного опроса |
| `mood:`, `anxiety:`, `energy:` | Шкалы 0..max |
| `sleep_dur:`, `sleep_q:`, `sleep_p:` | Блок сна |
| `med:` | Лекарства |
| `opt:` | Опциональный вопрос (индекс) |
| `pa_dur:` | Длительность физ. активности |
| `cqa:` | Custom question answer |
| `comment:` | Комментарий (skip) |
| `set:` | Меню настроек |
| `freq:` | Опросов в день (1..13) |
| `freq2:` | 📅 Частота опроса (тип + custom N дней) |
| `tz:` | Часовой пояс |
| `qs:` | Настройки вопросов |
| `cq:` | Custom-вопросы |
| `stats:` | Статистика (меню/настройки) |
| `stbrief:`, `stsel:`, `stfull:` | Период статистики (по режиму) |
| `export:` | Период экспорта |

## Константы

| Имя | Значение | Источник |
|-----|----------|----------|
| `MAX_COMMENT_LENGTH` | 1000 | `bot/constants.py` |
| `MAX_TEXT_LEN` | 150 | `bot/services/custom_question_service.py` (длина текста вопроса) |
| `MAX_ACTIVE_PER_USER` | 10 | Лимит активных custom-вопросов |
| `MAX_TEXT_ANSWER_LEN` | 1000 | Длина текстового ответа на custom-вопрос |
| `CUSTOM_DAYS_MIN/MAX` | 2 / 30 | Диапазон custom-days частоты |
| `PENDING_EXPIRE_HOURS` | 6 | `bot/config.py` |
| `DEFAULT_SLEEP_ASK_TIME` | 10:00 | `bot/utils/time_utils.py` |
| `SUICIDAL_HIGH_RISK_INDEX` | 4 | Индекс high-risk варианта в `suicidal_thoughts` |
| `SUMMARY_SENTINEL` | `"__summary__"` | Маркер текстового блока в статистике |

## Связанные документы

- См. [README.md](README.md) — индекс.
