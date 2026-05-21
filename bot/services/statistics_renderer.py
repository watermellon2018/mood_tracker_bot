"""Диспетчер рендереров блоков статистики.

Идея: render_*(ctx) -> list[str] (пути PNG) или ["__summary__"] для
текстового блока. handler сам решит, как отправить.

ctx — dict с уже подготовленными данными за период:
  - entries: list[SurveyEntry]
  - user_tz: str
  - days: int | None
  - answers_rows: list[dict]   (EAV system optional)
  - custom_rows: list[dict]
  - custom_q_snapshot: dict[int, tuple[text, atype, is_active]]

Если для блока нет данных — рендер возвращает []. handler собирает
skipped-блоки в один общий summary.
"""
import logging
from typing import Any, Callable

from bot.utils import plotting

logger = logging.getLogger(__name__)

# Маркер текстового summary (не PNG).
SUMMARY_SENTINEL = "__summary__"


# --- адаптеры. Каждый рендер унифицирован: ctx -> list[str].

def _r_summary(ctx: dict) -> list[str]:
    return [SUMMARY_SENTINEL]


def _r_mood(ctx: dict) -> list[str]:
    p = plotting.plot_mood(ctx["entries"], ctx["user_tz"])
    return [p] if p else []


def _r_anxiety(ctx: dict) -> list[str]:
    p = plotting.plot_anxiety(ctx["entries"], ctx["user_tz"])
    return [p] if p else []


def _r_energy(ctx: dict) -> list[str]:
    p = plotting.plot_energy(ctx["entries"], ctx["user_tz"])
    return [p] if p else []


def _r_sleep(ctx: dict) -> list[str]:
    p = plotting.plot_sleep(ctx["entries"], ctx["user_tz"])
    return [p] if p else []


def _r_irritability(ctx: dict) -> list[str]:
    p = plotting.plot_irritability(ctx["entries"], ctx["user_tz"])
    return [p] if p else []


def _r_impulsivity(ctx: dict) -> list[str]:
    p = plotting.plot_impulsivity(ctx["entries"], ctx["user_tz"])
    return [p] if p else []


def _r_mood_energy(ctx: dict) -> list[str]:
    p = plotting.plot_mood_energy(ctx["entries"], ctx["user_tz"])
    return [p] if p else []


def _r_mood_spread(ctx: dict) -> list[str]:
    p = plotting.plot_mood_spread(ctx["entries"], ctx["user_tz"])
    return [p] if p else []


def _r_sleep_problems(ctx: dict) -> list[str]:
    p = plotting.plot_sleep_problems(ctx["entries"], ctx["user_tz"])
    return [p] if p else []


def _r_optional_factory(code: str) -> Callable[[dict], list[str]]:
    """Рендер для system optional (EAV) — берёт ответы за период по коду."""
    def _r(ctx: dict) -> list[str]:
        p = plotting.plot_optional_question(ctx["answers_rows"], code, ctx["user_tz"])
        return [p] if p else []
    _r.__name__ = f"_r_optional_{code}"
    return _r


def _r_custom_questions(ctx: dict) -> list[str]:
    """Все графики по custom-вопросам, по которым есть данные."""
    paths: list[str] = []
    seen: set[int] = set()
    order: list[int] = []
    for a in ctx["custom_rows"]:
        qid = a["custom_question_id"]
        if qid not in seen:
            seen.add(qid)
            order.append(qid)
    for qid in order:
        meta = ctx["custom_q_snapshot"].get(qid)
        if meta is None:
            continue
        qtext, qtype, _ = meta
        try:
            p = plotting.plot_custom_question(
                ctx["custom_rows"], qid, qtext, qtype, ctx["user_tz"]
            )
            if p:
                paths.append(p)
        except Exception:
            logger.exception("Ошибка построения custom plot id=%s", qid)
    return paths


# ---- сборка диспетчера ----

STATISTICS_BLOCK_RENDERERS: dict[str, Callable[[dict], list[str]]] = {
    "summary":          _r_summary,
    "mood":             _r_mood,
    "anxiety":          _r_anxiety,
    "energy":           _r_energy,
    "sleep":            _r_sleep,
    "irritability":     _r_irritability,
    "impulsivity":      _r_impulsivity,
    "mood_energy":      _r_mood_energy,
    "mood_spread":      _r_mood_spread,
    "sleep_problems":   _r_sleep_problems,
    "custom_questions": _r_custom_questions,
}

# system optional коды (EAV) — рендерятся универсально по question_code.
_OPTIONAL_CODES = [
    "medications", "therapy", "menstrual_cycle", "suicidal_thoughts",
    "hypomania", "thought_speech_speed", "libido", "risky_behavior", "spending",
    "panic_attacks", "obsessive_thoughts", "avoidance", "somatic_anxiety",
    "anhedonia", "self_esteem_guilt", "appetite", "concentration",
    "productivity", "social_activity", "physical_activity", "substances",
    "caffeine", "late_phone", "stress_events", "aggression_conflicts",
]
for _code in _OPTIONAL_CODES:
    if _code not in STATISTICS_BLOCK_RENDERERS:
        STATISTICS_BLOCK_RENDERERS[_code] = _r_optional_factory(_code)


def render_block(block_code: str, ctx: dict) -> list[str]:
    """Возвращает список PNG-путей (или [SUMMARY_SENTINEL]) для блока.
    Пустой список — нет данных / нет рендера."""
    renderer = STATISTICS_BLOCK_RENDERERS.get(block_code)
    if renderer is None:
        logger.warning("statistics_renderer_missing block_code=%s", block_code)
        return []
    try:
        return renderer(ctx)
    except Exception:
        logger.exception("Ошибка рендера блока %s", block_code)
        return []
