# Документация Mood Tracker Bot

Эта папка — подробный справочник по всем фичам и внутреннему устройству Telegram-бота для отслеживания настроения, тревоги, сна, энергии и других показателей при БАР.

Документация написана так, чтобы её можно было использовать в качестве контекста при доработке проекта (включая работу AI-агентов). Она держит в одном месте: список фич, бизнес-правила, схему БД, политики опроса, команды, callback-протоколы, расписание и кризисные сценарии.

> Бот не ставит диагнозы и не дает медицинских рекомендаций. Все формулировки и UX подчинены принципу «безопасное самонаблюдение, нейтральные термины».

## Содержание

| Файл | О чём |
|------|-------|
| [01-overview.md](01-overview.md) | Общее описание, стек, точка входа, главное меню |
| [02-features.md](02-features.md) | Полный список фич бота с пояснениями |
| [03-commands.md](03-commands.md) | Все команды, кнопки reply-меню и их поведение |
| [04-survey-flow.md](04-survey-flow.md) | Пошаговый flow опроса: базовые шаги, опциональные вопросы, custom-вопросы |
| [05-question-policies.md](05-question-policies.md) | Политики показа вопросов (per_survey / once_per_day / first_until_answered / last_of_day), таргет даты |
| [06-question-settings.md](06-question-settings.md) | Настройка вопросов: пресеты, категории, suicide warning |
| [07-custom-questions.md](07-custom-questions.md) | Пользовательские вопросы: CRUD, типы ответов, лимиты |
| [08-statistics.md](08-statistics.md) | Режимы статистики (brief / selected / full), графики, настройки блоков |
| [09-export.md](09-export.md) | Экспорт в Excel: листы, формат, периоды |
| [10-scheduling-reminders.md](10-scheduling-reminders.md) | JobQueue, расписание, повторное напоминание, частота опроса |
| [11-settings.md](11-settings.md) | Меню «Настройки»: частота, временной промежуток, TZ, пауза |
| [12-timezones.md](12-timezones.md) | Onboarding TZ, валидация, IANA-имена, локальные даты |
| [13-database-schema.md](13-database-schema.md) | Все таблицы, индексы, CHECK-констрейнты, миграции 0001–0011 |
| [14-architecture.md](14-architecture.md) | Слои handlers/services/keyboards/utils, callback-протокол, FSM |
| [15-safety-and-crisis.md](15-safety-and-crisis.md) | Безопасные формулировки, кризисное сообщение, suicidal_thoughts |
| [16-deployment.md](16-deployment.md) | Docker, Alembic, .env, локальный запуск, логи |
| [17-glossary.md](17-glossary.md) | Глоссарий ключевых терминов и кодов |

## Быстрые ссылки

- [Точка входа `bot/main.py`](../bot/main.py)
- [Модели `bot/models.py`](../bot/models.py)
- [Каталог вопросов `bot/constants_questions.py`](../bot/constants_questions.py)
- [Каталог блоков статистики `bot/constants_statistics.py`](../bot/constants_statistics.py)
- [Миграции `migrations/versions/`](../migrations/versions)
