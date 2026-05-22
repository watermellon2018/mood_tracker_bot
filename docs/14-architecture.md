# 14. Архитектура

## Слои

```
┌──────────────────────────────────────────────────────────────────┐
│  Telegram (PTB Application + JobQueue)                            │
└──────────────────────────────────────────────────────────────────┘
            │                       ▲
            │ Update                 │ send_message, JobQueue.run_daily
            ▼                       │
┌──────────────────────────────────────────────────────────────────┐
│  handlers/                                                         │
│  ─ start.py, survey.py, settings.py, stats.py, export.py,         │
│  ─ add_sleep.py, edit_meds.py, timezone.py,                       │
│  ─ question_settings.py, custom_questions.py,                     │
│  ─ survey_frequency.py, common.py (error_handler)                 │
│                                                                    │
│  Хендлеры: ConversationHandler (FSM), CallbackQueryHandler,       │
│  CommandHandler, MessageHandler. Никаких прямых SQL.              │
└──────────────────────────────────────────────────────────────────┘
            │                       │
            ▼                       │ session_scope, чистые функции
┌──────────────────────────────────────────────────────────────────┐
│  services/                                                         │
│  ─ survey_service          — CRUD по записям, pending             │
│  ─ scheduler_service       — JobQueue (расписание + reminders)    │
│  ─ reminder_service        — отмена reminders                     │
│  ─ question_policy_service — политики, slot, target_date          │
│  ─ question_settings_service — настройки опциональных вопросов    │
│  ─ custom_question_service — CRUD custom-вопросов                 │
│  ─ statistics_settings_service — настройки блоков статистики      │
│  ─ statistics_renderer     — dispatch блоков на рендереры         │
│  ─ stats_service           — fetch + build_summary                 │
│  ─ survey_frequency_service — чистые функции (валидация частоты)  │
│  ─ export_service          — Excel генерация                      │
│  ─ nav_service             — safe_edit, close_menu                │
└──────────────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────────┐
│  models/  (SQLAlchemy ORM)   + database.session_scope             │
│  ─ User, UserSettings, SurveyEntry, PendingSurvey                 │
│  ─ QuestionCatalog, UserQuestionSettings, SurveyAnswer            │
│  ─ CustomQuestion, CustomQuestionAnswer                           │
│  ─ UserStatisticsBlock                                            │
└──────────────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────────┐
│  PostgreSQL                                                        │
└──────────────────────────────────────────────────────────────────┘

  utils/      ← вспомогательное (plotting, time_utils, validators, timezones)
  keyboards/  ← InlineKeyboardMarkup + ReplyKeyboardMarkup
  constants*  ← перечисления, лейблы, policy maps
  texts       ← все пользовательские строки (русский)
```

## Принципы

1. **Handlers тонкие**: переводят Update в вызовы services. Никаких SQL.
2. **Services не знают про Telegram**: чистые функции, принимают `Session` + параметры. Исключение: scheduler_service (использует PTB JobQueue).
3. **Чистые функции в utils**: legко тестировать (`compute_schedule`, `parse_time`, `validate_*`, `is_valid_iana_timezone`).
4. **Все user-facing строки в `texts.py` / `constants*.py`**: легко локализовать.
5. **callback_data — короткая, типизированная**: префиксы `survey:`, `set:`, `qs:`, `cq:` и т.д. Длинные коды мапятся в короткие (через `BLOCK_CALLBACK_SHORTS`, `CATEGORY_SHORT_TO_FULL`).
6. **Идемпотентность**: миграции, `schedule_user`, FSM `_finish_survey` — все безопасно вызывать повторно. Частичные unique-индексы ловят гонки.
7. **Логирование без PII**: содержимое комментариев не логируется, только id/code.

## session_scope

[`bot/database.py`](../bot/database.py):

```python
@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

`SessionLocal` с `expire_on_commit=False` — это важно: после `commit` объекты остаются usable, можно передавать наружу контекста. Это упрощает паттерн:

```python
with session_scope() as session:
    user = survey_service.get_or_create_user(session, tg_id, default_tz)
    settings = survey_service.get_settings(session, user.id)
# теперь user, settings можно использовать вне сессии (для schedule_user и т.п.)
scheduler_service.schedule_user(application, user, settings)
```

## FSM (ConversationHandler)

PTB `ConversationHandler` хранит state в `application.user_data[tg_id]`. ВАЖНО: не персистентный (memory-only), поэтому при рестарте бота незавершённые опросы теряются.

Поле `context.user_data["survey"]` — основное хранилище опроса. После `_finish_survey` или `cancel_command` — `.pop("survey")`.

### Защита от двойного входа

`_is_active_survey(context)` проверяет наличие ключа `survey`. Если есть — `unfinished_survey_keyboard` (resume / restart). resume сейчас перезапускает с начала (известное ограничение MVP).

### Несколько ConversationHandler'ов

Каждый handler имеет уникальное `name` (для дебага). `allow_reentry=False` — нельзя войти в опрос, если уже в опросе.

## Callback-роутинг

Большинство callback'ов — `CallbackQueryHandler(handler, pattern=r"^...")`. Хендлеры регистрируются в `main.py` в нужном порядке:

1. Сначала `ConversationHandler`'ы (они приоритетнее по `entry_points`).
2. Затем «глобальные» CallbackQueryHandler (для меню и навигации).

### Пример: callback `cq:add`

- ConversationHandler `cq_create` имеет `entry_points=[CallbackQueryHandler(cq_add_start, pattern=r"^cq:add$")]`.
- Общий роутер `build_cq_router()` имеет `pattern=r"^cq:(list|view:N|toggle:N|archive:N|archive_ok:N)$"` — НЕ включает `add`.

Порядок регистрации (см. `main.py`) гарантирует, что `cq:add` ловит FSM-handler.

## nav_service

[`bot/services/nav_service.py`](../bot/services/nav_service.py) — единые хелперы:

| Функция | Что |
|---------|-----|
| `safe_edit(update, text, markup)` | Редактирует callback-сообщение или шлёт новое. Подавляет «not modified», «not found» |
| `close_menu(update, context, fallback_text)` | Закрывает inline-меню: пытается удалить, fallback на edit без клавиатуры |
| `clear_state_keys(context, keys)` | Чистит FSM-keys из user_data |
| `clear_state_and_close(update, context, keys, fallback)` | Комбо |
| `answer_silently(query)` | query.answer() с подавлением ошибок |

Все функции глотают `BadRequest`, `Forbidden`, `TelegramError` и логируют на debug — чтобы повторный тап по кнопке не валил бота.

## Логирование

`setup_logging()` в [`bot/config.py`](../bot/config.py):

```python
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO),
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
```

Каждый модуль имеет `logger = logging.getLogger(__name__)`.

Логируется:
- Запуск бота (`main.py`).
- Создание пользователя.
- Изменения настроек.
- Отправка плановых и повторных уведомлений (с pending_id).
- Завершение опросов (id, slot).
- Применение пресета вопросов.
- Skip-блоки в опросе (с причиной).
- Ошибки БД, графиков, Excel.

НЕ логируется:
- Содержимое комментариев пользователя.
- Полные тексты сообщений.

## error_handler

[`bot/handlers/common.py`](../bot/handlers/common.py):

```python
async def error_handler(update, context):
    logger.exception("Необработанная ошибка", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(ERR_GENERIC)
        except Exception:
            pass
```

Регистрируется через `application.add_error_handler(...)` — last-resort защита от непредвиденных исключений.

## Расширение: добавление нового опционального вопроса

1. INSERT в `question_catalog` (или новая миграция).
2. Добавить `QUESTION_DEFINITIONS[code]` в `bot/constants_questions.py` (question_text + options).
3. Если нужно — добавить в `OPTIONAL_QUESTION_ORDER` и в политику `QUESTION_POLICIES`.
4. Если нужен график — добавить рендер в `statistics_renderer` или попасть под `_r_optional_factory` (универсальный EAV).

Никакого SQL-кода менять не надо — EAV (`survey_answers`) принимает новый код автоматически.

## Расширение: новый блок статистики

1. Добавить кортеж в `STATISTICS_BLOCKS`.
2. Добавить рендер в `STATISTICS_BLOCK_RENDERERS` (или попасть в `_OPTIONAL_CODES`).
3. Если нужен короткий код для callback — `BLOCK_CALLBACK_SHORTS`.
4. По необходимости — в `STATISTICS_DEFAULTS` или `STATISTICS_BRIEF`.

## Не-цели

- ❌ Webhook-режим (только polling).
- ❌ Cluster-safe (один инстанс).
- ❌ Persistent ConversationHandler (теряем состояние при рестарте).
- ❌ Локализация UI (всё в `texts.py` русский, но архитектура позволяет добавить).
- ❌ Rate-limit ручных опросов (антиспам).

См. секцию «Что можно улучшить потом» в [README.md](../README.md).
