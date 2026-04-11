"""
Модуль базы данных.
Все операции с SQLite собраны здесь.
"""

import aiosqlite
from config import DB_PATH


async def init_db():
    """Создаёт таблицы при первом запуске."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица игр (название + эмодзи)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                emoji TEXT NOT NULL
            )
        """)

        # Таблица участников (telegram user_id + username)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                display_name TEXT
            )
        """)

        # Таблица анонсов (добавлено поле announce_date)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                photo_file_id TEXT NOT NULL,
                announce_date TEXT NOT NULL DEFAULT '',
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                message_id INTEGER,
                chat_id INTEGER,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (game_id) REFERENCES games(id)
            )
        """)

        # Миграция: добавляем announce_date если таблица уже существует без него
        try:
            await db.execute("SELECT announce_date FROM announcements LIMIT 1")
        except Exception:
            await db.execute("ALTER TABLE announcements ADD COLUMN announce_date TEXT NOT NULL DEFAULT ''")

        # Таблица участников анонса
        await db.execute("""
            CREATE TABLE IF NOT EXISTS announcement_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                announcement_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                FOREIGN KEY (announcement_id) REFERENCES announcements(id),
                UNIQUE(announcement_id, user_id)
            )
        """)

        # Таблица голосов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                announcement_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                vote TEXT NOT NULL,
                FOREIGN KEY (announcement_id) REFERENCES announcements(id),
                UNIQUE(announcement_id, user_id)
            )
        """)

        # Таблица переносов (когда кто-то нажал ❌ и выбрал дату)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reschedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                announcement_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                chosen_date TEXT NOT NULL,
                chosen_time TEXT NOT NULL,
                FOREIGN KEY (announcement_id) REFERENCES announcements(id),
                UNIQUE(announcement_id, user_id)
            )
        """)

        # Таблица настроек бота (key-value)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Таблица предложений игр
        await db.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                steam_url TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                price_rub TEXT,
                image_url TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица сообщений об отмене (для авто-удаления)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cancel_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()


# === ИГРЫ ===

async def get_all_games():
    """Возвращает список всех игр."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM games ORDER BY name")
        return await cursor.fetchall()


async def add_game(name: str, emoji: str) -> int:
    """Добавляет новую игру. Возвращает ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO games (name, emoji) VALUES (?, ?)",
            (name, emoji)
        )
        await db.commit()
        return cursor.lastrowid


async def get_game(game_id: int):
    """Получает игру по ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        return await cursor.fetchone()


# === ПОЛЬЗОВАТЕЛИ ===

async def get_all_users():
    """Возвращает список всех зарегистрированных пользователей."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users ORDER BY display_name")
        return await cursor.fetchall()


async def add_user(user_id: int, username: str, display_name: str):
    """Добавляет пользователя (или обновляет, если уже есть)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, display_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                display_name = excluded.display_name
        """, (user_id, username, display_name))
        await db.commit()


async def remove_user(user_id: int):
    """Удаляет пользователя из базы."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_user(user_id: int):
    """Получает пользователя по telegram user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        return await cursor.fetchone()


# === АНОНСЫ ===

async def create_announcement(game_id: int, photo_file_id: str,
                                announce_date: str, start_time: str,
                                end_time: str,
                                participant_ids: list[int]) -> int:
    """Создаёт анонс и привязывает участников. Возвращает ID анонса."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO announcements (game_id, photo_file_id, announce_date, start_time, end_time)
            VALUES (?, ?, ?, ?, ?)
        """, (game_id, photo_file_id, announce_date, start_time, end_time))
        announcement_id = cursor.lastrowid

        # Добавляем участников
        for uid in participant_ids:
            await db.execute("""
                INSERT INTO announcement_participants (announcement_id, user_id)
                VALUES (?, ?)
            """, (announcement_id, uid))

        await db.commit()
        return announcement_id


async def update_announcement_message(announcement_id: int, message_id: int, chat_id: int):
    """Сохраняет ID сообщения анонса в группе."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE announcements SET message_id = ?, chat_id = ?
            WHERE id = ?
        """, (message_id, chat_id, announcement_id))
        await db.commit()


async def deactivate_announcement(announcement_id: int):
    """Деактивирует анонс (после нажатия ❌)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE announcements SET is_active = 0 WHERE id = ?",
            (announcement_id,)
        )
        await db.commit()


async def get_announcement(announcement_id: int):
    """Получает анонс по ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM announcements WHERE id = ?", (announcement_id,)
        )
        return await cursor.fetchone()


async def get_active_announcement():
    """Возвращает текущий активный анонс (последний)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM announcements WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        )
        return await cursor.fetchone()


async def get_announcement_participants(announcement_id: int):
    """Возвращает список user_id участников анонса."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT u.user_id, u.username, u.display_name
            FROM announcement_participants ap
            JOIN users u ON ap.user_id = u.user_id
            WHERE ap.announcement_id = ?
        """, (announcement_id,))
        return await cursor.fetchall()


async def update_announcement_time(announcement_id: int, start_time: str, end_time: str):
    """Обновляет время анонса (для админ-редактирования)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE announcements SET start_time = ?, end_time = ?
            WHERE id = ?
        """, (start_time, end_time, announcement_id))
        await db.commit()


async def update_announcement_participants(announcement_id: int, participant_ids: list[int]):
    """Заменяет список участников анонса (для админ-редактирования)."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Удаляем старых
        await db.execute(
            "DELETE FROM announcement_participants WHERE announcement_id = ?",
            (announcement_id,)
        )
        # Добавляем новых
        for uid in participant_ids:
            await db.execute("""
                INSERT INTO announcement_participants (announcement_id, user_id)
                VALUES (?, ?)
            """, (announcement_id, uid))
        # Удаляем голоса тех, кого убрали
        await db.execute("""
            DELETE FROM votes
            WHERE announcement_id = ? AND user_id NOT IN ({})
        """.format(",".join("?" * len(participant_ids))),
            (announcement_id, *participant_ids)
        )
        await db.commit()


# === ГОЛОСОВАНИЕ ===

async def set_vote(announcement_id: int, user_id: int, vote: str):
    """Записывает или обновляет голос (yes/no)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO votes (announcement_id, user_id, vote)
            VALUES (?, ?, ?)
            ON CONFLICT(announcement_id, user_id) DO UPDATE SET vote = excluded.vote
        """, (announcement_id, user_id, vote))
        await db.commit()


async def get_votes(announcement_id: int):
    """Возвращает все голоса по анонсу."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT v.user_id, v.vote, u.username, u.display_name
            FROM votes v
            JOIN users u ON v.user_id = u.user_id
            WHERE v.announcement_id = ?
        """, (announcement_id,))
        return await cursor.fetchall()


async def count_no_votes(announcement_id: int) -> int:
    """Считает количество голосов ❌ по анонсу."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT COUNT(*) FROM votes
            WHERE announcement_id = ? AND vote = 'no'
        """, (announcement_id,))
        row = await cursor.fetchone()
        return row[0]


# === ПЕРЕНОС ===

async def save_reschedule(announcement_id: int, user_id: int,
                           chosen_date: str, chosen_time: str):
    """Сохраняет выбранную дату/время переноса."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO reschedules (announcement_id, user_id, chosen_date, chosen_time)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(announcement_id, user_id) DO UPDATE SET
                chosen_date = excluded.chosen_date,
                chosen_time = excluded.chosen_time
        """, (announcement_id, user_id, chosen_date, chosen_time))
        await db.commit()


async def get_reschedules(announcement_id: int):
    """Возвращает все переносы по анонсу."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT r.*, u.username, u.display_name
            FROM reschedules r
            JOIN users u ON r.user_id = u.user_id
            WHERE r.announcement_id = ?
        """, (announcement_id,))
        return await cursor.fetchall()


async def get_latest_reschedule_date(announcement_id: int):
    """Возвращает самую позднюю дату переноса (для планирования)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT chosen_date, chosen_time
            FROM reschedules
            WHERE announcement_id = ?
            ORDER BY chosen_date DESC, chosen_time DESC
            LIMIT 1
        """, (announcement_id,))
        return await cursor.fetchone()


# === НАСТРОЙКИ ===

async def get_setting(key: str, default: str = "") -> str:
    """Получает настройку по ключу."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str):
    """Сохраняет настройку."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        await db.commit()


# === УДАЛЕНИЕ ===

async def delete_game(game_id: int):
    """Удаляет игру из базы."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM games WHERE id = ?", (game_id,))
        await db.commit()


async def get_all_active_announcements():
    """Возвращает все активные анонсы."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM announcements WHERE is_active = 1 ORDER BY id DESC"
        )
        return await cursor.fetchall()


async def get_pending_announcements():
    """
    Возвращает запланированные, но ещё не опубликованные анонсы.
    Признак: is_active = 1, но message_id IS NULL (не отправлен в группу).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM announcements WHERE is_active = 1 AND message_id IS NULL ORDER BY id"
        )
        return await cursor.fetchall()


async def cleanup_expired_pending():
    """
    Деактивирует запланированные анонсы (message_id IS NULL),
    у которых дата+время уже прошли. Они остаются в базе, но
    больше не показываются в списке активных.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Находим все pending анонсы
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, announce_date, start_time FROM announcements "
            "WHERE is_active = 1 AND message_id IS NULL"
        )
        rows = await cursor.fetchall()

        from datetime import datetime
        from tz import now as tz_now
        current = tz_now()
        cleaned = 0
        for row in rows:
            try:
                ann_dt = datetime.strptime(
                    f"{row['announce_date']} {row['start_time']}", "%Y-%m-%d %H:%M"
                )
                if ann_dt < current:
                    await db.execute(
                        "UPDATE announcements SET is_active = 0 WHERE id = ?",
                        (row['id'],)
                    )
                    cleaned += 1
            except (ValueError, TypeError):
                pass

        if cleaned:
            await db.commit()
        return cleaned


# === ПРЕДЛОЖЕНИЯ ИГР ===

async def add_suggestion(user_id: int, steam_url: str, title: str,
                          description: str, price_rub: str, image_url: str) -> int:
    """Сохраняет предложение игры."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO suggestions (user_id, steam_url, title, description, price_rub, image_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, steam_url, title, description, price_rub, image_url))
        await db.commit()
        return cursor.lastrowid


async def get_last_suggestion_time(user_id: int):
    """Возвращает время последнего предложения пользователя (антиспам)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT created_at FROM suggestions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

# === СООБЩЕНИЯ ОБ ОТМЕНЕ ===

async def save_cancel_message(message_id: int, chat_id: int):
    """Сохраняет ID сообщения об отмене для будущего удаления."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO cancel_messages (message_id, chat_id)
            VALUES (?, ?)
        """, (message_id, chat_id))
        await db.commit()


async def get_yesterday_cancel_messages():
    """Возвращает сообщения об отмене, созданные вчера (для авто-удаления)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT message_id, chat_id FROM cancel_messages
            WHERE date(created_at) < date('now')
        """)
        return await cursor.fetchall()


async def delete_old_cancel_messages():
    """Удаляет записи о старых сообщениях из БД."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM cancel_messages WHERE date(created_at) < date('now')")
        await db.commit()
