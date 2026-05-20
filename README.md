# Mood Tracker Bot

Telegram-бот для регулярного отслеживания настроения, тревоги, энергии, раздражительности, импульсивности, сна и приема лекарств при БАР.

**Бот не ставит диагнозы и не дает медицинских рекомендаций.** Он только фиксирует ответы пользователя, строит статистику и экспортирует данные.

## Возможности

- Пошаговые опросы по расписанию и вручную.
- Настраиваемая частота (1–13 раз/день) и временной промежуток.
- Повторное напоминание один раз, если пользователь не ответил.
- Статистика и графики PNG за 7 / 14 / 30 дней.
- Экспорт в Excel (Данные / Сводка / Дневная статистика).

## Стек

Python 3.11, python-telegram-bot 21 (с встроенной JobQueue), SQLAlchemy 2, Alembic, PostgreSQL, pandas, matplotlib, openpyxl, Docker.

> Вместо APScheduler используется встроенная в PTB JobQueue: она нативно интегрируется с event loop приложения и снимает класс ошибок с двойной инициализацией планировщика. Если требуется APScheduler — это можно перенастроить, обвязка scheduler_service инкапсулирована.

## Локальный запуск (conda env basic)

```
conda activate basic
pip install -r requirements.txt

# В .env должен быть DATABASE_URL до запущенного локального PostgreSQL
cp .env.example .env

# Применить миграции
alembic upgrade head

# Запустить бота
python -m bot.main
```

## Запуск в Docker

```
cp .env.example .env
# отредактируй BOT_TOKEN и POSTGRES_PASSWORD

docker compose up -d --build
```

Миграции применяются автоматически в `CMD` контейнера бота (`alembic upgrade head && python -m bot.main`).

### Просмотр логов

```
docker compose logs -f bot
```

### Ручные миграции

```
docker compose exec bot alembic upgrade head
docker compose exec bot alembic revision --autogenerate -m "description"
```

### Остановка

```
docker compose down
```

## Команды бота

- `/start` — регистрация и приветствие
- `/help` — помощь
- `/add` — пройти опрос вручную
- `/settings` — настройки уведомлений
- `/stats` — статистика и графики за период
- `/export` — экспорт данных в Excel
- `/pause` — отключить плановые опросы
- `/resume` — включить плановые опросы

## Структура

```
bot/
├── main.py              # сборка приложения, регистрация хендлеров
├── config.py            # настройки из .env
├── database.py          # SQLAlchemy engine / session_scope
├── models.py            # User, UserSettings, SurveyEntry, PendingSurvey
├── constants.py         # перечисления значений (категории сна и т.д.)
├── texts.py             # все русские строки
├── handlers/            # Telegram-хендлеры
├── services/            # бизнес-логика (опрос, расписание, статистика, экспорт)
├── keyboards/           # inline-клавиатуры
└── utils/               # time_utils, plotting, validators
migrations/              # Alembic
```

## База данных

- `users` — минимум данных: telegram_user_id, timezone, created_at.
- `user_settings` — частота, временной промежуток, флаги уведомлений, задержка напоминания. CHECK-констрейнты на диапазоны.
- `survey_entries` — ответы по всем шкалам, поля сна, лекарства, комментарий, источник.
- `pending_surveys` — статусы pending → reminder_sent → completed / expired.

## Безопасные формулировки

Бот никогда не пишет «гипомания», «депрессия» и т.п. Все тексты — нейтральные («может быть важной динамикой для наблюдения», «при необходимости данные можно обсудить со специалистом»).

## Логирование

Логируется: запуск, создание пользователя, изменения настроек, отправка плановых и повторных уведомлений, завершение опросов, ошибки БД / графиков / Excel. Содержимое комментариев пользователя не логируется.

## Что можно улучшить потом

- Персистентность `ConversationHandler` (сейчас при рестарте бота незавершенные опросы теряются).
- Точное состояние "продолжить незаконченный опрос" — сейчас перезапускает с первого шага.
- Webhook-режим вместо polling.
- Регулярный health-check соединения с БД.
- Тесты (pytest) для services и utils.
- Cluster-safe scheduling (если будет несколько инстансов бота).
- Локализация (вынесена в `texts.py`, добавить i18n несложно).
- Ограничение частоты ручных опросов (антиспам).
