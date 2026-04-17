"""
Хэндлер голосования.
Обрабатывает нажатия ✅ Буду / ❌ Не смогу.

v2: кнопки меняют текст когда ВСЕ проголосовали,
    announce_date в тексте, уведомления.
"""

import random
import logging
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery

import database as db
from keyboards.voting_kb import voting_keyboard
from keyboards.reschedule_kb import reschedule_when_keyboard

router = Router()
logger = logging.getLogger(__name__)

# Шуточные фразы для "виновника торжества"
CANCEL_PHRASES = [
    "Сегодня не играем 😢\nВиновник торжества: {user}\n\nНу ладно, простим... на этот раз 😏",
    "Сегодня не играем 😢\nВиновник торжества: {user}\n\n{user} решил, что реальная жизнь важнее. Спорное решение 🤔",
    "Сегодня не играем 😢\nВиновник торжества: {user}\n\nКоманда в шоке. Чат в слезах. {user} в бегах 🏃",
    "Сегодня не играем 😢\nВиновник торжества: {user}\n\nЛадно, пойдём трогать траву 🌿",
    "Сегодня не играем 😢\nВиновник торжества: {user}\n\nА ведь мы верили... 💔",
    "Сегодня не играем 😢\nВиновник торжества: {user}\n\nВот так всегда — один за всех, все из-за одного 🫠",
]

# Фразы для тех кто не нажал кнопку и анонс отменился
TIMEOUT_PHRASES = [
    "{user} так и не нажал кнопку 😒\nСегодня не играем.\n\nМолчание — знак... что кто-то забыл про телефон 📱",
    "{user} пропал с радаров 📡\nСегодня не играем.\n\nВидимо, кнопка была слишком далеко от пальца 🫠",
    "{user} ушёл в астрал 🧘\nСегодня не играем.\n\nМы подождали... но не дождались 💔",
]


@router.callback_query(F.data.startswith("vote:"))
async def process_vote(callback: CallbackQuery, bot: Bot):
    """Обработка голоса."""
    logger.info(f"Голос получен: {callback.data} от user_id={callback.from_user.id}")

    parts = callback.data.split(":")
    vote_type = parts[1]  # "yes" или "no"
    announcement_id = int(parts[2])

    user_id = callback.from_user.id
    announcement = await db.get_announcement(announcement_id)

    if not announcement or not announcement['is_active']:
        logger.info(f"Анонс #{announcement_id} неактивен, игнорируем голос от {user_id}")
        await callback.answer("⚠️ Этот анонс уже в архиве и неактивен", show_alert=True)
        return

    # Сценарий 3: проверяем что анонс ещё не прошёл по времени
    if announcement['announce_date'] and announcement['start_time']:
        try:
            from datetime import datetime
            from tz import now as tz_now
            ann_dt = datetime.strptime(
                f"{announcement['announce_date']} {announcement['start_time']}",
                "%Y-%m-%d %H:%M"
            )
            if ann_dt < tz_now():
                await callback.answer("⏰ Это голосование уже истекло", show_alert=True)
                return
        except (ValueError, TypeError):
            pass

    # Проверяем — участник ли этот пользователь
    participants = await db.get_announcement_participants(announcement_id)
    participant_ids = [p[0] for p in participants]
    logger.info(f"Участники анонса: {participant_ids}, голосующий: {user_id}")

    if user_id not in participant_ids:
        await callback.answer("Ты не в списке участников этого анонса", show_alert=True)
        return

    if vote_type == "yes":
        # === Голос ✅ Буду ===
        await db.set_vote(announcement_id, user_id, "yes")
        await update_announcement_text(announcement_id, bot)
        await callback.answer("Я в деле ⚔️", show_alert=False)

    elif vote_type == "no":
        # === Голос ❌ Не смогу ===
        await db.set_vote(announcement_id, user_id, "no")

        # Отменяем уведомления для этого анонса
        from handlers.notifications import cancel_reminders
        cancel_reminders(announcement_id)

        # Деактивируем анонс
        await db.deactivate_announcement(announcement_id)

        # Удаляем сообщение с анонсом из группы
        try:
            await bot.delete_message(
                chat_id=announcement['chat_id'],
                message_id=announcement['message_id']
            )
        except Exception:
            pass

        # НЕ пишем "Сегодня не играем" сразу!
        # Сначала спрашиваем дату, и ТОЛЬКО ПОТОМ решаем —
        # писать ли в группу (логика в reschedule.py save_and_schedule)

        # Пишем "виновнику" в ЛС — когда сможет?
        try:
            await bot.send_message(
                chat_id=user_id,
                text="Когда ты сможешь? 👀",
                reply_markup=reschedule_when_keyboard(announcement_id)
            )
            # Запускаем таймаут — если не ответит за 3ч, уведомим админа (сценарий 1)
            from handlers.notifications import schedule_reschedule_timeout
            schedule_reschedule_timeout(bot, announcement_id, user_id)
        except Exception:
            pass

        await callback.answer("❌ Анонс перенесён. Проверь ЛС бота.")


async def update_announcement_text(announcement_id: int, bot: Bot):
    """Обновляет текст анонса с текущими голосами. Меняет кнопки если все проголосовали."""
    announcement = await db.get_announcement(announcement_id)
    if not announcement:
        return

    game = await db.get_game(announcement['game_id'])
    participants = await db.get_announcement_participants(announcement_id)
    votes = await db.get_votes(announcement_id)

    # Собираем списки
    yes_list = []
    no_list = []
    pending_list = []

    vote_map = {v['user_id']: v['vote'] for v in votes}

    for p in participants:
        uid = p[0]
        uname = p[1]
        dname = p[2]
        display = f"@{uname}" if uname else (dname or str(uid))

        if uid in vote_map:
            if vote_map[uid] == "yes":
                yes_list.append(display)
            else:
                no_list.append(display)
        else:
            pending_list.append(display)

    # Формируем отображение даты
    date_display = _format_announce_date(announcement['announce_date'] or '')

    # Если игра удалена из БД — используем заглушку
    game_emoji = game['emoji'] if game else "👾"
    game_name = game['name'] if game else "Игра"

    # Формируем текст
    text = f"{date_display} {announcement['start_time']} – {announcement['end_time']}! {game_emoji}\n\n"

    if yes_list:
        text += f"✅ Идут: {', '.join(yes_list)}\n"
    if no_list:
        text += f"❌ Не смогут: {', '.join(no_list)}\n"
    if pending_list:
        text += f"⏳ Ждём ответа: {', '.join(pending_list)}\n"

    # Проверяем все ли проголосовали (все нажали ✅)
    all_voted = len(pending_list) == 0 and len(no_list) == 0 and len(yes_list) == len(participants)

    # Проверяем что message_id существует (анонс опубликован в группу)
    if not announcement['message_id']:
        logger.warning(f"Анонс #{announcement_id} не опубликован (message_id=NULL), пропускаем обновление")
        return

    # Обновляем подпись к фото с нужными кнопками
    try:
        await bot.edit_message_caption(
            chat_id=announcement['chat_id'],
            message_id=announcement['message_id'],
            caption=text,
            reply_markup=voting_keyboard(announcement_id, all_voted=all_voted)
        )
    except Exception as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            pass  # Текст не изменился — это нормально
        elif "message to edit not found" in error_msg or "message identifier is not specified" in error_msg:
            # Сообщение удалено из группы — деактивируем анонс
            logger.warning(f"Анонс #{announcement_id}: сообщение удалено из группы, деактивируем")
            await db.deactivate_announcement(announcement_id)
        else:
            logger.error(f"Ошибка обновления анонса #{announcement_id}: {e}")


def _format_announce_date(date_str: str) -> str:
    """Форматирует дату для отображения в анонсе."""
    if not date_str:
        return "Сегодня"
    try:
        from tz import now as tz_now
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = tz_now().date()
        if dt == today:
            return "Сегодня"
        elif dt == today + timedelta(days=1):
            return "Завтра"
        else:
            weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            return f"{weekday_names[dt.weekday()]}, {dt.strftime('%d.%m')}"
    except ValueError:
        return "Сегодня"
