# 07. Пользовательские (custom) вопросы

Пользователь может создать свои вопросы, которые автоматически попадут в ежедневный опрос. Реализация: [`bot/handlers/custom_questions.py`](../bot/handlers/custom_questions.py) + [`bot/services/custom_question_service.py`](../bot/services/custom_question_service.py).

## Модели

### CustomQuestion

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BigInteger PK | |
| `user_id` | FK users.id (CASCADE) | |
| `question_text` | Text | 1..150 символов (CHECK-констрейнт) |
| `answer_type` | String(32) | `scale_0_5` / `boolean` / `text` (CHECK) |
| `is_enabled` | Boolean | Задавать ли в опросе |
| `is_active` | Boolean | Soft-delete (архивация) |
| `sort_order` | Integer | |
| `created_at`, `updated_at` | TZ-aware |

**Уникальный частичный индекс**: `(user_id, lower(trim(question_text))) WHERE is_active=true` — нельзя иметь два активных вопроса с одинаковым (case-insensitive) текстом.

### CustomQuestionAnswer

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BigInteger PK | |
| `entry_id` | FK survey_entries.id (CASCADE) | |
| `custom_question_id` | FK custom_questions.id (RESTRICT) | |
| `answer_type` | String(32) | Дублирует тип для удобства аналитики |
| `answer_text` | Text? | Для `text` |
| `answer_numeric` | Numeric? | Для `scale_0_5` |
| `answer_bool` | Boolean? | Для `boolean` |

**Уникальный индекс** `(entry_id, custom_question_id)` — защита от дублей при двойном нажатии.

## Лимиты

- **Активных на пользователя**: 10 (`MAX_ACTIVE_PER_USER = 10`).
- **Длина текста вопроса**: 1..150 символов (`MAX_TEXT_LEN = 150`).
- **Длина текстового ответа**: 1..1000 символов (`MAX_TEXT_ANSWER_LEN = 1000`).

## Типы ответа

| Код | UI | Хранение |
|-----|----|----------|
| `scale_0_5` | «Шкала 0–5», кнопки 0..5 (callback `cqa:scale:N`) | `answer_numeric` (Decimal 0..5) |
| `boolean` | «Да / Нет», 2 кнопки (callback `cqa:bool:0|1`) | `answer_bool` |
| `text` | Свободный текстовый ввод (≤1000 симв) | `answer_text` |

## Защита от чужого id

`custom_question_service.get_owned(session, user_id, question_id)` — возвращает вопрос только если он принадлежит пользователю. Если попытка обратиться к чужому id обнаружена — логируется warning. Все мутации (`toggle`, `rename`, `archive`) проходят через `get_owned`.

## FSM создания

`build_cq_create_conversation()`, entry — callback `cq:add`.

```
ASK_TEXT  → пользователь вводит текст
            (валидация: непустой, ≤150 симв, не дубль среди активных)
ASK_TYPE  → выбор типа (cq:type:scale_0_5|boolean|text) или cq:cancel
ASK_CONFIRM → подтвердить (cq:confirm), изменить текст (cq:edit_text),
              изменить формат (cq:edit_type), отмена (cq:cancel)
END        → сохранение, сообщение «Вопрос добавлен и включен»
```

Перед стартом проверяется `count_active(user) >= MAX_ACTIVE_PER_USER` — если уже 10, отказ.

## FSM переименования

`build_cq_rename_conversation()`, entry — callback `cq:rename:<id>`.

```
RENAME_AWAIT_TEXT → новый текст
                    валидация и проверка дубля (исключая собственный id)
END                → UPDATE question_text + показ view-экрана
```

## Прочие операции через router

`build_cq_router()` (callback `cq:(list|view:N|toggle:N|archive:N|archive_ok:N)`):

- `cq:list` — открыть список «📝 Мои вопросы».
- `cq:view:N` — показать view-экран одного вопроса.
- `cq:toggle:N` — включить/выключить в опросе. (Активен остаётся в каталоге, просто `is_enabled` меняется.)
- `cq:archive:N` — показывает подтверждение «Архивировать?».
- `cq:archive_ok:N` — `archive(...)`: `is_active=False`, `is_enabled=False`. Старые ответы НЕ удаляются (хранятся для истории).

## View-экран одного вопроса

```
📝 Свой вопрос

Вопрос:
«<question_text>»

Формат ответа:
<Шкала 0–5 | Да / Нет | Текст>

Статус:
<Включен в ежедневный опрос | Выключен>
```

Кнопки:
- ⬜ Выключить / ✅ Включить (`cq:toggle:N`)
- ✏️ Переименовать (`cq:rename:N`)
- 🗑 Архивировать (`cq:archive:N`)
- ⬅️ К моим вопросам (`cq:list`)

## Где задаются в опросе

В `_init_survey` загружается список `enabled` (где `is_active=True AND is_enabled=True`):

```python
custom_qs = custom_question_service.get_enabled(session, user.id)
```

В FSM опроса состояние `CUSTOM_Q` циклится по `survey["custom_questions"]`. После окончания опциональных шагов → custom-вопросы → комментарий.

Реализация шага: `survey.py::custom_question_step`. Принимает либо callback (`cqa:scale:N` / `cqa:bool:0|1`), либо текстовое сообщение (для `text`-типа).

## Сохранение ответа

`custom_question_service.save_answer(session, entry_id, custom_question_id, answer_type, value)`:

1. Валидирует `value` по типу.
2. Заполняет нужное поле (`answer_numeric` / `answer_bool` / `answer_text`).
3. INSERT (с защитой от дубля через unique index).

В `_finish_survey` ошибка одного сохранения логируется, но не валит всю запись:

```python
for ans in custom_answers:
    try:
        custom_question_service.save_answer(...)
    except Exception:
        logger.exception("Не удалось сохранить ответ на custom_question id=%s", ...)
```

## Графики в статистике

Блок `custom_questions` рендерится через `plot_custom_question(rows, qid, qtext, qtype, user_tz)`:

- `scale_0_5` → линейный график со шкалой 0..5.
- `boolean` → бар-чарт «Да / Нет» за период.
- `text` → не строится (возвращает None).

Минимум для отображения — 2 точки данных (иначе график пропускается).

Подробно: [08-statistics.md](08-statistics.md).

## Экспорт

В Excel:
- Лист «Свои вопросы» (только если есть данные) с колонками: Дата и время, Вопрос, Формат, Ответ, Числовое (0-5).

Подробно: [09-export.md](09-export.md).

## История миграции

- **0006_custom_questions**: создание таблиц, изначально `scale_0_10`.
- **0007_rename_scale_type**: переименование `scale_0_10` → `scale_0_5` + обрезка старых ответов >5 до 5 (консервативно, чтобы аналитика не давала бессмысленные средние).

Подробно: [13-database-schema.md](13-database-schema.md).
