"""
Reply-клавиатуры меню (нижнее меню).
Разное для админа и обычного пользователя.
"""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    """Нижнее меню для админа."""
    buttons = [
        [KeyboardButton(text="📢 Анонс"), KeyboardButton(text="➕ Создать анонс")],
        [KeyboardButton(text="👥 Участники"), KeyboardButton(text="🎮 Игры")],
        [KeyboardButton(text="🎲 Предложить игру"), KeyboardButton(text="⚙️ Настройки")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def user_menu_keyboard() -> ReplyKeyboardMarkup:
    """Нижнее меню для обычного пользователя."""
    buttons = [
        [KeyboardButton(text="🎮 Анонсы"), KeyboardButton(text="🎲 Предложить игру")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Стартовое меню с одной кнопкой."""
    buttons = [
        [KeyboardButton(text="📋 Меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
