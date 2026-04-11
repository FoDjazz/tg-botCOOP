"""
Хэндлер меню (Reply Keyboard).
Разное меню для админа и обычного пользователя.
"""

from datetime import timedelta
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

import database as db
from config import ADMIN_ID, GROUP_CHAT_ID, ANNOUNCE_TOPIC_ID
from keyboards.menu_kb import admin_menu_keyboard, user_menu_keyboard, player_functions_keyboard
from tz import now

router = Router()


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


@router.message(F.text == "🎮 Игры")
async def admin_games_menu(message: Message):
    """Список игр с кнопками удаления."""
    if message.from_user.id != ADMIN_ID:
        return
    games = await db.get_all_games()
    if not games:
        await message.answer("Список игр пуст. Добавь через ➕ Создать анонс")
        return
    from keyboards.admin_kb import admin_games_list_keyboard
    await message.answer(
        "🎮 Игры (нажми 🗑 для удаления):",
        reply_markup=admin_games_list_keyboard(games)
    )


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


# === Пользователь ===

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


# === Функции игрока (подменю) ===

@router.message(F.text == "👤 Функции игрока")
async def player_functions(message: Message):
    """Открывает подменю с пользовательскими функциями."""
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👤 Функции игрока:", reply_markup=player_functions_keyboard())


@router.message(F.text == "⬅️ Назад в меню")
async def back_to_admin_menu(message: Message):
    """Возврат из подменю в основное меню админа."""
    if message.from_user.id == ADMIN_ID:
        await message.answer("👑 Админ-панель", reply_markup=admin_menu_keyboard())
    else:
        await message.answer("🎮 Меню", reply_markup=user_menu_keyboard())


# === Кнопка «Сегодня не играю» ===

@router.message(F.text == "🚫 Сегодня не играю")
async def today_not_playing(message: Message, bot):
    """
    Если активного анонса нет — постим в группу 'Сегодня не играем'.
    Если анонс есть — просим использовать кнопку ❌ под анонсом.
    """
    announcement = await db.get_active_announcement()

    if announcement and announcement['message_id']:
        await message.answer(
            "📢 Есть активный анонс — используй кнопку ❌ под ним в группе."
        )
        return

    # Нет активного опубликованного анонса — постим в группу
    user_name = message.from_user.first_name or "Кто-то"
    text = f"Сегодня игры не будет 😔\n({user_name} не может)"

    send_kwargs = {"chat_id": GROUP_CHAT_ID, "text": text}
    if ANNOUNCE_TOPIC_ID:
        send_kwargs["message_thread_id"] = ANNOUNCE_TOPIC_ID

    try:
        sent = await bot.send_message(**send_kwargs)
        await db.save_cancel_message(sent.message_id, sent.chat.id)
        await message.answer("✅ Сообщение отправлено в группу.")
    except Exception:
        await message.answer("❌ Не удалось отправить сообщение в группу.")


# «🎲 Предложить игру» обрабатывается в handlers/suggestions.py
