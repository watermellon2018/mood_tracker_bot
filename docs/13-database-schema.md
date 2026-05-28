# 13. Схема базы данных

PostgreSQL, SQLAlchemy 2.0, Alembic. Все модели в [`bot/models.py`](../bot/models.py). Миграции в [`migrations/versions/`](../migrations/versions/).

## Таблицы

```
users
  └─ user_settings (1:1)
  └─ survey_entries (1:N)
  │   └─ survey_answers (1:N)         — EAV для опциональных system-вопросов
  │   └─ custom_question_answers (1:N) — ответы на custom-вопросы
  └─ pending_surveys (1:N)
  └─ user_question_settings (M:M c question_catalog)
  └─ user_statistics_blocks (M:M по строкам block_code)
  └─ custom_questions (1:N)
       └─ custom_question_answers
question_catalog                       — справочник вопросов
```

## users

| Поле | Тип | Default | Комментарий |
|------|-----|---------|-------------|
| id | Integer PK | | |
| telegram_user_id | BigInteger UNIQUE | | Indexed |
| timezone | String(64) | "Europe/Moscow" | IANA-имя |
| timezone_set | Boolean (0002) | false | Делал ли явный выбор |
| created_at | TZ-aware DateTime | now() | |

`telegram_user_id` уникален и проиндексирован — основной ключ поиска пользователя.

## user_settings

| Поле | Тип | Default | CHECK |
|------|-----|---------|-------|
| id | Integer PK | | |
| user_id | FK users.id CASCADE UNIQUE | | |
| frequency_per_day | Integer | 3 | BETWEEN 1 AND 13 |
| start_time | Time | 07:00 | start_time < end_time |
| end_time | Time | 23:00 | |
| notifications_enabled | Boolean | true | |
| reminder_enabled | Boolean | true | |
| reminder_delay_minutes | Integer | 30 | BETWEEN 1 AND 1440 |
| survey_frequency_type (0010) | String(32) | "daily" | IN (daily, weekly, biweekly, custom_days) |
| survey_frequency_days (0010) | Integer? | NULL | NULL or BETWEEN 2 AND 30 |
| last_survey_notification_date (0010) | Date? | NULL | Локальная дата последнего планового пуша |
| created_at, updated_at | TZ-aware | now() | |

Связь 1:1 с users по `user_id`, CASCADE удаление.

## survey_entries

| Поле | Тип | Default | CHECK |
|------|-----|---------|-------|
| id | Integer PK | | |
| user_id | FK users.id CASCADE | | Indexed |
| created_at | TZ-aware | now() | Indexed |
| local_date (0003) | Date | | NOT NULL после бэкфилла |
| sleep_type (0003) | String(16) | "main" | IN (main, additional, none) |
| medication_filled (0003) | Boolean | true | |
| mood | Integer | | BETWEEN 0 AND 10 |
| anxiety | Integer | | BETWEEN 0 AND 5 |
| energy | Integer | | BETWEEN 0 AND 5 |
| irritability (0005: nullable) | Integer? | NULL | Колонка-legacy, теперь EAV |
| impulsivity (0005: nullable) | Integer? | NULL | Аналогично |
| sleep_duration_category | String(16) | | См. SLEEP_DURATION_CATEGORIES |
| sleep_quality | String(16) | | См. SLEEP_QUALITY_CATEGORIES |
| hard_to_fall_asleep | Boolean | false | |
| early_wakeup | Boolean | false | |
| frequent_wakeups | Boolean | false | |
| little_sleep_but_feel_good | Boolean | false | |
| long_sleep_not_restored | Boolean | false | |
| medication_taken | String(16) | | См. MEDICATION_OPTIONS |
| comment | Text? | NULL | |
| source | String(16) | | "scheduled" / "manual" / "reminder" |

### Индексы и уникальные констрейнты на survey_entries

- `ix_survey_entries_user_id` (user_id).
- `ix_survey_entries_created_at` (created_at).
- `ix_survey_entries_local_date` (user_id, local_date) — миграция 0003.
- `uq_survey_main_sleep_per_day` (user_id, local_date) WHERE sleep_type='main' — **частичный уникальный индекс**, один main-сон в день.
- `uq_survey_medication_per_day` (user_id, local_date) WHERE medication_filled=true — один запись лекарств в день.

Эти частичные индексы — основа защиты от дублей. FSM опроса ловит `IntegrityError` и деградирует (sleep_type=none, medication_filled=false).

## pending_surveys

| Поле | Тип | Default |
|------|-----|---------|
| id | Integer PK | |
| user_id | FK users.id CASCADE | Indexed |
| sent_at | TZ-aware | |
| reminder_sent_at | TZ-aware? | NULL |
| status | String(16) | "pending" / "reminder_sent" / "completed" / "expired" |
| created_at | TZ-aware | now() |

Индексы: `ix_pending_surveys_user_id`, `ix_pending_surveys_status`.

Жизненный цикл:

```
pending ─ (delay) ─→ reminder_sent ─ (answer) ─→ completed
       \─ (answer) ─→ completed
       \─ (PENDING_EXPIRE_HOURS=6) ─→ expired (через cleanup_expired_pendings)
```

## question_catalog (миграция 0004)

| Поле | Тип |
|------|-----|
| code | String(64) PK |
| title | String(255) |
| description | Text |
| category | String(64) — IN (base, depression, anxiety, hypomania, lifestyle, health) |
| is_required | Boolean |
| is_default_enabled | Boolean |
| is_active | Boolean |
| sort_order | Integer |
| ask_policy (0009) | String(64) — IN (per_survey, once_per_day, first_survey_until_answered, last_survey_of_day) |
| answer_target_date_policy (0009) | String(64) — IN (current_day, previous_day) |
| created_at, updated_at | TZ-aware |

Seed-данные — 5 базовых (mood/anxiety/sleep/energy/comment) + 27 опциональных. См. `CATALOG_ROWS` в [migrations/versions/0004_question_catalog.py](../migrations/versions/0004_question_catalog.py).

Политики обновляются в 0009 (seed для late_phone, sleep, medications, и др.) и 0011 (большая группа в `last_survey_of_day`).

## user_question_settings

| Поле | Тип |
|------|-----|
| user_id | FK users.id CASCADE — часть PK |
| question_code | FK question_catalog.code CASCADE — часть PK |
| is_enabled | Boolean |
| created_at, updated_at | TZ-aware |

PK — (user_id, question_code). Хранит ТОЛЬКО опциональные вопросы. Базовые всегда считаются включенными без записи.

## survey_answers (EAV, миграция 0004 + 0009)

| Поле | Тип |
|------|-----|
| id | BigInteger PK |
| entry_id | FK survey_entries.id CASCADE — Indexed |
| question_code | FK question_catalog.code RESTRICT — Indexed |
| answer_value | Text? |
| answer_numeric | Numeric? |
| log_date (0009) | Date NOT NULL — дата, к которой относится ответ |
| created_at | TZ-aware |

Индексы:
- `ix_survey_answers_entry_id` (entry_id).
- `ix_survey_answers_question_code` (question_code).
- `ix_survey_answers_qcode_logdate` (question_code, log_date) — для проверки «есть ли ответ за дату».

`log_date` обычно = `entry.local_date`, но для `late_phone` = `entry.local_date - 1`.

## custom_questions (миграция 0006)

| Поле | Тип | CHECK |
|------|-----|-------|
| id | BigInteger PK | |
| user_id | FK users.id CASCADE | |
| question_text | Text | char_length BETWEEN 1 AND 150 |
| answer_type | String(32) | IN (scale_0_5, boolean, text) — после миграции 0007 |
| is_enabled | Boolean default true | |
| is_active | Boolean default true | |
| sort_order | Integer | |
| created_at, updated_at | TZ-aware | |

Индексы:
- `ix_custom_questions_user_active` (user_id, is_active).
- `uq_custom_q_user_text_active` (user_id, lower(trim(question_text))) WHERE is_active=true — uniq, защита от дублей.

## custom_question_answers (миграция 0006)

| Поле | Тип |
|------|-----|
| id | BigInteger PK |
| entry_id | FK survey_entries.id CASCADE |
| custom_question_id | FK custom_questions.id RESTRICT |
| answer_type | String(32) |
| answer_text | Text? |
| answer_numeric | Numeric? |
| answer_bool | Boolean? |
| created_at | TZ-aware |

Уникальный индекс `uq_custom_answer_entry_question` (entry_id, custom_question_id) — защита от дублей.

## user_statistics_blocks (миграция 0008)

| Поле | Тип |
|------|-----|
| user_id | FK users.id CASCADE — часть PK |
| block_code | String(64) — часть PK |
| is_enabled | Boolean default true |
| created_at, updated_at | TZ-aware |

PK — (user_id, block_code). Если строки нет → блок включен только если в `STATISTICS_DEFAULTS` (см. [08-statistics.md](08-statistics.md)).

## История миграций

| # | Описание |
|---|----------|
| 0001 | Initial: users, user_settings, survey_entries, pending_surveys |
| 0002 | users.timezone_set Boolean (для onboarding TZ) |
| 0003 | survey_entries: sleep_type, medication_filled, local_date + частичные unique-индексы. Бэкфилл: оставляет один main-сон / одну запись лекарств в день |
| 0004 | question_catalog (seed 5+27), user_question_settings, survey_answers (EAV) |
| 0005 | irritability/impulsivity → NULLABLE, дроп range-CHECK (вопросы переехали в EAV) |
| 0006 | custom_questions, custom_question_answers + uniq index по нормализованному тексту |
| 0007 | answer_type scale_0_10 → scale_0_5, обрезка старых ответов >5 |
| 0008 | user_statistics_blocks |
| 0009 | question_catalog.ask_policy + answer_target_date_policy, survey_answers.log_date с бэкфиллом |
| 0010 | user_settings: survey_frequency_type, survey_frequency_days, last_survey_notification_date |
| 0011 | UPDATE question_catalog: перевод дневных итоговых вопросов в `last_survey_of_day` |

### Идемпотентность миграций

Все ALTER-ы используют `IF NOT EXISTS` / `DROP IF EXISTS`. Можно безопасно применять `alembic upgrade head` несколько раз. Это важно потому, что в Docker контейнере бот запускает миграции при каждом старте (`alembic upgrade head && python -m bot.main`).

### Downgrade

Каждая миграция имеет `downgrade()`. Downgrade миграции 0005 (восстановление NOT NULL на irritability/impulsivity) разрушителен — заполняет NULL нулями. Это сознательное решение: downgrade — не штатный сценарий.

## Принципы

1. **Минимум данных о пользователе** — только `telegram_user_id`, TZ, флаг onboarding. Никаких имён, телефонов.
2. **TZ-aware на created_at** — UTC в БД, локальная TZ при отображении.
3. **Idempotent commits** через частичные unique-индексы.
4. **EAV для опциональных** — гибкость в добавлении новых вопросов без миграций (хотя seed в question_catalog нужно делать).
5. **Soft-delete у custom_questions** (`is_active=False`) — историю не теряем.
6. **CASCADE удаление от users**: при удалении пользователя удаляются все его данные (settings, entries, answers, pendings, custom questions). Кроме `survey_answers.question_code` (RESTRICT) и `custom_question_answers.custom_question_id` (RESTRICT) — защищают каталоги.

## Связанные документы

- [04-survey-flow.md](04-survey-flow.md) — как FSM пишет в БД.
- [05-question-policies.md](05-question-policies.md) — `ask_policy` и `log_date`.
- [14-architecture.md](14-architecture.md) — слой service над БД.
