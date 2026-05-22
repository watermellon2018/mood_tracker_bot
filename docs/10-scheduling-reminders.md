# 10. Расписание и напоминания

Реализация: [`bot/services/scheduler_service.py`](../bot/services/scheduler_service.py) + [`bot/services/reminder_service.py`](../bot/services/reminder_service.py) + [`bot/services/survey_frequency_service.py`](../bot/services/survey_frequency_service.py).

Стек: **PTB JobQueue** напрямую (без APScheduler-обвязки). PTB JobQueue работает с локальной TZ через `time(tzinfo=...)` в `run_daily`.

## Слои

```
┌────────────────────────────────┐
│  scheduler_service              │  Создаёт jobs, отвечает за пушлы и reminders.
│  - schedule_user                │
│  - reschedule_all (на старте)   │
│  - schedule_cleanup (раз в час) │
│  - send_scheduled_survey (job)  │
│  - send_reminder (job)          │
│  - cleanup_expired_pendings     │
└────────────────────────────────┘
              │ использует
              ▼
┌────────────────────────────────┐
│  survey_frequency_service       │  Чистые функции:
│  - should_send_survey_today     │  нужно ли сегодня слать (daily/weekly/...)
│  - required_gap_days            │
│  - validate_custom_days         │
│  - format_survey_frequency      │
└────────────────────────────────┘
```

## Job-имена

| Префикс | Что |
|---------|-----|
| `scheduled:<tg_id>` | Daily-jobs планового опроса для пользователя |
| `reminder:<pending_id>` | Одноразовый job отправки повторного напоминания |
| `cleanup_expired_pendings` | Глобальный repeating-job очистки старых pending |

## schedule_user(application, user, settings)

1. Удаляет все старые `scheduled:<tg_id>` jobs.
2. Если `not settings.notifications_enabled` → выход.
3. `compute_schedule(frequency_per_day, start_time, end_time)` — равномерное распределение N времён между start и end.
4. Для каждого слота создаёт `run_daily(send_scheduled_survey, time=time(hh, mm, tz), name=name, data={tg_id, survey_slot})`.

`survey_slot` для каждого индекса считается через `question_policy_service.slot_for_index(total, idx)`:
- 1 слот → `single`.
- idx=0 → `first`, idx=N-1 → `last`, иначе `regular`.

### compute_schedule

[`bot/utils/time_utils.py`](../bot/utils/time_utils.py):

```python
if frequency_per_day == 1: return [start_time]
step = (end_minutes - start_minutes) / (frequency - 1)
result = [time(start + step*i) for i in range(frequency)]
```

Пример: 3 слота, 7:00–23:00 → 7:00, 15:00, 23:00.

## send_scheduled_survey(context)

Job-callback для планового пуша.

1. Достаёт `telegram_user_id`, `survey_slot` из `context.job.data`.
2. Проверяет `notifications_enabled` (мог измениться).
3. **Проверка частоты опроса** через `survey_frequency_service.should_send_survey_today(...)`:
   - daily → каждый день, разрешено всегда.
   - weekly → 7 дней с прошлого `last_survey_notification_date`.
   - biweekly → 14 дней.
   - custom_days → N дней.
   - Если ещё ни разу не слали (last_date is None) → разрешено.
   - Если `days_passed <= 0` (TZ-сдвиг ушёл в минус) → НЕ слать (защита от дублей).
4. Создаёт `PendingSurvey(status='pending', sent_at=now())`.
5. Шлёт `SURVEY_SCHEDULED_INTRO` + кнопка «Заполнить опрос» (`start_survey_keyboard(survey_slot)`).
6. **После успешной отправки** обновляет `settings.last_survey_notification_date = local_today` (если ещё не сегодняшняя). Это гарантирует, что несколько слотов в один день не «трясут» last_date зря.
7. Если `reminder_enabled` → ставит one-shot `run_once(send_reminder, when=timedelta(minutes=reminder_delay), name=f"reminder:{pending_id}")`.

## send_reminder(context)

1. Достаёт `pending_id`, `tg_id`, `survey_slot`.
2. Загружает `PendingSurvey`. Если уже не `pending` (т.е. completed / reminder_sent / expired) → выход (опрос мог быть пройден в это время).
3. `mark_pending_reminder_sent` — меняет статус и `reminder_sent_at`.
4. Шлёт `SURVEY_REMINDER` + ту же кнопку (с тем же `survey_slot`).

## Отмена reminder при завершении опроса

`_finish_survey` → `reminder_service.cancel_reminder_for_pending(application, pending_id)`:

```python
for job in job_queue.get_jobs_by_name(f"reminder:{pending_id}"):
    job.schedule_removal()
```

## Очистка истекших pending

`schedule_cleanup(application)` ставит `run_repeating(cleanup_expired_pendings, interval=1h, first=5min)`.

`cleanup_expired_pendings(context)`:
- `cutoff = now_utc - PENDING_EXPIRE_HOURS (=6)`.
- `UPDATE pending_surveys SET status='expired' WHERE status IN (pending, reminder_sent) AND sent_at < cutoff`.

## reschedule_all (post_init)

При запуске бота:
1. `schedule_cleanup` — глобальный очиститель.
2. `reschedule_all` — для всех `User` в БД ставит daily jobs (восстановление после перезапуска).

Это работает потому, что:
- Расписание полностью детерминировано настройками пользователя.
- Состояние pending pending'ов восстанавливается через cleanup.

## Частота опроса (survey_frequency)

| Тип | Описание |
|-----|----------|
| `daily` | каждый день (default) |
| `weekly` | раз в 7 дней |
| `biweekly` | раз в 14 дней |
| `custom_days` | каждые N дней (2..30) |

Поля в `user_settings`:
- `survey_frequency_type`: `daily` / `weekly` / `biweekly` / `custom_days`.
- `survey_frequency_days`: только для `custom_days`, 2..30. Иначе NULL.
- `last_survey_notification_date`: дата последнего планового пуша (NOT ручного `/add`).

Поток обновления (`/settings → 📅 Частота опроса`):
1. `freq2:menu` → меню с 4 опциями.
2. `freq2:set:daily|weekly|biweekly` → `update_survey_frequency(...)` + `schedule_user(...)`.
3. `freq2:custom` → FSM ввода N дней.
4. FSM валидирует 2..30 через `validate_custom_days(text)`.
5. Сохраняет `type='custom_days', days=N`.

### Применение частоты к слотам в дне

Частота применяется к **дню целиком**: если сегодня не «день опроса», ни один слот не отправляется. Если день опроса — все слоты дня уйдут.

После успешной отправки первого слота в дне `last_survey_notification_date` обновляется, и оставшиеся слоты этого дня всё равно пройдут проверку `should_send_survey_today` положительно (с фильтром `days_passed <= 0 → False`). Реализация:

```python
if settings.last_survey_notification_date != local_today:
    update_last_survey_notification_date(...)
```

То есть `last_date` обновляется только если ещё не равен сегодняшнему — без лишних UPDATE.

## Повторное напоминание

Поля в `user_settings`:
- `reminder_enabled` (bool, default True).
- `reminder_delay_minutes` (int 1..1440, default 30).

Гарантии:
- Не больше одного напоминания на pending (state `reminder_sent` → больше не дёргаем).
- При завершении опроса напоминание отменяется (через `schedule_removal`).
- При перезапуске бота: jobs не персистентны, поэтому существующие reminders теряются. Это известное ограничение MVP (см. README).

## Влияние смены TZ

При `/start` или смене TZ (`tz:<key>`) → `scheduler_service.schedule_user(application, user, settings)` пересобирает все daily jobs в новой TZ.

JobQueue.run_daily берет `time(tzinfo=...)` напрямую — PTB сам конвертирует в UTC внутри. Это снимает класс багов с DST/смещениями.

## Влияние пауза/возобновление

- `/pause` → `notifications_enabled=False` → `schedule_user` снимает все daily jobs.
- `/resume` → `notifications_enabled=True` → `schedule_user` ставит заново.

## Идемпотентность

`schedule_user` сначала удаляет старые jobs, потом ставит новые. Это безопасно вызывать любое количество раз.

## Связанные документы

- [04-survey-flow.md](04-survey-flow.md) — как survey_slot влияет на FSM.
- [05-question-policies.md](05-question-policies.md) — слоты и политики.
- [11-settings.md](11-settings.md) — UI настроек.
- [12-timezones.md](12-timezones.md) — TZ и локальные даты.
