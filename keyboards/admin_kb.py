"""
Inline-клавиатуры для админ-панели.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder  # ВОТ ЭТУ СТРОКУ ДОБАВЬ
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def admin_announce_keyboard(announcement_id: int) -> InlineKeyboardMarkup:
    """Кнопки управления конкретным анонсом."""
    buttons = [
        [InlineKeyboardButton(
            text="✏️ Изменить время",
            callback_data=f"adm:edit_time:{announcement_id}"
        )],
        [InlineKeyboardButton(
            text="👥 Изменить участников",
            callback_data=f"adm:edit_users:{announcement_id}"
        )],
        [InlineKeyboardButton(
            text="❌ Отменить анонс",
            callback_data=f"adm:cancel_confirm:{announcement_id}"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_select_announce_keyboard(announcements):
    builder = InlineKeyboardBuilder()
    
    for ann in announcements:
        # Убираем .get() и используем обычные скобки []
        date_str = ann['announce_date'] if ann['announce_date'] else ""
        time_str = ann['start_time'] if ann['start_time'] else ""
        
        # Формируем текст кнопки: Дата Время (Статус)
        status = "⏳" if not ann['message_id'] else "📨"
        btn_text = f"{status} #{ann['id']} — {date_str} {time_str}"
        
        builder.button(
            text=btn_text,
            callback_data=f"adm:show_announce:{ann['id']}"
        )
    
    builder.adjust(1)
    return builder.as_markup()


def confirm_cancel_keyboard(announcement_id: int) -> InlineKeyboardMarkup:
    """Подтверждение отмены анонса."""
    buttons = [
        [
            InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"adm:cancel_yes:{announcement_id}"),
            InlineKeyboardButton(text="⬅️ Нет, назад", callback_data=f"adm:cancel_no:{announcement_id}"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_settings_keyboard(notify_gather: bool, notify_remind: bool) -> InlineKeyboardMarkup:
    """Настройки уведомлений с чекбоксами."""
    gather_icon = "☑️" if notify_gather else "⬜"
    remind_icon = "☑️" if notify_remind else "⬜"
    buttons = [
        [InlineKeyboardButton(
            text=f"{gather_icon} Напоминание о сборе (10 мин)",
            callback_data="adm:toggle_notify_gather"
        )],
        [InlineKeyboardButton(
            text=f"{remind_icon} Напоминание проголосовать (30 мин)",
            callback_data="adm:toggle_notify_remind"
        )],
        [InlineKeyboardButton(
            text="♻️ Привести обзоры в порядок",
            callback_data="adm:reformat_reviews"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_edit_time_keyboard(announcement_id: int, hour: int, minute: int) -> InlineKeyboardMarkup:
    """Редактирование времени для админа."""
    buttons = [
        [InlineKeyboardButton(
            text=f"⏰ {hour:02d}:{minute:02d}",
            callback_data="adm_time_display"
        )],
        [
            InlineKeyboardButton(text="−1 час", callback_data=f"adm_time:{announcement_id}:-1h"),
            InlineKeyboardButton(text="+1 час", callback_data=f"adm_time:{announcement_id}:+1h"),
        ],
        [
            InlineKeyboardButton(text="−10 мин", callback_data=f"adm_time:{announcement_id}:-10m"),
            InlineKeyboardButton(text="+10 мин", callback_data=f"adm_time:{announcement_id}:+10m"),
        ],
        [InlineKeyboardButton(
            text="✏️ Ввести вручную",
            callback_data=f"adm_time:{announcement_id}:manual"
        )],
        [InlineKeyboardButton(
            text="✅ Сохранить",
            callback_data=f"adm_time:{announcement_id}:save"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_edit_participants_keyboard(users: list, selected_ids: list[int],
                                      announcement_id: int) -> InlineKeyboardMarkup:
    """Редактирование участников для админа."""
    buttons = []
    for user in users:
        uid = user['user_id']
        name = user['display_name'] or user['username'] or str(uid)
        prefix = "✅ " if uid in selected_ids else "⬜ "
        buttons.append([InlineKeyboardButton(
            text=f"{prefix}{name}",
            callback_data=f"adm_toggle_user:{announcement_id}:{uid}"
        )])
    buttons.append([
        InlineKeyboardButton(text="✅ Все", callback_data=f"adm_select_all:{announcement_id}"),
        InlineKeyboardButton(text="⬜ Сброс", callback_data=f"adm_deselect_all:{announcement_id}"),
    ])
    buttons.append([InlineKeyboardButton(
        text="💾 Сохранить",
        callback_data=f"adm_save_users:{announcement_id}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_games_list_keyboard(games: list) -> InlineKeyboardMarkup:
    """Список игр с кнопками удаления."""
    buttons = []
    for game in games:
        buttons.append([
            InlineKeyboardButton(
                text=f"{game['emoji']} {game['name']}",
                callback_data=f"adm_game_noop:{game['id']}"
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"adm_del_game:{game['id']}"
            ),
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_delete_game_keyboard(game_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления игры."""
    buttons = [
        [
            InlineKeyboardButton(text="✅ Удалить", callback_data=f"adm_del_game_yes:{game_id}"),
            InlineKeyboardButton(text="⬅️ Отмена", callback_data="adm_del_game_no"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_users_list_keyboard(users: list) -> InlineKeyboardMarkup:
    """Список пользователей с кнопками удаления."""
    buttons = []
    for user in users:
        uid = user['user_id']
        name = user['display_name'] or user['username'] or str(uid)
        uname = f" (@{user['username']})" if user['username'] else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{name}{uname}",
                callback_data=f"adm_user_noop:{uid}"
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"adm_del_user:{uid}"
            ),
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_delete_user_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления пользователя."""
    buttons = [
        [
            InlineKeyboardButton(text="✅ Удалить", callback_data=f"adm_del_user_yes:{user_id}"),
            InlineKeyboardButton(text="⬅️ Отмена", callback_data="adm_del_user_no"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
