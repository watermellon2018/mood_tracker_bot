# 08. Статистика и графики

Команда: `/stats` или кнопка «📊 Статистика». Handler: [`bot/handlers/stats.py`](../bot/handlers/stats.py).

## Три режима

| Режим | callback | Содержимое |
|-------|----------|------------|
| ⚡ Кратко (brief) | `stats:brief` | Фиксированный набор: `summary`, `mood`, `anxiety`, `sleep`, `energy` |
| 🎛 Выбранные блоки (selected) | `stats:selected` | Только блоки, включенные пользователем в настройках |
| 📦 Полный отчёт (full) | `stats:full` | Все блоки каталога; пустые автоматически скрываются |
| 📄 Excel-отчёт | `stats:excel` | Делегирует в `/export` |
| ⚙️ Настроить статистику | `stats:settings` | Чекбоксы по блокам |

## Период

После выбора режима пользователь выбирает период: 7 / 14 / 30 дней. Каждый режим имеет свой callback префикс (`stbrief`, `stsel`, `stfull`), чтобы знать, в каком режиме вернулся пользователь:
- `stbrief:N` → mode=brief, days=N.
- `stsel:N` → mode=selected.
- `stfull:N` → mode=full.

В `/export` есть дополнительная опция «Все данные» (`export:all`).

## Каталог блоков

Источник: [`bot/constants_statistics.py::STATISTICS_BLOCKS`](../bot/constants_statistics.py).

Кратко по блокам (категории: `base`, `health`, `hypomania`, `anxiety`, `depression`, `lifestyle`, `custom`):

| Код | Категория | Рендер |
|-----|-----------|--------|
| `summary` | base | Текст (саммари: средние, дни с пиками, лекарства) |
| `mood` | base | Линейный график с цветовыми зонами 0-3 / 4-6 / 7-10 |
| `anxiety` | base | Линейный график |
| `energy` | base | Линейный график |
| `sleep` | base | Парные бары длительности и качества по дням |
| `mood_energy` | base | Двойная Y-ось: настроение и энергия |
| `mood_spread` | base | Бар-чарт max-min настроения по дням (только дни с ≥2 записями) |
| `sleep_problems` | base | Горизонтальный бар-чарт счётчиков по 5 проблемам сна |
| `irritability` | hypomania | Линейный график (из EAV survey_answers) |
| `impulsivity` | hypomania | Линейный график (из EAV) |
| `medications` / `therapy` / ... | health, hypomania, anxiety, depression, lifestyle | EAV — рендер через `plot_optional_question` |
| `custom_questions` | custom | Серия графиков по каждому custom-вопросу (scale_0_5: линейный, boolean: бар-чарт) |

Полный список: см. `STATISTICS_BLOCKS` в [`bot/constants_statistics.py`](../bot/constants_statistics.py).

## STATISTICS_DEFAULTS

```python
STATISTICS_DEFAULTS = {"summary", "mood", "anxiety", "sleep", "energy"}
```

Для нового пользователя в режиме `selected` показываются эти блоки, пока он явно не включит/выключит что-то.

## STATISTICS_BRIEF

```python
STATISTICS_BRIEF = ["summary", "mood", "anxiety", "sleep", "energy"]
```

Brief — это «карта быстрого взгляда»: одно текстовое саммари и 4 ключевых графика.

## Архитектура рендерера

[`bot/services/statistics_renderer.py`](../bot/services/statistics_renderer.py):

```python
STATISTICS_BLOCK_RENDERERS: dict[str, Callable[[dict], list[str]]] = {
    "summary":          _r_summary,         # вернёт [SUMMARY_SENTINEL]
    "mood":             _r_mood,            # plot_mood(...)
    "anxiety":          _r_anxiety,
    ...
    "custom_questions": _r_custom_questions,
}
```

Плюс автоматическое заполнение для EAV-вопросов:
```python
_OPTIONAL_CODES = ["medications", "therapy", "menstrual_cycle", "suicidal_thoughts",
                   "hypomania", "thought_speech_speed", ...]
for code in _OPTIONAL_CODES:
    STATISTICS_BLOCK_RENDERERS.setdefault(code, _r_optional_factory(code))
```

`_r_optional_factory(code)` создаёт замыкание, которое вызывает `plot_optional_question(rows, code, tz)`.

Каждый рендер возвращает список:
- `[]` — нет данных или нет рендера (handler соберёт в «По части блоков пока недостаточно данных»).
- `[path1, path2, ...]` — пути к PNG.
- `["__summary__"]` — sentinel: на этом месте отправить текстовый summary через `stats_service.build_summary`.

## Поток `/stats N`

1. `_send_report(update, context, tg_id, mode, days)`:
   - `since = now_utc - days`.
   - Загружает в одной сессии: `entries`, `optional_answers` (EAV), `custom_answers`, `custom_q_snapshot`.
   - Сериализует в простые dict (после `expire_on_commit=False` объекты можно использовать вне сессии).
   - Определяет список блоков по режиму.
2. Для каждого блока вызывает `render_block(code, ctx)`.
3. Собирает:
   - `summary_text` (при встрече `__summary__` sentinel) — отправляется как текстовое сообщение.
   - `plot_paths` — пути PNG.
   - `skipped_no_data` — блоки с пустым выводом.
4. Отправляет графики **группами по 10** (Telegram media group limit) через `send_media_group(media=[InputMediaPhoto(...)])`.
5. В режиме `selected` если есть пропущенные блоки — шлёт сообщение «По части выбранных блоков пока недостаточно данных: ...» (с лейблами).
6. В finally — удаляет временные PNG.

## DISCLAIMER_FOOTER

К текстовому summary всегда добавляется:

```
Это наблюдение, не диагноз. При необходимости данные можно обсудить со специалистом.
```

## Настройка блоков (selected mode)

`stats:settings` → клавиатура с чекбоксами по всем блокам каталога. Тап → toggle через `statistics_settings_service.toggle_block`.

Сервис: [`bot/services/statistics_settings_service.py`](../bot/services/statistics_settings_service.py).

### Семантика хранения

```python
# Если в БД нет записи для блока:
#   - default-блок → считается ВКЛЮЧЕННЫМ
#   - не-default → считается ВЫКЛЮЧЕННЫМ
# Если есть запись — берём is_enabled явно.
```

`reset_to_default(user_id)` — DELETE всех записей пользователя. Поведение возвращается к дефолту автоматически.

## Короткие коды для callback_data

Длинные коды блоков мапятся в короткие через `BLOCK_CALLBACK_SHORTS`:

```python
"thought_speech_speed":  "tss"
"self_esteem_guilt":     "seg"
"somatic_anxiety":       "som"
"obsessive_thoughts":    "obs"
"aggression_conflicts":  "agc"
"physical_activity":     "pha"
"social_activity":       "soc"
"stress_events":         "str"
"menstrual_cycle":       "men"
"suicidal_thoughts":     "sui"
"panic_attacks":         "pan"
"risky_behavior":        "rsk"
"custom_questions":      "cst"
"sleep_problems":        "slp"
"mood_energy":           "mne"
"mood_spread":           "msp"
```

`block_to_short(code)` / `short_to_block(short)` — utility-функции. callback вида `stats:tgl:tss`.

## Текстовое саммари (build_summary)

Реализация: [`bot/services/stats_service.py::build_summary`](../bot/services/stats_service.py).

Содержит:
- Количество записей.
- Среднее, мин, макс настроение.
- Средняя тревога и энергия.
- Средняя раздражительность и импульсивность (если есть данные).
- Дни с настроением 8+ (счётчик по локальным датам, по максимуму mood в дне).
- Дни с тревогой 4+.
- Дни со сном < 5 часов.
- Дни с отметкой «мало сна, но чувствую себя отлично».
- Распределение по типам приёма лекарств.

Фильтрует `sleep_type='additional'` из шкальной выборки (там нули, не должны искажать средние).

## Графики (plotting)

Реализация: [`bot/utils/plotting.py`](../bot/utils/plotting.py). Backend matplotlib Agg (без GUI). Все функции возвращают путь к временному PNG (или None).

Ключевые функции:

- `plot_mood(entries, tz)` — линейный график с цветовыми зонами и легендой.
- `plot_anxiety/energy/irritability/impulsivity` — общая `_line_chart`.
- `plot_mood_energy` — две Y-оси.
- `plot_mood_spread` — бары `max(mood) - min(mood)` за день, только дни с ≥2 записями.
- `plot_sleep` — пара бар-чартов (длительность в часах / качество 1-5) по дням.
- `plot_sleep_problems` — горизонтальный бар-чарт счётчиков по 5 проблемам.
- `plot_optional_question(answers, code, tz, min_points=2)` — универсальный линейный график для EAV-ответов с подписями опций по Y.
- `plot_custom_question(answers, qid, qtext, qtype, tz, min_points=2)` — для custom-вопросов; text не графитим.

Все функции:
- Конвертируют `created_at` в локальную TZ пользователя через `_local_dt`.
- Фильтруют `sleep_type='additional'` (если нужно).
- Возвращают None при недостатке данных (`min_points=2` — нужны минимум 2 точки).
- Сохраняют в `tempfile.NamedTemporaryFile(suffix=".png", delete=False)`.

Handler чистит файлы после отправки в `finally`.

## Связанные документы

- [09-export.md](09-export.md) — Excel-экспорт.
- [13-database-schema.md](13-database-schema.md) — таблицы и индексы (`user_statistics_blocks`).
