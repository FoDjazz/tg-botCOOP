"""
handlers/reviews.py

Полный флоу системы оценок и обзоров:
  1. Выбор игры
  2. Оценка (trash / ok / good / masterpiece)
  3. После оценки: закончить / комментарий / обзор
  4. Обзор: свободный текст или 4 вопроса → генерация → подтверждение

Просмотр обзоров:
  Список игр → список авторов → чтение обзора

Админ:
  Отметить игру пройденной → рассылка → пинг без обзора
"""

import json
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import database as db
from config import ADMIN_ID, REVIEWS_TOPIC_ID
from services.review_builder import build_review
from keyboards.reviews_kb import (
    select_game_keyboard,
    rating_keyboard,
    after_rating_keyboard,
    review_mode_keyboard,
    confirm_review_keyboard,
    games_with_reviews_keyboard,
    review_authors_keyboard,
    read_review_keyboard,
    completed_game_keyboard,
    ping_reviews_keyboard,
    back_to_games_keyboard,
    my_game_page_keyboard,
)
from keyboards.menu_kb import user_menu_keyboard, admin_menu_keyboard

router = Router()


def _format_review_text(game_emoji: str, game_name: str, rating_label: str,
                         author: str, review_text: str,
                         comment: str | None = None) -> str:
    """Красивое форматирование обзора для публикации в группу."""
    text = (
        f"{game_emoji} <b>{game_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ Оценка: {rating_label}\n"
        f"✍️ Автор: {author}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    if comment:
        text += f"💬 <i>Комментарий:</i> {comment}\n\n"
    text += review_text
    return text




async def _show_my_game_page(target, user_id: int, media_item_id: int,
                               game_name: str, game_emoji: str, state: FSMContext):
    """
    Показывает центральный экран «Моя страница» для игры.
    target — CallbackQuery или Message.
    Редактирует сообщение если возможно, иначе отправляет новое.
    """
    from database import RATING_LABELS
    rating_row = await db.get_rating(media_item_id, user_id)
    comment_row = await db.get_comment(media_item_id, user_id)
    review_row = await db.get_review(media_item_id, user_id)

    rating_label = RATING_LABELS.get(rating_row['rating'], '—') if rating_row else '—'
    has_comment = bool(comment_row and comment_row['text'])
    has_review = bool(review_row and review_row['final_text'])

    lines = [f"{game_emoji} <b>{game_name}</b>", f"Оценка: {rating_label}"]
    if has_comment:
        lines.append(f"Комментарий: ✅")
    if has_review:
        lines.append(f"Обзор: ✅")

    text = "\n".join(lines)
    kb = my_game_page_keyboard(media_item_id, has_comment, has_review)

    await state.set_state(ReviewForm.after_rating)

    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


async def _clear_buttons(callback: CallbackQuery):
    """Убирает кнопки у текущего сообщения."""
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


logger = logging.getLogger(__name__)


# ============================================================
# FSM
# ============================================================

class ReviewForm(StatesGroup):
    # Выбор игры
    selecting_game = State()    # Шаг 0: список игр с кнопками

    # После оценки — выбор действия
    after_rating = State()      # Шаг 2.5: закончить/комментарий/обзор

    # Выбор режима обзора
    choosing_mode = State()     # Шаг 3: свободный или по вопросам

    # Вопросы (5 новых)
    q_hook      = State()   # Шаг 1: одним предложением — что за игра
    q_moment    = State()   # Шаг 2: конкретный момент
    q_liked     = State()   # Шаг 3: за что кайфовал
    q_disliked  = State()   # Шаг 4: что раздражало
    q_verdict   = State()   # Шаг 5: кому посоветуешь

    # Свободный обзор
    free_text = State()

    # Редактирование после предпросмотра
    edit_text = State()

    # Комментарий
    comment_text = State()


# Вопросы для guided режима (5 вопросов)
QUESTIONS = {
    ReviewForm.q_hook: (
        "🎮 Вопрос 1/5\n\n"
        "Одним предложением — что это за игра?\n"
        "Как бы объяснил другу который вообще не знает про неё?"
    ),
    ReviewForm.q_moment: (
        "⚡ Вопрос 2/5\n\n"
        "Вспомни один конкретный момент — эпичный, смешной или бесячий.\n"
        "Что первым всплывает в памяти?"
    ),
    ReviewForm.q_liked: (
        "👍 Вопрос 3/5\n\n"
        "За что кайфовал?\n"
        "Механика, атмосфера, персонажи, кооп — что зашло?"
    ),
    ReviewForm.q_disliked: (
        "😬 Вопрос 4/5\n\n"
        "Что раздражало или бесило?\n"
        "Если ничего — напиши что именно простил и почему."
    ),
    ReviewForm.q_verdict: (
        "🎯 Вопрос 5/5\n\n"
        "Твой вердикт по игре — стоит ли оно того?\n"
        "Можно кратко: «огонь», «мусор», «на один раз», «только в кооп» — как угодно."
    ),
}


# ============================================================
# ТОЧКИ ВХОДА
# ============================================================

@router.message(F.text == "⭐ Оценить игру")
async def start_rating(message: Message, state: FSMContext):
    """Кнопка из меню — начало флоу оценки."""
    await state.clear()

    # Собираем список игр: берём из media_items + games для эмодзи
    games = await db.get_all_games()
    if not games:
        await message.answer("Список игр пуст. Сначала добавь игры через анонсы.")
        return

    # Строим список для клавиатуры — добавляем id и title
    items = []
    for g in games:
        items.append({
            "id":    g['id'],
            "title": g['name'],
            "emoji": g['emoji'],
        })

    await state.set_state(ReviewForm.selecting_game)
    await message.answer(
        "⭐ Выбери игру для оценки:",
        reply_markup=select_game_keyboard(items)
    )


# Кнопки меню которые должны работать даже в FSM состоянии
_MENU_BUTTONS = {
    "📋 Меню", "⭐ Оценить игру", "📖 Обзоры", "🎮 Анонсы",
    "🎲 Предложить игру", "🚫 Сегодня не играю", "⬅️ Назад в меню",
    "👤 Я как игрок", "🏁 Мы прошли игру",
}

@router.message(ReviewForm.selecting_game)
async def selecting_game_text_guard(message: Message, state: FSMContext):
    """Сценарий 16: защита от текста на шаге выбора игры.
    Пропускаем команды и кнопки меню — они сбросят FSM сами."""
    if not message.text:
        return
    if message.text.startswith("/"):
        return
    # Кнопки меню — сбрасываем FSM и пропускаем дальше
    if message.text in _MENU_BUTTONS:
        await state.clear()
        return
    await message.answer("⚠️ Выбери игру кнопкой выше.")


@router.message(F.text == "📖 Обзоры")
async def start_view_reviews(message: Message, state: FSMContext):
    """Кнопка из меню — просмотр обзоров."""
    await state.clear()
    items = await db.get_media_items_with_content()
    if not items:
        await message.answer("Пока никто ничего не оценивал 😔")
        return
    await message.answer(
        "📖 Выбери игру:",
        reply_markup=games_with_reviews_keyboard(items)
    )


# ============================================================
# ШАГ 1: ВЫБОР ИГРЫ
# ============================================================

@router.callback_query(F.data.startswith("rev:select:"))
async def select_game(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал игру."""
    game_id = int(callback.data.split(":")[2])
    game = await db.get_game(game_id)
    if not game:
        await callback.answer("Игра не найдена", show_alert=True)
        return

    # Находим или создаём media_item
    item = await db.get_media_item_by_game_id(game_id)
    if not item:
        media_item_id = await db.create_media_item(
            game_id=game_id,
            title=game['name'],
            created_by=callback.from_user.id
        )
    else:
        media_item_id = item['id']

    await state.update_data(
        media_item_id=media_item_id,
        game_name=game['name'],
        game_emoji=game['emoji'],
    )

    # Если оценка уже есть — сразу на "Мою страницу", не заставляем оценивать заново
    existing = await db.get_rating(media_item_id, callback.from_user.id)
    if existing:
        await _show_my_game_page(
            callback, callback.from_user.id, media_item_id,
            game['name'], game['emoji'], state
        )
    else:
        await callback.message.edit_text(
            f"{game['emoji']} {game['name']}\n\nПоставь оценку:",
            reply_markup=rating_keyboard(media_item_id)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("rev:change_rating:"))
async def change_rating(callback: CallbackQuery, state: FSMContext):
    """Изменить оценку — показываем клавиатуру выбора оценки."""
    media_item_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    game_name = data.get("game_name", "игра")
    game_emoji = data.get("game_emoji", "🎮")
    await callback.message.edit_text(
        f"{game_emoji} {game_name}\n\nВыбери новую оценку:",
        reply_markup=rating_keyboard(media_item_id)
    )
    await callback.answer()


@router.callback_query(F.data == "rev:back_to_games")
async def back_to_games(callback: CallbackQuery, state: FSMContext):
    """Назад к списку игр."""
    games = await db.get_all_games()
    items = [{"id": g['id'], "title": g['name'], "emoji": g['emoji']} for g in games]
    await callback.message.edit_text(
        "⭐ Выбери игру для оценки:",
        reply_markup=select_game_keyboard(items)
    )
    await callback.answer()


# ============================================================
# ШАГ 2: ОЦЕНКА
# ============================================================

@router.callback_query(F.data.startswith("rev:rate:"))
async def set_rating(callback: CallbackQuery, state: FSMContext):
    """Пользователь поставил оценку."""
    parts = callback.data.split(":")
    media_item_id = int(parts[2])
    rating = parts[3]

    success = await db.set_rating(media_item_id, callback.from_user.id, rating)
    if not success:
        await callback.answer("Неверная оценка", show_alert=True)
        return

    from database import RATING_LABELS
    label = RATING_LABELS.get(rating, rating)

    data = await state.get_data()
    game_name = data.get("game_name", "игра")

    await callback.answer(f"Оценка сохранена: {label}")
    logger.info(f"user_id={callback.from_user.id} оценил media_item={media_item_id}: {rating}")

    # Обновляем опубликованный обзор в топике если есть
    review_row = await db.get_review(media_item_id, callback.from_user.id)
    if review_row and review_row['published_message_id'] and review_row['final_text']:
        try:
            from config import GROUP_CHAT_ID
            data2 = await state.get_data()
            g_name  = data2.get("game_name", "игра")
            g_emoji = data2.get("game_emoji", "🎮")
            user = callback.from_user
            author = f"@{user.username}" if user.username else user.first_name
            comment_row2 = await db.get_comment(media_item_id, callback.from_user.id)
            comment_text2 = comment_row2['text'] if comment_row2 and comment_row2['text'] else None
            pub_text = _format_review_text(g_emoji, g_name, label, author, review_row['final_text'], comment=comment_text2)
            await callback.bot.edit_message_text(
                chat_id=review_row['published_chat_id'],
                message_id=review_row['published_message_id'],
                text=pub_text,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Не удалось обновить обзор после смены оценки: {e}")

    data = await state.get_data()
    await _show_my_game_page(
        callback, callback.from_user.id, media_item_id,
        data.get("game_name", "игра"), data.get("game_emoji", "🎮"), state
    )


# ============================================================
# ПОСЛЕ ОЦЕНКИ: три пути
# ============================================================

@router.callback_query(F.data.startswith("rev:done:"))
async def rating_done(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал Готово — закрываем флоу оценки."""
    await state.clear()
    try:
        await callback.message.edit_text("✅ Готово! Спасибо за оценку 🎮")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("rev:back_after_rating:"))
async def back_after_rating(callback: CallbackQuery, state: FSMContext):
    """Назад к выбору: закончить / комментарий / обзор."""
    media_item_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    game_name = data.get("game_name", "игра")
    await callback.message.edit_text(
        f"Что добавишь к «{game_name}»?",
        reply_markup=after_rating_keyboard(media_item_id)
    )
    await callback.answer()


# ============================================================
# ПУТЬ А: КОММЕНТАРИЙ
# ============================================================

@router.callback_query(F.data.startswith("rev:comment:"))
async def start_comment(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал написать комментарий."""
    media_item_id = int(callback.data.split(":")[2])
    await state.update_data(media_item_id=media_item_id)
    await state.set_state(ReviewForm.comment_text)

    # Показываем текущий комментарий если есть
    existing = await db.get_comment(media_item_id, callback.from_user.id)
    if existing:
        hint = f"Твой текущий комментарий:\n«{existing['text']}»\n\nНапиши новый чтобы заменить:"
    else:
        hint = "Напиши короткий комментарий (до 500 символов):\n\n/cancel для отмены"

    await callback.message.edit_text(hint)
    await callback.answer()


@router.message(ReviewForm.comment_text)
async def process_comment(message: Message, state: FSMContext):
    """Получили комментарий — валидируем и сохраняем."""
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("↩️ Отменено.")
        return

    text = " ".join(message.text.strip().split()) if message.text else ""

    if len(text) < 3:
        await message.answer("Напиши хоть пару слов 🙂")
        return
    if len(text) > 500:
        await message.answer("Слишком длинно, покороче 😅 (максимум 500 символов)")
        return

    data = await state.get_data()
    media_item_id = data['media_item_id']

    await db.set_comment(media_item_id, message.from_user.id, text)
    logger.info(f"user_id={message.from_user.id} написал комментарий к media_item={media_item_id}")

    # Удаляем сообщение пользователя чтобы не засорять чат
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    game_name = data.get("game_name", "игра")
    game_emoji = data.get("game_emoji", "🎮")

    # Возвращаем на "Мою страницу" — редактируем предыдущее сообщение бота
    await _show_my_game_page(
        message, message.from_user.id, media_item_id,
        game_name, game_emoji, state
    )


# ============================================================
# ПУТЬ Б: ОБЗОР
# ============================================================

@router.callback_query(F.data.startswith("rev:review:"))
async def start_review(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал написать обзор."""
    media_item_id = int(callback.data.split(":")[2])
    await state.update_data(media_item_id=media_item_id)

    await state.set_state(ReviewForm.choosing_mode)
    await callback.message.edit_text(
        "📝 Как будешь писать обзор?",
        reply_markup=review_mode_keyboard(media_item_id)
    )
    await callback.answer()


# --- Свободный текст ---

@router.callback_query(F.data.startswith("rev:write_free:"))
async def write_free(callback: CallbackQuery, state: FSMContext):
    """Режим свободного текста."""
    media_item_id = int(callback.data.split(":")[2])
    await state.update_data(media_item_id=media_item_id, review_mode="free")
    await state.set_state(ReviewForm.free_text)

    existing = await db.get_review(media_item_id, callback.from_user.id)
    if existing:
        hint = (
            f"Твой текущий обзор:\n\n«{existing['final_text']}»\n\n"
            "Напиши новый чтобы заменить:\n\n/cancel для отмены"
        )
    else:
        hint = (
            "✍️ Пиши свободно — впечатления, фишки, что запомнилось.\n"
            "Без спойлеров 🙂\n\n/cancel для отмены"
        )

    await callback.message.edit_text(hint)
    await callback.answer()


@router.message(ReviewForm.free_text)
async def process_free_text(message: Message, state: FSMContext):
    """Получили свободный обзор."""
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("↩️ Отменено.")
        return

    text = " ".join(message.text.strip().split()) if message.text else ""

    if len(text) < 3:
        await message.answer("Напиши хоть пару слов 🙂")
        return
    if len(text) > 2000:
        await message.answer("Слишком длинно, покороче 😅 (максимум 2000 символов)")
        return

    data = await state.get_data()
    media_item_id = data['media_item_id']
    await state.update_data(draft_text=text)

    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(
        f"📝 Вот твой обзор:\n\n{text}\n\nОпубликовать?",
        reply_markup=confirm_review_keyboard(media_item_id)
    )


# --- Обзор по вопросам ---

@router.callback_query(F.data.startswith("rev:write_guided:"))
async def write_guided(callback: CallbackQuery, state: FSMContext):
    """Запускаем guided режим — первый вопрос."""
    media_item_id = int(callback.data.split(":")[2])
    await state.update_data(media_item_id=media_item_id, review_mode="guided")
    await state.set_state(ReviewForm.q_hook)

    await callback.message.edit_text(
        QUESTIONS[ReviewForm.q_hook] + "\n\n/cancel для отмены"
    )
    await callback.answer()


def _validate_answer(text: str) -> str | None:
    """Возвращает None если OK, иначе текст ошибки."""
    if len(text) < 3:
        return "Напиши хоть пару слов 🙂"
    if len(text) > 500:
        return "Слишком длинно, покороче 😅 (максимум 500 символов)"
    return None


@router.message(ReviewForm.q_hook)
async def process_q1(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("↩️ Отменено.")
        return
    text = " ".join(message.text.strip().split()) if message.text else ""
    err = _validate_answer(text)
    if err:
        await message.answer(err)
        return
    await state.update_data(q_hook=text)
    await state.set_state(ReviewForm.q_moment)
    await message.answer(QUESTIONS[ReviewForm.q_moment])


@router.message(ReviewForm.q_moment)
async def process_q2(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("↩️ Отменено.")
        return
    text = " ".join(message.text.strip().split()) if message.text else ""
    err = _validate_answer(text)
    if err:
        await message.answer(err)
        return
    await state.update_data(q_moment=text)
    await state.set_state(ReviewForm.q_liked)
    await message.answer(QUESTIONS[ReviewForm.q_liked])


@router.message(ReviewForm.q_liked)
async def process_q3(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("↩️ Отменено.")
        return
    text = " ".join(message.text.strip().split()) if message.text else ""
    err = _validate_answer(text)
    if err:
        await message.answer(err)
        return
    await state.update_data(q_liked=text)
    await state.set_state(ReviewForm.q_disliked)
    await message.answer(QUESTIONS[ReviewForm.q_disliked])


@router.message(ReviewForm.q_disliked)
async def process_q4(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("↩️ Отменено.")
        return
    text = " ".join(message.text.strip().split()) if message.text else ""
    err = _validate_answer(text)
    if err:
        await message.answer(err)
        return
    await state.update_data(q_disliked=text)
    await state.set_state(ReviewForm.q_verdict)
    await message.answer(QUESTIONS[ReviewForm.q_verdict])


@router.message(ReviewForm.q_verdict)
async def process_q5(message: Message, state: FSMContext, bot: Bot):
    """Последний вопрос — генерируем обзор."""
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("↩️ Отменено.")
        return

    text = " ".join(message.text.strip().split()) if message.text else ""
    err = _validate_answer(text)
    if err:
        await message.answer(err)
        return

    await state.update_data(q_verdict=text)
    data = await state.get_data()

    answers = {
        "hook":     data['q_hook'],
        "moment":   data['q_moment'],
        "liked":    data['q_liked'],
        "disliked": data['q_disliked'],
        "verdict":  text,
    }
    await state.update_data(answers=answers)

    wait_msg = await message.answer("⏳ Собираю обзор...")

    try:
        from config import GEMINI_API_KEY
        try:
            from config import GROQ_API_KEY
        except ImportError:
            GROQ_API_KEY = None
        api_key = GEMINI_API_KEY if GEMINI_API_KEY else None
        groq_key = GROQ_API_KEY if GROQ_API_KEY else None
    except ImportError:
        api_key = None

    draft = await build_review(answers, api_key=api_key, groq_key=groq_key)
    await state.update_data(draft_text=draft)

    try:
        await bot.delete_message(message.chat.id, wait_msg.message_id)
    except Exception:
        pass

    media_item_id = data['media_item_id']
    await message.answer(
        f"📝 Вот что получилось:\n\n{draft}\n\nОпубликовать?",
        reply_markup=confirm_review_keyboard(media_item_id)
    )


# ============================================================
# ПОДТВЕРЖДЕНИЕ ОБЗОРА
# ============================================================

@router.callback_query(F.data.startswith("rev:publish:"))
async def publish_review(callback: CallbackQuery, state: FSMContext):
    """Публикуем обзор."""
    media_item_id = int(callback.data.split(":")[2])
    data = await state.get_data()

    draft_text = data.get("draft_text", "")
    answers    = data.get("answers")
    answers_json = json.dumps(answers, ensure_ascii=False) if answers else None

    await db.set_review(
        media_item_id=media_item_id,
        user_id=callback.from_user.id,
        final_text=draft_text,
        answers_json=answers_json,
    )
    await state.clear()

    # Публикуем в топик обзоров если настроен
    game_name = data.get("game_name", "игра")
    game_emoji = data.get("game_emoji", "🎮")
    user = callback.from_user
    author = f"@{user.username}" if user.username else user.first_name

    # Получаем оценку пользователя
    rating_row = await db.get_rating(media_item_id, callback.from_user.id)
    from database import RATING_LABELS
    rating_label = RATING_LABELS.get(rating_row['rating'], "") if rating_row else ""

    # Красивое форматирование
    # Получаем комментарий если есть
    comment_row = await db.get_comment(media_item_id, callback.from_user.id)
    comment_text = comment_row['text'] if comment_row and comment_row['text'] else None

    pub_text = _format_review_text(game_emoji, game_name, rating_label, author, draft_text, comment=comment_text)

    try:
        from config import GROUP_CHAT_ID, REVIEWS_TOPIC_ID

        # Проверяем — публиковал ли уже обзор этот пользователь
        existing = await db.get_review(media_item_id, callback.from_user.id)
        pub_msg_id  = existing['published_message_id'] if existing else None
        pub_chat_id = existing['published_chat_id'] if existing else None

        sent = None
        if pub_msg_id and pub_chat_id:
            # Редактируем старое сообщение вместо нового
            try:
                await callback.bot.edit_message_text(
                    chat_id=pub_chat_id,
                    message_id=pub_msg_id,
                    text=pub_text,
                    parse_mode="HTML",
                )
                class _Sent:
                    message_id = pub_msg_id
                    class chat:
                        id = pub_chat_id
                sent = _Sent()
            except Exception:
                pass

        if sent is None:
            # Публикуем новое сообщение
            send_kwargs = {"chat_id": GROUP_CHAT_ID, "text": pub_text, "parse_mode": "HTML"}
            if REVIEWS_TOPIC_ID:
                send_kwargs["message_thread_id"] = REVIEWS_TOPIC_ID
            sent = await callback.bot.send_message(**send_kwargs)

        # Сохраняем message_id для будущих редактирований
        await db.update_review_message_id(
            media_item_id, callback.from_user.id,
            sent.message_id, sent.chat.id
        )

    except Exception as e:
        logger.warning(f"Не удалось опубликовать обзор в группу: {e}")

    logger.info(f"user_id={callback.from_user.id} опубликовал обзор к media_item={media_item_id}")
    await callback.answer("✅ Обзор опубликован!")

    await _show_my_game_page(
        callback, callback.from_user.id, media_item_id,
        game_name, game_emoji, state
    )


@router.callback_query(F.data.startswith("rev:edit:"))
async def edit_review(callback: CallbackQuery, state: FSMContext):
    """Пользователь хочет отредактировать обзор вручную."""
    media_item_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    draft = data.get("draft_text", "")

    await state.update_data(media_item_id=media_item_id)
    await state.set_state(ReviewForm.edit_text)
    await callback.message.edit_text(
        f"Текущий вариант:\n\n«{draft}»\n\n"
        "Напиши исправленный текст:\n\n/cancel для отмены"
    )
    await callback.answer()


@router.message(ReviewForm.edit_text)
async def process_edit_text(message: Message, state: FSMContext):
    """Получили отредактированный текст."""
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("↩️ Отменено.")
        return

    text = " ".join(message.text.strip().split()) if message.text else ""
    if len(text) < 3:
        await message.answer("Напиши хоть пару слов 🙂")
        return
    if len(text) > 2000:
        await message.answer("Слишком длинно, покороче 😅")
        return

    data = await state.get_data()
    media_item_id = data['media_item_id']
    await state.update_data(draft_text=text)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(
        f"📝 Обновлённый обзор:\n\n{text}\n\nОпубликовать?",
        reply_markup=confirm_review_keyboard(media_item_id)
    )


@router.callback_query(F.data.startswith("rev:discard:"))
async def discard_review(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбросил обзор."""
    media_item_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    await callback.answer("🗑 Обзор отменён")
    await _show_my_game_page(
        callback, callback.from_user.id, media_item_id,
        data.get("game_name", "игра"), data.get("game_emoji", "🎮"), state
    )


# ============================================================
# ПРОСМОТР ОБЗОРОВ
# ============================================================

@router.callback_query(F.data.startswith("rev:view_game:"))
async def view_game_reviews(callback: CallbackQuery, state: FSMContext):
    """Список авторов — все кто оценил или написал комментарий/обзор."""
    media_item_id = int(callback.data.split(":")[2])
    item = await db.get_media_item(media_item_id)
    if not item:
        await callback.answer("Игра не найдена", show_alert=True)
        return

    # Оценка комьюнити
    community_key = await db.get_community_rating(media_item_id)
    from database import RATING_LABELS
    if community_key:
        rating_line = f"Оценка от комьюнити: {RATING_LABELS[community_key]}"
        total = sum((await db.get_ratings_summary(media_item_id)).values())
        rating_line += f" ({total} {'голос' if total == 1 else 'голоса' if 2 <= total <= 4 else 'голосов'})"
    else:
        rating_line = "Оценок пока нет"

    # Все кто хоть что-то оставил
    contributors = await db.get_all_contributors(media_item_id)

    if not contributors:
        try:
            await callback.message.edit_text(
                f"🎮 {item['title']}\n\n{rating_line}\n\nНикто ещё ничего не написал.",
                reply_markup=back_to_games_keyboard()
            )
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                raise
        await callback.answer()
        return

    try:
        await callback.message.edit_text(
            f"🎮 {item['title']}\n\n"
            f"{rating_line}\n\n"
            f"Выбери автора:",
            reply_markup=review_authors_keyboard(contributors, media_item_id)
        )
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise
    await callback.answer()


@router.callback_query(F.data.startswith("rev:read:"))
async def read_review(callback: CallbackQuery, state: FSMContext):
    """Читаем всё что оставил автор: оценку + комментарий + обзор."""
    parts = callback.data.split(":")
    media_item_id = int(parts[2])
    author_id     = int(parts[3])

    item = await db.get_media_item(media_item_id)
    author = await db.get_user(author_id)
    author_name = (
        f"@{author['username']}" if author and author['username']
        else (author['display_name'] if author else str(author_id))
    )

    from database import RATING_LABELS
    rating_row = await db.get_rating(media_item_id, author_id)
    rating_label = RATING_LABELS.get(rating_row['rating'], "") if rating_row else ""

    comment_row = await db.get_comment(media_item_id, author_id)
    review_row  = await db.get_review(media_item_id, author_id)

    # Собираем текст
    text = f"🎮 <b>{item['title']}</b>\n"
    text += f"Автор: {author_name}\n"
    if rating_label:
        text += f"Оценка: {rating_label}\n"

    if comment_row:
        text += f"\n💬 <b>Комментарий:</b>\n{comment_row['text']}"

    if review_row:
        text += f"\n\n📝 <b>Обзор:</b>\n{review_row['final_text']}"

    if not comment_row and not review_row:
        text += "\n\nТолько оценка, без текста."

    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=read_review_keyboard(media_item_id)
        )
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise
    await callback.answer()


@router.callback_query(F.data == "rev:back_to_games_list")
async def back_to_games_list(callback: CallbackQuery, state: FSMContext):
    """Назад к списку игр с обзорами."""
    items = await db.get_media_items_with_content()
    if not items:
        await callback.message.edit_text("Пока никто ничего не оценивал 😔")
        await callback.answer()
        return
    try:
        await callback.message.edit_text(
            "📖 Выбери игру:",
            reply_markup=games_with_reviews_keyboard(items)
        )
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise
    await callback.answer()


# ============================================================
# ЗАЩИТА ОТ ТЕКСТА НА КНОПОЧНЫХ ШАГАХ (сценарии 16, 20)
# ============================================================

@router.message(ReviewForm.after_rating)
async def after_rating_text_guard(message: Message, state: FSMContext):
    """Сценарий 16: защита от текста на шаге выбора после оценки."""
    if not message.text:
        return
    if message.text.startswith("/"):
        return
    if message.text in _MENU_BUTTONS:
        await state.clear()
        return
    await message.answer("⚠️ Используй кнопки выше.")


@router.message(ReviewForm.choosing_mode)
async def choosing_mode_text_guard(message: Message, state: FSMContext):
    """Сценарий 20: защита от текста на шаге выбора режима обзора."""
    if not message.text:
        return
    if message.text.startswith("/"):
        return
    if message.text in _MENU_BUTTONS:
        await state.clear()
        return
    await message.answer("⚠️ Выбери режим кнопкой: «Напишу сам» или «По вопросам».")


# ============================================================
# ОТМЕНА
# ============================================================

@router.callback_query(F.data == "rev:cancel")
async def cancel_review(callback: CallbackQuery, state: FSMContext):
    """Отмена / закрытие любого шага."""
    await state.clear()
    await callback.message.delete()
    await callback.answer()


# ============================================================
# АДМИН: ОТМЕТИТЬ ИГРУ ПРОЙДЕННОЙ
# (Кнопка меню убрана — функция теперь в разделе 🎮 Игры)
# Callback rev:mark_done оставлен для совместимости
# ============================================================


@router.callback_query(F.data.startswith("rev:mark_done:"))
async def admin_mark_done_select(callback: CallbackQuery, bot: Bot):
    """Выбрана игра — помечаем пройденной, не запуская флоу оценки."""
    if callback.from_user.id != ADMIN_ID:
        return

    game_id = int(callback.data.split(":")[2])
    game = await db.get_game(game_id)
    if not game:
        await callback.answer("Игра не найдена", show_alert=True)
        return

    item = await db.get_media_item_by_game_id(game_id)
    if not item:
        media_item_id = await db.create_media_item(
            game_id=game_id,
            title=game['name'],
            created_by=callback.from_user.id
        )
    else:
        media_item_id = item['id']
        if item['is_completed']:
            await callback.message.edit_text(
                f"ℹ️ «{game['name']}» уже отмечена как пройденная."
            )
            await callback.answer()
            return

    await db.mark_completed(media_item_id)

    await callback.message.edit_text(
        f"✅ «{game['name']}» отмечена как пройденная!\n\n"
        "Хочешь попросить всех оценить игру?",
        reply_markup=completed_game_keyboard(media_item_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rev:completed:"))
async def admin_mark_completed(callback: CallbackQuery, bot: Bot):
    """Оставлен для совместимости."""
    if callback.from_user.id != ADMIN_ID:
        return

    media_item_id = int(callback.data.split(":")[2])
    item = await db.get_media_item(media_item_id)
    if not item:
        await callback.answer("Игра не найдена", show_alert=True)
        return

    await db.mark_completed(media_item_id)

    await callback.message.edit_text(
        f"✅ «{item['title']}» отмечена как пройденная!\n\n"
        "Хочешь попросить всех оценить игру?",
        reply_markup=completed_game_keyboard(media_item_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rev:notify_all:"))
async def notify_all_to_rate(callback: CallbackQuery, bot: Bot):
    """Рассылка всем пользователям — оцените игру."""
    if callback.from_user.id != ADMIN_ID:
        return

    media_item_id = int(callback.data.split(":")[2])
    item = await db.get_media_item(media_item_id)
    users = await db.get_all_users()

    sent = 0
    for user in users:
        if user['user_id'] == ADMIN_ID:
            continue
        try:
            await bot.send_message(
                chat_id=user['user_id'],
                text=(
                    f"🎮 Мы прошли «{item['title']}»!\n\n"
                    "Оцени игру и напиши пару слов — "
                    "нажми «⭐ Оценить игру» в меню."
                )
            )
            sent += 1
        except Exception:
            logger.warning(f"Не удалось отправить уведомление user_id={user['user_id']}")

    if sent == 0:
        await callback.message.edit_text(
            "⚠️ Никому не удалось отправить уведомление.\n"
            "Убедитесь что участники зарегистрированы через /start",
            reply_markup=ping_reviews_keyboard(media_item_id)
        )
    else:
        await callback.message.edit_text(
            f"✅ Уведомление отправлено {sent} участникам.\n\n"
            "Нажми кнопку ниже чтобы напомнить тем кто ещё не написал обзор:",
            reply_markup=ping_reviews_keyboard(media_item_id)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("rev:ping:"))
async def ping_without_review(callback: CallbackQuery, bot: Bot):
    """Пинг тех кто оценил но не написал обзор."""
    if callback.from_user.id != ADMIN_ID:
        return

    media_item_id = int(callback.data.split(":")[2])
    item = await db.get_media_item(media_item_id)
    users = await db.get_users_without_review(media_item_id)

    if not users:
        await callback.answer("Все уже написали обзор 🎉", show_alert=True)
        return

    sent = 0
    for user in users:
        try:
            await bot.send_message(
                chat_id=user['user_id'],
                text=(
                    f"📝 Напиши обзор на «{item['title']}»!\n\n"
                    "Нажми «⭐ Оценить игру» в меню — там можно добавить обзор."
                )
            )
            sent += 1
        except Exception:
            logger.warning(f"Не удалось отправить пинг user_id={user['user_id']}")

    await callback.message.edit_text(f"✅ Напоминание отправлено {sent} участникам.")
    await callback.answer()
