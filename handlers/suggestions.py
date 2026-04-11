"""
Хэндлер «Предложить игру».
Пользователь кидает ссылку на Steam, бот парсит инфу и публикует в топик.
"""

import re
import logging
from urllib.parse import quote
from html import escape as html_escape

import aiohttp
from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import database as db
from config import GROUP_CHAT_ID, SUGGESTIONS_TOPIC_ID

router = Router()
logger = logging.getLogger(__name__)


class SuggestForm(StatesGroup):
    """FSM для предложения игры."""
    waiting_link = State()


@router.message(F.text == "🎲 Предложить игру")
async def start_suggest(message: Message, state: FSMContext):
    """Запуск FSM — просим ссылку на Steam."""
    await state.set_state(SuggestForm.waiting_link)
    await message.answer(
        "🎲 Отправь ссылку на игру в Steam\n\n"
        "Формат: https://store.steampowered.com/app/XXXXX/\n\n"
        "Отправь /cancel для отмены"
    )


@router.message(SuggestForm.waiting_link)
async def process_steam_link(message: Message, state: FSMContext, bot: Bot):
    """Парсим ссылку, получаем данные из Steam API, публикуем."""
    text = message.text.strip() if message.text else ""

    if text.startswith("/"):
        await state.clear()
        await message.answer("↩️ Отменено.")
        return

    # Извлекаем app_id
    app_id = _extract_app_id(text)
    if not app_id:
        await message.answer(
            "❌ Не похоже на ссылку Steam!\n\n"
            "Нужна ссылка вида:\n"
            "https://store.steampowered.com/app/730/\n\n"
            "Попробуй ещё раз или /cancel"
        )
        return

    logger.info(f"Запрос Steam API для AppID={app_id} от user_id={message.from_user.id}")
    await message.answer("⏳ Загружаю данные из Steam...")

    game_data = await _fetch_steam_data(app_id)

    if not game_data:
        # Fallback: используем app_id как заглушку
        logger.warning(f"Steam API не вернул данные для AppID={app_id}, используем заглушку")
        game_data = {
            "title": f"Steam App #{app_id}",
            "description": "Не удалось загрузить описание из Steam.",
            "price": "Нет данных",
            "image": "",  # Без картинки
            "screenshots": [],
        }

    steam_url = f"https://store.steampowered.com/app/{app_id}/"
    steam_deep = f"steam://store/{app_id}"

    # Сохраняем в базу
    await db.add_suggestion(
        user_id=message.from_user.id,
        steam_url=steam_url,
        title=game_data["title"],
        description=game_data["description"][:300],
        price_rub=game_data["price"],
        image_url=game_data["image"]
    )

    # Формируем текст (HTML — поддерживает <code> для steam://)
    description = game_data["description"]
    if len(description) > 300:
        description = description[:297] + "..."

    title_escaped = html_escape(game_data["title"])
    desc_escaped = html_escape(description)
    price_escaped = html_escape(game_data["price"])
    user_name = html_escape(message.from_user.first_name or "Аноним")

    caption = (
        f"🎲 <b>{title_escaped}</b>\n\n"
        f"{desc_escaped}\n\n"
        f"💰 Цена: {price_escaped}\n"
        f"🖥 Открыть в приложении: <code>{steam_deep}</code>\n"
        f"👤 Предложил: {user_name}"
    )

    plati_url = f"https://plati.market/search/{quote(game_data['title'])}"

    # Кнопки — только HTTPS (Telegram не пускает steam://)
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛒 Steam", url=steam_url),
            InlineKeyboardButton(text="💸 Plati", url=plati_url),
        ]
    ])

    # Собираем альбом: лого + скриншоты (только если есть картинка)
    screenshots = game_data.get("screenshots", [])[:3]
    has_image = bool(game_data["image"])

    try:
        if has_image:
            # Есть картинка — отправляем альбом
            media = [InputMediaPhoto(media=game_data["image"], caption=caption, parse_mode="HTML")]
            for url in screenshots:
                if url:
                    media.append(InputMediaPhoto(media=url))

            media_kwargs = {"chat_id": GROUP_CHAT_ID, "media": media}
            if SUGGESTIONS_TOPIC_ID:
                media_kwargs["message_thread_id"] = SUGGESTIONS_TOPIC_ID
            await bot.send_media_group(**media_kwargs)
        else:
            # Нет картинки (fallback) — отправляем просто текст
            text_kwargs = {"chat_id": GROUP_CHAT_ID, "text": caption, "parse_mode": "HTML"}
            if SUGGESTIONS_TOPIC_ID:
                text_kwargs["message_thread_id"] = SUGGESTIONS_TOPIC_ID
            await bot.send_message(**text_kwargs)

        # 2. Отдельное сообщение с кнопками
        link_kwargs = {
            "chat_id": GROUP_CHAT_ID,
            "text": f"🔗 {game_data['title']}",
            "reply_markup": buttons,
        }
        if SUGGESTIONS_TOPIC_ID:
            link_kwargs["message_thread_id"] = SUGGESTIONS_TOPIC_ID
        await bot.send_message(**link_kwargs)

        await message.answer("✅ Игра опубликована в «Предложения»!")
    except Exception as e:
        logger.error(f"Ошибка публикации предложения: {e}")
        await message.answer("❌ Не удалось опубликовать. Попробуй позже.")

    await state.clear()


# === Вспомогательные ===

def _extract_app_id(url: str) -> str | None:
    """Извлекает app_id из ссылки Steam."""
    match = re.search(r"store\.steampowered\.com/app/(\d+)", url)
    return match.group(1) if match else None


async def _fetch_steam_data(app_id: str) -> dict | None:
    """
    Мультирегиональный запрос к Steam API.
    Приоритет: RU (рубли, русский) → KZ (тенге→рубли) → NL (евро, заглушка цены).
    Если описание на английском — переводим через deep_translator.
    """
    logger.info(f"Steam API: начинаем для AppID={app_id}")

    # === 1. Пробуем RU ===
    ru_data = await _steam_api_request(app_id, "ru", "russian")
    if ru_data:
        logger.info(f"Steam API: данные из RU для '{ru_data['title']}' (AppID={app_id})")
        return ru_data

    # === 2. Fallback на KZ (конвертация тенге → рубли) ===
    kz_data = await _steam_api_request(app_id, "kz", "english")
    if kz_data:
        # Конвертируем тенге в рубли (примерный курс: 1 руб ≈ 5 тенге)
        kz_data["price"] = _convert_kzt_to_rub(kz_data["price_raw"])
        # Переводим описание
        kz_data["description"] = await _translate_to_russian(kz_data["description"])
        logger.info(f"Steam API: данные из KZ для '{kz_data['title']}' (AppID={app_id})")
        return kz_data

    # === 3. Fallback на NL ===
    nl_data = await _steam_api_request(app_id, "nl", "english")
    if nl_data:
        nl_data["price"] = "Недоступно в РФ (см. цену на Plati)"
        nl_data["description"] = await _translate_to_russian(nl_data["description"])
        logger.info(f"Steam API: данные из NL для '{nl_data['title']}' (AppID={app_id})")
        return nl_data

    logger.warning(f"Steam API: не удалось получить данные ни из одного региона для AppID={app_id}")
    return None


async def _steam_api_request(app_id: str, cc: str, lang: str) -> dict | None:
    """Единичный запрос к Steam API для конкретного региона."""
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc={cc}&l={lang}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"Steam API [{cc.upper()}]: статус {resp.status} для AppID={app_id}")
                    return None

                data = await resp.json()
                if not data or app_id not in data:
                    return None

                app_data = data[app_id]
                if not app_data.get("success"):
                    logger.info(f"Steam API [{cc.upper()}]: success=false для AppID={app_id}")
                    return None

                info = app_data["data"]

                # Цена (сырая для конвертации + отформатированная)
                price = "Бесплатно 🆓"
                price_raw = 0
                if not info.get("is_free") and "price_overview" in info:
                    price = info["price_overview"].get("final_formatted", "Нет данных")
                    price_raw = info["price_overview"].get("final", 0)  # в копейках/тиынах

                # Скриншоты
                screenshots = [
                    ss.get("path_thumbnail", "")
                    for ss in info.get("screenshots", [])[:3]
                ]

                return {
                    "title": info.get("name", "Без названия"),
                    "description": info.get("short_description", ""),
                    "price": price,
                    "price_raw": price_raw,
                    "image": info.get("header_image", ""),
                    "screenshots": [s for s in screenshots if s],
                    "region": cc.upper(),
                }

    except Exception as e:
        logger.error(f"Steam API [{cc.upper()}] ошибка (AppID={app_id}): {e}")
        return None


def _convert_kzt_to_rub(price_tiin: int) -> str:
    """Конвертирует цену из тиын (KZT * 100) в рубли. Курс: 1 RUB ≈ 5 KZT."""
    if price_tiin <= 0:
        return "Бесплатно 🆓"
    kzt = price_tiin / 100  # тиыны → тенге
    rub = kzt / 5  # тенге → рубли (примерный курс)
    return f"~{int(rub)} руб. (конвертация из KZT)"


async def _translate_to_russian(text: str) -> str:
    """Переводит текст на русский через deep_translator. При ошибке возвращает оригинал."""
    if not text:
        return text
    try:
        from deep_translator import GoogleTranslator
        translated = GoogleTranslator(source="en", target="ru").translate(text)
        return translated or text
    except ImportError:
        logger.warning("deep_translator не установлен, описание останется на английском")
        return text
    except Exception as e:
        logger.warning(f"Ошибка перевода: {e}")
        return text
