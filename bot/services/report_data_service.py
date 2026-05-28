"""Сбор данных для PDF-отчёта за период.

ReportData — dataclass с уже агрегированными значениями. Без хранения сырых
записей, чтобы PDF-builder не нагружался лишним.

Все даты в TZ пользователя. Группировка по local_date пользователя, не по
created_at UTC. Дополнительный сон (sleep_type='additional') исключаем
из шкал (там нули), но используем для отчёта по сну.
"""
from __future__ import annotations

import logging
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from bot.constants import MEDICATION_LABELS, SLEEP_DURATION_TO_HOURS
from bot.constants_questions import QUESTION_DEFINITIONS
from bot.models import (
    CustomQuestion,
    CustomQuestionAnswer,
    SurveyAnswer,
    SurveyEntry,
    User,
)
from bot.services import menstrual_cycle_service as mcs
from bot.utils.time_utils import get_tz

logger = logging.getLogger(__name__)


# ---------- результат ----------

@dataclass
class DailyScales:
    """Дневные медианы для базовых шкал."""
    by_date: dict[date, float] = field(default_factory=dict)
    # Min/max берутся из тех же ежедневных медиан (а не из сырых точек) —
    # это устойчивее к одному "плохому опросу".
    min_value: float | None = None
    max_value: float | None = None
    median_value: float | None = None
    sample_days: int = 0


@dataclass
class SleepStats:
    by_date_hours: dict[date, float] = field(default_factory=dict)
    by_date_quality: dict[date, int] = field(default_factory=dict)
    median_hours: float | None = None
    min_hours: float | None = None
    max_hours: float | None = None
    days_filled: int = 0
    additional_sleeps: int = 0  # кол-во доп. снов за период


@dataclass
class MedicationStats:
    by_value_count: Counter = field(default_factory=Counter)
    days_with_intake: int = 0  # 'yes' + 'partial'
    days_filled: int = 0
    percent_taken: float | None = None


@dataclass
class OptionalStats:
    code: str
    title: str
    answer_type_hint: str  # 'scale' | 'choice' | 'boolean' | 'text'
    by_date_median: dict[date, float] = field(default_factory=dict)
    choice_counter: Counter = field(default_factory=Counter)
    text_answers: list[tuple[date, str]] = field(default_factory=list)
    bool_yes_days: int = 0
    bool_days: int = 0
    median_value: float | None = None
    min_value: float | None = None
    max_value: float | None = None


@dataclass
class CustomStats:
    custom_question_id: int
    title: str
    answer_type: str  # 'scale_0_5' | 'boolean' | 'text'
    is_archived: bool
    by_date_median: dict[date, float] = field(default_factory=dict)
    bool_yes_days: int = 0
    bool_days: int = 0
    text_answers: list[tuple[date, str]] = field(default_factory=list)
    median_value: float | None = None


@dataclass
class CommentRow:
    log_date: date
    text: str


@dataclass
class DailyAggregate:
    log_date: date
    mood: float | None = None
    anxiety: float | None = None
    energy: float | None = None
    sleep_hours: float | None = None
    has_comment: bool = False
    comment_excerpt: str | None = None


@dataclass
class ReportData:
    user_id: int
    telegram_user_id: int
    timezone: str
    date_from: date
    date_to: date
    generated_at_local: datetime

    days_with_data: int = 0
    total_surveys: int = 0
    surveys_per_day: float | None = None

    mood: DailyScales = field(default_factory=DailyScales)
    anxiety: DailyScales = field(default_factory=DailyScales)
    energy: DailyScales = field(default_factory=DailyScales)
    sleep: SleepStats = field(default_factory=SleepStats)
    medication: MedicationStats = field(default_factory=MedicationStats)

    optionals: list[OptionalStats] = field(default_factory=list)
    customs: list[CustomStats] = field(default_factory=list)
    comments: list[CommentRow] = field(default_factory=list)
    daily_table: list[DailyAggregate] = field(default_factory=list)

    cycle_summary: dict[str, Any] | None = None

    @property
    def has_meaningful_data(self) -> bool:
        return self.total_surveys > 0


# ---------- константы ----------

# Подмножество EAV-вопросов, по которым строим разделы. По умолчанию берём
# QUESTION_DEFINITIONS, кроме тех, что вынесены в отдельные домены / уже есть
# в базовых блоках.
_EXCLUDED_OPTIONAL_CODES = {
    "menstrual_cycle",   # отдельный домен
    "medications",       # отдельный блок (medication_taken в SurveyEntry)
    "comment",           # отдельный блок
}

# Подсказка по типу ответа, основанная на вариантах: всё, что имеет ровно 2
# опции с "Нет"/"Да"-подобным смыслом, считаем boolean. Прочее со списком
# опций — choice. Если у нас числовой ответ (answer_numeric не NULL и в
# QUESTION_DEFINITIONS — есть варианты) — это шкала. Здесь упрощённо:
# всё, что не помечено явно, считаем scale (0..N-1).
_BOOLEAN_LIKE_CODES: set[str] = set()  # сейчас явных boolean optional нет
_TEXT_CODES: set[str] = set()          # сейчас явных text optional нет
_CHOICE_CODES: set[str] = {
    # Это «не шкалы», у которых варианты не упорядочены численно.
    "medications",  # на всякий — но он в EXCLUDED
}


def _hint_for(code: str) -> str:
    if code in _BOOLEAN_LIKE_CODES:
        return "boolean"
    if code in _TEXT_CODES:
        return "text"
    if code in _CHOICE_CODES:
        return "choice"
    return "scale"


# ---------- утилиты ----------

def _local_date_of(dt: datetime, tz_name: str) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_tz(tz_name)).date()


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _summarize_scales(daily: DailyScales) -> None:
    """Заполняет min/max/median полей DailyScales по уже собранным by_date."""
    if not daily.by_date:
        return
    values = list(daily.by_date.values())
    daily.min_value = float(min(values))
    daily.max_value = float(max(values))
    daily.median_value = _median(values)
    daily.sample_days = len(values)


# ---------- основной сбор ----------

def collect_report_data(
    session: Session,
    user: User,
    date_from: date,
    date_to: date,
) -> ReportData:
    """Собирает ReportData за период [date_from, date_to] включительно.

    Запрос делается по entries.created_at в UTC-диапазоне, отображённом из TZ
    юзера: [start_of(date_from), start_of(date_to+1)). Группировка же — по
    local_date пользователя (через to_local_date в Python).
    """
    # Перевод диапазона дат в UTC-окно для запроса.
    tz_zi = ZoneInfo(user.timezone) if user.timezone else ZoneInfo("UTC")
    local_start_dt = datetime.combine(date_from, time.min, tzinfo=tz_zi)
    local_end_dt_excl = datetime.combine(
        date_to + timedelta(days=1), time.min, tzinfo=tz_zi
    )
    utc_start = local_start_dt.astimezone(timezone.utc)
    utc_end_excl = local_end_dt_excl.astimezone(timezone.utc)

    entries: list[SurveyEntry] = list(
        session.scalars(
            select(SurveyEntry)
            .where(
                and_(
                    SurveyEntry.user_id == user.id,
                    SurveyEntry.created_at >= utc_start,
                    SurveyEntry.created_at < utc_end_excl,
                )
            )
            .order_by(SurveyEntry.created_at.asc())
        )
    )

    data = ReportData(
        user_id=user.id,
        telegram_user_id=user.telegram_user_id,
        timezone=user.timezone,
        date_from=date_from,
        date_to=date_to,
        generated_at_local=datetime.now(tz_zi),
    )

    if not entries:
        # Цикл показываем даже без entries (отдельный домен).
        data.cycle_summary = _collect_cycle_summary(session, user, date_to)
        return data

    # ---------- группируем ----------
    by_day_mood: dict[date, list[int]] = defaultdict(list)
    by_day_anx: dict[date, list[int]] = defaultdict(list)
    by_day_energy: dict[date, list[int]] = defaultdict(list)
    by_day_sleep_hours: dict[date, list[float]] = defaultdict(list)
    by_day_sleep_quality: dict[date, list[int]] = defaultdict(list)
    additional_sleeps = 0
    med_counter: Counter = Counter()
    med_days_filled = 0
    med_days_intake = 0
    comments_acc: list[tuple[date, str]] = []
    daily_table_map: dict[date, DailyAggregate] = {}
    main_entries_ids: list[int] = []

    for e in entries:
        d = _local_date_of(e.created_at, user.timezone)

        if e.sleep_type == "additional":
            additional_sleeps += 1
        else:
            # Шкалы считаем только по основным опросам.
            by_day_mood[d].append(int(e.mood))
            by_day_anx[d].append(int(e.anxiety))
            by_day_energy[d].append(int(e.energy))
            main_entries_ids.append(e.id)

            # лекарства: одна запись в день максимум (бизнес-правило)
            if e.medication_filled:
                med_days_filled += 1
                med_counter[e.medication_taken] += 1
                if e.medication_taken in ("yes", "partial"):
                    med_days_intake += 1

            # Сон: только если sleep_type == 'main' с реальным заполнением.
            if (
                e.sleep_type == "main"
                and e.sleep_duration_category != "skipped"
            ):
                by_day_sleep_hours[d].append(
                    SLEEP_DURATION_TO_HOURS.get(e.sleep_duration_category, 0)
                )
                from bot.constants import SLEEP_QUALITY_TO_SCORE
                q = SLEEP_QUALITY_TO_SCORE.get(e.sleep_quality)
                if q:
                    by_day_sleep_quality[d].append(int(q))

            # Комментарии
            if e.comment and e.comment.strip():
                comments_acc.append((d, e.comment.strip()))

    data.total_surveys = sum(1 for e in entries if e.sleep_type != "additional")
    data.days_with_data = len(by_day_mood)
    if data.days_with_data:
        data.surveys_per_day = round(
            data.total_surveys / data.days_with_data, 2
        )

    # ---------- базовые шкалы ----------
    for daily, source in (
        (data.mood, by_day_mood),
        (data.anxiety, by_day_anx),
        (data.energy, by_day_energy),
    ):
        for d, vs in source.items():
            m = _median([float(v) for v in vs])
            if m is not None:
                daily.by_date[d] = m
        _summarize_scales(daily)

    # ---------- сон ----------
    for d, vs in by_day_sleep_hours.items():
        data.sleep.by_date_hours[d] = float(_median(vs) or 0)
    for d, vs in by_day_sleep_quality.items():
        m = _median([float(v) for v in vs])
        if m is not None:
            data.sleep.by_date_quality[d] = int(round(m))
    if data.sleep.by_date_hours:
        hrs = list(data.sleep.by_date_hours.values())
        data.sleep.median_hours = _median(hrs)
        data.sleep.min_hours = min(hrs)
        data.sleep.max_hours = max(hrs)
        data.sleep.days_filled = len(hrs)
    data.sleep.additional_sleeps = additional_sleeps

    # ---------- лекарства ----------
    data.medication.by_value_count = med_counter
    data.medication.days_filled = med_days_filled
    data.medication.days_with_intake = med_days_intake
    if med_days_filled:
        data.medication.percent_taken = round(
            100.0 * med_days_intake / med_days_filled, 1
        )

    # ---------- optional answers (EAV) ----------
    if main_entries_ids:
        opt_rows = list(
            session.scalars(
                select(SurveyAnswer).where(
                    SurveyAnswer.entry_id.in_(main_entries_ids)
                )
            )
        )
        # Чтобы перевести entry_id → local_date, переиспользуем словарик.
        entry_to_date: dict[int, date] = {
            e.id: _local_date_of(e.created_at, user.timezone)
            for e in entries if e.sleep_type != "additional"
        }
        by_code_day_vals: dict[str, dict[date, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        by_code_choices: dict[str, Counter] = defaultdict(Counter)
        by_code_texts: dict[str, list[tuple[date, str]]] = defaultdict(list)
        for a in opt_rows:
            if a.question_code in _EXCLUDED_OPTIONAL_CODES:
                continue
            d = entry_to_date.get(a.entry_id)
            if d is None:
                continue
            if a.answer_numeric is not None:
                by_code_day_vals[a.question_code][d].append(float(a.answer_numeric))
            if a.answer_value:
                by_code_choices[a.question_code][a.answer_value] += 1
                # Текст для текстовых вопросов (если такие появятся) — храним
                # отдельно. Сейчас всё через choice.
                by_code_texts[a.question_code].append((d, a.answer_value))

        all_codes = set(by_code_day_vals.keys()) | set(by_code_choices.keys())
        for code in sorted(all_codes):
            defn = QUESTION_DEFINITIONS.get(code, {})
            title = defn.get("question_text", code)
            stats = OptionalStats(
                code=code,
                title=title,
                answer_type_hint=_hint_for(code),
            )
            day_vals = by_code_day_vals.get(code, {})
            for d, vs in day_vals.items():
                m = _median(vs)
                if m is not None:
                    stats.by_date_median[d] = m
            if stats.by_date_median:
                vals = list(stats.by_date_median.values())
                stats.median_value = _median(vals)
                stats.min_value = float(min(vals))
                stats.max_value = float(max(vals))
            stats.choice_counter = by_code_choices.get(code, Counter())
            data.optionals.append(stats)

    # ---------- custom questions ----------
    if main_entries_ids:
        cq_rows = list(
            session.scalars(
                select(CustomQuestionAnswer).where(
                    CustomQuestionAnswer.entry_id.in_(main_entries_ids)
                )
            )
        )
        questions_map = {
            q.id: q for q in session.scalars(
                select(CustomQuestion).where(CustomQuestion.user_id == user.id)
            )
        }
        by_qid_day: dict[int, dict[date, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        by_qid_bool: dict[int, list[bool]] = defaultdict(list)
        by_qid_text: dict[int, list[tuple[date, str]]] = defaultdict(list)
        entry_to_date_full: dict[int, date] = {
            e.id: _local_date_of(e.created_at, user.timezone)
            for e in entries
        }
        for a in cq_rows:
            d = entry_to_date_full.get(a.entry_id)
            if d is None:
                continue
            if a.answer_type == "scale_0_5" and a.answer_numeric is not None:
                by_qid_day[a.custom_question_id][d].append(float(a.answer_numeric))
            elif a.answer_type == "boolean" and a.answer_bool is not None:
                by_qid_bool[a.custom_question_id].append(bool(a.answer_bool))
            elif a.answer_type == "text" and a.answer_text:
                by_qid_text[a.custom_question_id].append((d, a.answer_text))

        all_qids = (
            set(by_qid_day.keys())
            | set(by_qid_bool.keys())
            | set(by_qid_text.keys())
        )
        for qid in sorted(all_qids):
            q = questions_map.get(qid)
            if q is None:
                # ответы на чужой вопрос — не должно произойти, но защитимся
                logger.warning(
                    "report custom answer id=%s without parent question", qid
                )
                continue
            stats = CustomStats(
                custom_question_id=qid,
                title=q.question_text,
                answer_type=q.answer_type,
                is_archived=not q.is_active,
            )
            if qid in by_qid_day:
                for d, vs in by_qid_day[qid].items():
                    m = _median(vs)
                    if m is not None:
                        stats.by_date_median[d] = m
                if stats.by_date_median:
                    stats.median_value = _median(
                        list(stats.by_date_median.values())
                    )
            if qid in by_qid_bool:
                vals = by_qid_bool[qid]
                stats.bool_days = len(vals)
                stats.bool_yes_days = sum(1 for v in vals if v)
            if qid in by_qid_text:
                # Ограничим списком 20 последних.
                texts = sorted(by_qid_text[qid], key=lambda x: x[0], reverse=True)
                stats.text_answers = texts[:20]
            data.customs.append(stats)

    # ---------- комментарии ----------
    comments_sorted = sorted(comments_acc, key=lambda x: x[0])
    # 50 последних, чтобы PDF не раздулся.
    if len(comments_sorted) > 50:
        comments_sorted = comments_sorted[-50:]
    data.comments = [CommentRow(log_date=d, text=t) for d, t in comments_sorted]

    # ---------- daily table ----------
    all_days = sorted(set(by_day_mood.keys()) | set(by_day_sleep_hours.keys()))
    comment_by_day: dict[date, str] = {}
    for d, t in comments_acc:
        # Берём первый непустой комментарий в день
        comment_by_day.setdefault(d, t)
    for d in all_days:
        row = DailyAggregate(log_date=d)
        if d in data.mood.by_date:
            row.mood = data.mood.by_date[d]
        if d in data.anxiety.by_date:
            row.anxiety = data.anxiety.by_date[d]
        if d in data.energy.by_date:
            row.energy = data.energy.by_date[d]
        if d in data.sleep.by_date_hours:
            row.sleep_hours = data.sleep.by_date_hours[d]
        if d in comment_by_day:
            row.has_comment = True
            t = comment_by_day[d]
            row.comment_excerpt = t if len(t) <= 60 else t[:57] + "…"
        data.daily_table.append(row)

    # ---------- cycle ----------
    data.cycle_summary = _collect_cycle_summary(session, user, date_to)

    return data


def _collect_cycle_summary(
    session: Session, user: User, local_today: date
) -> dict[str, Any] | None:
    """Возвращает summary цикла, если функция включена ИЛИ есть данные."""
    try:
        summary = mcs.get_cycle_summary(session, user.id, local_today)
    except Exception:
        logger.exception("Не удалось получить summary цикла user_id=%s", user.id)
        return None
    if not summary.get("is_enabled") and summary.get("latest_period_start") is None:
        return None
    return summary
