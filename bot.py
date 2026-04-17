"""
Точка входа — запуск бота.
"""

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
import database as db
from handlers import announce, voting, reschedule, menu, admin, suggestions, reviews

# Логирование: и в консоль, и в файл
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),                          # Консоль
        logging.FileHandler("bot.log", mode="w", encoding="utf-8"),  # Файл (чистый при каждом запуске)
    ]
)
logger = logging.getLogger(__name__)


async def main():
    """Главная функция запуска бота."""
    await db.init_db()
    logger.info("База данных инициализирована")

    # Миграция: добавляем статусы игр если колонки нет
    await db.ensure_media_items_status_column()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Порядок роутеров важен
    dp.include_router(menu.router)
    dp.include_router(admin.router)
    dp.include_router(suggestions.router)
    dp.include_router(reviews.router)
    dp.include_router(announce.router)
    dp.include_router(voting.router)
    dp.include_router(reschedule.router)

    # Проверяем часовой пояс
    from tz import now
    logger.info(f"Бот запущен! Текущее время (по конфигу): {now().strftime('%Y-%m-%d %H:%M')}")

    # Чистим прошедшие неопубликованные анонсы
    cleaned = await db.cleanup_expired_pending()
    if cleaned:
        logger.info(f"Деактивировано {cleaned} прошедших запланированных анонсов")

    # Деактивируем прошедшие опубликованные анонсы и убираем кнопки (сценарий 13)
    expired = await db.cleanup_expired_published(bot)
    if expired:
        logger.info(f"Деактивировано {expired} прошедших опубликованных анонсов")

    # Восстанавливаем запланированные анонсы и уведомления
    from handlers.reschedule import restore_scheduled_announcements
    await restore_scheduled_announcements(bot)

    # Восстанавливаем уведомления для уже опубликованных анонсов
    from handlers.notifications import restore_notifications, schedule_midnight_cleanup
    await restore_notifications(bot)

    # Запускаем ежедневную очистку (00:01 по UTC+7)
    asyncio.create_task(schedule_midnight_cleanup(bot))
    logger.info("Ежедневная очистка запланирована")

    # Запускаем автобэкап (раз в 3 дня)
    from handlers.notifications import schedule_auto_backup
    asyncio.create_task(schedule_auto_backup(bot))
    logger.info("Автобэкап запланирован (каждые 3 дня)")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
