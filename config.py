"""
Конфигурация бота.
Замени значения на свои перед запуском.
"""

# Токен бота — получи у @BotFather в Telegram
BOT_TOKEN = "8654848008:AAGUKbv7ND8JSCtMlX-1JV7LWVBa1GhuxOs"

# ID группы, куда бот будет публиковать анонсы
GROUP_CHAT_ID = -1003145314307  # Замени на свой ID группы

# ID топика (thread) для анонсов, если используешь форум-группу
ANNOUNCE_TOPIC_ID = 3  # Например: 123

# ID топика для предложений игр (если форум-группа)
SUGGESTIONS_TOPIC_ID = 21  # Например: 456

# ID топика «Обзоры» в группе (если используешь форум с топиками)
REVIEWS_TOPIC_ID = 2003  # или число, например: 42

# Ключ Gemini API (оставь пустым если не используешь)
GEMINI_API_KEY = "AIzaSyAs3wezYQ3jfFUu3Wak5Qpx2cwE8wGsErw"

# ID администратора
ADMIN_ID = 568313598  # Замени на свой Telegram user ID

# Часовой пояс (UTC+7 для Новосибирска)
# Используется во ВСЕХ расчётах времени
TIMEZONE_OFFSET_HOURS = 7

# Время по умолчанию для анонса (часы, минуты)
DEFAULT_HOUR = 20
DEFAULT_MINUTE = 0

# За сколько часов до игры публиковать перенесённый анонс
HOURS_BEFORE_ANNOUNCE = 6

# Путь к базе данных
DB_PATH = "game_bot.db"
GROQ_API_KEY = "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"
