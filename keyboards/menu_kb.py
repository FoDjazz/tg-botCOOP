"""
Reply-клавиатуры меню (нижнее меню).
"""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    """Основное меню админа — чистое, только управление."""
    buttons = [
        [KeyboardButton(text="📢 Анонс"), KeyboardButton(text="➕ Создать анонс")],
        [KeyboardButton(text="👥 Участники"), KeyboardButton(text="🎮 Игры")],
        [KeyboardButton(text="👤 Функции игрока"), KeyboardButton(text="⚙️ Настройки")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def player_functions_keyboard() -> ReplyKeyboardMarkup:
    """Подменю с пользовательскими функциями (для админа)."""
    buttons = [
        [KeyboardButton(text="🎲 Предложить игру"), KeyboardButton(text="🚫 Сегодня не играю")],
        [KeyboardButton(text="⬅️ Назад в меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def user_menu_keyboard() -> ReplyKeyboardMarkup:
    """Меню обычного пользователя."""
    buttons = [
        [KeyboardButton(text="🎮 Анонсы"), KeyboardButton(text="🎲 Предложить игру")],
        [KeyboardButton(text="🚫 Сегодня не играю")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Стартовое меню с одной кнопкой."""
    buttons = [
        [KeyboardButton(text="📋 Меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
