import logging
import re

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.config import config, setup_logging
from bot.handlers.common import error_handler
from bot.handlers.export import export_handlers
from bot.handlers.settings import (
    build_settings_conversation,
    frequency_callback,
    settings_command,
    settings_menu_callback,
)
from bot.handlers.start import (
    help_command,
    menu_command,
    pause_command,
    reply_menu_router,
    resume_command,
    start_command,
)
from bot.keyboards.main_menu import (
    BTN_EXPORT,
    BTN_HELP,
    BTN_PAUSE,
    BTN_RESUME,
    BTN_SETTINGS,
    BTN_STATS,
)
from bot.handlers.add_sleep import build_add_sleep_conversation
from bot.handlers.custom_questions import (
    build_cq_create_conversation,
    build_cq_list_entry,
    build_cq_rename_conversation,
    build_cq_router,
)
from bot.handlers.edit_meds import build_edit_meds_conversation
from bot.handlers.question_settings import build_qs_handler
from bot.handlers.stats import stats_handlers
from bot.handlers.survey import (
    build_survey_conversation,
    unfinished_choice_callback,
)
from bot.handlers.timezone import build_timezone_handler
from bot.services import scheduler_service

logger = logging.getLogger(__name__)


async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Запуск бота"),
            BotCommand("menu", "Главное меню"),
            BotCommand("help", "Помощь"),
            BotCommand("add", "Добавить запись"),
            BotCommand("add_sleep", "Добавить ещё один сон"),
            BotCommand("edit_meds", "Изменить лекарства за сегодня"),
            BotCommand("settings", "Настройки уведомлений"),
            BotCommand("stats", "Статистика"),
            BotCommand("export", "Экспорт в Excel"),
            BotCommand("pause", "Отключить уведомления"),
            BotCommand("resume", "Включить уведомления"),
        ]
    )
    scheduler_service.schedule_cleanup(application)
    scheduler_service.reschedule_all(application)
    logger.info("Бот запущен")


def main() -> None:
    setup_logging()
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в окружении")

    builder = Application.builder().token(config.BOT_TOKEN).post_init(_post_init)
    if config.HTTPS_PROXY:
        # PTB 21 принимает proxy на отдельных Request-объектах для get/post.
        logger.info("Используется HTTPS-прокси для Telegram API")
        builder = builder.proxy(config.HTTPS_PROXY).get_updates_proxy(config.HTTPS_PROXY)
    application = builder.build()

    # Опрос — ставим первым, чтобы перехватывать survey:start раньше прочих.
    application.add_handler(build_survey_conversation())
    application.add_handler(build_add_sleep_conversation())
    application.add_handler(build_edit_meds_conversation())
    application.add_handler(
        CallbackQueryHandler(unfinished_choice_callback, pattern=r"^unfinished:")
    )

    # Команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("pause", pause_command))
    application.add_handler(CommandHandler("resume", resume_command))

    # Reply-меню у поля ввода: ловим нажатия по точному тексту кнопок.
    # Кнопку BTN_ADD ловит ConversationHandler опроса как entry point.
    menu_texts = [BTN_STATS, BTN_EXPORT, BTN_SETTINGS, BTN_HELP, BTN_PAUSE, BTN_RESUME]
    menu_regex = "^(" + "|".join(re.escape(t) for t in menu_texts) + ")$"
    application.add_handler(
        MessageHandler(filters.Regex(menu_regex), reply_menu_router)
    )

    # Настройки
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(build_settings_conversation())
    application.add_handler(
        CallbackQueryHandler(
            settings_menu_callback,
            pattern=r"^set:(freq|tz|toggle_notif|toggle_rem|close)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(frequency_callback, pattern=r"^freq:\d+$")
    )

    # Настройка частоты прохождения опроса (раз в день/неделю/2 недели/N дней).
    # Custom-days FSM ставим первым, чтобы перехватить freq2:custom.
    from bot.handlers.survey_frequency import (
        build_custom_days_conversation,
        build_frequency_open_handler,
        build_frequency_router,
    )
    application.add_handler(build_custom_days_conversation())
    application.add_handler(build_frequency_open_handler())
    application.add_handler(build_frequency_router())

    # Выбор часового пояса (onboarding + смена из настроек).
    application.add_handler(build_timezone_handler())

    # Настройки вопросов опроса.
    application.add_handler(build_qs_handler())

    # Пользовательские вопросы. ConversationHandlers первыми — они владеют
    # cq:add и cq:rename:N, остальные cq:* идёт в общий роутер.
    application.add_handler(build_cq_create_conversation())
    application.add_handler(build_cq_rename_conversation())
    application.add_handler(build_cq_list_entry())
    application.add_handler(build_cq_router())

    # Статистика и экспорт
    for h in stats_handlers():
        application.add_handler(h)
    for h in export_handlers():
        application.add_handler(h)

    application.add_error_handler(error_handler)

    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
