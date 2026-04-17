import asyncio
import logging
"""
Хэндлер меню (Reply Keyboard).
Разное меню для админа и обычного пользователя.
"""

from datetime import timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import database as db
from config import ADMIN_ID, GROUP_CHAT_ID, ANNOUNCE_TOPIC_ID
from keyboards.menu_kb import admin_menu_keyboard, admin_player_keyboard, user_menu_keyboard, player_functions_keyboard
from tz import now

logger = logging.getLogger(__name__)
router = Router()


# ============================================================
# FSM — Добавление игры вручную
# ============================================================

class AddGameForm(StatesGroup):
    waiting_name   = State()   # Шаг 1: название
    waiting_emoji  = State()   # Шаг 2: emoji
    waiting_status = State()   # Шаг 3: статус (через callback)


# Кнопки меню — прерывают FSM добавления игры
_ADD_GAME_MENU_BUTTONS = {
    "📋 Меню", "⭐ Оценить игру", "📖 Обзоры", "🎮 Анонсы",
    "🎲 Предложить игру", "🚫 Сегодня не играю", "⬅️ Назад в меню",
    "👤 Меню пользователя", "📢 Анонс", "➕ Создать анонс",
    "👥 Участники", "🎮 Игры", "⚙️ Настройки",
}



def _format_date(date_str: str) -> str:
    """Форматирует дату для отображения."""
    if not date_str:
        return "Сегодня"
    try:
        from datetime import datetime
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = now().date()
        if dt == today:
            return "Сегодня"
        elif dt == today + timedelta(days=1):
            return "Завтра"
        else:
            weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            return f"{weekday_names[dt.weekday()]}, {dt.strftime('%d.%m')}"
    except ValueError:
        return date_str


@router.message(F.text == "📋 Меню")
@router.message(Command("menu"))
@router.message(F.text.lower() == "меню")
async def show_menu(message: Message, state: FSMContext):
    """Показывает меню в зависимости от роли."""
    current_state = await state.get_state()
    if current_state:
        await state.clear()

    if message.from_user.id == ADMIN_ID:
        await message.answer("👑 Админ-панель", reply_markup=admin_menu_keyboard())
    else:
        await message.answer("🎮 Меню", reply_markup=user_menu_keyboard())


# === Админ ===

@router.message(F.text == "➕ Создать анонс")
async def admin_create_announce(message: Message, state: FSMContext):
    """Кнопка создания анонса — запускает FSM."""
    if message.from_user.id != ADMIN_ID:
        return
    from handlers.announce import AnnounceForm
    await state.clear()
    await state.set_state(AnnounceForm.waiting_photo)
    await message.answer(
        "🎮 *Создание анонса*\n\n"
        "Шаг 1/5: Отправь картинку для анонса",
        parse_mode="Markdown"
    )


@router.message(F.text == "📢 Анонс")
async def admin_announce_menu(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    # Берём ВСЕ активные анонсы
    all_announcements = await db.get_all_active_announcements()

    # Фильтруем прошедшие по времени (но НЕ деактивируем — остаются в базе)
    current = now()
    announcements = []
    for ann in all_announcements:
        try:
            from datetime import datetime
            ann_dt = datetime.strptime(
                f"{ann['announce_date']} {ann['start_time']}", "%Y-%m-%d %H:%M"
            )
            if ann_dt > current:
                announcements.append(ann)
        except (ValueError, TypeError):
            announcements.append(ann)

    if not announcements:
        await message.answer("Нет активных анонсов.\n\nНажми ➕ Создать анонс")
        return

    if len(announcements) == 1:
        # Один анонс — сразу показываем управление
        announcement = announcements[0]
        game = await db.get_game(announcement['game_id'])

        if not game:
            # Игра удалена из базы — показываем без названия
            game_display = "❓ Игра удалена"
        else:
            game_display = f"🎮 {game['emoji']} {game['name']}"

        participants = await db.get_announcement_participants(announcement['id'])
        votes = await db.get_votes(announcement['id'])
        vote_map = {v['user_id']: v['vote'] for v in votes}

        yes_list, no_list, pending_list = [], [], []
        for p in participants:
            uid, uname, dname = p[0], p[1], p[2]
            display = f"@{uname}" if uname else (dname or str(uid))
            if uid in vote_map:
                (yes_list if vote_map[uid] == "yes" else no_list).append(display)
            else:
                pending_list.append(display)

        date_display = _format_date(announcement['announce_date'] or '')
        status = "📨 Опубликован" if announcement['message_id'] else "⏳ Запланирован"

        text = (
            f"📢 Анонс #{announcement['id']}\n\n"
            f"{game_display}\n"
            f"📅 {date_display}\n"
            f"⏰ {announcement['start_time']} – {announcement['end_time']}\n"
            f"Статус: {status}\n\n"
        )
        if yes_list:
            text += f"✅ Идут: {', '.join(yes_list)}\n"
        if no_list:
            text += f"❌ Не смогут: {', '.join(no_list)}\n"
        if pending_list:
            text += f"⏳ Ждём: {', '.join(pending_list)}\n"

        from keyboards.admin_kb import admin_announce_keyboard
        await message.answer(text, reply_markup=admin_announce_keyboard(announcement['id']))
    else:
        # Несколько — показываем список с датами
        from keyboards.admin_kb import admin_select_announce_keyboard
        await message.answer(
            f"📢 Найдено {len(announcements)} анонсов:",
            reply_markup=admin_select_announce_keyboard(announcements)
        )


@router.message(F.text == "👥 Участники")
async def admin_users_menu(message: Message):
    """Список участников с кнопками удаления."""
    if message.from_user.id != ADMIN_ID:
        return
    users = await db.get_all_users()
    if not users:
        await message.answer("Список пуст. Участники регистрируются через /start")
        return
    from keyboards.admin_kb import admin_users_list_keyboard
    await message.answer(
        "👥 Участники (нажми 🗑 для удаления):",
        reply_markup=admin_users_list_keyboard(users)
    )


# ============================================================
# РАЗДЕЛ «🎮 ИГРЫ»
# Все callback начинаются с gm: чтобы не конфликтовать
# ============================================================

PAGE_SIZE = 8  # игр на одной странице


def _games_text(items, games) -> str:
    """Формирует текст главного экрана Игры."""
    from database import GAME_STATUSES
    if not games and not items:
        return "🎮 Игры\n\nСписок пуст. Нажми ➕ Добавить игру."
    if items:
        lines = [f"{GAME_STATUSES.get(i['status'], '❓')} {i['title']}" for i in items]
        return "🎮 Игры:\n\n" + "\n".join(lines)
    return "🎮 Игры:\n\n" + "\n".join(f"{g['emoji']} {g['name']}" for g in games)


def _games_main_keyboard():
    """Кнопки действий на главном экране раздела Игры."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить игру",        callback_data="gm:add")],
        [InlineKeyboardButton(text="✏️ Сменить статус",      callback_data="gm:status_list:0")],
        [InlineKeyboardButton(text="🏁 Отметить пройденной", callback_data="gm:done_list:0")],
        [InlineKeyboardButton(text="🗑 Удалить игру",         callback_data="gm:delete_list")],
    ])


def _paginated_keyboard(items: list, cb_prefix: str, offset: int,
                         back_cb: str, label_fn) -> 'InlineKeyboardMarkup':
    """
    Универсальная пагинированная клавиатура.
    items      — полный список объектов
    cb_prefix  — префикс callback для кнопки выбора, напр. 'gm:status_pick'
    offset     — текущее смещение страницы
    back_cb    — callback кнопки Назад
    label_fn   — функция item -> str для текста кнопки
    """
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    page = items[offset: offset + PAGE_SIZE]
    buttons = []

    for item in page:
        buttons.append([InlineKeyboardButton(
            text=label_fn(item),
            callback_data=f"{cb_prefix}:{item['id']}"
        )])

    # Навигация — показываем только если нужна
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️", callback_data=f"{cb_prefix.rsplit(':', 1)[0]}:{offset - PAGE_SIZE}"
        ))
    if offset + PAGE_SIZE < len(items):
        nav.append(InlineKeyboardButton(
            text="➡️", callback_data=f"{cb_prefix.rsplit(':', 1)[0]}:{offset + PAGE_SIZE}"
        ))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(F.text == "🎮 Игры")
async def admin_games_menu(message: Message):
    """Главный экран раздела Игры."""
    if message.from_user.id != ADMIN_ID:
        return
    items = await db.get_all_media_items_with_status('game')
    games = await db.get_all_games()
    await message.answer(_games_text(items, games), reply_markup=_games_main_keyboard())


async def _edit_to_games_main(callback: CallbackQuery):
    """Редактирует текущее сообщение до главного экрана Игры."""
    items = await db.get_all_media_items_with_status('game')
    games = await db.get_all_games()
    try:
        await callback.message.edit_text(
            _games_text(items, games),
            reply_markup=_games_main_keyboard()
        )
    except Exception:
        pass


# ── Возврат к главному экрану ─────────────────────────────

@router.callback_query(F.data == "gm:back")
async def gm_back(callback: CallbackQuery):
    await _edit_to_games_main(callback)
    await callback.answer()


# ── Добавить игру ────────────────────────────────────────

@router.callback_query(F.data == "gm:add")
async def gm_add_start(callback: CallbackQuery, state: FSMContext):
    """Начало FSM добавления игры."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    await state.set_state(AddGameForm.waiting_name)
    await callback.message.edit_text(
        "➕ Добавление игры\n\n"
        "Шаг 1/3: Введи название игры\n\n"
        "Для отмены нажми /cancel"
    )
    await callback.answer()


@router.message(AddGameForm.waiting_name)
async def gm_add_name(message: Message, state: FSMContext):
    """Получаем название игры."""
    if not message.text:
        return
    if message.text.startswith("/"):
        await state.clear()
        await message.answer("↩️ Отменено.")
        return
    if message.text in _ADD_GAME_MENU_BUTTONS:
        await state.clear()
        return

    name = message.text.strip()
    if len(name) > 100:
        await message.answer("⚠️ Название слишком длинное (макс. 100 символов). Попробуй ещё раз:")
        return

    await state.update_data(game_name=name)
    await state.set_state(AddGameForm.waiting_emoji)
    await message.answer(
        f"➕ Добавление игры\n\n"
        f"Название: <b>{name}</b>\n\n"
        f"Шаг 2/3: Отправь один emoji для игры\n"
        f"Или /skip чтобы использовать 🎮",
        parse_mode="HTML"
    )


@router.message(AddGameForm.waiting_emoji)
async def gm_add_emoji(message: Message, state: FSMContext):
    """Получаем emoji для игры."""
    if not message.text:
        return
    if message.text.startswith("/cancel"):
        await state.clear()
        await message.answer("↩️ Отменено.")
        return
    if message.text in _ADD_GAME_MENU_BUTTONS:
        await state.clear()
        return

    data = await state.get_data()
    name = data["game_name"]

    if message.text.startswith("/skip"):
        emoji = "🎮"
    else:
        emoji = message.text.strip()
        # Простая проверка — берём первый символ
        if len(emoji) > 8:
            await message.answer("⚠️ Отправь один emoji или /skip:")
            return

    await state.update_data(game_emoji=emoji)
    await state.set_state(AddGameForm.waiting_status)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await message.answer(
        f"➕ Добавление игры\n\n"
        f"Название: <b>{name}</b>\n"
        f"Emoji: {emoji}\n\n"
        f"Шаг 3/3: Выбери статус:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Запланирована", callback_data="gm:add_status:planned")],
            [InlineKeyboardButton(text="🎮 В процессе",    callback_data="gm:add_status:in_progress")],
            [InlineKeyboardButton(text="✅ Уже пройдена",  callback_data="gm:add_status:completed")],
            [InlineKeyboardButton(text="❌ Отмена",        callback_data="gm:add_cancel")],
        ])
    )


@router.callback_query(F.data.startswith("gm:add_status:"))
async def gm_add_status(callback: CallbackQuery, state: FSMContext):
    """Финальный шаг — сохраняем игру с выбранным статусом."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return

    data = await state.get_data()
    name  = data.get("game_name", "")
    emoji = data.get("game_emoji", "🎮")
    status = callback.data.split(":")[2]

    if not name:
        await callback.answer("Данные потеряны, начни заново", show_alert=True)
        await state.clear()
        return

    # Создаём игру в games
    game_id = await db.add_game(name, emoji)

    # Создаём media_item со статусом
    media_item_id = await db.create_media_item(
        game_id=game_id,
        title=name,
        created_by=callback.from_user.id
    )
    await db.set_game_status(media_item_id, status)

    # Если добавляется как пройденная — отмечаем completed
    if status == "completed":
        await db.mark_completed_safe(media_item_id)

    await state.clear()

    from database import GAME_STATUSES
    status_label = GAME_STATUSES.get(status, "❓")
    await callback.message.edit_text(
        f"✅ Игра добавлена!\n\n"
        f"{emoji} <b>{name}</b>\n"
        f"Статус: {status_label}",
        parse_mode="HTML"
    )
    await callback.answer()

    # Возвращаем главный экран Игры через секунду
    import asyncio
    await asyncio.sleep(1.5)
    await _edit_to_games_main(callback)


@router.callback_query(F.data == "gm:add_cancel")
async def gm_add_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена добавления игры."""
    await state.clear()
    await _edit_to_games_main(callback)
    await callback.answer("Отменено")


# ── Сменить статус ────────────────────────────────────────


@router.callback_query(F.data.startswith("gm:status_list:"))
async def gm_status_list(callback: CallbackQuery):
    """Список игр для смены статуса с пагинацией."""
    from database import GAME_STATUSES
    offset = int(callback.data.split(":")[2])
    items = await db.get_all_media_items_with_status('game')
    if not items:
        await callback.answer("Список игр пуст", show_alert=True)
        return

    def label(item):
        return f"{GAME_STATUSES.get(item['status'], '❓')} {item['title']}"

    kb = _paginated_keyboard(items, "gm:status_pick", offset, "gm:back", label)
    try:
        await callback.message.edit_text("✏️ Выбери игру для смены статуса:", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("gm:status_pick:"))
async def gm_status_pick(callback: CallbackQuery):
    """Кнопки выбора нового статуса."""
    from database import GAME_STATUSES
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    media_item_id = int(callback.data.split(":")[2])
    item = await db.get_media_item(media_item_id)
    if not item:
        await callback.answer("Игра не найдена", show_alert=True)
        await asyncio.sleep(1)
        await _edit_to_games_main(callback)
        return

    current = GAME_STATUSES.get(item['status'], '❓')
    await callback.message.edit_text(
        f"🎮 {item['title']}\nСейчас: {current}\n\nВыбери новый статус:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Запланирована", callback_data=f"gm:status_set:{media_item_id}:planned")],
            [InlineKeyboardButton(text="🎮 В процессе",    callback_data=f"gm:status_set:{media_item_id}:in_progress")],
            [InlineKeyboardButton(text="✅ Пройдена",      callback_data=f"gm:status_set:{media_item_id}:completed")],
            [InlineKeyboardButton(text="⬅️ Назад",         callback_data="gm:status_list:0")],
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gm:status_set:"))
async def gm_status_set(callback: CallbackQuery):
    """Применяем новый статус и возвращаемся на главный экран."""
    from database import GAME_STATUSES
    parts = callback.data.split(":")
    media_item_id, new_status = int(parts[2]), parts[3]

    item = await db.get_media_item(media_item_id)
    if not item:
        await callback.answer("Игра не найдена", show_alert=True)
        await asyncio.sleep(1)
        await _edit_to_games_main(callback)
        return

    await db.set_game_status(media_item_id, new_status)
    label = GAME_STATUSES.get(new_status, '❓')
    await callback.answer(f"Статус → {label}")
    await _edit_to_games_main(callback)


# ── Отметить пройденной ───────────────────────────────────

@router.callback_query(F.data.startswith("gm:done_list:"))
async def gm_done_list(callback: CallbackQuery):
    """Список всех игр для отметки пройденной (включая уже пройденные)."""
    from database import GAME_STATUSES
    offset = int(callback.data.split(":")[2])
    items = await db.get_all_media_items_with_status('game')
    if not items:
        await callback.answer("Список игр пуст", show_alert=True)
        return

    def label(item):
        status = GAME_STATUSES.get(item['status'], '❓')
        return f"{status} {item['title']}"

    kb = _paginated_keyboard(items, "gm:done_pick", offset, "gm:back", label)
    try:
        await callback.message.edit_text("🏁 Какую игру прошли?", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("gm:done_pick:"))
async def gm_done_pick(callback: CallbackQuery):
    """Отмечаем игру пройденной."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    media_item_id = int(callback.data.split(":")[2])
    item = await db.get_media_item(media_item_id)
    if not item:
        await callback.answer("Игра не найдена", show_alert=True)
        await asyncio.sleep(1)
        await _edit_to_games_main(callback)
        return

    # Игра уже пройдена — предлагаем только рассылку
    if item['is_completed']:
        await callback.message.edit_text(
            f"ℹ️ «{item['title']}» уже отмечена как пройденная.\n\nПопросить всех оценить?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Попросить всех оценить", callback_data=f"gm:notify:{media_item_id}")],
                [InlineKeyboardButton(text="⬅️ Назад к играм",          callback_data="gm:back")],
            ])
        )
        await callback.answer()
        return

    # Атомарное обновление: UPDATE WHERE is_completed = 0
    updated = await db.mark_completed_safe(media_item_id)
    if not updated:
        # Кто-то успел раньше (race condition)
        await callback.answer("Уже отмечена другим действием", show_alert=True)
        await asyncio.sleep(1)
        await _edit_to_games_main(callback)
        return

    await callback.message.edit_text(
        f"✅ «{item['title']}» отмечена как пройденная!\n\nПопросить всех оценить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Попросить всех оценить", callback_data=f"gm:notify:{media_item_id}")],
            [InlineKeyboardButton(text="⬅️ Назад к играм",          callback_data="gm:back")],
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gm:notify:"))
async def gm_notify(callback: CallbackQuery, bot: Bot):
    """Рассылка всем участникам — оцените игру."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    media_item_id = int(callback.data.split(":")[2])
    item = await db.get_media_item(media_item_id)
    if not item:
        await callback.answer("Игра не найдена", show_alert=True)
        return

    users = await db.get_all_users()
    sent = 0
    for user in users:
        if user['user_id'] == ADMIN_ID:
            continue
        try:
            await bot.send_message(
                chat_id=user['user_id'],
                text=f"🎮 Мы прошли «{item['title']}»!\n\nОцени игру — нажми «⭐ Оценить игру» в меню."
            )
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)  # защита от rate limit

    total = len([u for u in users if u['user_id'] != ADMIN_ID])
    text = (
        f"✅ Уведомление отправлено {sent} из {total} участников."
        if sent > 0
        else "⚠️ Никому не отправлено. Убедись что участники зарегистрированы через /start"
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Напомнить написать обзор", callback_data=f"gm:ping:{media_item_id}")],
            [InlineKeyboardButton(text="⬅️ Назад к играм",            callback_data="gm:back")],
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gm:ping:"))
async def gm_ping(callback: CallbackQuery, bot: Bot):
    """Напоминание тем кто не написал обзор."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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
                text=f"📝 Напиши обзор на «{item['title']}»!\n\nНажми «⭐ Оценить игру» в меню."
            )
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)

    total = len(users)
    await callback.message.edit_text(
        f"✅ Напоминание отправлено {sent} из {total} участников.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Напомнить ещё раз",  callback_data=f"gm:ping:{media_item_id}")],
            [InlineKeyboardButton(text="⬅️ Назад к играм",      callback_data="gm:back")],
        ])
    )
    await callback.answer()


# ── Удалить игру ──────────────────────────────────────────

@router.callback_query(F.data == "gm:delete_list")
async def gm_delete_list(callback: CallbackQuery):
    """Список игр для удаления — через существующую admin_kb клавиатуру."""
    games = await db.get_all_games()
    if not games:
        await callback.answer("Список игр пуст", show_alert=True)
        return

    from keyboards.admin_kb import admin_games_list_keyboard
    try:
        await callback.message.edit_text(
            "🗑 Выбери игру для удаления:",
            reply_markup=admin_games_list_keyboard(games)
        )
    except Exception:
        pass
    await callback.answer()


# После удаления через adm_del_game_yes: возвращаем на главный экран
# Это уже есть в admin.py — там показывается обновлённый список через admin_games_list_keyboard
# Добавляем только кнопку «Назад к Играм» в admin_kb если нужно (опционально)

# «🎲 Предложить игру» обрабатывается в handlers/suggestions.py

# ============================================================
# ПЕРЕОФОРМЛЕНИЕ ОБЗОРОВ
# ============================================================

@router.callback_query(F.data == "adm:reformat_reviews")
async def reformat_reviews(callback: CallbackQuery, bot: Bot):
    """
    Приводит все опубликованные обзоры в порядок.
    - Обзоры по вопросам: пересобирает из answers_json через шаблон
    - Обзоры от руки: текст не трогает
    - Groq: только корректура для отображения, НЕ сохраняет в базу
    - edit_message_text: без fallback на send_message
    """
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return

    from config import GROUP_CHAT_ID, REVIEWS_TOPIC_ID
    from database import RATING_LABELS
    from handlers.reviews import _format_review_text
    from services.review_builder import build_from_template, clean_text_with_groq

    try:
        from config import GROQ_API_KEY
    except ImportError:
        GROQ_API_KEY = None

    await callback.message.edit_text("⏳ Переоформляю обзоры...")
    await callback.answer()

    reviews = await db.get_all_reviews_for_reformat()
    if not reviews:
        await callback.message.edit_text("Обзоров пока нет.")
        return

    updated = 0
    failed = 0
    import json as _json

    for rev in reviews:
        game_emoji   = rev['game_emoji'] or "🎮"
        game_name    = rev['game_title'] or "игра"
        rating_label = RATING_LABELS.get(rev['rating'], "") if rev['rating'] else ""
        author       = f"@{rev['username']}" if rev['username'] else (rev['display_name'] or "Игрок")

        # Определяем текст для отображения (НЕ меняем базу)
        answers_json = rev['answers_json'] if 'answers_json' in rev.keys() else None
        if answers_json:
            # Обзор по вопросам — пересобираем из ответов
            try:
                answers = _json.loads(answers_json)
                display_text = build_from_template(answers)
                # Обновляем final_text в базе только для обзоров по вопросам
                await db.set_review(
                    rev['media_item_id'], rev['user_id'],
                    final_text=display_text, answers_json=answers_json
                )
            except Exception as e:
                logger.warning(f"Ошибка сборки шаблона: {e}")
                display_text = rev['final_text'] or ""
        else:
            # Обзор от руки — берём как есть, только корректура через Groq
            original_text = rev['final_text'] or ""
            if GROQ_API_KEY and original_text:
                cleaned = await clean_text_with_groq(original_text, GROQ_API_KEY)
                display_text = cleaned if cleaned else original_text
                # НЕ сохраняем в базу — только для отображения
            else:
                display_text = original_text

        # Получаем комментарий
        comment_row = await db.get_comment(rev['media_item_id'], rev['user_id'])
        comment_text = comment_row['text'] if comment_row and comment_row['text'] else None

        pub_text = _format_review_text(
            game_emoji, game_name, rating_label, author,
            display_text, comment=comment_text
        )

        pub_msg_id  = rev['published_message_id']
        pub_chat_id = rev['published_chat_id']

        if not pub_msg_id or not pub_chat_id:
            logger.warning(f"Нет published_message_id для обзора {rev['id']}")
            failed += 1
            continue

        try:
            await bot.edit_message_text(
                chat_id=pub_chat_id,
                message_id=pub_msg_id,
                text=pub_text,
                parse_mode="HTML",
            )
            updated += 1
        except Exception as edit_err:
            err_str = str(edit_err).lower()
            if "message is not modified" in err_str:
                updated += 1  # уже актуально
            else:
                logger.warning(f"Не удалось отредактировать обзор msg_id={pub_msg_id}: {edit_err}")
                failed += 1

        await asyncio.sleep(0.1)

    text_result = f"✅ Готово!\n\nОбновлено: {updated}"
    if failed:
        text_result += f"\nНе удалось: {failed}"

    from keyboards.admin_kb import admin_settings_keyboard
    notify_gather = await db.get_setting("notify_gather", "1")
    notify_remind = await db.get_setting("notify_remind", "1")
    await callback.message.edit_text(
        text_result,
        reply_markup=admin_settings_keyboard(notify_gather == "1", notify_remind == "1")
    )


# ============================================================
# НАСТРОЙКИ (АДМИН)
# ============================================================

@router.message(F.text == "⚙️ Настройки")
async def admin_settings_menu(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    notify_gather = await db.get_setting("notify_gather", "1")
    notify_remind = await db.get_setting("notify_remind", "1")
    from keyboards.admin_kb import admin_settings_keyboard
    await message.answer(
        "🔔 Уведомления:",
        reply_markup=admin_settings_keyboard(notify_gather == "1", notify_remind == "1")
    )


# ============================================================
# ПОЛЬЗОВАТЕЛЬ
# ============================================================

@router.message(F.text == "🎮 Анонсы")
async def user_announcements(message: Message):
    announcement = await db.get_active_announcement()
    if not announcement:
        await message.answer("Сейчас нет активных анонсов.")
        return
    game = await db.get_game(announcement['game_id'])
    game_display = f"🎮 {game['emoji']} {game['name']}" if game else "🎮 Игра"
    await message.answer(
        f"📢 Текущий анонс:\n\n"
        f"{game_display}\n"
        f"⏰ {announcement['start_time']} – {announcement['end_time']}\n\n"
        f"Голосуй в группе!"
    )


@router.message(F.text.in_({"👤 Функции игрока", "👤 Я как игрок", "👤 Меню пользователя"}))
async def player_functions(message: Message, state: FSMContext):
    """Открывает подменю с пользовательскими функциями."""
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer("👤 Меню пользователя:", reply_markup=admin_player_keyboard())


@router.message(F.text == "⬅️ Назад в меню")
async def back_to_admin_menu(message: Message):
    """Возврат из подменю в основное меню админа."""
    if message.from_user.id == ADMIN_ID:
        await message.answer("👑 Админ-панель", reply_markup=admin_menu_keyboard())
    else:
        await message.answer("🎮 Меню", reply_markup=user_menu_keyboard())


@router.message(F.text == "🚫 Сегодня не играю")
async def today_not_playing(message: Message, bot: Bot):
    """
    Если активного анонса нет — постим в группу.
    Если анонс есть — просим использовать кнопку ❌ под анонсом.
    Защита от двойного нажатия (сценарий 9).
    """
    announcement = await db.get_active_announcement()

    if announcement and announcement['message_id']:
        await message.answer(
            "📢 Есть активный анонс — используй кнопку ❌ под ним в группе."
        )
        return

    already_sent = await db.get_today_cancel_message_count(message.from_user.id)
    if already_sent > 0:
        await message.answer("Ты уже отправил это сегодня 😄")
        return

    user_name = message.from_user.first_name or "Кто-то"
    text = f"Сегодня игры не будет 😔\n({user_name} не может)"

    send_kwargs = {"chat_id": GROUP_CHAT_ID, "text": text}
    if ANNOUNCE_TOPIC_ID:
        send_kwargs["message_thread_id"] = ANNOUNCE_TOPIC_ID

    try:
        sent = await bot.send_message(**send_kwargs)
        await db.save_cancel_message(sent.message_id, sent.chat.id, message.from_user.id)
        await message.answer("✅ Сообщение отправлено в группу.")
    except Exception:
        await message.answer("❌ Не удалось отправить сообщение в группу.")
