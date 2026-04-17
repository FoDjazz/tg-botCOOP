"""
keyboards/reviews_kb.py

Клавиатуры для системы оценок, комментариев и обзоров.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import RATING_LABELS


# === ВЫБОР ИГРЫ ===

def select_game_keyboard(games: list) -> InlineKeyboardMarkup:
    """
    Список игр для оценки/обзора.
    games — список строк из media_items или games.
    """
    builder = InlineKeyboardBuilder()
    for item in games:
        builder.button(
            text=f"{item['emoji']} {item['title']}" if 'emoji' in item.keys() else item['title'],
            callback_data=f"rev:select:{item['id']}"
        )
    builder.button(text="❌ Отмена", callback_data="rev:cancel")
    builder.adjust(1)
    return builder.as_markup()


# === ВЫБОР ОЦЕНКИ ===

def rating_keyboard(media_item_id: int) -> InlineKeyboardMarkup:
    """Кнопки выбора оценки."""
    buttons = [
        [InlineKeyboardButton(
            text=RATING_LABELS['trash'],
            callback_data=f"rev:rate:{media_item_id}:trash"
        )],
        [InlineKeyboardButton(
            text=RATING_LABELS['ok'],
            callback_data=f"rev:rate:{media_item_id}:ok"
        )],
        [InlineKeyboardButton(
            text=RATING_LABELS['good'],
            callback_data=f"rev:rate:{media_item_id}:good"
        )],
        [InlineKeyboardButton(
            text=RATING_LABELS['masterpiece'],
            callback_data=f"rev:rate:{media_item_id}:masterpiece"
        )],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="rev:back_to_games")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === ПОСЛЕ ОЦЕНКИ ===

def after_rating_keyboard(media_item_id: int) -> InlineKeyboardMarkup:
    """Что делать после оценки: закончить / комментарий / обзор."""
    buttons = [
        [InlineKeyboardButton(
            text="✅ Готово",
            callback_data=f"rev:done:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="💬 Написать комментарий",
            callback_data=f"rev:comment:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="📝 Написать обзор",
            callback_data=f"rev:review:{media_item_id}"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === РЕЖИМ НАПИСАНИЯ ОБЗОРА ===

def review_mode_keyboard(media_item_id: int) -> InlineKeyboardMarkup:
    """Выбор режима написания обзора: сам или по вопросам."""
    buttons = [
        [InlineKeyboardButton(
            text="✍️ Напишу сам",
            callback_data=f"rev:write_free:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="🎯 По вопросам",
            callback_data=f"rev:write_guided:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"rev:back_after_rating:{media_item_id}"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === ПОДТВЕРЖДЕНИЕ ОБЗОРА ===

def confirm_review_keyboard(media_item_id: int) -> InlineKeyboardMarkup:
    """Показывается после генерации обзора — опубликовать / переписать / выбросить."""
    buttons = [
        [InlineKeyboardButton(
            text="✅ Опубликовать",
            callback_data=f"rev:publish:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="✏️ Редактировать",
            callback_data=f"rev:edit:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="🗑 Выбросить",
            callback_data=f"rev:discard:{media_item_id}"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === ПРОСМОТР ОБЗОРОВ — СПИСОК ИГР ===

def games_with_reviews_keyboard(items: list) -> InlineKeyboardMarkup:
    """Список игр у которых есть обзоры."""
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(
            text=item['title'],
            callback_data=f"rev:view_game:{item['id']}"
        )
    builder.button(text="❌ Закрыть", callback_data="rev:cancel")
    builder.adjust(1)
    return builder.as_markup()


# === ПРОСМОТР ОБЗОРОВ — СПИСОК АВТОРОВ ===

def review_authors_keyboard(contributors: list, media_item_id: int) -> InlineKeyboardMarkup:
    """
    Список авторов — все кто оставил оценку/комментарий/обзор.
    contributors — результат get_all_contributors().
    """
    builder = InlineKeyboardBuilder()
    for user in contributors:
        name = user['display_name'] or user['username'] or str(user['user_id'])
        builder.button(
            text=f"👤 {name}",
            callback_data=f"rev:read:{media_item_id}:{user['user_id']}"
        )
    builder.button(
        text="⬅️ Назад",
        callback_data="rev:back_to_games_list"
    )
    builder.adjust(1)
    return builder.as_markup()


def back_to_games_keyboard() -> InlineKeyboardMarkup:
    """Простая кнопка назад к списку игр."""
    buttons = [
        [InlineKeyboardButton(
            text="⬅️ К списку игр",
            callback_data="rev:back_to_games_list"
        )],
        [InlineKeyboardButton(
            text="🏠 В меню",
            callback_data="rev:cancel"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === ЧТЕНИЕ ОБЗОРА ===

def read_review_keyboard(media_item_id: int) -> InlineKeyboardMarkup:
    """Кнопки под прочитанным обзором."""
    buttons = [
        [InlineKeyboardButton(
            text="⬅️ К списку авторов",
            callback_data=f"rev:view_game:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="🏠 В меню",
            callback_data="rev:cancel"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === МОЯ СТРАНИЦА ИГРЫ (центральный экран после оценки) ===

def my_game_page_keyboard(media_item_id: int,
                           has_comment: bool = False,
                           has_review: bool = False) -> InlineKeyboardMarkup:
    """
    Центральный экран после оценки.
    Кнопки меняют текст в зависимости от того что уже есть.
    """
    buttons = [
        [InlineKeyboardButton(
            text="✏️ Изменить оценку",
            callback_data=f"rev:change_rating:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="💬 Изменить комментарий" if has_comment else "💬 Написать комментарий",
            callback_data=f"rev:comment:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="📝 Редактировать обзор" if has_review else "📝 Написать обзор",
            callback_data=f"rev:review:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="✅ Готово",
            callback_data=f"rev:done:{media_item_id}"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === АДМИН: РАССЫЛКА ПОСЛЕ ПРОХОЖДЕНИЯ ===


def completed_game_keyboard(media_item_id: int) -> InlineKeyboardMarkup:
    """Кнопки для админа после отметки игры пройденной."""
    buttons = [
        [InlineKeyboardButton(
            text="📢 Попросить всех оценить",
            callback_data=f"rev:notify_all:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="⬅️ В меню",
            callback_data="rev:cancel"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === АДМИН: ПИНГ ТЕХ КТО НЕ НАПИСАЛ ОБЗОР ===

def ping_reviews_keyboard(media_item_id: int) -> InlineKeyboardMarkup:
    """Кнопка пинга пользователей без обзора."""
    buttons = [
        [InlineKeyboardButton(
            text="🔔 Напомнить написать обзор",
            callback_data=f"rev:ping:{media_item_id}"
        )],
        [InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="rev:cancel"
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
