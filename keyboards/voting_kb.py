"""
Клавиатура голосования под анонсом.
Кнопки меняют текст на прикольные варианты когда ВСЕ проголосовали.
"""

import random
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Варианты текстов кнопок после того как ВСЕ проголосовали ✅
FUN_YES_TEXTS = [
    "Готов к игре ⚔️",
    "Я в деле 😎",
    "С братвой 🎮",
    "Вперёд в бой 💪",
    "Заряжен 🔋",
]

FUN_NO_TEXTS = [
    "Стать воздуханом 💨",
    "Я вентилятор 💨",
    "Кинуть братву 💨",
    "Сдуться 💨",
    "Испариться 💨",
]


def voting_keyboard(announcement_id: int, all_voted: bool = False) -> InlineKeyboardMarkup:
    """
    Кнопки голосования.
    all_voted=False → стандартные ✅ Буду / ❌ Не смогу
    all_voted=True  → рандомные прикольные тексты
    """
    if all_voted:
        yes_text = random.choice(FUN_YES_TEXTS)
        no_text = random.choice(FUN_NO_TEXTS)
    else:
        yes_text = "✅ Буду"
        no_text = "❌ Не смогу"

    buttons = [
        [
            InlineKeyboardButton(
                text=yes_text,
                callback_data=f"vote:yes:{announcement_id}"
            ),
            InlineKeyboardButton(
                text=no_text,
                callback_data=f"vote:no:{announcement_id}"
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
