"""
Хэндлер админ-панели.
Редактирование анонсов, удаление игр/пользователей, настройки уведомлений.
"""

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import database as db
from config import ADMIN_ID, GROUP_CHAT_ID, ANNOUNCE_TOPIC_ID, DEFAULT_HOUR, DEFAULT_MINUTE
from keyboards.admin_kb import (
    admin_announce_keyboard,
    admin_edit_time_keyboard,
    admin_edit_participants_keyboard,
    admin_settings_keyboard,
    confirm_cancel_keyboard,
    admin_games_list_keyboard,
    confirm_delete_game_keyboard,
    admin_users_list_keyboard,
    confirm_delete_user_keyboard,
)
from keyboards.voting_kb import voting_keyboard
from handlers.notifications import cancel_reminders

router = Router()

# Временное хранилище для админского пикера времени
admin_time_state: dict[int, dict] = {}

# Временное хранилище для списка участников
admin_users_state: dict[int, list[int]] = {}


class AdminForm(StatesGroup):
    """FSM для ручного ввода времени через админку."""
    manual_time = State()


# === Показ конкретного анонса из списка ===

@router.callback_query(F.data.startswith("adm:show_announce:"))
async def admin_show_announce(callback: CallbackQuery):
    """Показывает управление конкретным анонсом из списка."""
    if callback.from_user.id != ADMIN_ID:
        return
    announcement_id = int(callback.data.split(":")[2])
    announcement = await db.get_announcement(announcement_id)
    if not announcement:
        await callback.answer("Анонс не найден", show_alert=True)
        return

    game = await db.get_game(announcement['game_id'])
    game_display = f"🎮 {game['emoji']} {game['name']}" if game else "❓ Игра удалена"

    participants = await db.get_announcement_participants(announcement_id)
    votes = await db.get_votes(announcement_id)
    vote_map = {v['user_id']: v['vote'] for v in votes}

    yes_list, no_list, pending_list = [], [], []
    for p in participants:
        uid, uname, dname = p[0], p[1], p[2]
        display = f"@{uname}" if uname else (dname or str(uid))
        if uid in vote_map:
            (yes_list if vote_map[uid] == "yes" else no_list).append(display)
        else:
            pending_list.append(display)

    status = "📨 Опубликован" if announcement['message_id'] else "⏳ Запланирован"
    text = (
        f"📢 Анонс #{announcement['id']}\n\n"
        f"{game_display}\n"
        f"📅 {announcement['announce_date'] or '?'}\n"
        f"⏰ {announcement['start_time']} – {announcement['end_time']}\n"
        f"Статус: {status}\n\n"
    )
    if yes_list:
        text += f"✅ Идут: {', '.join(yes_list)}\n"
    if no_list:
        text += f"❌ Не смогут: {', '.join(no_list)}\n"
    if pending_list:
        text += f"⏳ Ждём: {', '.join(pending_list)}\n"

    await callback.message.edit_text(
        text,
        reply_markup=admin_announce_keyboard(announcement_id)
    )
    await callback.answer()


# === Редактирование времени ===

@router.callback_query(F.data.startswith("adm:edit_time:"))
async def admin_edit_time(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    announcement_id = int(callback.data.split(":")[2])
    announcement = await db.get_announcement(announcement_id)
    if not announcement:
        await callback.answer("Анонс не найден", show_alert=True)
        return

    h, m = map(int, announcement['start_time'].split(":"))
    admin_time_state[callback.from_user.id] = {
        "hour": h, "minute": m, "announcement_id": announcement_id
    }

    await callback.message.edit_text(
        "✏️ Изменение времени анонса:",
        reply_markup=admin_edit_time_keyboard(announcement_id, h, m)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_time:"))
async def admin_adjust_time(callback: CallbackQuery, bot: Bot, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    parts = callback.data.split(":")
    announcement_id = int(parts[1])
    action = parts[2]

    uid = callback.from_user.id
    if uid not in admin_time_state:
        admin_time_state[uid] = {"hour": DEFAULT_HOUR, "minute": DEFAULT_MINUTE, "announcement_id": announcement_id}

    ts = admin_time_state[uid]
    hour, minute = ts["hour"], ts["minute"]

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
        await state.set_state(AdminForm.manual_time)
        await state.update_data(admin_announcement_id=announcement_id)
        await callback.message.edit_text("✏️ Введи время в формате HH:MM\nНапример: 21:30")
        await callback.answer()
        return
    elif action == "save":
        start_time = f"{hour:02d}:{minute:02d}"
        end_m = minute + 10
        end_h = hour
        if end_m >= 60:
            end_m -= 60
            end_h += 1
        end_time = f"{end_h:02d}:{end_m:02d}"

        await db.update_announcement_time(announcement_id, start_time, end_time)
        admin_time_state.pop(uid, None)

        await _refresh_group_message(bot, announcement_id)

        announcement = await db.get_announcement(announcement_id)
        if announcement and announcement['announce_date']:
            from handlers.notifications import schedule_vote_reminders
            await schedule_vote_reminders(bot, announcement_id, announcement['announce_date'], start_time)

        await callback.message.edit_text(f"✅ Время обновлено: {start_time} – {end_time}")
        await callback.answer()
        return

    admin_time_state[uid] = {"hour": hour, "minute": minute, "announcement_id": announcement_id}
    await callback.message.edit_text(
        "✏️ Изменение времени анонса:",
        reply_markup=admin_edit_time_keyboard(announcement_id, hour, minute)
    )
    await callback.answer()


@router.callback_query(F.data == "adm_time_display")
async def adm_time_noop(callback: CallbackQuery):
    await callback.answer("Используй кнопки ниже")


@router.message(AdminForm.manual_time)
async def admin_manual_time(message: Message, state: FSMContext, bot: Bot):
    text = message.text.strip()
    try:
        parts = text.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, IndexError):
        await message.answer("❌ Неверный формат! Введи как HH:MM")
        return

    data = await state.get_data()
    announcement_id = data.get("admin_announcement_id")
    await state.clear()

    if not announcement_id:
        await message.answer("Ошибка, попробуй заново через меню.")
        return

    start_time = f"{hour:02d}:{minute:02d}"
    end_m = minute + 10
    end_h = hour
    if end_m >= 60:
        end_m -= 60
        end_h += 1
    end_time = f"{end_h:02d}:{end_m:02d}"

    await db.update_announcement_time(announcement_id, start_time, end_time)
    admin_time_state.pop(message.from_user.id, None)
    await _refresh_group_message(bot, announcement_id)

    announcement = await db.get_announcement(announcement_id)
    if announcement and announcement['announce_date']:
        from handlers.notifications import schedule_vote_reminders
        await schedule_vote_reminders(bot, announcement_id, announcement['announce_date'], start_time)

    await message.answer(f"✅ Время обновлено: {start_time} – {end_time}")


# === Редактирование участников ===

@router.callback_query(F.data.startswith("adm:edit_users:"))
async def admin_edit_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    announcement_id = int(callback.data.split(":")[2])
    participants = await db.get_announcement_participants(announcement_id)
    current_ids = [p[0] for p in participants]
    admin_users_state[callback.from_user.id] = current_ids
    users = await db.get_all_users()
    await callback.message.edit_text(
        "👥 Редактирование участников:",
        reply_markup=admin_edit_participants_keyboard(users, current_ids, announcement_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_toggle_user:"))
async def admin_toggle_user(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    parts = callback.data.split(":")
    announcement_id = int(parts[1])
    user_id = int(parts[2])
    selected = admin_users_state.get(callback.from_user.id, [])
    if user_id in selected:
        selected.remove(user_id)
    else:
        selected.append(user_id)
    admin_users_state[callback.from_user.id] = selected
    users = await db.get_all_users()
    await callback.message.edit_reply_markup(
        reply_markup=admin_edit_participants_keyboard(users, selected, announcement_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_select_all:"))
async def admin_select_all_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    announcement_id = int(callback.data.split(":")[1])
    users = await db.get_all_users()
    all_ids = [u['user_id'] for u in users]
    admin_users_state[callback.from_user.id] = all_ids
    await callback.message.edit_reply_markup(
        reply_markup=admin_edit_participants_keyboard(users, all_ids, announcement_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_deselect_all:"))
async def admin_deselect_all_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    announcement_id = int(callback.data.split(":")[1])
    admin_users_state[callback.from_user.id] = []
    users = await db.get_all_users()
    await callback.message.edit_reply_markup(
        reply_markup=admin_edit_participants_keyboard(users, [], announcement_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_save_users:"))
async def admin_save_users(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        return
    announcement_id = int(callback.data.split(":")[1])
    selected = admin_users_state.pop(callback.from_user.id, [])
    if not selected:
        await callback.answer("❌ Выбери хотя бы одного!", show_alert=True)
        return
    await db.update_announcement_participants(announcement_id, selected)
    await _refresh_group_message(bot, announcement_id)
    await callback.message.edit_text(f"✅ Участники обновлены ({len(selected)} чел.)")
    await callback.answer()


# === Отмена анонса (с подтверждением) ===

@router.callback_query(F.data.startswith("adm:cancel_confirm:"))
async def admin_cancel_confirm(callback: CallbackQuery):
    """Спрашиваем подтверждение."""
    if callback.from_user.id != ADMIN_ID:
        return
    announcement_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        f"❓ Отменить анонс #{announcement_id}?",
        reply_markup=confirm_cancel_keyboard(announcement_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:cancel_yes:"))
async def admin_cancel_yes(callback: CallbackQuery, bot: Bot):
    """Подтверждённая отмена — без сообщения в группу."""
    if callback.from_user.id != ADMIN_ID:
        return

    announcement_id = int(callback.data.split(":")[2])
    announcement = await db.get_announcement(announcement_id)
    if not announcement:
        await callback.answer("Анонс не найден", show_alert=True)
        return

    await db.deactivate_announcement(announcement_id)
    cancel_reminders(announcement_id)

    # Удаляем сообщение из группы, но НЕ пишем об отмене
    try:
        await bot.delete_message(
            chat_id=announcement['chat_id'],
            message_id=announcement['message_id']
        )
    except Exception:
        pass

    await callback.message.edit_text("✅ Анонс отменён.")
    await callback.answer()


@router.callback_query(F.data.startswith("adm:cancel_no:"))
async def admin_cancel_no(callback: CallbackQuery):
    """Отмена отмены — возврат к управлению анонсом."""
    if callback.from_user.id != ADMIN_ID:
        return
    announcement_id = int(callback.data.split(":")[2])
    from keyboards.admin_kb import admin_announce_keyboard
    await callback.message.edit_text(
        "Управление анонсом:",
        reply_markup=admin_announce_keyboard(announcement_id)
    )
    await callback.answer()


# === Удаление игр ===

@router.callback_query(F.data.startswith("adm_game_noop:"))
async def game_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("adm_del_game:"))
async def admin_delete_game_ask(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    game_id = int(callback.data.split(":")[1])
    game = await db.get_game(game_id)
    if not game:
        await callback.answer("Игра не найдена", show_alert=True)
        return
    await callback.message.edit_text(
        f"🗑 Удалить игру {game['emoji']} {game['name']}?",
        reply_markup=confirm_delete_game_keyboard(game_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_del_game_yes:"))
async def admin_delete_game_yes(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        return
    game_id = int(callback.data.split(":")[1])

    # Деактивируем все активные анонсы с этой игрой и убираем кнопки
    announcements = await db.get_announcements_by_game(game_id)
    for ann in announcements:
        await db.deactivate_announcement(ann['id'])
        if ann['message_id'] and ann['chat_id']:
            from handlers.notifications import cancel_reminders
            cancel_reminders(ann['id'])
            try:
                await bot.edit_message_reply_markup(
                    chat_id=ann['chat_id'],
                    message_id=ann['message_id'],
                    reply_markup=None
                )
            except Exception:
                pass

    await db.delete_game(game_id)

    # Показываем обновлённый список
    games = await db.get_all_games()
    if games:
        await callback.message.edit_text(
            "✅ Игра удалена. Связанные анонсы деактивированы.\n\n🎮 Игры:",
            reply_markup=admin_games_list_keyboard(games)
        )
    else:
        await callback.message.edit_text(
            "✅ Игра удалена. Связанные анонсы деактивированы."
        )
    await callback.answer()


@router.callback_query(F.data == "adm_del_game_no")
async def admin_delete_game_no(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    games = await db.get_all_games()
    if games:
        await callback.message.edit_text(
            "🎮 Игры:",
            reply_markup=admin_games_list_keyboard(games)
        )
    else:
        await callback.message.edit_text("Список игр пуст.")
    await callback.answer()


# === Удаление пользователей ===

@router.callback_query(F.data.startswith("adm_user_noop:"))
async def user_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("adm_del_user:"))
async def admin_delete_user_ask(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.split(":")[1])
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    name = user['display_name'] or user['username'] or str(user_id)
    await callback.message.edit_text(
        f"🗑 Удалить пользователя {name}?",
        reply_markup=confirm_delete_user_keyboard(user_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_del_user_yes:"))
async def admin_delete_user_yes(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.split(":")[1])
    await db.remove_user(user_id)
    users = await db.get_all_users()
    if users:
        await callback.message.edit_text(
            "✅ Удалён.\n\n👥 Участники:",
            reply_markup=admin_users_list_keyboard(users)
        )
    else:
        await callback.message.edit_text("✅ Удалён. Список пуст.")
    await callback.answer()


@router.callback_query(F.data == "adm_del_user_no")
async def admin_delete_user_no(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    users = await db.get_all_users()
    if users:
        await callback.message.edit_text(
            "👥 Участники:",
            reply_markup=admin_users_list_keyboard(users)
        )
    else:
        await callback.message.edit_text("Список пуст.")
    await callback.answer()


# === Настройки уведомлений ===

@router.callback_query(F.data == "adm:toggle_notify_gather")
async def toggle_notify_gather(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    current = await db.get_setting("notify_gather", "1")
    new_val = "0" if current == "1" else "1"
    await db.set_setting("notify_gather", new_val)
    await callback.answer(
        "Напоминание о сборе включено 🔔" if new_val == "1" else "Напоминание о сборе отключено 🔕",
        show_alert=True
    )
    notify_remind = await db.get_setting("notify_remind", "1")
    await callback.message.edit_reply_markup(
        reply_markup=admin_settings_keyboard(new_val == "1", notify_remind == "1")
    )


@router.callback_query(F.data == "adm:toggle_notify_remind")
async def toggle_notify_remind(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    current = await db.get_setting("notify_remind", "1")
    new_val = "0" if current == "1" else "1"
    await db.set_setting("notify_remind", new_val)
    await callback.answer(
        "Напоминание проголосовать включено 🔔" if new_val == "1" else "Напоминание проголосовать отключено 🔕",
        show_alert=True
    )
    notify_gather = await db.get_setting("notify_gather", "1")
    await callback.message.edit_reply_markup(
        reply_markup=admin_settings_keyboard(notify_gather == "1", new_val == "1")
    )


# === Вспомогательная функция ===

async def _refresh_group_message(bot: Bot, announcement_id: int):
    """Обновляет сообщение анонса в группе после редактирования."""
    from handlers.voting import update_announcement_text
    await update_announcement_text(announcement_id, bot)
