# 12. Часовые пояса (Timezones)

Все «локальные даты» в боте считаются в TZ пользователя. Время в БД хранится как `DateTime(timezone=True)` (UTC), но отображение, расписание и логика «сегодня / вчера» — в локальной TZ.

Handler: [`bot/handlers/timezone.py`](../bot/handlers/timezone.py). Утилиты: [`bot/utils/timezones.py`](../bot/utils/timezones.py), [`bot/utils/time_utils.py`](../bot/utils/time_utils.py).

## Onboarding

Поле `users.timezone_set` (Boolean, default False, миграция 0002) фиксирует, делал ли пользователь явный выбор. До явного выбора:
- timezone = `DEFAULT_TIMEZONE` (из `.env`, по умолчанию `Europe/Moscow`).
- При каждом `/start` показывается `prompt_timezone_choice` (inline-клавиатура).

После выбора `timezone_set=True` и больше не предлагаем.

Проверка: `needs_timezone_setup(telegram_user_id)`:

```python
with session_scope() as session:
    user = get_user_by_tg(session, telegram_user_id)
    if user is None: return True
    return not user.timezone_set
```

## Набор TZ для выбора

`TIMEZONE_CALLBACK_MAP` (короткий ключ → label + IANA-имя):

### Основная страница

| Кнопка | IANA |
|--------|------|
| Москва (`tz:msk`) | Europe/Moscow |
| Санкт-Петербург (`tz:spb`) | Europe/Moscow |
| Екатеринбург (`tz:ekb`) | Asia/Yekaterinburg |
| Новосибирск (`tz:nsk`) | Asia/Novosibirsk |
| Красноярск (`tz:kra`) | Asia/Krasnoyarsk |
| Иркутск (`tz:irk`) | Asia/Irkutsk |
| Владивосток (`tz:vvo`) | Asia/Vladivostok |

Плюс «Другое» (`tz:more`) и «Отмена» (`tz:cancel`).

### Доп. страница (`tz:more`)

| Кнопка | IANA |
|--------|------|
| Стокгольм (`tz:stk`) | Europe/Stockholm |
| Берлин (`tz:ber`) | Europe/Berlin |
| Лондон (`tz:lon`) | Europe/London |
| Стамбул (`tz:ist`) | Europe/Istanbul |
| Дубай (`tz:dxb`) | Asia/Dubai |
| Тбилиси (`tz:tbs`) | Asia/Tbilisi |
| Ереван (`tz:evn`) | Asia/Yerevan |
| Алматы (`tz:ala`) | Asia/Almaty |

Плюс «Назад» (`tz:back`) и «Отмена» (`tz:cancel`).

## Валидация

`bot/utils/timezones.py::is_valid_iana_timezone(name)`:

```python
try:
    ZoneInfo(name); return True
except (ZoneInfoNotFoundError, ValueError):
    return False
```

Если в `TIMEZONE_CALLBACK_MAP` будет невалидное имя — handler логирует error и показывает сообщение об ошибке, не записывая в БД.

## Поток выбора TZ

callback `timezone_callback`:

1. `tz:more` → переход на дополнительную страницу.
2. `tz:back` → возврат на основную.
3. `tz:cancel` → `nav_service.close_menu(...)` с текстом «Отменено. Часовой пояс не изменён.»
4. `tz:<key>` → берёт IANA из `TIMEZONE_CALLBACK_MAP`:
   - Валидирует через `is_valid_iana_timezone`.
   - `survey_service.set_user_timezone(session, tg_id, tz_name)` — обновляет `timezone` + `timezone_set=True`.
   - `scheduler_service.schedule_user(application, user, settings)` — пересобирает расписание в новой TZ.
   - Шлёт подтверждение: «Готово. Твой часовой пояс: <label> (<IANA>). Уведомления будут приходить по твоему местному времени.»

## Утилиты времени

[`bot/utils/time_utils.py`](../bot/utils/time_utils.py):

| Функция | Что |
|---------|-----|
| `compute_schedule(freq, start, end) → list[time]` | Равномерно распределяет N времён |
| `get_tz(tz_name) → pytz.BaseTzInfo` | pytz.timezone(name), fallback на Europe/Moscow |
| `parse_time(value) → time | None` | Парсит HH:MM |
| `user_local_date(tz_name) → date` | Сегодня в локальной TZ |
| `user_local_now(tz_name) → datetime` | Сейчас в локальной TZ (aware) |
| `can_ask_sleep_question(now, first, has_main) → bool` | Можно ли уже спрашивать про сон |
| `period_start(now, days) → datetime` | Для статистики |
| `get_next_notification_utc(tz, time) → datetime` | Для логов и тестов |

## DEFAULT_SLEEP_ASK_TIME

```python
DEFAULT_SLEEP_ASK_TIME = time(10, 0)
```

После полуночи (т.е. новая локальная дата уже наступила) вопрос «как спал» нельзя задавать, пока не наступит хотя бы `min(start_time, 10:00)`. Иначе пользователь, который ещё не лёг (например, в 02:00), получит абсурдный вопрос за «новый день».

Используется в `_init_survey` (см. [04-survey-flow.md](04-survey-flow.md)).

## Локальная vs UTC

| Что | TZ |
|-----|----|
| Все `created_at`, `sent_at`, `reminder_sent_at` | UTC (БД хранит TZ-aware) |
| `local_date` в `survey_entries` | Локальная дата пользователя на момент сохранения |
| `log_date` в `survey_answers` | Локальная (target_date по политике) |
| `last_survey_notification_date` | Локальная (для частоты опроса) |
| Расписание JobQueue (run_daily) | Локальная (PTB сам конвертирует в UTC внутри) |
| Графики matplotlib | Конвертация UTC → локальная при рендере |
| Excel «Дата и время» | Локальная (naive datetime — openpyxl не любит aware) |

## Смена TZ — что происходит с историей

`local_date` уже записан — он не меняется при смене TZ. Это означает: исторические записи остаются привязанными к дате на момент их создания. Это сознательное решение (без backfill).

Графики и Excel конвертируют `created_at` (UTC) в текущую TZ пользователя — поэтому отображаются в актуальной TZ.

## Связанные документы

- [10-scheduling-reminders.md](10-scheduling-reminders.md) — JobQueue и TZ.
- [13-database-schema.md](13-database-schema.md) — поля `local_date`, `log_date`.
