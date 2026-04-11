"""
Хэндлер уведомлений.

1) За 30 минут до начала — напоминание тем, кто НЕ нажал ✅
2) За 10 минут до начала — если кто-то не нажал ✅, анонс отменяется
3) В момент начала (start_time) — уведомление «На сборы 10 минут» (если включено)

Все таймеры через asyncio. При перезагрузке восстанавливаются из БД.
"""

import asyncio
import random
import logging
from datetime import datetime, timedelta
from aiogram import Bot

import database as db
from config import GROUP_CHAT_ID, ANNOUNCE_TOPIC_ID
from keyboards.reschedule_kb import reschedule_when_keyboard
from tz import now as tz_now

logger = logging.getLogger(__name__)

# Хранилище задач уведомлений: announcement_id -> list[asyncio.Task]
reminder_tasks: dict[int, list[asyncio.Task]] = {}

TIMEOUT_PHRASES = [
    "{user} так и не нажал кнопку 😒\nСегодня не играем.\n\nМолчание — знак... что кто-то забыл про телефон 📱",
    "{user} пропал с радаров 📡\nСегодня не играем.\n\nВидимо, кнопка была слишком далеко от пальца 🫠",
    "{user} ушёл в астрал 🧘\nСегодня не играем.\n\nМы подождали... но не дождались 💔",
    "{user} играет в прятки с кнопкой 🙈\nСегодня не играем.\n\nСпойлер: кнопка победила.",
]


async def schedule_vote_reminders(bot: Bot, announcement_id: int,
                                    date_str: str, start_time: str):
    """Планирует уведомления для анонса."""
    cancel_reminders(announcement_id)

    try:
        game_dt = datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        logger.error(f"Не удалось распарсить дату/время: {date_str} {start_time}")
        return

    current = tz_now()
    tasks = []

    # За 30 минут: напоминание проголосовать
    delay_30 = (game_dt - timedelta(minutes=30) - current).total_seconds()
    if delay_30 > 0:
        tasks.append(asyncio.create_task(
            _remind_to_vote(bot, announcement_id, delay_30)
        ))
        logger.info(f"  → Напоминание проголосовать через {delay_30/60:.0f} мин")

    # За 10 минут: авто-отмена
    delay_10 = (game_dt - timedelta(minutes=10) - current).total_seconds()
    if delay_10 > 0:
        tasks.append(asyncio.create_task(
            _auto_cancel_if_not_voted(bot, announcement_id, delay_10)
        ))
        logger.info(f"  → Авто-отмена через {delay_10/60:.0f} мин")

    # В start_time: уведомление о сборе
    delay_start = (game_dt - current).total_seconds()
    if delay_start > 0:
        tasks.append(asyncio.create_task(
            _gather_notification(bot, announcement_id, delay_start)
        ))
        logger.info(f"  → Уведомление о сборе через {delay_start/60:.0f} мин")

    reminder_tasks[announcement_id] = tasks
    logger.info(f"Запланировано {len(tasks)} уведомлений для анонса #{announcement_id} "
                f"(игра: {date_str} {start_time}, сейчас: {current.strftime('%H:%M')})")


def cancel_reminders(announcement_id: int):
    """Отменяет все запланированные уведомления для анонса."""
    tasks = reminder_tasks.pop(announcement_id, [])
    for task in tasks:
        task.cancel()


async def restore_notifications(bot: Bot):
    """
    Вызывается при старте бота.
    Восстанавливает уведомления для всех активных опубликованных анонсов.
    """
    all_active = await db.get_all_active_announcements()
    restored = 0
    for ann in all_active:
        # Только опубликованные (message_id заполнен) и с датой
        if not ann['message_id'] or not ann['announce_date']:
            continue
        try:
            game_dt = datetime.strptime(
                f"{ann['announce_date']} {ann['start_time']}", "%Y-%m-%d %H:%M"
            )
            # Только будущие анонсы
            if game_dt > tz_now():
                await schedule_vote_reminders(
                    bot, ann['id'], ann['announce_date'], ann['start_time']
                )
                restored += 1
        except (ValueError, TypeError):
            continue

    if restored:
        logger.info(f"Восстановлено уведомлений для {restored} активных анонсов")
    else:
        logger.info("Нет активных анонсов для восстановления уведомлений")


async def _remind_to_vote(bot: Bot, announcement_id: int, delay: float):
    """За 30 минут — напоминание тем кто не нажал ✅."""
    await asyncio.sleep(delay)

    announcement = await db.get_announcement(announcement_id)
    if not announcement or not announcement['is_active']:
        return

    notify_remind = await db.get_setting("notify_remind", "1")
    if notify_remind != "1":
        return

    participants = await db.get_announcement_participants(announcement_id)
    votes = await db.get_votes(announcement_id)
    voted_ids = {v['user_id'] for v in votes}

    sent_to = 0
    for p in participants:
        uid = p[0]
        if uid not in voted_ids:
            try:
                await bot.send_message(
                    chat_id=uid,
                    text="⚠️ Эй, ты забыл подтвердить! Определись, люди ждут твоего решения!"
                )
                sent_to += 1
            except Exception:
                logger.warning(f"Не удалось отправить напоминание пользователю {uid}")

    logger.info(f"Напоминание проголосовать: отправлено {sent_to} пользователям (анонс #{announcement_id})")


async def _auto_cancel_if_not_voted(bot: Bot, announcement_id: int, delay: float):
    """За 10 минут — если кто-то не нажал ✅, анонс отменяется."""
    await asyncio.sleep(delay)

    announcement = await db.get_announcement(announcement_id)
    if not announcement or not announcement['is_active']:
        return

    participants = await db.get_announcement_participants(announcement_id)
    votes = await db.get_votes(announcement_id)
    voted_yes_ids = {v['user_id'] for v in votes if v['vote'] == 'yes'}

    not_confirmed = []
    for p in participants:
        if p[0] not in voted_yes_ids:
            not_confirmed.append(p)

    if not not_confirmed:
        logger.info(f"Анонс #{announcement_id}: все подтвердили, авто-отмена не нужна")
        return

    culprit = not_confirmed[0]
    culprit_uid = culprit[0]
    culprit_uname = culprit[1]
    culprit_display = f"@{culprit_uname}" if culprit_uname else (culprit[2] or str(culprit_uid))

    logger.info(f"Анонс #{announcement_id}: авто-отмена, виновник: {culprit_display}")

    await db.deactivate_announcement(announcement_id)

    tasks = reminder_tasks.get(announcement_id, [])
    current = asyncio.current_task()
    for task in tasks:
        if task is not current:
            task.cancel()
    reminder_tasks.pop(announcement_id, None)

    try:
        await bot.delete_message(
            chat_id=announcement['chat_id'],
            message_id=announcement['message_id']
        )
    except Exception:
        pass

    phrase = random.choice(TIMEOUT_PHRASES).format(user=culprit_display)
    send_kwargs = {"chat_id": GROUP_CHAT_ID, "text": phrase}
    if ANNOUNCE_TOPIC_ID:
        send_kwargs["message_thread_id"] = ANNOUNCE_TOPIC_ID
    await bot.send_message(**send_kwargs)

    try:
        await bot.send_message(
            chat_id=culprit_uid,
            text="Ты не подтвердил участие, и анонс был отменён 😔\n\n"
                 "Когда ты сможешь? 👀",
            reply_markup=reschedule_when_keyboard(announcement_id)
        )
    except Exception:
        logger.warning(f"Не удалось написать виновнику {culprit_uid}")


async def _gather_notification(bot: Bot, announcement_id: int, delay: float):
    """В момент начала — «На сборы 10 минут» всем подтвердившим."""
    await asyncio.sleep(delay)

    announcement = await db.get_announcement(announcement_id)
    if not announcement or not announcement['is_active']:
        return

    notify_gather = await db.get_setting("notify_gather", "1")
    if notify_gather != "1":
        return

    participants = await db.get_announcement_participants(announcement_id)
    votes = await db.get_votes(announcement_id)
    voted_yes_ids = {v['user_id'] for v in votes if v['vote'] == 'yes'}

    sent_to = 0
    for p in participants:
        uid = p[0]
        if uid in voted_yes_ids:
            try:
                await bot.send_message(
                    chat_id=uid,
                    text="🎮 На сборы 10 минут. Моем жопы и заходим в Discord!"
                )
                sent_to += 1
            except Exception:
                logger.warning(f"Не удалось уведомить о сборе пользователя {uid}")

    logger.info(f"Уведомление о сборе: отправлено {sent_to} пользователям (анонс #{announcement_id})")

# === Ежедневная очистка в полночь ===

async def schedule_midnight_cleanup(bot: Bot):
    """
    Запускает ежедневную задачу на 00:01 (по UTC+7).
    - Убирает кнопки у вчерашних анонсов
    - Удаляет сообщения об отмене
    """
    while True:
        # Считаем сколько секунд до 00:01 следующего дня
        current = tz_now()
        tomorrow = current.replace(hour=0, minute=1, second=0, microsecond=0) + timedelta(days=1)
        delay = (tomorrow - current).total_seconds()
        logger.info(f"Очистка запланирована через {delay/3600:.1f}ч ({tomorrow.strftime('%d.%m %H:%M')})")

        await asyncio.sleep(delay)

        logger.info("🧹 Запуск ежедневной очистки...")

        try:
            await _cleanup_old_buttons(bot)
            await _cleanup_cancel_messages(bot)
        except Exception as e:
            logger.error(f"Ошибка ежедневной очистки: {e}")


async def _cleanup_old_buttons(bot: Bot):
    """Убирает кнопки голосования у вчерашних анонсов."""
    all_active = await db.get_all_active_announcements()
    current = tz_now()
    cleaned = 0

    for ann in all_active:
        if not ann['message_id'] or not ann['announce_date']:
            continue
        try:
            ann_dt = datetime.strptime(
                f"{ann['announce_date']} {ann['start_time']}", "%Y-%m-%d %H:%M"
            )
            # Если анонс был вчера или раньше — убираем кнопки и деактивируем
            if ann_dt.date() < current.date():
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=ann['chat_id'],
                        message_id=ann['message_id'],
                        reply_markup=None
                    )
                except Exception:
                    pass
                await db.deactivate_announcement(ann['id'])
                cleaned += 1
        except (ValueError, TypeError):
            pass

    logger.info(f"Очистка кнопок: деактивировано {cleaned} вчерашних анонсов")


async def _cleanup_cancel_messages(bot: Bot):
    """Удаляет вчерашние сообщения 'Сегодня не играем' из группы."""
    messages = await db.get_yesterday_cancel_messages()
    deleted = 0

    for msg in messages:
        try:
            await bot.delete_message(chat_id=msg[1], message_id=msg[0])
            deleted += 1
        except Exception:
            pass

    await db.delete_old_cancel_messages()
    logger.info(f"Очистка отмен: удалено {deleted} сообщений")
