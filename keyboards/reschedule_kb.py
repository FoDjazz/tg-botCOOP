"""
Клавиатуры для переноса игровой сессии.
Добавлено: кнопки «Назад», кнопка «Изменить время» в ЛС.
"""

from datetime import datetime, timedelta
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from tz import now as tz_now


def reschedule_when_keyboard(announcement_id: int) -> InlineKeyboardMarkup:
    """Когда сможешь? Быстрый выбор."""
    today = tz_now()
    tomorrow = today + timedelta(days=1)

    buttons = [
        [InlineKeyboardButton(
            text="🕐 Сегодня позже",
            callback_data=f"resched:today:{announcement_id}"
        )],
        [InlineKeyboardButton(
            text=f"📅 Завтра ({tomorrow.strftime('%d.%m')})",
            callback_data=f"resched:tomorrow:{announcement_id}"
        )],
        [InlineKeyboardButton(
            text="📆 Выбрать дату",
            callback_data=f"resched:pick_date:{announcement_id}"
        )],
        [InlineKeyboardButton(
            text="🤷‍♂️ Не знаю когда",
            callback_data=f"resched:idk_when:{announcement_id}"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def date_picker_keyboard(announcement_id: int, start_offset: int = 0) -> InlineKeyboardMarkup:
    """Карусель выбора даты — показывает 5 ближайших дней + Назад."""
    today = tz_now()
    buttons = []
    weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    row = []
    for i in range(start_offset, start_offset + 5):
        day = today + timedelta(days=i + 1)
        day_str = day.strftime("%d.%m")
        weekday = weekday_names[day.weekday()]
        row.append(InlineKeyboardButton(
            text=f"{weekday} {day_str}",
            callback_data=f"resched:date:{announcement_id}:{day.strftime('%Y-%m-%d')}"
        ))
    buttons.append(row)

    # Навигация
    nav_row = []
    if start_offset > 0:
        nav_row.append(InlineKeyboardButton(
            text="⬅️ Раньше",
            callback_data=f"resched:nav:{announcement_id}:{start_offset - 5}"
        ))
    nav_row.append(InlineKeyboardButton(
        text="➡️ Позже",
        callback_data=f"resched:nav:{announcement_id}:{start_offset + 5}"
    ))
    buttons.append(nav_row)

    # Кнопка назад — вернуться к выбору «Сегодня/Завтра/Дата»
    buttons.append([InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data=f"resched:back_when:{announcement_id}"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def time_picker_reschedule_keyboard(announcement_id: int, date_str: str,
                                      hour: int = 20, minute: int = 0) -> InlineKeyboardMarkup:
    """Выбор времени для переноса + Назад."""
    buttons = [
        [InlineKeyboardButton(
            text=f"⏰ {hour:02d}:{minute:02d}",
            callback_data="resched_time_display"
        )],
        [
            InlineKeyboardButton(text="−1 час", callback_data=f"resched_time:{announcement_id}:{date_str}:-1h"),
            InlineKeyboardButton(text="+1 час", callback_data=f"resched_time:{announcement_id}:{date_str}:+1h"),
        ],
        [
            InlineKeyboardButton(text="−10 мин", callback_data=f"resched_time:{announcement_id}:{date_str}:-10m"),
            InlineKeyboardButton(text="+10 мин", callback_data=f"resched_time:{announcement_id}:{date_str}:+10m"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"resched:back_when:{announcement_id}"),
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"resched_time:{announcement_id}:{date_str}:confirm"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def edit_reschedule_keyboard(announcement_id: int) -> InlineKeyboardMarkup:
    """Кнопка 'Изменить время' — показывается после сохранения переноса в ЛС."""
    buttons = [
        [InlineKeyboardButton(
            text="✏️ Изменить время",
            callback_data=f"resched:edit_time:{announcement_id}"
        )]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
