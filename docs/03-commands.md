# 03. Команды и кнопки

## Слэш-команды

Список зарегистрирован в `bot/main.py::_post_init` через `bot.set_my_commands`, чтобы Telegram показывал их в подсказках.

| Команда | Описание | Handler |
|---------|----------|---------|
| `/start` | Регистрация + приветствие + onboarding TZ | `bot/handlers/start.py::start_command` |
| `/menu` | Главное меню | `bot/handlers/start.py::menu_command` |
| `/help` | Помощь (текст из `texts.HELP`) | `bot/handlers/start.py::help_command` |
| `/add` | Пройти опрос вручную | `bot/handlers/survey.py::add_command` |
| `/add_sleep` | Добавить дополнительный сон | `bot/handlers/add_sleep.py::add_sleep_command` |
| `/edit_meds` | Изменить запись о лекарствах за сегодня | `bot/handlers/edit_meds.py::edit_meds_command` |
| `/settings` | Меню настроек | `bot/handlers/settings.py::settings_command` |
| `/stats` | Меню статистики | `bot/handlers/stats.py::stats_command` |
| `/export` | Выбор периода и экспорт в Excel | `bot/handlers/export.py::export_command` |
| `/pause` | Отключить плановые опросы (`notifications_enabled=false`) | `bot/handlers/start.py::pause_command` |
| `/resume` | Включить плановые опросы | `bot/handlers/start.py::resume_command` |
| `/cancel` | Отмена внутри FSM (опрос / настройки / custom-questions) | в каждом ConversationHandler как fallback |

## Reply-клавиатура (главное меню)

Закрепленная reply-клавиатура у поля ввода (`is_persistent=True`, `resize_keyboard=True`). См. [`bot/keyboards/main_menu.py`](../bot/keyboards/main_menu.py).

Раскладка:

```
[📝 Добавить запись]   [⏸ Пауза / ▶️ Возобновить]
[📊 Статистика] [📤 Экспорт] [⚙️ Настройки]
```

Кнопка «📝 Добавить запись» захватывается ConversationHandler опроса как entry-point. Остальные — `MessageHandler(filters.Regex(...))` в `bot/handlers/start.py::reply_menu_router`, который вызывает соответствующие command-функции.

Кнопка «Пауза» / «Возобновить» показывается динамически на основе `settings.notifications_enabled`.

## /start — регистрация и onboarding

1. `survey_service.get_or_create_user(tg_id, DEFAULT_TIMEZONE)`. Создание `User` + `UserSettings` (default-значения).
2. Если у пользователя уже есть settings — `scheduler_service.schedule_user(...)` пересобирает расписание (на случай restart).
3. Отправляется `WELCOME` + reply-клавиатура.
4. Если `not user.timezone_set` — показывает inline-клавиатуру выбора TZ (`prompt_timezone_choice`).

## /add — опрос

1. Проверяет `_is_active_survey(context)` (нет ли висящего опроса в `user_data`). Если есть — предлагает «Продолжить / Начать заново» (callback `unfinished:resume|restart`).
2. `_init_survey(context, SOURCE_MANUAL, tg_id, SURVEY_SLOT_MANUAL)`:
   - Берет `User` + локальную дату/время.
   - Проверяет `has_main_sleep_for_date`, `has_medication_for_date` → определяет `skip_sleep`, `skip_medication`.
   - Через `can_ask_sleep_question` проверяет, что уже наступило утро (после полуночи рано спрашивать про сон).
   - Считает план опциональных шагов через `question_policy_service.build_daily_survey_steps`.
   - Загружает custom-вопросы.
3. Шлёт `Q_MOOD` + клавиатуру.
4. Возвращает state `MOOD`.

Подробно про flow: [04-survey-flow.md](04-survey-flow.md).

## /add_sleep — дополнительный сон

ConversationHandler из двух шагов: длительность → качество. Запись `SurveyEntry` с `sleep_type='additional'` через `survey_service.save_additional_sleep`. Шкалы заполняются нулями, не учитываются в статистике (фильтр `sleep_type != 'additional'`).

## /edit_meds — обновить лекарства за сегодня

1. Ищет существующую запись с `medication_filled=True` за `user_local_date(user.timezone)`.
2. Если нет — отвечает «Запиши через /add», конец.
3. Если есть — показывает выбор нового значения (`medication_keyboard`).
4. UPDATE через `survey_service.update_medication`.

## /settings — меню настроек

Inline-меню (`settings_menu_keyboard`):

- `set:freq` — выбор частоты (1..13) — `freq:N` callback.
- `set:start` / `set:end` — FSM, ввод HH:MM (`build_settings_conversation`).
- `freq2:menu` — открыть «📅 Частота опроса».
- `set:tz` — открыть выбор TZ.
- `set:toggle_notif` — переключить `notifications_enabled`.
- `set:toggle_rem` — переключить `reminder_enabled`.
- `qs:menu` — открыть настройки вопросов.
- `set:close` — закрыть меню (через `nav_service.close_menu`).

Подробно: [11-settings.md](11-settings.md).

## /stats — статистика

Меню (`stats_menu_keyboard`):

- `stats:brief` — кратко (фикс. набор).
- `stats:selected` — выбранные блоки пользователя.
- `stats:full` — все блоки.
- `stats:excel` — делегирует в `/export` flow.
- `stats:settings` — настройка блоков (галочки).
- `stats:back` — закрыть меню.

После выбора режима — выбор периода (7/14/30 дней) через `period_keyboard`. callback вида `stbrief:7|14|30`, `stsel:7|14|30`, `stfull:7|14|30`.

Подробно: [08-statistics.md](08-statistics.md).

## /export — экспорт в Excel

Меню выбора периода с дополнительным «Все данные». callback вида `export:7|14|30|all`.

После выбора:
1. Загружает `entries`, `optional_answers`, `custom_answers`, `custom_questions_map`.
2. Если пусто — `ERR_NO_DATA`.
3. Через `export_service.build_excel(...)` собирает временный `.xlsx`.
4. Шлёт документом с именем `mood_export_{period}.xlsx`.
5. Чистит временный файл.

Подробно: [09-export.md](09-export.md).

## /pause и /resume

Меняют `settings.notifications_enabled` и пересобирают расписание через `scheduler_service.schedule_user`. Расписание удаляется целиком, если notifications_enabled=False.

## Callback-протокол (префиксы)

Все callback_data имеют префикс с двоеточием. Это позволяет роутить хендлерами по `pattern=r"^prefix:..."`.

| Префикс | Где | Документ |
|---------|-----|----------|
| `survey:start[:<slot>]` | старт опроса по кнопке | [04-survey-flow.md](04-survey-flow.md) |
| `unfinished:resume|restart` | продолжить/начать заново | survey.py |
| `mood:N`, `anxiety:N`, `energy:N` | шкалы 0..max | survey.py |
| `sleep_dur:KEY`, `sleep_q:KEY`, `sleep_p:KEY` | сон | survey.py |
| `med:KEY` | лекарства | survey.py / edit_meds.py |
| `opt:IDX` | опциональный вопрос (индекс варианта) | survey.py |
| `pa_dur:KEY` | длительность физ. активности | survey.py |
| `cqa:scale:N`, `cqa:bool:0|1` | ответ на custom-вопрос | survey.py |
| `comment:skip` | пропустить комментарий | survey.py |
| `set:freq|start|end|tz|toggle_notif|toggle_rem|close` | меню настроек | settings.py |
| `freq:N` | выбор «опросов в день» (1..13) | settings.py |
| `freq2:menu|back|set:<type>|custom|cancel` | частота опроса | survey_frequency.py |
| `tz:<key>|more|back|cancel` | таймзона | timezone.py |
| `qs:menu|back|presets|preset:<code>|manual|cat:<short>|tgl:<code>|reset|suicide_confirm|suicide_cancel|cq_list` | настройки вопросов | question_settings.py |
| `cq:add|list|view:<id>|toggle:<id>|archive:<id>|archive_ok:<id>|rename:<id>|type:<type>|confirm|edit_text|edit_type|cancel` | custom-вопросы | custom_questions.py |
| `stats:menu|back|brief|selected|full|excel|settings|reset|tgl:<short>` | статистика | stats.py |
| `stbrief:N`, `stsel:N`, `stfull:N` | период статистики | stats.py |
| `export:7|14|30|all` | период экспорта | export.py |

## Ограничения callback_data

Telegram ограничивает `callback_data` 64 байтами. Поэтому:
- Длинные коды вопросов мапятся в короткие через `CATEGORY_FULL_TO_SHORT` ([`bot/constants_questions.py`](../bot/constants_questions.py)).
- Длинные коды блоков статистики мапятся в короткие через `BLOCK_CALLBACK_SHORTS` ([`bot/constants_statistics.py`](../bot/constants_statistics.py)).

Например: `qs:cat:depr` (а не `qs:cat:depression`); `stats:tgl:tss` (вместо `thought_speech_speed`).
