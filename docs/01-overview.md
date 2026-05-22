# 01. Общий обзор

## Назначение

Mood Tracker Bot — Telegram-бот для регулярного отслеживания состояния пользователя при БАР (биполярном аффективном расстройстве). Бот:

- Регулярно (по расписанию) просит пользователя пройти короткий опрос.
- Хранит ответы в PostgreSQL.
- Строит статистику (PNG-графики) и текстовое саммари.
- Экспортирует данные в Excel.
- Не ставит диагнозы и не выдает медицинских рекомендаций.

## Стек

| Слой | Технология |
|------|------------|
| Язык | Python 3.11 |
| Telegram | python-telegram-bot 21.6 (с встроенной JobQueue, без APScheduler-обвязки сверху) |
| ORM | SQLAlchemy 2.0 |
| Миграции | Alembic 1.13 |
| БД | PostgreSQL |
| Графики | matplotlib (backend Agg) |
| Excel | pandas + openpyxl |
| Прокси | httpx[socks] (SOCKS5 поддерживается) |
| TZ | pytz + zoneinfo |
| Контейнер | Docker, docker-compose |

См. [requirements.txt](../requirements.txt) для точных версий.

## Структура каталогов

```
bot/
├── main.py                       # сборка Application, регистрация хендлеров, post_init
├── config.py                     # Config из .env + setup_logging
├── database.py                   # SQLAlchemy engine + session_scope (контекст-менеджер)
├── models.py                     # SQLAlchemy модели: User, UserSettings, SurveyEntry,
│                                 # PendingSurvey, QuestionCatalog, UserQuestionSettings,
│                                 # SurveyAnswer, CustomQuestion, CustomQuestionAnswer,
│                                 # UserStatisticsBlock
├── constants.py                  # перечисления значений в БД (категории сна,
│                                 # медикаменты, шкалы и т.п.)
├── constants_questions.py        # каталог вопросов (UI-маппинг), пресеты,
│                                 # политики, опции, double-step physical_activity
├── constants_statistics.py       # каталог блоков статистики, defaults, brief-режим,
│                                 # callback shorts (длинные коды не влезают в callback_data)
├── texts.py                      # все user-facing строки (русские)
├── handlers/                     # Telegram-хендлеры (entry-points + FSM)
├── services/                     # бизнес-логика (опрос, расписание, статистика,
│                                 # экспорт, политики, частота)
├── keyboards/                    # inline + reply клавиатуры
└── utils/                        # time_utils, plotting, validators, timezones
migrations/                       # Alembic
```

## Точка входа

`bot/main.py::main()`:
1. Загружает `BOT_TOKEN` из `.env`.
2. Собирает `Application` (PTB) с опциональным HTTPS-прокси.
3. Регистрирует все хендлеры (порядок важен — см. ниже).
4. В `post_init` стартует JobQueue: `schedule_cleanup` (раз в час, expired pendings) и `reschedule_all` (расписание для всех пользователей).
5. Запускает `application.run_polling(drop_pending_updates=True)`.

### Порядок регистрации хендлеров

Порядок имеет значение: PTB матчит хендлеры в порядке регистрации.

1. `build_survey_conversation()` — ConversationHandler опроса. Регистрируется первым, чтобы захватывать `survey:start` и кнопку «Добавить запись».
2. `build_add_sleep_conversation()` — `/add_sleep`.
3. `build_edit_meds_conversation()` — `/edit_meds`.
4. `unfinished_choice_callback` — для `unfinished:resume|restart`.
5. Команды: `/start`, `/menu`, `/help`, `/pause`, `/resume`.
6. `MessageHandler` reply-меню по точному совпадению текста (роутер `reply_menu_router`).
7. `/settings` + `build_settings_conversation()` (FSM ввода времени).
8. Inline-callback для меню настроек (`set:freq|tz|toggle_notif|toggle_rem|close`).
9. `build_custom_days_conversation()` — `freq2:custom` (custom-N дней).
10. `build_frequency_open_handler()` + `build_frequency_router()` — `freq2:menu`, `freq2:back`, `freq2:set:...`.
11. `build_timezone_handler()` — `tz:*`.
12. `build_qs_handler()` — настройки вопросов (`qs:*`).
13. Custom-questions: `build_cq_create_conversation()`, `build_cq_rename_conversation()`, `build_cq_list_entry()`, `build_cq_router()`.
14. `stats_handlers()` — статистика.
15. `export_handlers()` — экспорт.
16. `error_handler` — глобальный.

## Главное меню (reply-клавиатура)

Закреплённая reply-клавиатура (определена в [`bot/keyboards/main_menu.py`](../bot/keyboards/main_menu.py)) показывается у поля ввода:

| Кнопка | Действие |
|--------|----------|
| 📝 Добавить запись | Запуск опроса вручную (`/add`) |
| ⏸ Пауза / ▶️ Возобновить | Переключает `notifications_enabled` |
| 📊 Статистика | Открывает inline-меню режимов |
| 📤 Экспорт | Выбор периода → Excel |
| ⚙️ Настройки | Inline-меню настроек |

Кнопки маршрутизируются в `bot/handlers/start.py::reply_menu_router` через `MessageHandler(filters.Regex(...))`. «📝 Добавить запись» намеренно НЕ попадает в роутер: её ловит ConversationHandler опроса как entry-point.

## Связанные документы

- [02-features.md](02-features.md) — список фич.
- [03-commands.md](03-commands.md) — команды.
- [14-architecture.md](14-architecture.md) — архитектура слоёв.
