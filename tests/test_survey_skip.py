"""Тесты кнопки «Пропустить» под вопросом опроса.

Покрывают пропуск опциональных и пользовательских вопросов: при «Пропустить»
ответ НЕ сохраняется (ни в optional_answers/custom_answers, ни в БД), а опрос
двигается к следующему шагу. См. bot.handlers.survey.optional_question_step /
physical_activity_duration_step / custom_question_step.
"""
import asyncio

import pytest

from bot.handlers import survey
from bot.handlers.survey import (
    COMMENT,
    CUSTOM_Q,
    OPTIONAL_Q,
    custom_question_step,
    optional_question_step,
    physical_activity_duration_step,
)


# ---------- async-заглушки telegram ----------

class _FakeMessage:
    """Сообщение, чьи reply_text возвращают новые _FakeMessage с растущими id."""

    _counter = 1000

    def __init__(self):
        _FakeMessage._counter += 1
        self.message_id = _FakeMessage._counter
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(text)
        return _FakeMessage()


class _FakeQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.edited = []

    async def answer(self):
        return None

    async def edit_message_text(self, text):
        self.edited.append(text)


class _FakeUpdate:
    def __init__(self, data, message, tg_id=42):
        self.callback_query = _FakeQuery(data, message)
        self.message = None
        self.effective_user = type("U", (), {"id": tg_id})()


class _FakeContext:
    def __init__(self, survey_state):
        self.user_data = {"survey": survey_state}


def _run(coro):
    return asyncio.run(coro)


def _base_survey_state(**overrides):
    """Минимальный survey-state с q_msg_id, совпадающим с message_id вопроса,
    чтобы _is_stale_press не отбраковал нажатие."""
    state = {
        "q_msg_id": None,
        "optional_plan": [],
        "optional_idx": 0,
        "optional_answers": [],
        "pa_pending": None,
        "custom_questions": [],
        "custom_idx": 0,
        "custom_answers": [],
    }
    state.update(overrides)
    return state


# ---------- опциональные вопросы ----------

def test_optional_skip_does_not_save_and_advances():
    # План из одного вопроса concentration. Нажали «Пропустить».
    msg = _FakeMessage()
    state = _base_survey_state(
        q_msg_id=msg.message_id,
        optional_plan=[
            {"code": "concentration", "target_date": "2026-06-20",
             "ask_policy": "last_or_after_noon"},
        ],
    )
    ctx = _FakeContext(state)
    upd = _FakeUpdate("opt:skip", msg)

    result = _run(optional_question_step(upd, ctx))

    # Ответ не записан, индекс продвинут, опрос ушёл за пределы плана -> к custom/комменту.
    assert state["optional_answers"] == []
    assert state["optional_idx"] == 1
    # custom-вопросов нет -> следующий шаг COMMENT.
    assert result == COMMENT
    assert any("Пропущено" in t for t in upd.callback_query.edited)


def test_optional_skip_moves_to_next_optional():
    # Два опциональных: пропускаем первый -> показываем второй (OPTIONAL_Q).
    msg = _FakeMessage()
    state = _base_survey_state(
        q_msg_id=msg.message_id,
        optional_plan=[
            {"code": "concentration", "target_date": "2026-06-20",
             "ask_policy": "last_or_after_noon"},
            {"code": "anhedonia", "target_date": "2026-06-20",
             "ask_policy": "last_survey_of_day"},
        ],
    )
    ctx = _FakeContext(state)
    upd = _FakeUpdate("opt:skip", msg)

    result = _run(optional_question_step(upd, ctx))

    assert state["optional_answers"] == []
    assert state["optional_idx"] == 1
    assert result == OPTIONAL_Q


def test_optional_skip_on_physical_activity_skips_whole_question():
    # physical_activity — двухшаговый. «Пропустить» на первом шаге не должен
    # уводить в PHYS_ACT_DURATION и не должен записывать ответ.
    msg = _FakeMessage()
    state = _base_survey_state(
        q_msg_id=msg.message_id,
        optional_plan=[
            {"code": "physical_activity", "target_date": "2026-06-20",
             "ask_policy": "last_or_after_noon"},
        ],
    )
    ctx = _FakeContext(state)
    upd = _FakeUpdate("opt:skip", msg)

    result = _run(optional_question_step(upd, ctx))

    assert state["optional_answers"] == []
    assert state["pa_pending"] is None
    assert state["optional_idx"] == 1
    assert result == COMMENT


# ---------- physical_activity: пропуск длительности ----------

def test_pa_duration_skip_discards_pending_and_advances():
    # Ответили «Да» (pa_pending взведён), затем «Пропустить» длительность.
    msg = _FakeMessage()
    state = _base_survey_state(
        q_msg_id=msg.message_id,
        optional_plan=[
            {"code": "physical_activity", "target_date": "2026-06-20",
             "ask_policy": "last_or_after_noon"},
        ],
        optional_idx=0,
        pa_pending={"code": "physical_activity",
                    "target_date_iso": "2026-06-20"},
    )
    ctx = _FakeContext(state)
    upd = _FakeUpdate("pa_dur:skip", msg)

    result = _run(physical_activity_duration_step(upd, ctx))

    # Ответ не записан, pending сброшен, индекс продвинут.
    assert state["optional_answers"] == []
    assert state["pa_pending"] is None
    assert state["optional_idx"] == 1
    assert result == COMMENT


# ---------- пользовательские вопросы ----------

@pytest.mark.parametrize("qtype", ["scale_0_5", "boolean", "text"])
def test_custom_skip_does_not_save_and_advances(qtype):
    # «Пропустить» работает для любого типа custom-вопроса.
    msg = _FakeMessage()
    state = _base_survey_state(
        q_msg_id=msg.message_id,
        custom_questions=[{"id": 7, "text": "Свой вопрос?", "type": qtype}],
        custom_idx=0,
    )
    ctx = _FakeContext(state)
    upd = _FakeUpdate("cqa:skip", msg)

    result = _run(custom_question_step(upd, ctx))

    assert state["custom_answers"] == []
    assert state["custom_idx"] == 1
    # custom-вопросов больше нет -> COMMENT.
    assert result == COMMENT
    assert any("Пропущено" in t for t in upd.callback_query.edited)
