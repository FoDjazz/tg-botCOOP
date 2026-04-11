"""
Хэндлер создания анонса.
Пошаговый процесс через FSM (Finite State Machine).

Добавлено v2:
- Кнопка «Назад» на каждом шаге
- Выбор даты (Сегодня/Завтра/Выбрать)
- Ручной ввод времени
- Шаги: Фото → Игра → Дата → Время → Участники
"""

from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import database as db
from config import GROUP_CHAT_ID, ANNOUNCE_TOPIC_ID, DEFAULT_HOUR, DEFAULT_MINUTE
from tz import now as tz_now
from keyboards.announce_kb import (
    games_keyboard, date_selection_keyboard, announce_date_picker_keyboard,
    time_picker_keyboard, participants_keyboard
)
from keyboards.voting_kb import voting_keyboard
from keyboards.menu_kb import main_menu_keyboard

router = Router()


# === FSM States ===

class AnnounceForm(StatesGroup):
    """Состояния создания анонса."""
    waiting_photo = State()        # Шаг 1: Ждём картинку
    choosing_game = State()        # Шаг 2: Выбор игры
    adding_game_name = State()     # Шаг 2.1: Ввод названия новой игры
    adding_game_emoji = State()    # Шаг 2.2: Ввод эмодзи для новой игры
    choosing_date = State()        # Шаг 3: Выбор даты
    choosing_time = State()        # Шаг 4: Настройка времени
    manual_time_input = State()    # Шаг 4.1: Ручной ввод времени
    choosing_participants = State() # Шаг 5: Выбор участников


# === Команда /announce ===

@router.message(Command("announce"))
async def cmd_announce(message: Message, state: FSMContext):
    """Начало создания анонса. Бот просит отправить картинку."""
    await state.clear()
    await state.set_state(AnnounceForm.waiting_photo)
    await message.answer(
        "🎮 *Создание анонса*\n\n"
        "Шаг 1/5: Отправь картинку для анонса",
        parse_mode="Markdown"
    )


# === Шаг 1: Картинка ===

@router.message(AnnounceForm.waiting_photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    """Получили картинку — переходим к выбору игры."""
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_file_id)

    games = await db.get_all_games()
    await state.set_state(AnnounceForm.choosing_game)
    await message.answer(
        "Шаг 2/5: Выбери игру",
        reply_markup=games_keyboard(games)
    )


@router.message(AnnounceForm.waiting_photo)
async def process_photo_invalid(message: Message):
    """Если отправили не картинку."""
    await message.answer("❌ Нужна именно картинка! Отправь фото.")


# === Шаг 2: Выбор игры ===

@router.callback_query(AnnounceForm.choosing_game, F.data.startswith("select_game:"))
async def select_game(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал существующую игру → переходим к выбору даты."""
    game_id = int(callback.data.split(":")[1])
    game = await db.get_game(game_id)
    await state.update_data(game_id=game_id, game_name=game['name'], game_emoji=game['emoji'])

    await state.set_state(AnnounceForm.choosing_date)
    await callback.message.edit_text(
        f"Выбрана игра: {game['emoji']} {game['name']}\n\n"
        "Шаг 3/5: Выбери дату",
        reply_markup=date_selection_keyboard()
    )
    await callback.answer()


@router.callback_query(AnnounceForm.choosing_game, F.data == "add_new_game")
async def add_new_game(callback: CallbackQuery, state: FSMContext):
    """Пользователь хочет добавить новую игру."""
    await state.set_state(AnnounceForm.adding_game_name)
    await callback.message.edit_text(
        "Введи название новой игры:\n\n"
        "(Отправь /cancel для отмены)"
    )
    await callback.answer()


# Кнопка «Назад» с шага игры → обратно к фото
@router.callback_query(AnnounceForm.choosing_game, F.data == "back_to_photo")
async def back_to_photo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AnnounceForm.waiting_photo)
    await callback.message.edit_text(
        "🎮 *Создание анонса*\n\n"
        "Шаг 1/5: Отправь картинку для анонса",
        parse_mode="Markdown"
    )
    await callback.answer()


# === Добавление новой игры ===

@router.message(AnnounceForm.adding_game_name)
async def process_game_name(message: Message, state: FSMContext):
    """Получили название игры, теперь просим эмодзи."""
    if message.text and message.text.startswith("/"):
        await state.set_state(AnnounceForm.choosing_game)
        games = await db.get_all_games()
        await message.answer("Шаг 2/5: Выбери игру", reply_markup=games_keyboard(games))
        return
    await state.update_data(new_game_name=message.text.strip())
    await state.set_state(AnnounceForm.adding_game_emoji)
    await message.answer("Теперь отправь эмодзи для этой игры (1 символ):")


@router.message(AnnounceForm.adding_game_emoji)
async def process_game_emoji(message: Message, state: FSMContext):
    """Получили эмодзи — проверяем и сохраняем игру."""
    emoji_text = message.text.strip()

    import emoji as emoji_lib
    if len(emoji_text) > 2 and not emoji_lib.is_emoji(emoji_text):
        await message.answer("❌ Нужен ровно 1 эмодзи! Попробуй ещё раз:")
        return

    data = await state.get_data()
    game_name = data['new_game_name']

    game_id = await db.add_game(game_name, emoji_text)
    await state.update_data(game_id=game_id, game_name=game_name, game_emoji=emoji_text)

    # Переходим к выбору даты
    await state.set_state(AnnounceForm.choosing_date)
    await message.answer(
        f"✅ Игра добавлена: {emoji_text} {game_name}\n\n"
        "Шаг 3/5: Выбери дату",
        reply_markup=date_selection_keyboard()
    )


# === Шаг 3: Выбор даты ===

@router.callback_query(AnnounceForm.choosing_date, F.data.startswith("ann_date:"))
async def select_announce_date(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора даты."""
    parts = callback.data.split(":")
    action = parts[1]  # today, tomorrow, pick, exact

    if action in ("today", "tomorrow", "exact"):
        # Прямой выбор даты
        date_str = parts[2]
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

        today = tz_now().date()
        if dt.date() == today:
            date_display = "Сегодня"
        elif dt.date() == today + timedelta(days=1):
            date_display = "Завтра"
        else:
            date_display = f"{weekday_names[dt.weekday()]}, {dt.strftime('%d.%m')}"

        await state.update_data(
            announce_date=date_str,
            announce_date_display=date_display,
            hour=DEFAULT_HOUR,
            minute=DEFAULT_MINUTE,
        )
        await state.set_state(AnnounceForm.choosing_time)

        data = await state.get_data()
        await callback.message.edit_text(
            f"Дата: {date_display}\n\n"
            "Шаг 4/5: Настрой время начала",
            reply_markup=time_picker_keyboard(DEFAULT_HOUR, DEFAULT_MINUTE)
        )

    elif action == "pick":
        # Карусель дат
        offset = int(parts[2])
        await callback.message.edit_text(
            "Выбери дату:",
            reply_markup=announce_date_picker_keyboard(offset)
        )

    await callback.answer()


# Назад из карусели дат → выбор Сегодня/Завтра/Дата
@router.callback_query(AnnounceForm.choosing_date, F.data == "back_to_date_select")
async def back_to_date_select(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Шаг 3/5: Выбери дату",
        reply_markup=date_selection_keyboard()
    )
    await callback.answer()


# Назад из даты → выбор игры
@router.callback_query(AnnounceForm.choosing_date, F.data == "back_to_game")
async def back_to_game(callback: CallbackQuery, state: FSMContext):
    games = await db.get_all_games()
    await state.set_state(AnnounceForm.choosing_game)
    await callback.message.edit_text(
        "Шаг 2/5: Выбери игру",
        reply_markup=games_keyboard(games)
    )
    await callback.answer()


# === Шаг 4: Выбор времени ===

@router.callback_query(AnnounceForm.choosing_time, F.data.startswith("time:"))
async def adjust_time(callback: CallbackQuery, state: FSMContext):
    """Обработка нажатий кнопок +/- час/минута, ручной ввод, подтверждение."""
    action = callback.data.split(":")[1]
    data = await state.get_data()
    hour = data.get('hour', DEFAULT_HOUR)
    minute = data.get('minute', DEFAULT_MINUTE)
    date_display = data.get('announce_date_display', '')

    if action == "+1h":
        hour = (hour + 1) % 24
    elif action == "-1h":
        hour = (hour - 1) % 24
    elif action == "+10m":
        minute += 10
        if minute >= 60:
            minute -= 60
            hour = (hour + 1) % 24
    elif action == "-10m":
        minute -= 10
        if minute < 0:
            minute += 60
            hour = (hour - 1) % 24
    elif action == "manual":
        # Переход к ручному вводу
        await state.set_state(AnnounceForm.manual_time_input)
        await callback.message.edit_text(
            "✏️ Введи время в формате HH:MM\n"
            "Например: 21:30"
        )
        await callback.answer()
        return
    elif action == "confirm":
        # Проверка: нельзя выбрать время в прошлом
        data_check = await state.get_data()
        announce_date = data_check.get('announce_date', '')
        if announce_date:
            chosen_dt = datetime.strptime(f"{announce_date} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")
            if chosen_dt < tz_now():
                await callback.answer("❌ Нельзя выбрать время в прошлом!", show_alert=True)
                return

        # Подтверждение → переходим к участникам
        await state.update_data(hour=hour, minute=minute)

        users = await db.get_all_users()
        if not users:
            await callback.message.edit_text(
                "⚠️ Нет зарегистрированных пользователей!\n"
                "Сначала добавь участников командой /adduser @username"
            )
            await callback.answer()
            return

        await state.set_state(AnnounceForm.choosing_participants)
        await state.update_data(selected_users=[])
        await callback.message.edit_text(
            "Шаг 5/5: Выбери участников",
            reply_markup=participants_keyboard(users, [])
        )
        await callback.answer()
        return

    await state.update_data(hour=hour, minute=minute)

    await callback.message.edit_text(
        f"Дата: {date_display}\n\n"
        "Шаг 4/5: Настрой время начала",
        reply_markup=time_picker_keyboard(hour, minute)
    )
    await callback.answer()


# Нажатие на кнопку с временем (информационная)
@router.callback_query(AnnounceForm.choosing_time, F.data == "time_display")
async def time_display_noop(callback: CallbackQuery):
    await callback.answer("Используй кнопки ниже для настройки времени")


# Назад из времени → дата
@router.callback_query(AnnounceForm.choosing_time, F.data == "back_to_date")
async def back_to_date(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AnnounceForm.choosing_date)
    data = await state.get_data()
    game_name = data.get('game_name', '')
    game_emoji = data.get('game_emoji', '')
    await callback.message.edit_text(
        f"Выбрана игра: {game_emoji} {game_name}\n\n"
        "Шаг 3/5: Выбери дату",
        reply_markup=date_selection_keyboard()
    )
    await callback.answer()


# === Шаг 4.1: Ручной ввод времени ===

@router.message(AnnounceForm.manual_time_input)
async def process_manual_time(message: Message, state: FSMContext):
    """Валидация ручного ввода времени HH:MM."""
    text = message.text.strip()
    try:
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, IndexError):
        await message.answer(
            "❌ Неверный формат! Введи время как HH:MM\n"
            "Например: 21:30"
        )
        return

    # Проверка: нельзя выбрать время в прошлом
    data = await state.get_data()
    announce_date = data.get('announce_date', '')
    if announce_date:
        chosen_dt = datetime.strptime(f"{announce_date} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")
        if chosen_dt < tz_now():
            await message.answer("❌ Нельзя выбрать время в прошлом! Введи будущее время.")
            return

    await state.update_data(hour=hour, minute=minute)
    await state.set_state(AnnounceForm.choosing_time)

    date_display = data.get('announce_date_display', '')

    await message.answer(
        f"Дата: {date_display}\n\n"
        "Шаг 4/5: Настрой время начала",
        reply_markup=time_picker_keyboard(hour, minute)
    )


# === Шаг 5: Выбор участников ===

@router.callback_query(AnnounceForm.choosing_participants, F.data.startswith("toggle_user:"))
async def toggle_participant(callback: CallbackQuery, state: FSMContext):
    """Переключаем выбор участника."""
    user_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = data.get('selected_users', [])

    if user_id in selected:
        selected.remove(user_id)
    else:
        selected.append(user_id)

    await state.update_data(selected_users=selected)
    users = await db.get_all_users()
    await callback.message.edit_reply_markup(
        reply_markup=participants_keyboard(users, selected)
    )
    await callback.answer()


@router.callback_query(AnnounceForm.choosing_participants, F.data == "select_all_users")
async def select_all(callback: CallbackQuery, state: FSMContext):
    users = await db.get_all_users()
    all_ids = [u['user_id'] for u in users]
    await state.update_data(selected_users=all_ids)
    await callback.message.edit_reply_markup(
        reply_markup=participants_keyboard(users, all_ids)
    )
    await callback.answer()


@router.callback_query(AnnounceForm.choosing_participants, F.data == "deselect_all_users")
async def deselect_all(callback: CallbackQuery, state: FSMContext):
    await state.update_data(selected_users=[])
    users = await db.get_all_users()
    await callback.message.edit_reply_markup(
        reply_markup=participants_keyboard(users, [])
    )
    await callback.answer()


# Назад из участников → время
@router.callback_query(AnnounceForm.choosing_participants, F.data == "back_to_time")
async def back_to_time(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    hour = data.get('hour', DEFAULT_HOUR)
    minute = data.get('minute', DEFAULT_MINUTE)
    date_display = data.get('announce_date_display', '')

    await state.set_state(AnnounceForm.choosing_time)
    await callback.message.edit_text(
        f"Дата: {date_display}\n\n"
        "Шаг 4/5: Настрой время начала",
        reply_markup=time_picker_keyboard(hour, minute)
    )
    await callback.answer()


@router.callback_query(AnnounceForm.choosing_participants, F.data == "confirm_participants")
async def confirm_and_publish(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """
    Подтверждение — создаём анонс в БД.
    Если до игры <= 6 часов → публикуем сразу.
    Если > 6 часов → только сохраняем, публикация по таймеру.
    """
    data = await state.get_data()
    selected = data.get('selected_users', [])

    if not selected:
        await callback.answer("❌ Выбери хотя бы одного участника!", show_alert=True)
        return

    # Формируем время
    hour = data['hour']
    minute = data['minute']
    start_h, start_m = hour, minute
    end_m = minute + 10
    end_h = hour
    if end_m >= 60:
        end_m -= 60
        end_h += 1

    start_time = f"{start_h:02d}:{start_m:02d}"
    end_time = f"{end_h:02d}:{end_m:02d}"
    game_emoji = data['game_emoji']
    game_name = data['game_name']
    photo_file_id = data['photo_file_id']
    game_id = data['game_id']
    announce_date = data.get('announce_date', tz_now().strftime("%Y-%m-%d"))
    date_display = data.get('announce_date_display', 'Сегодня')

    # Собираем упоминания участников
    mentions = []
    for uid in selected:
        user = await db.get_user(uid)
        if user and user['username']:
            mentions.append(f"@{user['username']}")
        elif user:
            mentions.append(user['display_name'] or str(uid))

    # Создаём анонс в базе (message_id = NULL — ещё не опубликован)
    announcement_id = await db.create_announcement(
        game_id=game_id,
        photo_file_id=photo_file_id,
        announce_date=announce_date,
        start_time=start_time,
        end_time=end_time,
        participant_ids=selected
    )

    # Считаем: сколько времени до игры?
    from config import HOURS_BEFORE_ANNOUNCE
    game_dt = datetime.strptime(f"{announce_date} {start_time}", "%Y-%m-%d %H:%M")
    current = tz_now()
    hours_until_game = (game_dt - current).total_seconds() / 3600

    if hours_until_game <= HOURS_BEFORE_ANNOUNCE:
        # До игры <= 6 часов → публикуем СРАЗУ
        text = (
            f"{date_display} {start_time} – {end_time}! {game_emoji}\n\n"
            f"Участники:\n{' '.join(mentions)}"
        )

        send_kwargs = {
            "chat_id": GROUP_CHAT_ID,
            "photo": photo_file_id,
            "caption": text,
            "reply_markup": voting_keyboard(announcement_id),
        }
        if ANNOUNCE_TOPIC_ID:
            send_kwargs["message_thread_id"] = ANNOUNCE_TOPIC_ID

        sent_msg = await bot.send_photo(**send_kwargs)
        await db.update_announcement_message(announcement_id, sent_msg.message_id, sent_msg.chat.id)

        # Планируем уведомления
        from handlers.notifications import schedule_vote_reminders
        await schedule_vote_reminders(bot, announcement_id, announce_date, start_time)

        await callback.message.edit_text("✅ Анонс опубликован в группу!")
    else:
        # До игры > 6 часов → НЕ публикуем, только планируем
        from handlers.reschedule import schedule_auto_announce
        await schedule_auto_announce(bot, announcement_id)

        publish_dt = game_dt - timedelta(hours=HOURS_BEFORE_ANNOUNCE)
        await callback.message.edit_text(
            f"✅ Анонс создан и запланирован!\n\n"
            f"📅 {date_display} в {start_time}\n"
            f"📢 Публикация в группу: {publish_dt.strftime('%d.%m в %H:%M')}"
        )

    await state.clear()
    await callback.answer()


# === Защита от текста на шагах с кнопками ===
# (На шагах ввода названия игры, эмодзи и ручного времени текст принимается нормально)

@router.message(AnnounceForm.choosing_game)
async def game_text_invalid(message: Message):
    """Если на шаге выбора игры отправили текст вместо кнопки."""
    await message.answer("⚠️ Используй кнопки выше для выбора игры.")


@router.message(AnnounceForm.choosing_date)
async def date_text_invalid(message: Message):
    """Если на шаге выбора даты отправили текст."""
    await message.answer("⚠️ Используй кнопки для выбора даты.")


@router.message(AnnounceForm.choosing_time)
async def time_text_invalid(message: Message):
    """Если на шаге настройки времени отправили текст."""
    await message.answer("⚠️ Используй кнопки для настройки времени.\nИли нажми «✏️ Ввести вручную».")


@router.message(AnnounceForm.choosing_participants)
async def participants_text_invalid(message: Message):
    """Если на шаге выбора участников отправили текст."""
    await message.answer("⚠️ Используй кнопки для выбора участников.")


# === Команды управления пользователями ===

@router.message(Command("adduser"))
async def cmd_add_user(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) == 1:
        user = message.from_user
        await db.add_user(
            user_id=user.id,
            username=user.username or "",
            display_name=user.first_name or user.username or str(user.id)
        )
        await message.answer(f"✅ Ты добавлен: {user.first_name}")
        return
    username = args[1].lstrip("@")
    await message.answer(
        f"⚠️ Чтобы добавить @{username}, этот пользователь должен "
        f"сначала написать боту /start в ЛС.\n\n"
        f"Или пусть напишет /adduser боту напрямую."
    )


@router.message(Command("removeuser"))
async def cmd_remove_user(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /removeuser @username")
        return
    users = await db.get_all_users()
    target = args[1].lstrip("@")
    for user in users:
        if user['username'] == target:
            await db.remove_user(user['user_id'])
            await message.answer(f"✅ Пользователь @{target} удалён")
            return
    await message.answer(f"❌ Пользователь @{target} не найден")


@router.message(Command("users"))
async def cmd_list_users(message: Message):
    users = await db.get_all_users()
    if not users:
        await message.answer("Список пуст. Добавь участников через /adduser")
        return
    lines = []
    for i, user in enumerate(users, 1):
        name = user['display_name'] or user['username'] or str(user['user_id'])
        username = f"(@{user['username']})" if user['username'] else ""
        lines.append(f"{i}. {name} {username}")
    await message.answer("👥 Участники:\n\n" + "\n".join(lines))


@router.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    await db.add_user(
        user_id=user.id,
        username=user.username or "",
        display_name=user.first_name or user.username or str(user.id)
    )
    await message.answer(
        f"👋 Привет, {user.first_name}!\n\n"
        "Ты зарегистрирован. Теперь тебя можно добавлять в анонсы.\n\n"
        "Нажми 📋 Меню для управления.",
        reply_markup=main_menu_keyboard()
    )


@router.message(Command("games"))
async def cmd_games(message: Message):
    games = await db.get_all_games()
    if not games:
        await message.answer("Список игр пуст. Добавь при создании анонса через /announce")
        return
    lines = [f"{g['emoji']} {g['name']}" for g in games]
    await message.answer("🎮 Игры:\n\n" + "\n".join(lines))
