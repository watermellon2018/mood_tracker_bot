"""Handler-ы экрана 'Вопросы опроса'. Без FSM — всё через CallbackQueryHandler
с edit_message_text, чтобы не засорять чат."""

import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.config import config
from bot.constants_questions import (
    CATEGORY_LABELS,
    CATEGORY_SHORT_TO_FULL,
    PRESETS,
)
from bot.database import session_scope
from bot.keyboards.question_settings_keyboards import (
    qs_categories_keyboard,
    qs_category_questions_keyboard,
    qs_preset_applied_keyboard,
    qs_presets_keyboard,
    qs_root_keyboard,
    qs_suicide_warning_keyboard,
)
from bot.models import QuestionCatalog
from bot.services import nav_service, question_settings_service, survey_service
from bot.services.question_settings_service import SUICIDAL_CODE

logger = logging.getLogger(__name__)

ROOT_TEXT = (
    "Вопросы опроса\n\n"
    "Обязательные вопросы всегда включены:\n"
    "✓ Настроение\n✓ Тревога\n✓ Сон\n✓ Энергия\n✓ Комментарий\n\n"
    "Дополнительные вопросы можно включить или выключить. "
    "Они появятся в ежедневном опросе сразу после сохранения."
)

PRESETS_TEXT = (
    "🌧 Готовые наборы\n\n"
    "Выберите, что вы хотите отслеживать.\n"
    "Можно будет изменить список вручную позже."
)

MANUAL_TEXT = (
    "🛠 Настроить вопросы\n\n"
    "Выберите категорию. Внутри можно включать и выключать вопросы.\n"
    "Изменения сохраняются автоматически."
)

SUICIDE_WARNING = (
    "Этот блок нужен только для самонаблюдения и не заменяет помощь специалиста.\n\n"
    "Если вы чувствуете, что можете навредить себе, обратитесь за срочной помощью: "
    "к близкому человеку, врачу, в экстренную службу или местную кризисную линию."
)

RESET_DONE = (
    "Дополнительные вопросы отключены. В ежедневном опросе останутся только базовые "
    "вопросы."
)


# ---------- entry ----------

async def qs_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открыть корневой экран. Вызывается из settings menu (callback qs:menu)."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    logger.info("Открыты настройки вопросов tg=%s", update.effective_user.id)
    await _show(update, ROOT_TEXT, qs_root_keyboard())


async def qs_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Единый callback-роутер для всех qs:* кнопок (кроме qs:menu — он входная точка)."""
    query = update.callback_query
    await query.answer()
    data = query.data
    tg_id = update.effective_user.id

    if data == "qs:menu":
        await _show(update, ROOT_TEXT, qs_root_keyboard())
        return

    if data == "qs:back":
        # qs:back теперь = закрыть inline-меню (близко к нативному поведению).
        # nav_service.close_menu сначала пытается удалить сообщение, чтобы
        # не оставлять зависшее меню без кнопок (важно на мобильнике).
        await nav_service.close_menu(update, context)
        return

    if data == "qs:presets":
        await _show(update, PRESETS_TEXT, qs_presets_keyboard())
        return

    if data.startswith("qs:preset:"):
        preset_code = data.split(":", 2)[2]
        preset = PRESETS.get(preset_code)
        if preset is None:
            await _show(update, "Набор не найден.", qs_presets_keyboard())
            return
        try:
            with session_scope() as session:
                user = survey_service.get_or_create_user(
                    session, tg_id, config.DEFAULT_TIMEZONE
                )
                count = question_settings_service.apply_preset(
                    session, user.id, preset_code
                )
        except Exception:
            logger.exception("Ошибка применения пресета %s", preset_code)
            await _show(update, "Не удалось применить набор.", qs_presets_keyboard())
            return
        text = (
            f'Готово. Я включил вопросы из набора "{preset["label"]}" '
            f'({count} шт).\nВы можете изменить список вручную.'
        )
        await _show(update, text, qs_preset_applied_keyboard())
        return

    if data == "qs:manual":
        await _show(update, MANUAL_TEXT, qs_categories_keyboard())
        return

    if data.startswith("qs:cat:"):
        short = data.split(":", 2)[2]
        full = CATEGORY_SHORT_TO_FULL.get(short)
        if full is None:
            await _show(update, "Категория не найдена.", qs_categories_keyboard())
            return
        await _render_category(update, tg_id, full)
        return

    if data.startswith("qs:tgl:"):
        code = data.split(":", 2)[2]
        await _handle_toggle(update, context, tg_id, code)
        return

    if data == "qs:suicide_confirm":
        try:
            with session_scope() as session:
                user = survey_service.get_or_create_user(
                    session, tg_id, config.DEFAULT_TIMEZONE
                )
                question_settings_service.set_suicidal_after_confirm(session, user.id)
            logger.info("Включён suicidal_thoughts tg=%s после подтверждения", tg_id)
        except Exception:
            logger.exception("Ошибка включения suicidal_thoughts")
        # Возвращаемся к экрану категории health.
        await _render_category(update, tg_id, "health")
        return

    if data == "qs:suicide_cancel":
        await _render_category(update, tg_id, "health")
        return

    if data == "qs:reset":
        try:
            with session_scope() as session:
                user = survey_service.get_or_create_user(
                    session, tg_id, config.DEFAULT_TIMEZONE
                )
                question_settings_service.reset_optional(session, user.id)
        except Exception:
            logger.exception("Ошибка сброса опциональных вопросов")
            await _show(update, "Не удалось выполнить сброс.", qs_root_keyboard())
            return
        await _show(update, RESET_DONE, qs_root_keyboard())
        return


# ---------- helpers ----------

async def _handle_toggle(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tg_id: int,
    code: str,
) -> None:
    # Особый путь: включение suicidal_thoughts требует warning.
    if code == SUICIDAL_CODE:
        # Если он сейчас выключен — показать warning, иначе выключить сразу.
        is_currently_enabled = False
        try:
            with session_scope() as session:
                user = survey_service.get_or_create_user(
                    session, tg_id, config.DEFAULT_TIMEZONE
                )
                is_currently_enabled = SUICIDAL_CODE in (
                    question_settings_service.enabled_optional_codes(session, user.id)
                )
        except Exception:
            logger.exception("Ошибка чтения состояния suicidal_thoughts")

        if not is_currently_enabled:
            await _show(update, SUICIDE_WARNING, qs_suicide_warning_keyboard())
            return
        # Выключение — без подтверждения.
        try:
            with session_scope() as session:
                user = survey_service.get_or_create_user(
                    session, tg_id, config.DEFAULT_TIMEZONE
                )
                question_settings_service.toggle_question(session, user.id, code)
        except Exception:
            logger.exception("Ошибка выключения suicidal_thoughts")
        await _render_category(update, tg_id, "health")
        return

    # Обычный toggle.
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            question_settings_service.toggle_question(session, user.id, code)
    except Exception:
        logger.exception("Ошибка переключения вопроса %s", code)

    # Перерисовать экран категории, к которой относится вопрос.
    try:
        with session_scope() as session:
            q = session.get(QuestionCatalog, code)
            category = q.category if q is not None else None
    except Exception:
        category = None
    if category and category != "base":
        await _render_category(update, tg_id, category)


async def _render_category(update: Update, tg_id: int, category: str) -> None:
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            questions = question_settings_service.optional_questions_by_category(
                session, category
            )
            enabled = question_settings_service.enabled_optional_codes(session, user.id)
    except Exception:
        logger.exception("Ошибка рендера категории %s", category)
        await _show(update, "Не удалось загрузить категорию.", qs_categories_keyboard())
        return

    label = CATEGORY_LABELS.get(category, category)
    text = (
        f"{label}\n\n"
        "Нажмите на вопрос, чтобы включить или выключить его.\n"
        "Изменения сохраняются автоматически."
    )
    await _show(
        update, text, qs_category_questions_keyboard(questions, enabled)
    )


async def _show(update: Update, text: str, markup) -> None:
    """edit_message_text там, где можно (callback); иначе шлёт новое сообщение."""
    query = update.callback_query
    if query is not None:
        try:
            await query.edit_message_text(text, reply_markup=markup)
            return
        except BadRequest:
            # 'message not modified' и подобное — просто шлём заново.
            pass
        target = query.message
    else:
        target = update.message
    await target.reply_text(text, reply_markup=markup)


def build_qs_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(qs_router, pattern=r"^qs:")
