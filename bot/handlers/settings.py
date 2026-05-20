import logging

from telegram import Update
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
from bot.handlers.timezone import prompt_timezone_choice
from bot.keyboards.settings_keyboards import (
    frequency_keyboard,
    settings_menu_keyboard,
)
from bot.services import scheduler_service, survey_service
from bot.utils.timezones import label_for_timezone
from bot.texts import (
    SETTINGS_END_PROMPT,
    SETTINGS_FREQ_PROMPT,
    SETTINGS_HEADER,
    SETTINGS_INVALID_FREQ,
    SETTINGS_INVALID_RANGE,
    SETTINGS_INVALID_TIME,
    SETTINGS_START_PROMPT,
    SETTINGS_UPDATED,
)
from bot.utils.time_utils import parse_time
from bot.utils.validators import validate_frequency

logger = logging.getLogger(__name__)

AWAIT_START_TIME, AWAIT_END_TIME = range(2)


def _format_settings(user, settings) -> str:
    notif = "включены" if settings.notifications_enabled else "выключены"
    rem = "включено" if settings.reminder_enabled else "выключено"
    tz_label = label_for_timezone(user.timezone)
    tz_line = (
        f"Часовой пояс: {tz_label} ({user.timezone})"
        if tz_label != user.timezone
        else f"Часовой пояс: {user.timezone}"
    )
    return (
        SETTINGS_HEADER
        + f"Частота опросов: {settings.frequency_per_day} раз в день\n"
        + f"Промежуток: {settings.start_time.strftime('%H:%M')}–"
        + f"{settings.end_time.strftime('%H:%M')}\n"
        + tz_line + "\n"
        + f"Повторное напоминание: {rem}\n"
        + f"Уведомления: {notif}"
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    with session_scope() as session:
        user = survey_service.get_or_create_user(session, tg_id, config.DEFAULT_TIMEZONE)
        settings = survey_service.get_settings(session, user.id)
        text = _format_settings(user, settings)
        markup = settings_menu_keyboard(
            settings.notifications_enabled, settings.reminder_enabled
        )
    await update.message.reply_text(text, reply_markup=markup)


async def settings_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int | None:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]
    tg_id = update.effective_user.id

    if action == "freq":
        await query.message.reply_text(
            SETTINGS_FREQ_PROMPT, reply_markup=frequency_keyboard()
        )
        return None

    if action == "start":
        await query.message.reply_text(SETTINGS_START_PROMPT)
        return AWAIT_START_TIME

    if action == "end":
        await query.message.reply_text(SETTINGS_END_PROMPT)
        return AWAIT_END_TIME

    if action == "tz":
        await prompt_timezone_choice(update)
        return None

    if action in ("toggle_notif", "toggle_rem"):
        with session_scope() as session:
            user = survey_service.get_or_create_user(
                session, tg_id, config.DEFAULT_TIMEZONE
            )
            settings = survey_service.get_settings(session, user.id)
            if action == "toggle_notif":
                settings.notifications_enabled = not settings.notifications_enabled
            else:
                settings.reminder_enabled = not settings.reminder_enabled
        scheduler_service.schedule_user(context.application, user, settings)
        with session_scope() as session:
            user = survey_service.get_user_by_tg(session, tg_id)
            settings = survey_service.get_settings(session, user.id)
            text = _format_settings(user, settings)
            markup = settings_menu_keyboard(
                settings.notifications_enabled, settings.reminder_enabled
            )
        await query.message.reply_text(text, reply_markup=markup)
        return None

    return None


async def frequency_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    try:
        value = int(query.data.split(":")[1])
    except ValueError:
        return
    if not validate_frequency(value):
        await query.message.reply_text(SETTINGS_INVALID_FREQ)
        return
    tg_id = update.effective_user.id
    with session_scope() as session:
        user = survey_service.get_or_create_user(session, tg_id, config.DEFAULT_TIMEZONE)
        settings = survey_service.get_settings(session, user.id)
        settings.frequency_per_day = value
    scheduler_service.schedule_user(context.application, user, settings)
    await query.message.reply_text(SETTINGS_UPDATED)
    await settings_command_via_callback(update, context)


async def settings_command_via_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    tg_id = update.effective_user.id
    with session_scope() as session:
        user = survey_service.get_user_by_tg(session, tg_id)
        settings = survey_service.get_settings(session, user.id)
        text = _format_settings(user, settings)
        markup = settings_menu_keyboard(
            settings.notifications_enabled, settings.reminder_enabled
        )
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(text, reply_markup=markup)


# ----- text inputs (mini-conversation) -----

async def receive_start_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    t = parse_time(update.message.text)
    if t is None:
        await update.message.reply_text(SETTINGS_INVALID_TIME)
        return AWAIT_START_TIME
    tg_id = update.effective_user.id
    with session_scope() as session:
        user = survey_service.get_or_create_user(session, tg_id, config.DEFAULT_TIMEZONE)
        settings = survey_service.get_settings(session, user.id)
        if t >= settings.end_time:
            await update.message.reply_text(SETTINGS_INVALID_RANGE)
            return AWAIT_START_TIME
        settings.start_time = t
    scheduler_service.schedule_user(context.application, user, settings)
    await update.message.reply_text(SETTINGS_UPDATED)
    return ConversationHandler.END


async def receive_end_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    t = parse_time(update.message.text)
    if t is None:
        await update.message.reply_text(SETTINGS_INVALID_TIME)
        return AWAIT_END_TIME
    tg_id = update.effective_user.id
    with session_scope() as session:
        user = survey_service.get_or_create_user(session, tg_id, config.DEFAULT_TIMEZONE)
        settings = survey_service.get_settings(session, user.id)
        if t <= settings.start_time:
            await update.message.reply_text(SETTINGS_INVALID_RANGE)
            return AWAIT_END_TIME
        settings.end_time = t
    scheduler_service.schedule_user(context.application, user, settings)
    await update.message.reply_text(SETTINGS_UPDATED)
    return ConversationHandler.END


def build_settings_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                settings_menu_callback,
                pattern=r"^set:(start|end)$",
            ),
        ],
        states={
            AWAIT_START_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_start_time)
            ],
            AWAIT_END_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_end_time)
            ],
        },
        fallbacks=[CommandHandler("cancel", _cancel)],
        name="settings_conversation",
        persistent=False,
    )


async def _cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END
