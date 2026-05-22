# 09. Экспорт в Excel

Команда: `/export` или кнопка «📤 Экспорт». Handler: [`bot/handlers/export.py`](../bot/handlers/export.py). Сервис: [`bot/services/export_service.py`](../bot/services/export_service.py).

## Поток

1. `/export` → меню выбора периода: 7 / 14 / 30 / Все данные. callback `export:7|14|30|all`.
2. После выбора:
   - Сообщение `EXPORT_PREPARING` («Готовлю файл...»).
   - Загрузка `entries` + `optional_answers` + `custom_answers` + `custom_questions_map` в одной сессии.
   - Сериализация в простые dict (чтобы не зависеть от сессии).
3. `export_service.build_excel(...)` — генерация `.xlsx` во временный файл.
4. Отправка `send_document(filename=f"mood_export_{period}.xlsx")`.
5. Удаление временного файла.

При пустых данных — `ERR_NO_DATA` («За выбранный период пока нет записей»).

## Структура Excel-файла

Создаётся через `pd.ExcelWriter(engine="openpyxl")`. Листы:

### Лист «Данные»

Каждая запись `survey_entries` — одна строка. Колонки:

| Колонка | Источник |
|---------|----------|
| Дата и время | `created_at` в локальной TZ пользователя (naive datetime — openpyxl плохо дружит с aware) |
| Тип записи | `main` → «опрос», `none` → «опрос (без сна)», `additional` → «доп. сон» |
| Настроение, Тревога, Энергия | mood/anxiety/energy. Для `additional` — пусто |
| Раздражительность, Импульсивность | если NULL — пусто |
| Длительность сна | label из `SLEEP_DURATION_LABELS` |
| Качество сна | label из `SLEEP_QUALITY_LABELS` |
| Долго не мог(ла) уснуть | `да` / `нет` |
| Раннее пробуждение | `да` / `нет` |
| Частые пробуждения | `да` / `нет` |
| Мало сна, но чувствую себя отлично | `да` / `нет` |
| Много сна, но не восстановился/восстановилась | `да` / `нет` |
| Прием лекарств | если `medication_filled=False` — пусто, иначе label |
| Комментарий | свободный текст |
| Источник записи | «плановый» / «ручной» / «после напоминания» |

### Лист «Сводка»

Транспонированная (1 строка → 2 колонки `Показатель / Значение`):

- Период.
- Количество записей.
- Среднее / Минимальное / Максимальное настроение.
- Средняя тревога, энергия.
- Средняя раздражительность, импульсивность (если есть данные).
- Дней с настроением 8+.
- Дней с тревогой 4+.
- Дней со сном меньше 5 часов.
- Дней без приема лекарств (все записи дня имеют `medication_taken='no'`).

При отсутствии данных шкал — только период и количество.

### Лист «Дневная статистика»

Агрегаты по локальным датам:

- Дата.
- Количество записей.
- Среднее / Мин / Макс настроение.
- Разброс настроения (max - min).
- Средняя тревога.
- Средняя энергия.
- Сон (часов, примерно) — max по `SLEEP_DURATION_TO_HOURS`.
- Прием лекарств — Counter по `medication_taken`, например «Да: 2, Частично: 1».
- Комментарии за день — все непустые комменты через ` | `.

### Лист «Опциональные ответы» (только если есть)

Long-format по `survey_answers`:

| Колонка | Описание |
|---------|----------|
| Дата и время | `entry.created_at` в локальной TZ |
| Вопрос (код) | `question_code` |
| Вопрос | `QUESTION_DEFINITIONS[code]["question_text"]` без `?` |
| Ответ | `answer_value` (текст или код варианта или JSON для physical_activity) |
| Ответ (число 0-4) | `answer_numeric` |

### Лист «Свои вопросы» (только если есть)

Long-format по `custom_question_answers`:

| Колонка | Описание |
|---------|----------|
| Дата и время | в локальной TZ |
| Вопрос | `question_text` без `?` |
| Формат | «Шкала 0–5» / «Да / Нет» / «Текст» |
| Ответ | `0..5` / `Да|Нет` / текст |
| Числовое (0-5) | `answer_numeric` (для аналитики) |

## Фильтрация при подсчётах в сводке

```python
scale_entries = [e for e in entries if e.sleep_type != "additional"]  # mood/anxiety/energy/irritability/impulsivity
sleep_entries = [e for e in entries
                 if e.sleep_type in ("main", "additional")
                 and e.sleep_duration_category != "skipped"]
med_entries   = [e for e in entries if e.medication_filled]
```

Это нужно, потому что:
- `additional` записи имеют нули в шкалах — не должны портить среднее.
- `skipped`-сон не должен учитываться в часах.
- Записи без `medication_filled` не должны попадать в «дней без приёма».

## Названия колонок и тексты

Все человекочитаемые лейблы берутся из:
- `bot/constants.py` — `SLEEP_DURATION_LABELS`, `SLEEP_QUALITY_LABELS`, `MEDICATION_LABELS`.
- `bot/constants_questions.py` — `QUESTION_DEFINITIONS` (для опциональных).

## Источники записи

| Код | Label |
|-----|-------|
| `scheduled` | плановый |
| `manual` | ручной |
| `reminder` | после напоминания |

## Локальное время

`_to_local(dt, tz)` — конвертирует aware-datetime из БД (UTC) в локальную TZ пользователя и убирает `tzinfo`:

```python
def _to_local(dt, tz) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).replace(tzinfo=None)
```

Без `replace(tzinfo=None)` openpyxl не корректно записывает в Excel (timezone-aware datetime приводит к ошибкам или «сломанным» датам).

## Делегирование из /stats

Кнопка «📄 Excel-отчёт» в `/stats` (callback `stats:excel`) делегирует в `/export` flow:

```python
if data == "stats:excel":
    await _show(update, EXPORT_CHOOSE_PERIOD, period_keyboard("export", include_all=True))
```

То есть после нажатия пользователь видит то же меню выбора периода, что и для `/export`.

## Связанные документы

- [08-statistics.md](08-statistics.md) — графики (другой формат вывода тех же данных).
- [13-database-schema.md](13-database-schema.md) — таблицы.
