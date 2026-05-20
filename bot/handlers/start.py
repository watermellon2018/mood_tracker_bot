import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import config
from bot.database import session_scope
from bot.handlers.timezone import needs_timezone_setup, prompt_timezone_choice
from bot.keyboards.main_menu import (
    BTN_EXPORT,
    BTN_HELP,
    BTN_PAUSE,
    BTN_RESUME,
    BTN_SETTINGS,
    BTN_STATS,
    main_menu_keyboard,
)
from bot.services import scheduler_service, survey_service
from bot.texts import HELP, PAUSE_OK, RESUME_OK, WELCOME

logger = logging.getLogger(__name__)


def _get_notifications_enabled(tg_id: int) -> bool:
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            settings = survey_service.get_settings(session, user.id)
            if settings is not None:
                return settings.notifications_enabled
    except Exception:
        logger.exception("Не удалось получить настройки для главного меню")
    return True


async def _send_main_menu(update: Update, text: str) -> None:
    """Отправляет text вместе с reply-меню. Подбирает Пауза/Возобновить."""
    notifications_enabled = _get_notifications_enabled(update.effective_user.id)
    markup = main_menu_keyboard(notifications_enabled)
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(text, reply_markup=markup)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            settings = survey_service.get_settings(session, user.id)
        if settings is not None:
            scheduler_service.schedule_user(context.application, user, settings)
    except Exception:
        logger.exception("Ошибка в /start")
        await update.message.reply_text(
            "Не удалось инициализировать пользователя. Попробуй позже."
        )
        return
    await _send_main_menu(update, WELCOME)
    if needs_timezone_setup(tg_id):
        await prompt_timezone_choice(update)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_main_menu(update, "Главное меню")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_main_menu(update, HELP)


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            settings = survey_service.get_settings(session, user.id)
            if settings is None:
                return
            settings.notifications_enabled = False
        scheduler_service.schedule_user(context.application, user, settings)
        logger.info("Пользователь tg=%s поставил на паузу", tg_id)
    except Exception:
        logger.exception("Ошибка в /pause")
    await _send_main_menu(update, PAUSE_OK)


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    try:
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            settings = survey_service.get_settings(session, user.id)
            if settings is None:
                return
            settings.notifications_enabled = True
        scheduler_service.schedule_user(context.application, user, settings)
        logger.info("Пользователь tg=%s возобновил уведомления", tg_id)
    except Exception:
        logger.exception("Ошибка в /resume")
    await _send_main_menu(update, RESUME_OK)


async def reply_menu_router(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Роутер нажатий reply-клавиатуры. Кнопка 'Добавить запись' обрабатывается
    отдельно — как entry point ConversationHandler в survey.py."""
    from bot.handlers.export import export_command
    from bot.handlers.settings import settings_command
    from bot.handlers.stats import stats_command

    text = (update.message.text or "").strip()

    if text == BTN_STATS:
        await stats_command(update, context)
    elif text == BTN_EXPORT:
        await export_command(update, context)
    elif text == BTN_SETTINGS:
        await settings_command(update, context)
    elif text == BTN_HELP:
        await help_command(update, context)
    elif text == BTN_PAUSE:
        await pause_command(update, context)
    elif text == BTN_RESUME:
        await resume_command(update, context)
