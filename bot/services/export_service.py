import logging
import tempfile
from collections import Counter
from datetime import datetime, timezone
from statistics import median
from typing import Sequence

import pandas as pd

from bot.constants import (
    MEDICATION_LABELS,
    SLEEP_DURATION_LABELS,
    SLEEP_DURATION_TO_HOURS,
    SLEEP_QUALITY_LABELS,
)
from bot.models import SurveyEntry
from bot.utils.time_utils import get_tz

logger = logging.getLogger(__name__)


def _yes_no(v: bool) -> str:
    return "да" if v else "нет"


def _source_label(s: str) -> str:
    return {
        "scheduled": "плановый",
        "manual": "ручной",
        "reminder": "после напоминания",
    }.get(s, s)


def _to_local(dt: datetime, tz) -> datetime:
    """Приводит created_at из БД к локальной TZ пользователя и убирает tzinfo
    (Excel/openpyxl плохо работает с timezone-aware datetime)."""
    if dt.tzinfo is None:
        # PostgreSQL c timezone=True всегда отдаёт aware, но на всякий случай.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).replace(tzinfo=None)


def build_excel(
    entries: Sequence[SurveyEntry],
    period_label: str,
    user_timezone: str,
    optional_answers: list[dict] | None = None,
    custom_answers: list[dict] | None = None,
    custom_questions_map: dict[int, str] | None = None,
) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    f.close()

    tz = get_tz(user_timezone)
    # Кэшируем локальное время каждой записи: оно нужно и в строках, и в группировках.
    local_dt: dict[int, datetime] = {id(e): _to_local(e.created_at, tz) for e in entries}

    data_rows = [
        {
            "Дата и время": local_dt[id(e)],
            "Тип записи": {
                "main": "опрос",
                "none": "опрос (без сна)",
                "additional": "доп. сон",
            }.get(e.sleep_type, e.sleep_type),
            "Настроение": e.mood if e.sleep_type != "additional" else "",
            "Тревога": e.anxiety if e.sleep_type != "additional" else "",
            "Энергия": e.energy if e.sleep_type != "additional" else "",
            # irritability/impulsivity теперь опциональные — для новых записей
            # значения хранятся в Survey_answers и попадают на лист
            # "Опциональные ответы". В колонке остаётся пустая ячейка.
            "Раздражительность": e.irritability if e.irritability is not None else "",
            "Импульсивность": e.impulsivity if e.impulsivity is not None else "",
            "Длительность сна": SLEEP_DURATION_LABELS.get(
                e.sleep_duration_category, e.sleep_duration_category
            ),
            "Качество сна": SLEEP_QUALITY_LABELS.get(
                e.sleep_quality, e.sleep_quality
            ),
            "Долго не мог(ла) уснуть": _yes_no(e.hard_to_fall_asleep),
            "Раннее пробуждение": _yes_no(e.early_wakeup),
            "Частые пробуждения": _yes_no(e.frequent_wakeups),
            "Мало сна, но чувствую себя отлично": _yes_no(e.little_sleep_but_feel_good),
            "Много сна, но не восстановился/восстановилась": _yes_no(
                e.long_sleep_not_restored
            ),
            "Прием лекарств": "" if not e.medication_filled else MEDICATION_LABELS.get(
                e.medication_taken, e.medication_taken
            ),
            "Комментарий": e.comment or "",
            "Источник записи": _source_label(e.source),
        }
        for e in entries
    ]
    df_data = pd.DataFrame(data_rows)

    # Сводка не должна учитывать дополнительный сон (там нули в шкалах) и
    # пропуски сна — для шкал берём только полноценные записи опроса.
    scale_entries = [e for e in entries if e.sleep_type != "additional"]
    sleep_entries = [
        e for e in entries
        if e.sleep_type in ("main", "additional")
        and e.sleep_duration_category != "skipped"
    ]
    med_entries = [e for e in entries if e.medication_filled]

    if scale_entries:
        moods = [e.mood for e in scale_entries]
        by_day: dict = {}
        for e in scale_entries:
            by_day.setdefault(local_dt[id(e)].date(), []).append(e)
        sleep_by_day: dict = {}
        for e in sleep_entries:
            sleep_by_day.setdefault(local_dt[id(e)].date(), []).append(e)
        med_by_day: dict = {}
        for e in med_entries:
            med_by_day.setdefault(local_dt[id(e)].date(), []).append(e)

        days_high_mood = sum(
            1 for vs in by_day.values() if max(x.mood for x in vs) >= 8
        )
        days_high_anx = sum(
            1 for vs in by_day.values() if max(x.anxiety for x in vs) >= 4
        )
        days_low_sleep = sum(
            1
            for vs in sleep_by_day.values()
            if max(SLEEP_DURATION_TO_HOURS.get(x.sleep_duration_category, 0) for x in vs)
            < 5
        )
        days_no_med = sum(
            1 for vs in med_by_day.values() if all(x.medication_taken == "no" for x in vs)
        )
        # irritability/impulsivity теперь опциональные — учитываем только заполненные
        irrit_vals = [e.irritability for e in scale_entries if e.irritability is not None]
        impuls_vals = [e.impulsivity for e in scale_entries if e.impulsivity is not None]

        summary = {
            "Период": period_label,
            "Количество записей": len(entries),
            "Среднее настроение": round(sum(moods) / len(moods), 2),
            "Минимальное настроение": min(moods),
            "Максимальное настроение": max(moods),
            "Средняя тревога": round(
                sum(e.anxiety for e in scale_entries) / len(scale_entries), 2
            ),
            "Средняя энергия": round(
                sum(e.energy for e in scale_entries) / len(scale_entries), 2
            ),
        }
        if irrit_vals:
            summary["Средняя раздражительность"] = round(sum(irrit_vals) / len(irrit_vals), 2)
        if impuls_vals:
            summary["Средняя импульсивность"] = round(sum(impuls_vals) / len(impuls_vals), 2)
        summary.update({
            "Дней с настроением 8+": days_high_mood,
            "Дней с тревогой 4+": days_high_anx,
            "Дней со сном меньше 5 часов": days_low_sleep,
            "Дней без приема лекарств": days_no_med,
        })
    else:
        summary = {"Период": period_label, "Количество записей": 0}
    df_summary = pd.DataFrame([summary]).T.reset_index()
    df_summary.columns = ["Показатель", "Значение"]

    daily_rows = []
    by_day_full: dict = {}
    for e in entries:
        by_day_full.setdefault(local_dt[id(e)].date(), []).append(e)
    for day in sorted(by_day_full.keys()):
        items = by_day_full[day]
        moods = [x.mood for x in items]
        sleep_hours = max(
            SLEEP_DURATION_TO_HOURS.get(x.sleep_duration_category, 0) for x in items
        )
        med_counter = Counter(x.medication_taken for x in items)
        med_summary = ", ".join(
            f"{MEDICATION_LABELS.get(k, k)}: {v}" for k, v in med_counter.items()
        )
        comments = [x.comment for x in items if x.comment]
        # На дневных графиках точки = медиана за день. Здесь, в Excel, цифры
        # должны совпадать с графиками, поэтому переходим на медиану. Сырые
        # значения за каждую запись по-прежнему доступны на листе «Данные».
        daily_rows.append(
            {
                "Дата": day,
                "Количество записей": len(items),
                "Медиана настроения": round(float(median(moods)), 2),
                "Минимальное настроение": min(moods),
                "Максимальное настроение": max(moods),
                "Разброс настроения": max(moods) - min(moods),
                "Медиана тревоги": round(
                    float(median(x.anxiety for x in items)), 2
                ),
                "Медиана энергии": round(
                    float(median(x.energy for x in items)), 2
                ),
                "Сон (часов, примерно)": sleep_hours,
                "Прием лекарств": med_summary,
                "Комментарии за день": " | ".join(comments),
            }
        )
    df_daily = pd.DataFrame(daily_rows)

    # Лист "Опциональные ответы": long-format со всеми ответами на дополнительные
    # вопросы. Пустой DataFrame не пишется как лист, если строк нет — не страшно.
    df_optional = None
    if optional_answers:
        # Импорт здесь, чтобы не создавать циклов и не подгружать константы зря.
        from bot.constants_questions import QUESTION_DEFINITIONS

        opt_rows = []
        for row in optional_answers:
            code = row["question_code"]
            title = QUESTION_DEFINITIONS.get(code, {}).get("question_text", code)
            opt_rows.append({
                "Дата и время": _to_local(row["created_at"], tz),
                "Вопрос (код)": code,
                "Вопрос": title.rstrip("?"),
                "Ответ": row["answer_value"],
                "Ответ (число 0-4)": row["answer_numeric"],
            })
        df_optional = pd.DataFrame(opt_rows)

    # Лист "Свои вопросы": long-format custom-ответов.
    df_custom = None
    if custom_answers:
        q_map = custom_questions_map or {}
        cust_rows = []
        for row in custom_answers:
            qid = row["custom_question_id"]
            qtext = q_map.get(qid, f"(вопрос #{qid})").rstrip("?")
            atype = row["answer_type"]
            # Единый столбец "Ответ" — приводим к строке для удобства.
            if atype == "scale_0_5":
                ans_value = row.get("answer_numeric")
                ans_display = "" if ans_value is None else str(int(ans_value))
            elif atype == "boolean":
                b = row.get("answer_bool")
                ans_display = "" if b is None else ("Да" if b else "Нет")
            else:  # text
                ans_display = row.get("answer_text") or ""
            cust_rows.append({
                "Дата и время": _to_local(row["created_at"], tz),
                "Вопрос": qtext,
                "Формат": {
                    "scale_0_5": "Шкала 0–5",
                    "boolean": "Да / Нет",
                    "text": "Текст",
                }.get(atype, atype),
                "Ответ": ans_display,
                "Числовое (0-5)": row.get("answer_numeric"),
            })
        df_custom = pd.DataFrame(cust_rows)

    try:
        with pd.ExcelWriter(f.name, engine="openpyxl") as writer:
            df_data.to_excel(writer, sheet_name="Данные", index=False)
            df_summary.to_excel(writer, sheet_name="Сводка", index=False)
            df_daily.to_excel(writer, sheet_name="Дневная статистика", index=False)
            if df_optional is not None and not df_optional.empty:
                df_optional.to_excel(
                    writer, sheet_name="Опциональные ответы", index=False
                )
            if df_custom is not None and not df_custom.empty:
                df_custom.to_excel(
                    writer, sheet_name="Свои вопросы", index=False
                )
    except Exception:
        logger.exception("Ошибка генерации Excel")
        raise

    return f.name
