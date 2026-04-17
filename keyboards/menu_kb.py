"""
Reply-клавиатуры меню (нижнее меню).
Разное для админа и обычного пользователя.
"""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    """Нижнее меню для админа — управление ботом."""
    buttons = [
        [KeyboardButton(text="📢 Анонс"), KeyboardButton(text="➕ Создать анонс")],
        [KeyboardButton(text="👥 Участники"), KeyboardButton(text="🎮 Игры")],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="👤 Меню пользователя")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def admin_player_keyboard() -> ReplyKeyboardMarkup:
    """Подменю для админа в режиме игрока — те же функции что у пользователя."""
    buttons = [
        [KeyboardButton(text="🎮 Анонсы"), KeyboardButton(text="🎲 Предложить игру")],
        [KeyboardButton(text="⭐ Оценить игру"), KeyboardButton(text="📖 Обзоры")],
        [KeyboardButton(text="🚫 Сегодня не играю")],
        [KeyboardButton(text="⬅️ Назад в меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def user_menu_keyboard() -> ReplyKeyboardMarkup:
    """Нижнее меню для обычного пользователя."""
    buttons = [
        [KeyboardButton(text="🎮 Анонсы"), KeyboardButton(text="🎲 Предложить игру")],
        [KeyboardButton(text="⭐ Оценить игру"), KeyboardButton(text="📖 Обзоры")],
        [KeyboardButton(text="🚫 Сегодня не играю")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Стартовое меню с одной кнопкой."""
    buttons = [
        [KeyboardButton(text="📋 Меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def player_functions_keyboard() -> ReplyKeyboardMarkup:
    """Псевдоним для совместимости."""
    return admin_player_keyboard()
