"""
Клавиатуры для создания анонса.
Добавлено: кнопка «Назад», выбор даты, ручной ввод времени.
"""

from datetime import datetime, timedelta
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from tz import now as tz_now


def games_keyboard(games: list) -> InlineKeyboardMarkup:
    """Клавиатура выбора игры. Показывает список + 'Добавить новую' + 'Назад'."""
    buttons = []
    for game in games:
        buttons.append([InlineKeyboardButton(
            text=f"{game['emoji']} {game['name']}",
            callback_data=f"select_game:{game['id']}"
        )])
    buttons.append([InlineKeyboardButton(
        text="➕ Добавить новую игру",
        callback_data="add_new_game"
    )])
    # Назад — к шагу загрузки картинки
    buttons.append([InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="back_to_photo"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def date_selection_keyboard() -> InlineKeyboardMarkup:
    """Выбор даты анонса: Сегодня / Завтра / Выбрать дату + Назад."""
    today = tz_now()
    tomorrow = today + timedelta(days=1)
    buttons = [
        [InlineKeyboardButton(
            text=f"📅 Сегодня ({today.strftime('%d.%m')})",
            callback_data=f"ann_date:today:{today.strftime('%Y-%m-%d')}"
        )],
        [InlineKeyboardButton(
            text=f"📅 Завтра ({tomorrow.strftime('%d.%m')})",
            callback_data=f"ann_date:tomorrow:{tomorrow.strftime('%Y-%m-%d')}"
        )],
        [InlineKeyboardButton(
            text="📆 Выбрать дату",
            callback_data="ann_date:pick:0"
        )],
        [InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_to_game"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def announce_date_picker_keyboard(start_offset: int = 0) -> InlineKeyboardMarkup:
    """Карусель дат для создания анонса (аналог reschedule)."""
    today = tz_now()
    buttons = []
    weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    row = []
    for i in range(start_offset, start_offset + 5):
        day = today + timedelta(days=i)  # начинаем с сегодня
        day_str = day.strftime("%d.%m")
        weekday = weekday_names[day.weekday()]
        row.append(InlineKeyboardButton(
            text=f"{weekday} {day_str}",
            callback_data=f"ann_date:exact:{day.strftime('%Y-%m-%d')}"
        ))
    buttons.append(row)

    # Навигация
    nav_row = []
    if start_offset > 0:
        nav_row.append(InlineKeyboardButton(
            text="⬅️ Раньше",
            callback_data=f"ann_date:pick:{start_offset - 5}"
        ))
    nav_row.append(InlineKeyboardButton(
        text="➡️ Позже",
        callback_data=f"ann_date:pick:{start_offset + 5}"
    ))
    buttons.append(nav_row)

    # Назад к выбору даты
    buttons.append([InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="back_to_date_select"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def time_picker_keyboard(hour: int, minute: int) -> InlineKeyboardMarkup:
    """Клавиатура настройки времени: кнопка-часы, +/-, ручной ввод, назад."""
    buttons = [
        # Текущее время — нажимаемая кнопка
        [InlineKeyboardButton(
            text=f"⏰ {hour:02d}:{minute:02d}",
            callback_data="time_display"
        )],
        # Часы
        [
            InlineKeyboardButton(text="−1 час", callback_data="time:-1h"),
            InlineKeyboardButton(text="+1 час", callback_data="time:+1h"),
        ],
        # Минуты
        [
            InlineKeyboardButton(text="−10 мин", callback_data="time:-10m"),
            InlineKeyboardButton(text="+10 мин", callback_data="time:+10m"),
        ],
        # Ручной ввод
        [InlineKeyboardButton(
            text="✏️ Ввести вручную",
            callback_data="time:manual"
        )],
        # Подтверждение + Назад
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_date"),
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="time:confirm"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def participants_keyboard(users: list, selected_ids: list[int]) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора участников. Множественный выбор.
    Выбранные отмечаются галочкой ✅. Есть кнопка «Назад».
    """
    buttons = []
    for user in users:
        uid = user['user_id']
        name = user['display_name'] or user['username'] or str(uid)
        prefix = "✅ " if uid in selected_ids else "⬜ "
        buttons.append([InlineKeyboardButton(
            text=f"{prefix}{name}",
            callback_data=f"toggle_user:{uid}"
        )])

    # Кнопки управления
    buttons.append([
        InlineKeyboardButton(text="✅ Выбрать всех", callback_data="select_all_users"),
        InlineKeyboardButton(text="⬜ Сбросить", callback_data="deselect_all_users"),
    ])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_time"),
        InlineKeyboardButton(text="📢 Опубликовать", callback_data="confirm_participants"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
