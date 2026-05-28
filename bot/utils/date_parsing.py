"""Парсер пользовательского ввода даты.

Поддерживает:
  - 'сегодня', 'вчера' (RU);
  - 'today', 'yesterday' (EN, на всякий случай);
  - DD.MM.YYYY;
  - DD.MM (год берётся из local_today; если получившаяся дата в будущем
    более чем на 30 дней — пробуем предыдущий год);
  - YYYY-MM-DD.

Возвращает date или None. Дальнейшую валидацию (не будущее, не старее N лет,
не пересекается с открытым периодом) делает вызывающий код, не парсер.
"""
import re
from datetime import date, timedelta

_RE_DOT_FULL = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_RE_DOT_SHORT = re.compile(r"^(\d{1,2})\.(\d{1,2})$")
_RE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")

# Если DD.MM даёт дату в будущем больше, чем на этот зазор — считаем, что
# пользователь имел в виду прошлый год.
_FUTURE_GAP_DAYS = 30


def parse_user_date(text: str, local_today: date) -> date | None:
    raw = (text or "").strip().lower()
    if not raw:
        return None

    if raw in ("сегодня", "today"):
        return local_today
    if raw in ("вчера", "yesterday"):
        return local_today - timedelta(days=1)
    if raw in ("позавчера",):
        return local_today - timedelta(days=2)

    m = _RE_DOT_FULL.match(raw)
    if m:
        return _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))

    m = _RE_ISO.match(raw)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _RE_DOT_SHORT.match(raw)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        d = _safe_date(local_today.year, month, day)
        if d is None:
            return None
        # Если получилось далёкое будущее (например, в январе ввели "30.12"),
        # значит, скорее всего, имелся в виду прошлый год.
        if (d - local_today).days > _FUTURE_GAP_DAYS:
            d = _safe_date(local_today.year - 1, month, day)
        return d

    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None
