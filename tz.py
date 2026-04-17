"""
Хелпер для часового пояса.
Все модули импортируют now() отсюда вместо datetime.now().
"""

from datetime import datetime, timezone, timedelta
from config import TIMEZONE_OFFSET_HOURS

# Часовой пояс как объект
TZ = timezone(timedelta(hours=TIMEZONE_OFFSET_HOURS))


def now() -> datetime:
    """Возвращает текущее время в настроенном часовом поясе (без tzinfo, naive)."""
    # Возвращаем naive datetime чтобы корректно сравнивать с данными из БД
    return datetime.now(TZ).replace(tzinfo=None)
