"""UI для пользовательских вопросов: список, создание (FSM), переименование (FSM),
смена частоты, вкл/выкл, архивирование. Сам ответ в ежедневном опросе —
в bot/handlers/survey.py.
"""

import logging
from types import SimpleNamespace

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.config import config
from bot.database import session_scope
from bot.keyboards.custom_question_keyboards import (
    cq_archive_confirm_keyboard,
    cq_confirm_keyboard,
    cq_created_keyboard,
    cq_empty_keyboard,
    cq_every_n_days_keyboard,
    cq_frequency_keyboard,
    cq_list_keyboard,
    cq_nth_survey_keyboard,
    cq_type_keyboard,
    cq_view_keyboard,
)
from bot.services import custom_question_service, survey_service
from bot.services.custom_question_service import (
    ANSWER_TYPES,
    FREQUENCY_BIWEEKLY,
    FREQUENCY_EVERY_N_DAYS,
    FREQUENCY_EVERY_SURVEY,
    FREQUENCY_NTH_SURVEY,
    FREQUENCY_TYPES,
    FREQUENCY_WEEKLY,
    MAX_TEXT_LEN,
    ValidationError,
)

logger = logging.getLogger(__name__)

# FSM states.
ASK_TEXT, ASK_TYPE, ASK_FREQUENCY, ASK_EVERY_N, ASK_CONFIRM = range(5)
RENAME_AWAIT_TEXT = 0
# FSM смены частоты у существующего вопроса.
EDIT_FREQ_PICK_TYPE, EDIT_FREQ_PICK_N = range(2)

# Подписи типов для UI.
TYPE_LABELS = {
    "scale_0_5": "Шкала 0–5",
    "boolean": "Да / Нет",
    "text": "Текст",
}

ASK_TEXT_PROMPT = (
    "Введите текст вопроса, который хотите добавить в ежедневный опрос.\n"
    'Например: "Насколько сильная была боль в спине?"'
)
ASK_TYPE_PROMPT = "Выберите формат ответа:"
ASK_FREQUENCY_PROMPT = (
    "Как часто задавать этот вопрос?\n\n"
    "• «В каждом опросе» — всегда.\n"
    "• «В определённое время дня» — утром, в середине дня или вечером.\n"
    "• «Раз в N дней / неделю / две недели» — в последнем опросе подходящего "
    "дня (по сути вечером)."
)
ASK_NTH_SURVEY_PROMPT = "Когда задавать вопрос?"
ASK_EVERY_N_DAYS_PROMPT = "Раз в сколько дней задавать вопрос?"
LIST_HEADER = "📝 Мои вопросы\n\nНажмите на вопрос, чтобы настроить его."
EMPTY_TEXT = (
    "Вы пока не создавали своих вопросов.\n"
    "Нажмите «➕ Добавить вопрос», чтобы создать первый."
)


_SLOT_LABELS = {
    1: "Утром (первый опрос дня)",
    2: "В середине дня",
    3: "Вечером (последний опрос дня)",
}


def frequency_label(frequency_type: str, every_n: int | None) -> str:
    if frequency_type == FREQUENCY_EVERY_SURVEY:
        return "В каждом опросе"
    if frequency_type == FREQUENCY_NTH_SURVEY:
        return _SLOT_LABELS.get(every_n or 0, f"Слот {every_n}")
    if frequency_type == FREQUENCY_EVERY_N_DAYS:
        return f"Раз в {every_n} дн. (вечером)"
    if frequency_type == FREQUENCY_WEEKLY:
        return "Раз в неделю (вечером)"
    if frequency_type == FREQUENCY_BIWEEKLY:
        return "Раз в две недели (вечером)"
    return frequency_type


# ---------- helpers ----------

async def _show(update: Update, text: str, markup) -> None:
    query = update.callback_query
    if query is not None:
        try:
            await query.edit_message_text(text, reply_markup=markup)
            return
        except BadRequest:
            pass
        target = query.message
    else:
        target = update.message
    await target.reply_text(text, reply_markup=markup)


async def _show_list(update: Update, tg_id: int) -> None:
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            questions = custom_question_service.get_active(session, user.id)
    except Exception:
        logger.exception("Ошибка чтения списка custom questions")
        await _show(update, "Не удалось загрузить список.", cq_empty_keyboard())
        return

    if not questions:
        await _show(update, EMPTY_TEXT, cq_empty_keyboard())
        return
    await _show(update, LIST_HEADER, cq_list_keyboard(questions))


# ---------- list / open ----------

async def cq_list_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback qs:cq_list — открыть список своих вопросов."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    logger.info("Открыты Мои вопросы tg=%s", update.effective_user.id)
    await _show_list(update, update.effective_user.id)


async def cq_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Единый callback-роутер для cq:* кнопок, не входящих в FSM."""
    query = update.callback_query
    await query.answer()
    data = query.data
    tg_id = update.effective_user.id

    if data == "cq:list":
        await _show_list(update, tg_id)
        return

    if data.startswith("cq:view:"):
        qid = _parse_id(data)
        if qid is None:
            return
        await _show_view(update, tg_id, qid)
        return

    if data.startswith("cq:toggle:"):
        qid = _parse_id(data)
        if qid is None:
            return
        try:
            with session_scope() as session:
                user = survey_service.get_or_create_user(
                    session, tg_id, config.DEFAULT_TIMEZONE
                )
                custom_question_service.toggle(session, user.id, qid)
        except Exception:
            logger.exception("Ошибка toggle custom_question id=%s", qid)
        await _show_view(update, tg_id, qid)
        return

    if data.startswith("cq:archive:"):
        qid = _parse_id(data)
        if qid is None:
            return
        await _show(
            update,
            "Архивировать этот вопрос?\n\n"
            "Он больше не будет появляться в ежедневном опросе, "
            "но старые ответы сохранятся для истории.",
            cq_archive_confirm_keyboard(qid),
        )
        return

    if data.startswith("cq:archive_ok:"):
        qid = _parse_id(data)
        if qid is None:
            return
        try:
            with session_scope() as session:
                user = survey_service.get_or_create_user(
                    session, tg_id, config.DEFAULT_TIMEZONE
                )
                custom_question_service.archive(session, user.id, qid)
        except Exception:
            logger.exception("Ошибка archive custom_question id=%s", qid)
        await _show_list(update, tg_id)
        return


def _parse_id(data: str) -> int | None:
    try:
        return int(data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        return None


async def _show_view(update: Update, tg_id: int, question_id: int) -> None:
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            q = custom_question_service.get_owned(session, user.id, question_id)
            if q is not None:
                snapshot = {
                    "id": q.id,
                    "text": q.question_text,
                    "type": q.answer_type,
                    "is_enabled": q.is_enabled,
                    "freq_type": q.ask_frequency_type,
                    "every_n": q.ask_every_n,
                }
            else:
                snapshot = None
    except Exception:
        logger.exception("Ошибка чтения custom_question id=%s", question_id)
        await _show_list(update, tg_id)
        return

    if snapshot is None:
        await _show_list(update, tg_id)
        return

    status = (
        "Включен в ежедневный опрос" if snapshot["is_enabled"] else "Выключен"
    )
    text = (
        f"📝 Свой вопрос\n\n"
        f"Вопрос:\n«{snapshot['text']}»\n\n"
        f"Формат ответа:\n{TYPE_LABELS.get(snapshot['type'], snapshot['type'])}\n\n"
        f"Частота:\n{frequency_label(snapshot['freq_type'], snapshot['every_n'])}\n\n"
        f"Статус:\n{status}"
    )
    # cq_view_keyboard ожидает CustomQuestion-подобный объект. SimpleNamespace
    # достаточен — клавиатура читает только id и is_enabled.
    view_q = SimpleNamespace(id=snapshot["id"], is_enabled=snapshot["is_enabled"])
    await _show(update, text, cq_view_keyboard(view_q))


# ---------- FSM: create ----------

async def cq_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point на cq:add. Проверяет лимит и спрашивает текст."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    tg_id = update.effective_user.id

    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            already = custom_question_service.count_active(session, user.id)
    except Exception:
        logger.exception("Ошибка проверки лимита custom questions")
        await _show(update, "Не удалось проверить лимит.", cq_empty_keyboard())
        return ConversationHandler.END

    if already >= custom_question_service.MAX_ACTIVE_PER_USER:
        await _show(
            update,
            f"Пока можно добавить до {custom_question_service.MAX_ACTIVE_PER_USER} "
            "своих вопросов. Чтобы добавить новый, архивируйте один из старых.",
            cq_empty_keyboard(),
        )
        return ConversationHandler.END

    context.user_data["cq_new"] = {}
    await _show(update, ASK_TEXT_PROMPT, None)
    logger.info("Начато создание custom_question tg=%s", tg_id)
    return ASK_TEXT


async def cq_receive_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Текст не может быть пустым. Введите вопрос:")
        return ASK_TEXT
    if len(text) > MAX_TEXT_LEN:
        await update.message.reply_text(
            f"Слишком длинный текст (макс. {MAX_TEXT_LEN} символов). Сократите:"
        )
        return ASK_TEXT

    tg_id = update.effective_user.id
    # Проверяем дубль среди активных пользователя.
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            existing = [
                q for q in custom_question_service.get_active(session, user.id)
                if q.question_text.strip().lower() == text.lower()
            ]
    except Exception:
        logger.exception("Ошибка проверки дубля custom question")
        existing = []

    if existing:
        await update.message.reply_text(
            "У вас уже есть активный вопрос с таким текстом. Введите другой:"
        )
        return ASK_TEXT

    context.user_data["cq_new"]["text"] = text
    await update.message.reply_text(ASK_TYPE_PROMPT, reply_markup=cq_type_keyboard())
    return ASK_TYPE


async def cq_receive_type(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "cq:cancel":
        return await _cancel(update, context)

    answer_type = data.split(":", 2)[2] if data.startswith("cq:type:") else None
    if answer_type not in ANSWER_TYPES:
        await query.message.reply_text("Неизвестный формат. Попробуйте ещё раз:")
        return ASK_TYPE

    context.user_data["cq_new"]["type"] = answer_type
    # Переходим к выбору частоты.
    await query.edit_message_text(
        ASK_FREQUENCY_PROMPT, reply_markup=cq_frequency_keyboard()
    )
    return ASK_FREQUENCY


async def cq_receive_frequency(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cq:cancel":
        return await _cancel(update, context)

    if not data.startswith("cq:freq_set:"):
        return ASK_FREQUENCY
    ftype = data.split(":", 2)[2]
    if ftype not in FREQUENCY_TYPES:
        return ASK_FREQUENCY

    new = context.user_data.setdefault("cq_new", {})
    new["freq_type"] = ftype
    new["every_n"] = None

    if ftype == FREQUENCY_NTH_SURVEY:
        await query.edit_message_text(
            ASK_NTH_SURVEY_PROMPT, reply_markup=cq_nth_survey_keyboard()
        )
        return ASK_EVERY_N
    if ftype == FREQUENCY_EVERY_N_DAYS:
        await query.edit_message_text(
            ASK_EVERY_N_DAYS_PROMPT, reply_markup=cq_every_n_days_keyboard()
        )
        return ASK_EVERY_N

    return await _show_confirm(update, context)


async def cq_receive_every_n(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cq:cancel":
        return await _cancel(update, context)
    if data == "cq:freq_back":
        await query.edit_message_text(
            ASK_FREQUENCY_PROMPT, reply_markup=cq_frequency_keyboard()
        )
        return ASK_FREQUENCY

    if not data.startswith("cq:freq_n:"):
        return ASK_EVERY_N
    try:
        n = int(data.split(":", 2)[2])
    except ValueError:
        return ASK_EVERY_N

    new = context.user_data.setdefault("cq_new", {})
    ftype = new.get("freq_type")
    try:
        _, normalized_n = custom_question_service.validate_frequency(ftype, n)
    except ValidationError:
        # Перерисуем клавиатуру для текущего типа.
        if ftype == FREQUENCY_NTH_SURVEY:
            await query.edit_message_text(
                ASK_NTH_SURVEY_PROMPT, reply_markup=cq_nth_survey_keyboard()
            )
        else:
            await query.edit_message_text(
                ASK_EVERY_N_DAYS_PROMPT, reply_markup=cq_every_n_days_keyboard()
            )
        return ASK_EVERY_N
    new["every_n"] = normalized_n
    return await _show_confirm(update, context)


async def _show_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    new = context.user_data.get("cq_new") or {}
    text = new.get("text", "")
    answer_type = new.get("type", "")
    ftype = new.get("freq_type", FREQUENCY_EVERY_SURVEY)
    every_n = new.get("every_n")
    body = (
        f"Добавить этот вопрос в ежедневный опрос?\n\n"
        f"Вопрос:\n«{text}»\n\n"
        f"Формат ответа:\n{TYPE_LABELS.get(answer_type, answer_type)}\n\n"
        f"Частота:\n{frequency_label(ftype, every_n)}"
    )
    query = update.callback_query
    if query is not None:
        try:
            await query.edit_message_text(body, reply_markup=cq_confirm_keyboard())
        except BadRequest:
            await query.message.reply_text(body, reply_markup=cq_confirm_keyboard())
    else:
        await update.message.reply_text(body, reply_markup=cq_confirm_keyboard())
    return ASK_CONFIRM


async def cq_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cq:cancel":
        return await _cancel(update, context)

    if data == "cq:edit_text":
        await query.edit_message_text(ASK_TEXT_PROMPT)
        return ASK_TEXT

    if data == "cq:edit_type":
        await query.edit_message_text(
            ASK_TYPE_PROMPT, reply_markup=cq_type_keyboard()
        )
        return ASK_TYPE

    if data == "cq:edit_freq":
        await query.edit_message_text(
            ASK_FREQUENCY_PROMPT, reply_markup=cq_frequency_keyboard()
        )
        return ASK_FREQUENCY

    if data != "cq:confirm":
        return ASK_CONFIRM

    new = context.user_data.get("cq_new") or {}
    text = new.get("text")
    answer_type = new.get("type")
    ftype = new.get("freq_type", FREQUENCY_EVERY_SURVEY)
    every_n = new.get("every_n")
    if not text or not answer_type:
        await query.edit_message_text("Что-то пошло не так. Попробуйте заново.")
        context.user_data.pop("cq_new", None)
        return ConversationHandler.END

    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            q = custom_question_service.create(
                session,
                user.id,
                text,
                answer_type,
                ask_frequency_type=ftype,
                ask_every_n=every_n,
            )
            qid = q.id
    except ValidationError as e:
        await query.edit_message_text(str(e), reply_markup=cq_empty_keyboard())
        context.user_data.pop("cq_new", None)
        return ConversationHandler.END
    except Exception:
        logger.exception("Ошибка создания custom_question")
        await query.edit_message_text(
            "Не удалось создать вопрос. Попробуйте позже.",
            reply_markup=cq_empty_keyboard(),
        )
        context.user_data.pop("cq_new", None)
        return ConversationHandler.END

    logger.info("Создан custom_question id=%s tg=%s", qid, tg_id)
    await query.edit_message_text(
        "Вопрос добавлен и включен в ежедневный опрос.",
        reply_markup=cq_created_keyboard(),
    )
    context.user_data.pop("cq_new", None)
    return ConversationHandler.END


async def _cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("cq_new", None)
    if update.callback_query is not None:
        await update.callback_query.edit_message_text(
            "Создание отменено.", reply_markup=cq_empty_keyboard()
        )
    else:
        await update.message.reply_text("Отменено.")
    return ConversationHandler.END


async def _cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("cq_new", None)
    context.user_data.pop("cq_edit_freq", None)
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


def build_cq_create_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cq_add_start, pattern=r"^cq:add$"),
        ],
        states={
            ASK_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cq_receive_text),
            ],
            ASK_TYPE: [
                CallbackQueryHandler(
                    cq_receive_type, pattern=r"^cq:(type:[a-z_0-9]+|cancel)$"
                ),
            ],
            ASK_FREQUENCY: [
                CallbackQueryHandler(
                    cq_receive_frequency,
                    pattern=r"^cq:(freq_set:[a-z_]+|cancel)$",
                ),
            ],
            ASK_EVERY_N: [
                CallbackQueryHandler(
                    cq_receive_every_n,
                    pattern=r"^cq:(freq_n:\d+|freq_back|cancel)$",
                ),
            ],
            ASK_CONFIRM: [
                CallbackQueryHandler(
                    cq_confirm,
                    pattern=r"^cq:(confirm|edit_text|edit_type|edit_freq|cancel)$",
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", _cancel_cmd)],
        name="cq_create_conversation",
        persistent=False,
    )


# ---------- FSM: rename ----------

async def cq_rename_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    qid = _parse_id(query.data)
    if qid is None:
        return ConversationHandler.END
    # Проверяем, что вопрос принадлежит пользователю.
    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            q = custom_question_service.get_owned(session, user.id, qid)
    except Exception:
        logger.exception("Ошибка проверки прав на custom_question id=%s", qid)
        return ConversationHandler.END

    if q is None or not q.is_active:
        await query.edit_message_text("Вопрос не найден.")
        return ConversationHandler.END

    context.user_data["cq_rename_id"] = qid
    await query.edit_message_text("Введите новый текст вопроса.")
    return RENAME_AWAIT_TEXT


async def cq_rename_receive(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    text = (update.message.text or "").strip()
    qid = context.user_data.get("cq_rename_id")
    if not qid:
        await update.message.reply_text("Что-то пошло не так. Попробуйте заново.")
        return ConversationHandler.END

    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            custom_question_service.rename(session, user.id, qid, text)
    except ValidationError as e:
        await update.message.reply_text(str(e))
        return RENAME_AWAIT_TEXT
    except Exception:
        logger.exception("Ошибка переименования custom_question id=%s", qid)
        await update.message.reply_text("Не удалось переименовать вопрос.")
        context.user_data.pop("cq_rename_id", None)
        return ConversationHandler.END

    context.user_data.pop("cq_rename_id", None)
    await update.message.reply_text("Готово. Текст вопроса обновлён.")
    await _show_view(update, tg_id, qid)
    return ConversationHandler.END


def build_cq_rename_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cq_rename_start, pattern=r"^cq:rename:\d+$"),
        ],
        states={
            RENAME_AWAIT_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cq_rename_receive),
            ],
        },
        fallbacks=[CommandHandler("cancel", _cancel_cmd)],
        name="cq_rename_conversation",
        persistent=False,
    )


# ---------- FSM: edit frequency ----------

async def cq_edit_freq_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    qid = _parse_id(query.data)
    if qid is None:
        return ConversationHandler.END
    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            q = custom_question_service.get_owned(session, user.id, qid)
            if q is None or not q.is_active:
                q = None
    except Exception:
        logger.exception("Ошибка чтения custom_question id=%s", qid)
        return ConversationHandler.END

    if q is None:
        await query.edit_message_text("Вопрос не найден.")
        return ConversationHandler.END

    context.user_data["cq_edit_freq"] = {"id": qid}
    await query.edit_message_text(
        ASK_FREQUENCY_PROMPT,
        reply_markup=cq_frequency_keyboard(cancel_data=f"cq:freq_cancel:{qid}"),
    )
    return EDIT_FREQ_PICK_TYPE


async def cq_edit_freq_pick_type(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    state = context.user_data.get("cq_edit_freq") or {}
    qid = state.get("id")

    if data.startswith("cq:freq_cancel:"):
        return await _edit_freq_cancel(update, context, qid)

    if not data.startswith("cq:freq_set:"):
        return EDIT_FREQ_PICK_TYPE
    ftype = data.split(":", 2)[2]
    if ftype not in FREQUENCY_TYPES:
        return EDIT_FREQ_PICK_TYPE

    state["freq_type"] = ftype
    state["every_n"] = None
    cancel_cb = f"cq:freq_cancel:{qid}"

    if ftype == FREQUENCY_NTH_SURVEY:
        await query.edit_message_text(
            ASK_NTH_SURVEY_PROMPT,
            reply_markup=cq_nth_survey_keyboard(cancel_data=cancel_cb),
        )
        return EDIT_FREQ_PICK_N
    if ftype == FREQUENCY_EVERY_N_DAYS:
        await query.edit_message_text(
            ASK_EVERY_N_DAYS_PROMPT,
            reply_markup=cq_every_n_days_keyboard(cancel_data=cancel_cb),
        )
        return EDIT_FREQ_PICK_N

    return await _commit_edit_freq(update, context, qid, ftype, None)


async def cq_edit_freq_pick_n(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    state = context.user_data.get("cq_edit_freq") or {}
    qid = state.get("id")

    if data.startswith("cq:freq_cancel:"):
        return await _edit_freq_cancel(update, context, qid)
    if data == "cq:freq_back":
        await query.edit_message_text(
            ASK_FREQUENCY_PROMPT,
            reply_markup=cq_frequency_keyboard(cancel_data=f"cq:freq_cancel:{qid}"),
        )
        return EDIT_FREQ_PICK_TYPE

    if not data.startswith("cq:freq_n:"):
        return EDIT_FREQ_PICK_N
    try:
        n = int(data.split(":", 2)[2])
    except ValueError:
        return EDIT_FREQ_PICK_N

    ftype = state.get("freq_type")
    try:
        _, normalized_n = custom_question_service.validate_frequency(ftype, n)
    except ValidationError:
        return EDIT_FREQ_PICK_N

    return await _commit_edit_freq(update, context, qid, ftype, normalized_n)


async def _commit_edit_freq(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    qid: int,
    ftype: str,
    every_n: int | None,
) -> int:
    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            custom_question_service.update_frequency(
                session, user.id, qid, ftype, every_n
            )
    except ValidationError as e:
        if update.callback_query is not None:
            await update.callback_query.edit_message_text(str(e))
        context.user_data.pop("cq_edit_freq", None)
        await _show_view(update, tg_id, qid)
        return ConversationHandler.END
    except Exception:
        logger.exception("Ошибка обновления частоты custom_question id=%s", qid)
        if update.callback_query is not None:
            await update.callback_query.edit_message_text(
                "Не удалось обновить частоту."
            )
        context.user_data.pop("cq_edit_freq", None)
        await _show_view(update, tg_id, qid)
        return ConversationHandler.END

    context.user_data.pop("cq_edit_freq", None)
    await _show_view(update, tg_id, qid)
    return ConversationHandler.END


async def _edit_freq_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE, qid: int | None
) -> int:
    context.user_data.pop("cq_edit_freq", None)
    tg_id = update.effective_user.id
    if qid is not None:
        await _show_view(update, tg_id, qid)
    else:
        await _show_list(update, tg_id)
    return ConversationHandler.END


def build_cq_edit_freq_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cq_edit_freq_start, pattern=r"^cq:freq:\d+$"),
        ],
        states={
            EDIT_FREQ_PICK_TYPE: [
                CallbackQueryHandler(
                    cq_edit_freq_pick_type,
                    pattern=r"^cq:(freq_set:[a-z_]+|freq_cancel:\d+)$",
                ),
            ],
            EDIT_FREQ_PICK_N: [
                CallbackQueryHandler(
                    cq_edit_freq_pick_n,
                    pattern=r"^cq:(freq_n:\d+|freq_back|freq_cancel:\d+)$",
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", _cancel_cmd)],
        name="cq_edit_freq_conversation",
        persistent=False,
    )


def build_cq_router() -> CallbackQueryHandler:
    """Роутер для кнопок, не входящих в FSM: list, view, toggle, archive."""
    return CallbackQueryHandler(
        cq_router,
        pattern=r"^cq:(list|view:\d+|toggle:\d+|archive:\d+|archive_ok:\d+)$",
    )


def build_cq_list_entry() -> CallbackQueryHandler:
    """Открыть Мои вопросы из меню qs."""
    return CallbackQueryHandler(cq_list_open, pattern=r"^qs:cq_list$")
