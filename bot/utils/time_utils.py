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
