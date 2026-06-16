"""Тесты гард-логики от стейл-нажатий в опросе.

Покрывают bot.handlers.survey._remember_question_msg / _is_stale_press —
защиту от нажатий на клавиатуру брошенного опроса после рестарта
(allow_reentry=True). См. survey_start_callback.
"""
from types import SimpleNamespace

from bot.handlers.survey import (
    _is_stale_press,
    _is_stale_unfinished_press,
    _remember_question_msg,
)


def _make_update(message_id: int | None, tg_id: int = 42):
    message = None if message_id is None else SimpleNamespace(message_id=message_id)
    return SimpleNamespace(
        callback_query=SimpleNamespace(message=message),
        effective_user=SimpleNamespace(id=tg_id),
    )


def _make_context(survey: dict | None):
    return SimpleNamespace(user_data={"survey": survey} if survey is not None else {})


def test_remember_question_msg_stores_id():
    ctx = _make_context({"q_msg_id": None})
    _remember_question_msg(ctx, SimpleNamespace(message_id=777))
    assert ctx.user_data["survey"]["q_msg_id"] == 777


def test_remember_question_msg_noop_without_survey():
    ctx = _make_context(None)
    # Не должно падать, если опроса нет.
    _remember_question_msg(ctx, SimpleNamespace(message_id=1))
    assert "survey" not in ctx.user_data


def test_fresh_press_not_stale():
    ctx = _make_context({"q_msg_id": 100})
    update = _make_update(message_id=100)
    assert _is_stale_press(update, ctx) is False


def test_stale_press_from_old_message():
    # Свежий опрос ждёт ответа на сообщении 200, а нажали на старом 100.
    ctx = _make_context({"q_msg_id": 200})
    update = _make_update(message_id=100)
    assert _is_stale_press(update, ctx) is True


def test_no_survey_is_stale():
    # После _finish_survey опроса нет — любое нажатие стейл.
    ctx = _make_context(None)
    update = _make_update(message_id=100)
    assert _is_stale_press(update, ctx) is True


def test_unset_q_msg_id_not_stale():
    # До первого вопроса q_msg_id ещё None — не блокируем.
    ctx = _make_context({"q_msg_id": None})
    update = _make_update(message_id=100)
    assert _is_stale_press(update, ctx) is False


def test_stale_press_when_message_missing():
    # Кнопка без сообщения (edge) — считаем стейл, раз q_msg_id ждёт конкретный id.
    ctx = _make_context({"q_msg_id": 200})
    update = _make_update(message_id=None)
    assert _is_stale_press(update, ctx) is True


# ---- _is_stale_unfinished_press: гард на кнопку Продолжить/Начать заново ----

def test_unfinished_legit_press_not_stale():
    # /add показал unfinished-сообщение M1, на нём же и нажали — легит.
    ctx = _make_context({"unfinished_msg_id": 555})
    update = _make_update(message_id=555)
    assert _is_stale_unfinished_press(update, ctx) is False


def test_unfinished_stale_after_restart():
    # Новый опрос не показывал unfinished-диалог (id=None), нажали на старом M1.
    ctx = _make_context({"unfinished_msg_id": None})
    update = _make_update(message_id=555)
    assert _is_stale_unfinished_press(update, ctx) is True


def test_unfinished_wrong_message_is_stale():
    # unfinished ждали на 555, нажали на другом 999.
    ctx = _make_context({"unfinished_msg_id": 555})
    update = _make_update(message_id=999)
    assert _is_stale_unfinished_press(update, ctx) is True


def test_unfinished_no_survey_is_stale():
    ctx = _make_context(None)
    update = _make_update(message_id=555)
    assert _is_stale_unfinished_press(update, ctx) is True
