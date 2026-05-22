from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytz


def compute_schedule(
    frequency_per_day: int, start_time: time, end_time: time
) -> list[time]:
    """Возвращает равномерно распределенные времена опросов.

    end_time входит в расписание. Если frequency_per_day == 1,
    отправляем только в start_time.
    """
    if frequency_per_day < 1:
        return []
    if frequency_per_day == 1:
        return [start_time]

    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    if end_minutes <= start_minutes:
        return [start_time]

    step = (end_minutes - start_minutes) / (frequency_per_day - 1)
    result: list[time] = []
    for i in range(frequency_per_day):
        m = round(start_minutes + step * i)
        result.append(time(hour=m // 60, minute=m % 60))
    return result


def get_tz(tz_name: str) -> pytz.BaseTzInfo:
    try:
        return pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        return pytz.timezone("Europe/Moscow")


def parse_time(value: str) -> time | None:
    """Парсит строку HH:MM в time. None, если формат неверный."""
    value = value.strip()
    if len(value) != 5 or value[2] != ":":
        return None
    try:
        hh = int(value[:2])
        mm = int(value[3:])
    except ValueError:
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return time(hour=hh, minute=mm)


def now_in_tz(tz_name: str) -> datetime:
    return datetime.now(get_tz(tz_name))


def user_local_date(tz_name: str) -> date:
    """Текущая дата в TZ пользователя. Используется для проверок 'сегодня'."""
    return datetime.now(ZoneInfo(tz_name)).date()


def user_local_now(tz_name: str) -> datetime:
    """Текущий момент в TZ пользователя (timezone-aware datetime).

    Используется там, где нужны и дата, и время в локальной зоне (например,
    чтобы решить, можно ли уже спрашивать про сон — см. can_ask_sleep_question).
    """
    return datetime.now(ZoneInfo(tz_name))


# Самое позднее время суток, после которого даже у "сов" с поздним
# notification_time уже можно спрашивать про сон. Если первый слот стоит
# на 21:00, спросить «как спал» в 21:00 — поздно; ориентируемся хотя бы
# на 10:00 локального утра.
DEFAULT_SLEEP_ASK_TIME = time(10, 0)


def can_ask_sleep_question(
    local_now: datetime,
    first_survey_time: time | None,
    has_main_sleep_today: bool,
) -> bool:
    """Можно ли сейчас задавать блок sleep.

    Правила:
      1. Если основной сон за текущую локальную дату уже записан — нет.
      2. Иначе вопрос можно задавать только начиная с
         sleep_question_start_time = min(first_survey_time, DEFAULT_SLEEP_ASK_TIME).
         Это защита от случая «полночь+, новая дата уже наступила, но
         пользователь ещё не ложился» — мы не должны его дёргать с
         «как спал», пока не наступило утро.

    Если first_survey_time не задан (нет UserSettings), используем
    DEFAULT_SLEEP_ASK_TIME как порог.
    """
    if has_main_sleep_today:
        return False

    if first_survey_time is None:
        threshold = DEFAULT_SLEEP_ASK_TIME
    else:
        threshold = min(first_survey_time, DEFAULT_SLEEP_ASK_TIME)

    return local_now.time() >= threshold


def period_start(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


def get_next_notification_utc(user_timezone: str, notification_time: time) -> datetime:
    """Возвращает ближайший в будущем момент `notification_time` в TZ пользователя,
    приведённый к UTC. Полезно для логов и тестов: расписание у PTB задаётся напрямую
    в локальной TZ через JobQueue.run_daily, отдельный пересчёт там не нужен.
    """
    tz = ZoneInfo(user_timezone)
    now_local = datetime.now(tz)
    target_local = datetime.combine(now_local.date(), notification_time, tzinfo=tz)
    if target_local <= now_local:
        target_local += timedelta(days=1)
    return target_local.astimezone(ZoneInfo("UTC"))
