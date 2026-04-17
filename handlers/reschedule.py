"""
Хэндлер переноса игровой сессии.
v2: кнопки «Назад», кнопка «Изменить время» в ЛС, announce_date.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery

import database as db
from config import (
    GROUP_CHAT_ID, ANNOUNCE_TOPIC_ID, ADMIN_ID,
    DEFAULT_HOUR, DEFAULT_MINUTE, HOURS_BEFORE_ANNOUNCE
)
from tz import now as tz_now
from handlers.voting import CANCEL_PHRASES
from keyboards.reschedule_kb import (
    date_picker_keyboard,
    time_picker_reschedule_keyboard,
    reschedule_when_keyboard,
    edit_reschedule_keyboard
)
from keyboards.voting_kb import voting_keyboard

router = Router()
logger = logging.getLogger(__name__)

# Хранилище запланированных задач (announcement_id -> asyncio.Task)
scheduled_tasks: dict[int, asyncio.Task] = {}

# Хранилище времени для пикера (user_id -> {hour, minute})
reschedule_time_state: dict[int, dict] = {}


@router.callback_query(F.data.startswith("resched:today:"))
async def resched_today(callback: CallbackQuery):
    announcement_id = int(callback.data.split(":")[2])
    today = tz_now().strftime("%Y-%m-%d")
    reschedule_time_state[callback.from_user.id] = {
        "hour": DEFAULT_HOUR + 1, "minute": DEFAULT_MINUTE
    }
    await callback.message.edit_text(
        "Выбери время на сегодня:",
        reply_markup=time_picker_reschedule_keyboard(
            announcement_id, today, DEFAULT_HOUR + 1, DEFAULT_MINUTE
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith("resched:tomorrow:"))
async def resched_tomorrow(callback: CallbackQuery, bot: Bot):
    announcement_id = int(callback.data.split(":")[2])
    tomorrow = (tz_now() + timedelta(days=1)).strftime("%Y-%m-%d")
    await save_and_schedule(
        callback, bot, announcement_id,
        tomorrow, f"{DEFAULT_HOUR:02d}:{DEFAULT_MINUTE:02d}"
    )


@router.callback_query(F.data.startswith("resched:pick_date:"))
async def show_date_picker(callback: CallbackQuery):
    announcement_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        "Выбери дату:",
        reply_markup=date_picker_keyboard(announcement_id, 0)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("resched:nav:"))
async def navigate_dates(callback: CallbackQuery):
    parts = callback.data.split(":")
    announcement_id = int(parts[2])
    offset = max(0, int(parts[3]))
    await callback.message.edit_reply_markup(
        reply_markup=date_picker_keyboard(announcement_id, offset)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("resched:date:"))
async def select_date(callback: CallbackQuery):
    parts = callback.data.split(":")
    announcement_id = int(parts[2])
    date_str = parts[3]
    reschedule_time_state[callback.from_user.id] = {
        "hour": DEFAULT_HOUR, "minute": DEFAULT_MINUTE
    }
    await callback.message.edit_text(
        f"Дата: {date_str}\nВыбери время:",
        reply_markup=time_picker_reschedule_keyboard(
            announcement_id, date_str, DEFAULT_HOUR, DEFAULT_MINUTE
        )
    )
    await callback.answer()


# === Кнопка «Назад» ===

@router.callback_query(F.data.startswith("resched:back_when:"))
async def back_to_when(callback: CallbackQuery):
    announcement_id = int(callback.data.split(":")[2])
    reschedule_time_state.pop(callback.from_user.id, None)
    await callback.message.edit_text(
        "Когда ты сможешь? 👀",
        reply_markup=reschedule_when_keyboard(announcement_id)
    )
    await callback.answer()


# === Кнопка «Изменить время» после сохранения ===

@router.callback_query(F.data.startswith("resched:edit_time:"))
async def edit_reschedule_time(callback: CallbackQuery):
    announcement_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        "Когда ты сможешь? 👀",
        reply_markup=reschedule_when_keyboard(announcement_id)
    )
    await callback.answer()


# === Кнопка «Не знаю когда» ===

@router.callback_query(F.data.startswith("resched:idk_when:"))
async def idk_when(callback: CallbackQuery, bot: Bot):
    """Пользователь не знает когда сможет — уведомляем админа."""
    announcement_id = int(callback.data.split(":")[2])
    user = callback.from_user
    user_name = user.first_name or user.username or str(user.id)

    await callback.message.edit_text(
        "🤷‍♂️ Ок, я сообщу админу.\n"
        "Он выберет дату или отменит анонс."
    )
    await callback.answer()

    # Пишем админу
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ Удалить анонс",
            callback_data=f"adm:cancel_confirm:{announcement_id}"
        )],
        [InlineKeyboardButton(
            text="📅 Выбрать дату самому",
            callback_data=f"resched:admin_pick:{announcement_id}"
        )],
    ])

    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🤷‍♂️ {user_name} не определился с датой\n"
                 f"Анонс #{announcement_id}",
            reply_markup=admin_kb
        )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение админу: {e}")


@router.callback_query(F.data.startswith("resched:admin_pick:"))
async def admin_pick_date(callback: CallbackQuery):
    """Админ сам выбирает дату для переноса."""
    announcement_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        f"📅 Выбери дату для анонса #{announcement_id}:",
        reply_markup=reschedule_when_keyboard(announcement_id)
    )
    await callback.answer()


# === Пикер времени ===

@router.callback_query(F.data.startswith("resched_time:"))
async def adjust_reschedule_time(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    announcement_id = int(parts[1])
    date_str = parts[2]
    action = parts[3]

    uid = callback.from_user.id
    if uid not in reschedule_time_state:
        reschedule_time_state[uid] = {"hour": DEFAULT_HOUR, "minute": DEFAULT_MINUTE}

    ts = reschedule_time_state[uid]
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
    elif action == "confirm":
        # Проверка: нельзя перенести на время в прошлом
        chosen_dt = datetime.strptime(f"{date_str} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")
        if chosen_dt < tz_now():
            await callback.answer("❌ Нельзя выбрать время в прошлом!", show_alert=True)
            return
        time_str = f"{hour:02d}:{minute:02d}"
        reschedule_time_state.pop(uid, None)
        await save_and_schedule(callback, bot, announcement_id, date_str, time_str)
        return

    reschedule_time_state[uid] = {"hour": hour, "minute": minute}
    await callback.message.edit_text(
        f"Дата: {date_str}\nВыбери время:",
        reply_markup=time_picker_reschedule_keyboard(
            announcement_id, date_str, hour, minute
        )
    )
    await callback.answer()


@router.callback_query(F.data == "resched_time_display")
async def resched_time_display_noop(callback: CallbackQuery):
    await callback.answer("Используй кнопки ниже для настройки времени")


# === Сохранение и планирование ===

async def save_and_schedule(callback: CallbackQuery, bot: Bot,
                              announcement_id: int, date_str: str, time_str: str):
    """
    Сохраняет перенос, создаёт новый анонс в БД,
    и решает — писать ли "Сегодня не играем" в группу.
    
    Логика:
    - Если новая дата = СЕГОДНЯ → молча создаём анонс, НЕ пишем в группу
    - Если новая дата = ЗАВТРА+ → пишем шуточное "Сегодня не играем" в группу
    """
    user_id = callback.from_user.id
    await db.save_reschedule(announcement_id, user_id, date_str, time_str)

    # Берём самую позднюю дату среди всех переносов
    latest = await db.get_latest_reschedule_date(announcement_id)
    latest_date, latest_time = latest[0], latest[1]

    # Формируем время с +10 мин на сбор
    h, m = map(int, latest_time.split(":"))
    start_time = f"{h:02d}:{m:02d}"
    end_h, end_m = h, m + 10
    if end_m >= 60:
        end_m -= 60
        end_h += 1
    end_time = f"{end_h:02d}:{end_m:02d}"

    # Получаем данные старого анонса
    old = await db.get_announcement(announcement_id)
    if not old:
        logger.error(f"Старый анонс #{announcement_id} не найден!")
        return

    participants = await db.get_announcement_participants(announcement_id)
    participant_ids = [p[0] for p in participants]

    # Создаём новый анонс в БД — message_id останется NULL (ещё не опубликован)
    new_id = await db.create_announcement(
        game_id=old['game_id'], photo_file_id=old['photo_file_id'],
        announce_date=latest_date, start_time=start_time, end_time=end_time,
        participant_ids=participant_ids
    )
    logger.info(f"Создан запланированный анонс #{new_id} на {latest_date} {start_time}")

    # Переносим голоса "yes" из старого анонса в новый
    try:
        old_votes = await db.get_votes(announcement_id)
        for vote in old_votes:
            if vote['vote'] == 'yes':
                await db.save_vote(new_id, vote['user_id'], 'yes')
        if old_votes:
            yes_count = sum(1 for v in old_votes if v['vote'] == 'yes')
            logger.info(f"Перенесено {yes_count} голосов 'yes' в анонс #{new_id}")
    except Exception as e:
        logger.warning(f"Не удалось перенести голоса: {e}")

    # Обновляем текст нового анонса с перенесёнными голосами (после публикации)
    async def _update_votes_after_publish():
        import asyncio as _asyncio
        await _asyncio.sleep(3)  # ждём пока анонс опубликуется
        try:
            from handlers.voting import update_announcement_text
            await update_announcement_text(new_id, bot)
        except Exception as e:
            logger.warning(f"Не удалось обновить голоса в новом анонсе: {e}")
    asyncio.create_task(_update_votes_after_publish())

    # === Решаем: писать ли "Сегодня не играем" в группу ===
    current = tz_now()
    new_date = datetime.strptime(latest_date, "%Y-%m-%d").date()
    today = current.date()

    if new_date > today:
        # Новая дата — завтра или позже → пишем в группу
        # Находим кто нажал ❌
        votes = await db.get_votes(announcement_id)
        no_voters = [v for v in votes if v['vote'] == 'no']
        if no_voters:
            culprit_uid = no_voters[0]['user_id']
            culprit_user = await db.get_user(culprit_uid)
            if culprit_user and culprit_user['username']:
                user_mention = f"@{culprit_user['username']}"
            else:
                user_mention = culprit_user['display_name'] if culprit_user else "Кто-то"
        else:
            user_mention = "Кто-то"

        import random
        phrase = random.choice(CANCEL_PHRASES).format(user=user_mention)

        send_kwargs = {"chat_id": GROUP_CHAT_ID, "text": phrase}
        if ANNOUNCE_TOPIC_ID:
            send_kwargs["message_thread_id"] = ANNOUNCE_TOPIC_ID

        try:
            cancel_msg = await bot.send_message(**send_kwargs)
            # Сохраняем ID сообщения об отмене для будущей очистки
            await db.save_cancel_message(cancel_msg.message_id, cancel_msg.chat.id)
            logger.info(f"Отправлено 'Сегодня не играем' в группу (дата переноса: {latest_date})")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение об отмене: {e}")
    else:
        logger.info(f"Перенос на сегодня ({latest_date} {latest_time}) — молча обновляем")

    # Показываем пользователю подтверждение
    dt = datetime.strptime(f"{latest_date} {latest_time}", "%Y-%m-%d %H:%M")
    weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_name = weekday_names[dt.weekday()]

    publish_dt = dt - timedelta(hours=HOURS_BEFORE_ANNOUNCE)
    if publish_dt <= current:
        publish_info = "Анонс выйдет в ближайшие секунды!"
    else:
        publish_info = f"Анонс выйдет: {publish_dt.strftime('%d.%m в %H:%M')}"

    await callback.message.edit_text(
        f"✅ Записано!\n\n"
        f"Ближайшая игра: {day_name}, {dt.strftime('%d.%m')} в {latest_time}\n"
        f"{publish_info}",
        reply_markup=edit_reschedule_keyboard(announcement_id)
    )
    await callback.answer()

    # Планируем публикацию
    await schedule_auto_announce(bot, new_id)


async def schedule_auto_announce(bot: Bot, announcement_id: int):
    """
    Планирует публикацию анонса за HOURS_BEFORE_ANNOUNCE часов до начала игры.
    Если время уже прошло — публикует сразу.
    Анонс берётся из БД по ID.
    """
    # Отменяем предыдущую задачу если была
    if announcement_id in scheduled_tasks:
        scheduled_tasks[announcement_id].cancel()

    announcement = await db.get_announcement(announcement_id)
    if not announcement or not announcement['is_active']:
        logger.warning(f"Анонс #{announcement_id} не найден или неактивен, пропускаем")
        return

    # Если уже опубликован (message_id заполнен) — не публикуем повторно
    if announcement['message_id']:
        logger.info(f"Анонс #{announcement_id} уже опубликован, пропускаем")
        return

    # Вычисляем когда публиковать
    game_dt = datetime.strptime(
        f"{announcement['announce_date']} {announcement['start_time']}",
        "%Y-%m-%d %H:%M"
    )
    publish_dt = game_dt - timedelta(hours=HOURS_BEFORE_ANNOUNCE)
    delay = (publish_dt - tz_now()).total_seconds()

    if delay <= 60:
        # Время публикации уже наступило — публикуем сразу
        logger.info(f"Анонс #{announcement_id}: публикуем сразу (delay={delay:.0f}с)")
        try:
            await publish_announcement(bot, announcement_id)
        except Exception as e:
            logger.error(f"Ошибка публикации анонса #{announcement_id}: {e}")
        return

    logger.info(f"Анонс #{announcement_id}: публикация через {delay / 3600:.1f}ч ({publish_dt.strftime('%d.%m %H:%M')})")

    async def auto_publish():
        await asyncio.sleep(delay)
        try:
            await publish_announcement(bot, announcement_id)
        except Exception as e:
            logger.error(f"Ошибка авто-публикации анонса #{announcement_id}: {e}")

    task = asyncio.create_task(auto_publish())
    scheduled_tasks[announcement_id] = task


async def publish_announcement(bot: Bot, announcement_id: int):
    """
    Публикует существующий анонс из БД в группу.
    Анонс уже создан (create_announcement), просто отправляем и сохраняем message_id.
    """
    announcement = await db.get_announcement(announcement_id)
    if not announcement:
        logger.error(f"Анонс #{announcement_id} не найден!")
        return
    if not announcement['is_active']:
        logger.info(f"Анонс #{announcement_id} деактивирован, не публикуем")
        return
    if announcement['message_id']:
        logger.info(f"Анонс #{announcement_id} уже опубликован, пропускаем")
        return

    game = await db.get_game(announcement['game_id'])
    if game:
        game_emoji = game['emoji']
    else:
        game_emoji = "👾"
        logger.warning(f"Игра id={announcement['game_id']} не найдена, используем заглушку")

    participants = await db.get_announcement_participants(announcement_id)

    # Форматируем дату
    dt = datetime.strptime(announcement['announce_date'], "%Y-%m-%d")
    today = tz_now().date()
    if dt.date() == today:
        date_display = "Сегодня"
    elif dt.date() == today + timedelta(days=1):
        date_display = "Завтра"
    else:
        weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        date_display = f"{weekday_names[dt.weekday()]}, {dt.strftime('%d.%m')}"

    mentions = []
    for p in participants:
        mentions.append(f"@{p[1]}" if p[1] else (p[2] or str(p[0])))

    text = (
        f"{date_display} {announcement['start_time']} – {announcement['end_time']}! {game_emoji}\n\n"
        f"Участники:\n{' '.join(mentions)}"
    )

    send_kwargs = {
        "chat_id": GROUP_CHAT_ID, "photo": announcement['photo_file_id'],
        "caption": text, "reply_markup": voting_keyboard(announcement_id),
    }
    if ANNOUNCE_TOPIC_ID:
        send_kwargs["message_thread_id"] = ANNOUNCE_TOPIC_ID

    sent_msg = await bot.send_photo(**send_kwargs)
    await db.update_announcement_message(announcement_id, sent_msg.message_id, sent_msg.chat.id)

    logger.info(f"Анонс #{announcement_id} опубликован в группу!")

    # Планируем уведомления
    from handlers.notifications import schedule_vote_reminders
    await schedule_vote_reminders(
        bot, announcement_id,
        announcement['announce_date'], announcement['start_time']
    )

    scheduled_tasks.pop(announcement_id, None)


async def restore_scheduled_announcements(bot: Bot):
    """
    Вызывается при старте бота.
    Сканирует БД на наличие запланированных, но не опубликованных анонсов
    (is_active=1, message_id IS NULL) и ставит их в очередь.
    """
    pending = await db.get_pending_announcements()
    if not pending:
        logger.info("Нет запланированных анонсов для восстановления")
        return

    for ann in pending:
        logger.info(f"Восстанавливаем запланированный анонс #{ann['id']} на {ann['announce_date']} {ann['start_time']}")
        try:
            await schedule_auto_announce(bot, ann['id'])
        except Exception as e:
            logger.error(f"Ошибка восстановления анонса #{ann['id']}: {e}")

    logger.info(f"Восстановлено {len(pending)} запланированных анонсов")
