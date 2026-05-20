"""Список таймзон для выбора пользователем + маппинг короткий-ключ -> IANA."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Короткие ключи нужны, потому что telegram callback_data ограничен 64 байтами
# и желательно сократить нагрузку. Сами IANA-имена хранятся отдельно.
# Несколько городов могут указывать на одну IANA-зону (Москва и Питер).
TIMEZONE_CALLBACK_MAP: dict[str, dict[str, str]] = {
    # --- основная страница ---
    "tz:msk": {"label": "Москва", "timezone": "Europe/Moscow"},
    "tz:spb": {"label": "Санкт-Петербург", "timezone": "Europe/Moscow"},
    "tz:ekb": {"label": "Екатеринбург", "timezone": "Asia/Yekaterinburg"},
    "tz:nsk": {"label": "Новосибирск", "timezone": "Asia/Novosibirsk"},
    "tz:kra": {"label": "Красноярск", "timezone": "Asia/Krasnoyarsk"},
    "tz:irk": {"label": "Иркутск", "timezone": "Asia/Irkutsk"},
    "tz:vvo": {"label": "Владивосток", "timezone": "Asia/Vladivostok"},
    # --- доп. страница ---
    "tz:stk": {"label": "Стокгольм", "timezone": "Europe/Stockholm"},
    "tz:ber": {"label": "Берлин", "timezone": "Europe/Berlin"},
    "tz:lon": {"label": "Лондон", "timezone": "Europe/London"},
    "tz:ist": {"label": "Стамбул", "timezone": "Europe/Istanbul"},
    "tz:dxb": {"label": "Дубай", "timezone": "Asia/Dubai"},
    "tz:tbs": {"label": "Тбилиси", "timezone": "Asia/Tbilisi"},
    "tz:evn": {"label": "Ереван", "timezone": "Asia/Yerevan"},
    "tz:ala": {"label": "Алматы", "timezone": "Asia/Almaty"},
}

# Порядок отображения. Разделение на страницы — UI-решение, не функциональное.
TZ_PAGE_MAIN: list[str] = [
    "tz:msk", "tz:spb", "tz:ekb", "tz:nsk",
    "tz:kra", "tz:irk", "tz:vvo",
]
TZ_PAGE_MORE: list[str] = [
    "tz:stk", "tz:ber", "tz:lon", "tz:ist",
    "tz:dxb", "tz:tbs", "tz:evn", "tz:ala",
]


def is_valid_iana_timezone(name: str) -> bool:
    """True, если zoneinfo знает такое имя."""
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def label_for_timezone(tz_name: str) -> str:
    """Подбирает читабельную подпись по IANA-имени. Если нет в маппинге —
    возвращает само имя (это нормально, например для пользователя с кастомной TZ)."""
    for entry in TIMEZONE_CALLBACK_MAP.values():
        if entry["timezone"] == tz_name:
            return entry["label"]
    return tz_name
