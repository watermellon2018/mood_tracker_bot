# 11. Настройки уведомлений (/settings)

Handler: [`bot/handlers/settings.py`](../bot/handlers/settings.py) + [`bot/handlers/survey_frequency.py`](../bot/handlers/survey_frequency.py). Keyboards: [`bot/keyboards/settings_keyboards.py`](../bot/keyboards/settings_keyboards.py).

## Главный экран `/settings`

Текст:
```
Текущие настройки:

Опросов в день: <freq>
Частота опроса: <human-readable>
Промежуток: <start>–<end>
Часовой пояс: <label> (<IANA>)
Повторное напоминание: <включено|выключено>
Уведомления: <включены|выключены>
```

Клавиатура (`settings_menu_keyboard`):

```
[Опросов в день] [Время начала] [Время окончания]
[📅 Частота опроса]
[Часовой пояс] [Выключить уведомления / Включить уведомления]
[Выключить повторное напоминание / Включить...]
[Вопросы опроса]
[⬅️ Назад]
```

## Опросов в день

callback `set:freq` → клавиатура с кнопками 1..13 (по 7 в ряд через `frequency_keyboard`).

После выбора `freq:N`:
1. Валидация `validate_frequency(N)` (1..13).
2. `settings.frequency_per_day = N`.
3. `scheduler_service.schedule_user(...)` пересобирает расписание.
4. Показывает обновлённое меню.

## Время начала / окончания (FSM)

`set:start` / `set:end` запускают `build_settings_conversation`:

```
AWAIT_START_TIME → пользователь вводит HH:MM
                   парсинг через parse_time(value)
                   проверка t < settings.end_time
                   UPDATE start_time
AWAIT_END_TIME    → аналогично
```

Валидаторы:
- Формат HH:MM строго: 5 символов, двоеточие на 3-й позиции, числовые границы.
- `SETTINGS_INVALID_TIME` — формат не подходит.
- `SETTINGS_INVALID_RANGE` — `start >= end` (нарушает CHECK-констрейнт).

После успешного UPDATE → `schedule_user(...)`.

## 📅 Частота опроса (FSM с router)

callback `freq2:menu` → отдельный экран. См. подробно: [10-scheduling-reminders.md](10-scheduling-reminders.md#частота-опроса-survey_frequency).

Клавиатура (`survey_frequency_keyboard(current_type)`):

```
[✅ Каждый день / Каждый день]        freq2:set:daily
[✅ Раз в неделю / Раз в неделю]      freq2:set:weekly
[✅ Раз в 2 недели / ...]             freq2:set:biweekly
[✅ Каждые N дней / Каждые N дней]    freq2:custom (запускает FSM)
[⬅️ Назад]                            freq2:back (close_menu)
```

Активная опция отмечена `✅`.

### FSM ввода custom N дней

Entry: `freq2:custom`. State: `AWAIT_CUSTOM_DAYS`.
- Пользователь вводит число.
- `validate_custom_days(text)` — целое число 2..30.
- Сохранение через `update_survey_frequency(user_id, FREQ_CUSTOM, N)`.
- Перезапуск расписания.

Кнопка «⬅️ Назад» внутри FSM → `freq2:cancel` → возврат к меню частоты.

## Часовой пояс (set:tz)

`set:tz` → `prompt_timezone_choice(update)` → inline-клавиатура `timezone_main_keyboard` (см. [12-timezones.md](12-timezones.md)).

## Уведомления вкл/выкл (set:toggle_notif)

Эквивалент `/pause` или `/resume`:

```python
settings.notifications_enabled = not settings.notifications_enabled
scheduler_service.schedule_user(...)
```

Перерисовывает меню настроек.

## Повторное напоминание вкл/выкл (set:toggle_rem)

```python
settings.reminder_enabled = not settings.reminder_enabled
scheduler_service.schedule_user(...)
```

(schedule_user пересобирает daily jobs; reminders, привязанные к pending pending'ам, обрабатываются на лету в `send_scheduled_survey`.)

## Вопросы опроса (qs:menu)

Открывает раздел настройки вопросов. См. [06-question-settings.md](06-question-settings.md).

## ⬅️ Назад (set:close)

`nav_service.close_menu(update, context)`:
1. Пытается удалить сообщение.
2. Если нельзя — `edit_message_text("Меню закрыто.")` без клавиатуры.
3. Если и edit не получился — `reply_text(...)` новое сообщение.

Это даёт чистый UX на мобильнике (нет «зависших» меню без кнопок).

## Default-настройки нового пользователя

При первом обращении создаётся `UserSettings` с:

```python
frequency_per_day = 3
start_time = time(7, 0)
end_time = time(23, 0)
notifications_enabled = True
reminder_enabled = True
reminder_delay_minutes = 30
survey_frequency_type = "daily"
survey_frequency_days = None
last_survey_notification_date = None
```

## Валидаторы

- `validate_frequency(int) → bool`: 1..13.
- `parse_time(str) → time | None`: HH:MM формат.
- `validate_custom_days(str) → int | None`: 2..30.

CHECK-констрейнты в БД (см. [13-database-schema.md](13-database-schema.md)):
- `frequency_per_day BETWEEN 1 AND 13`.
- `start_time < end_time`.
- `reminder_delay_minutes BETWEEN 1 AND 1440`.
- `survey_frequency_type IN (...)`.
- `survey_frequency_days IS NULL OR survey_frequency_days BETWEEN 2 AND 30`.

## Связанные документы

- [10-scheduling-reminders.md](10-scheduling-reminders.md) — как настройки превращаются в jobs.
- [12-timezones.md](12-timezones.md) — TZ.
