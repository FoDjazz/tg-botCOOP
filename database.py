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
                user_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Миграция: добавляем user_id в cancel_messages если нет
        try:
            await db.execute("SELECT user_id FROM cancel_messages LIMIT 1")
        except Exception:
            await db.execute("ALTER TABLE cancel_messages ADD COLUMN user_id INTEGER")
            await db.commit()

        # Миграция: published_message_id / published_chat_id в reviews
        try:
            await db.execute("SELECT published_message_id FROM reviews LIMIT 1")
        except Exception:
            await db.execute("ALTER TABLE reviews ADD COLUMN published_message_id INTEGER")
            await db.execute("ALTER TABLE reviews ADD COLUMN published_chat_id INTEGER")
            await db.commit()

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
    """Удаляет игру из games и связанный media_item."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT name FROM games WHERE id = ?", (game_id,))
        game = await cursor.fetchone()
        await db.execute("DELETE FROM games WHERE id = ?", (game_id,))
        if game:
            await db.execute(
                "DELETE FROM media_items WHERE type = 'game' AND title = ? COLLATE NOCASE",
                (game['name'],)
            )
        await db.commit()


async def get_announcements_by_game(game_id: int) -> list:
    """Возвращает все активные анонсы для указанной игры."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM announcements WHERE game_id = ? AND is_active = 1",
            (game_id,)
        )
        rows = await cursor.fetchall()
        return rows


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

async def save_cancel_message(message_id: int, chat_id: int, user_id: int | None = None):
    """Сохраняет ID сообщения об отмене для будущего удаления."""
    from tz import now as tz_now
    created_at = tz_now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO cancel_messages (message_id, chat_id, user_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (message_id, chat_id, user_id, created_at))
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


# ================================================================
# БЛОК 2 — MEDIA ITEMS, ОЦЕНКИ, КОММЕНТАРИИ, ОБЗОРЫ
# ================================================================

async def _get_db():
    """Открывает соединение с включёнными FOREIGN KEY."""
    db = await aiosqlite.connect(DB_PATH)
    await db.execute("PRAGMA foreign_keys = ON")
    db.row_factory = aiosqlite.Row
    return db


# === MEDIA ITEMS ===

async def get_media_item_by_game_id(game_id: int):
    """Ищет media_item по game_id через совпадение title с таблицей games."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT name FROM games WHERE id = ?", (game_id,))
        game = await cursor.fetchone()
        if not game:
            return None
        cursor = await db.execute(
            "SELECT * FROM media_items WHERE type = 'game' AND title = ? COLLATE NOCASE",
            (game['name'],)
        )
        return await cursor.fetchone()


async def create_media_item(game_id: int, title: str, created_by: int) -> int:
    """Создаёт запись в media_items для игры. Возвращает ID."""
    db = await _get_db()
    try:
        cursor = await db.execute("""
            INSERT OR IGNORE INTO media_items (type, title, created_by)
            VALUES ('game', ?, ?)
        """, (title, created_by))
        await db.commit()
        if cursor.lastrowid:
            return cursor.lastrowid
        cursor = await db.execute(
            "SELECT id FROM media_items WHERE type = 'game' AND title = ? COLLATE NOCASE",
            (title,)
        )
        row = await cursor.fetchone()
        return row['id']
    finally:
        await db.close()


async def get_media_item(media_item_id: int):
    """Получает media_item по ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM media_items WHERE id = ?", (media_item_id,)
        )
        return await cursor.fetchone()


async def get_all_media_items(type: str = 'game'):
    """Возвращает все media_items по типу."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM media_items WHERE type = ? ORDER BY title", (type,)
        )
        return await cursor.fetchall()


async def mark_completed(media_item_id: int) -> bool:
    """Помечает игру как пройденную."""
    from tz import now as tz_now
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM media_items WHERE id = ?", (media_item_id,)
        )
        if not await cursor.fetchone():
            return False
        await db.execute("""
            UPDATE media_items
            SET is_completed = 1, completed_at = ?, status = 'completed'
            WHERE id = ?
        """, (tz_now().strftime("%Y-%m-%d %H:%M"), media_item_id))
        await db.commit()
        return True
    finally:
        await db.close()


async def mark_completed_safe(media_item_id: int) -> bool:
    """
    Атомарно помечает игру пройденной только если ещё не пройдена.
    Возвращает True если обновление прошло, False если уже было пройдено.
    Защита от race condition: UPDATE WHERE is_completed = 0.
    """
    from tz import now as tz_now
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE media_items
            SET is_completed = 1, completed_at = ?, status = 'completed'
            WHERE id = ? AND is_completed = 0
        """, (tz_now().strftime("%Y-%m-%d %H:%M"), media_item_id))
        await db.commit()
        return cursor.rowcount > 0


async def get_media_items_with_reviews():
    """Возвращает media_items у которых есть хотя бы один обзор."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT DISTINCT m.* FROM media_items m
            INNER JOIN reviews r ON r.media_item_id = m.id
            ORDER BY m.title
        """)
        return await cursor.fetchall()


async def get_media_items_with_content():
    """Возвращает media_items у которых есть оценка, комментарий или обзор."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT DISTINCT m.* FROM media_items m
            WHERE EXISTS (SELECT 1 FROM ratings r WHERE r.media_item_id = m.id)
               OR EXISTS (SELECT 1 FROM comments c WHERE c.media_item_id = m.id)
               OR EXISTS (SELECT 1 FROM reviews rv WHERE rv.media_item_id = m.id)
            ORDER BY m.title
        """)
        return await cursor.fetchall()


async def get_media_items_with_ratings():
    """Возвращает media_items у которых есть хотя бы одна оценка."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT DISTINCT m.* FROM media_items m
            INNER JOIN ratings r ON r.media_item_id = m.id
            ORDER BY m.title
        """)
        return await cursor.fetchall()


async def get_all_contributors(media_item_id: int):
    """Все пользователи у которых есть оценка/комментарий/обзор для игры."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT DISTINCT u.user_id, u.username, u.display_name FROM users u
            WHERE EXISTS (
                SELECT 1 FROM ratings r WHERE r.media_item_id = ? AND r.user_id = u.user_id
            ) OR EXISTS (
                SELECT 1 FROM comments c WHERE c.media_item_id = ? AND c.user_id = u.user_id
            ) OR EXISTS (
                SELECT 1 FROM reviews rv WHERE rv.media_item_id = ? AND rv.user_id = u.user_id
            )
            ORDER BY u.display_name
        """, (media_item_id, media_item_id, media_item_id))
        return await cursor.fetchall()


async def update_announcement_datetime(announcement_id: int,
                                        start_time: str, end_time: str,
                                        announce_date: str,
                                        new_message_id: int,
                                        new_chat_id: int):
    """Обновляет время и message_id существующего анонса (перенос на сегодня)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE announcements
            SET start_time = ?, end_time = ?, announce_date = ?,
                message_id = ?, chat_id = ?
            WHERE id = ?
        """, (start_time, end_time, announce_date, new_message_id, new_chat_id, announcement_id))
        await db.commit()


# === RATINGS ===

VALID_RATINGS = ('trash', 'ok', 'good', 'masterpiece')

RATING_LABELS = {
    'trash':       '🗑 Мусор',
    'ok':          '😐 Проходняк',
    'good':        '👍 Похвально',
    'masterpiece': '💎 Изумительно',
}

RATING_WEIGHTS = {
    'trash':       1,
    'ok':          2,
    'good':        3,
    'masterpiece': 4,
}


async def set_rating(media_item_id: int, user_id: int, rating: str) -> bool:
    """Сохраняет или обновляет оценку пользователя."""
    if rating not in VALID_RATINGS:
        return False
    from tz import now as tz_now
    now_str = tz_now().strftime("%Y-%m-%d %H:%M")
    db = await _get_db()
    try:
        await db.execute("""
            INSERT INTO ratings (media_item_id, user_id, rating, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(media_item_id, user_id) DO UPDATE SET
                rating = excluded.rating, updated_at = excluded.updated_at
        """, (media_item_id, user_id, rating, now_str, now_str))
        await db.commit()
        return True
    finally:
        await db.close()


async def get_rating(media_item_id: int, user_id: int):
    """Возвращает оценку конкретного пользователя или None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM ratings WHERE media_item_id = ? AND user_id = ?",
            (media_item_id, user_id)
        )
        return await cursor.fetchone()


async def get_ratings_summary(media_item_id: int) -> dict:
    """Возвращает количество каждой оценки."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT rating, COUNT(*) as cnt FROM ratings
            WHERE media_item_id = ? GROUP BY rating
        """, (media_item_id,))
        rows = await cursor.fetchall()
    result = {r: 0 for r in VALID_RATINGS}
    for row in rows:
        result[row[0]] = row[1]
    return result


async def get_community_rating(media_item_id: int) -> str | None:
    """Считает среднюю оценку и возвращает вербальную метку."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT rating, COUNT(*) as cnt FROM ratings
            WHERE media_item_id = ? GROUP BY rating
        """, (media_item_id,))
        rows = await cursor.fetchall()
    if not rows:
        return None
    total_score, total_count = 0, 0
    for row in rows:
        weight = RATING_WEIGHTS.get(row[0], 0)
        total_score += weight * row[1]
        total_count += row[1]
    if total_count == 0:
        return None
    avg = total_score / total_count
    if avg < 1.75:   return 'trash'
    elif avg < 2.50: return 'ok'
    elif avg < 3.25: return 'good'
    else:            return 'masterpiece'


async def get_user_ratings(user_id: int):
    """Возвращает все оценки пользователя с названиями игр."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT r.*, m.title, m.type FROM ratings r
            JOIN media_items m ON r.media_item_id = m.id
            WHERE r.user_id = ? ORDER BY r.updated_at DESC
        """, (user_id,))
        return await cursor.fetchall()


# === COMMENTS ===

async def set_comment(media_item_id: int, user_id: int, text: str):
    """Сохраняет или обновляет комментарий пользователя."""
    from tz import now as tz_now
    now_str = tz_now().strftime("%Y-%m-%d %H:%M")
    db = await _get_db()
    try:
        await db.execute("""
            INSERT INTO comments (media_item_id, user_id, text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(media_item_id, user_id) DO UPDATE SET
                text = excluded.text, updated_at = excluded.updated_at
        """, (media_item_id, user_id, text, now_str, now_str))
        await db.commit()
    finally:
        await db.close()


async def get_comment(media_item_id: int, user_id: int):
    """Возвращает комментарий конкретного пользователя или None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM comments WHERE media_item_id = ? AND user_id = ?",
            (media_item_id, user_id)
        )
        return await cursor.fetchone()


async def get_all_comments(media_item_id: int):
    """Возвращает все комментарии к игре с именами пользователей."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT c.*, u.username, u.display_name FROM comments c
            JOIN users u ON c.user_id = u.user_id
            WHERE c.media_item_id = ? ORDER BY c.updated_at DESC
        """, (media_item_id,))
        return await cursor.fetchall()


# === REVIEWS ===

async def set_review(media_item_id: int, user_id: int,
                     final_text: str, answers_json: str | None = None):
    """Сохраняет или обновляет обзор пользователя."""
    from tz import now as tz_now
    now_str = tz_now().strftime("%Y-%m-%d %H:%M")
    db = await _get_db()
    try:
        await db.execute("""
            INSERT INTO reviews
                (media_item_id, user_id, answers_json, final_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(media_item_id, user_id) DO UPDATE SET
                answers_json = excluded.answers_json,
                final_text = excluded.final_text,
                updated_at = excluded.updated_at
        """, (media_item_id, user_id, answers_json, final_text, now_str, now_str))
        await db.commit()
    finally:
        await db.close()


async def update_review_message_id(media_item_id: int, user_id: int,
                                    message_id: int, chat_id: int):
    """Сохраняет message_id опубликованного обзора для последующего редактирования."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE reviews SET published_message_id = ?, published_chat_id = ?
            WHERE media_item_id = ? AND user_id = ?
        """, (message_id, chat_id, media_item_id, user_id))
        await db.commit()


async def get_review(media_item_id: int, user_id: int):
    """Возвращает обзор конкретного пользователя или None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM reviews WHERE media_item_id = ? AND user_id = ?",
            (media_item_id, user_id)
        )
        return await cursor.fetchone()


async def get_all_reviews(media_item_id: int):
    """Возвращает все обзоры к игре с именами пользователей."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT r.*, u.username, u.display_name FROM reviews r
            JOIN users u ON r.user_id = u.user_id
            WHERE r.media_item_id = ? ORDER BY r.updated_at DESC
        """, (media_item_id,))
        return await cursor.fetchall()


async def get_all_reviews_for_reformat() -> list:
    """
    Возвращает все опубликованные обзоры с данными для переоформления.
    Включает: media_item, user, rating, review.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                r.id, r.media_item_id, r.user_id, r.final_text,
                r.published_message_id, r.published_chat_id, r.answers_json,
                m.title as game_title,
                COALESCE(g.emoji, '🎮') as game_emoji,
                u.username, u.display_name,
                rt.rating
            FROM reviews r
            JOIN media_items m ON m.id = r.media_item_id
            LEFT JOIN games g ON g.id = m.game_id
            JOIN users u ON u.user_id = r.user_id
            LEFT JOIN ratings rt ON rt.media_item_id = r.media_item_id
                AND rt.user_id = r.user_id
            ORDER BY r.updated_at DESC
        """)
        return await cursor.fetchall()


async def get_users_without_review(media_item_id: int):
    """Возвращает пользователей у которых есть оценка но нет обзора."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT u.* FROM ratings rat
            JOIN users u ON rat.user_id = u.user_id
            WHERE rat.media_item_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM reviews rev
                  WHERE rev.media_item_id = rat.media_item_id
                    AND rev.user_id = rat.user_id
              )
        """, (media_item_id,))
        return await cursor.fetchall()


# === ОТМЕНА (антиспам + UTC фикс) ===

async def get_today_cancel_message_count(user_id: int) -> int:
    """Количество сообщений 'Сегодня не играю' от пользователя за сегодня."""
    from tz import now as tz_now
    from datetime import datetime, timezone, timedelta
    from config import TIMEZONE_OFFSET_HOURS
    today_str = tz_now().strftime("%Y-%m-%d")
    tz_obj = timezone(timedelta(hours=TIMEZONE_OFFSET_HOURS))
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT created_at FROM cancel_messages WHERE user_id = ?", (user_id,)
        )
        rows = await cursor.fetchall()
    count = 0
    for row in rows:
        try:
            created_utc = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            created_utc = created_utc.replace(tzinfo=timezone.utc)
            created_local = created_utc.astimezone(tz_obj).replace(tzinfo=None)
            if created_local.strftime("%Y-%m-%d") == today_str:
                count += 1
        except Exception:
            pass
    return count


async def get_active_reschedule_for_announcement(original_announcement_id: int):
    """Проверяет есть ли уже активный анонс после переноса (защита от клона)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT game_id, created_at FROM announcements WHERE id = ?",
            (original_announcement_id,)
        )
        original = await cursor.fetchone()
        if not original:
            return None
        cursor = await db.execute("""
            SELECT id, announce_date, start_time FROM announcements
            WHERE game_id = ? AND is_active = 1 AND id != ? AND created_at > ?
            ORDER BY id DESC LIMIT 1
        """, (original['game_id'], original_announcement_id, original['created_at']))
        return await cursor.fetchone()


async def cleanup_expired_published(bot=None) -> int:
    """Деактивирует опубликованные анонсы у которых время прошло."""
    from datetime import datetime
    from tz import now as tz_now
    current = tz_now()
    cleaned = 0
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT id, announce_date, start_time, message_id, chat_id
            FROM announcements WHERE is_active = 1 AND message_id IS NOT NULL
        """)
        rows = await cursor.fetchall()
    for row in rows:
        try:
            ann_dt = datetime.strptime(
                f"{row['announce_date']} {row['start_time']}", "%Y-%m-%d %H:%M"
            )
            if ann_dt < current:
                if bot and row['message_id'] and row['chat_id']:
                    try:
                        await bot.edit_message_reply_markup(
                            chat_id=row['chat_id'],
                            message_id=row['message_id'],
                            reply_markup=None
                        )
                    except Exception:
                        pass
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE announcements SET is_active = 0 WHERE id = ?", (row['id'],)
                    )
                    await db.commit()
                cleaned += 1
        except (ValueError, TypeError):
            pass
    return cleaned


# === СТАТУСЫ ИГР ===

GAME_STATUSES = {
    'planned':     '📋 Запланирована',
    'in_progress': '🎮 В процессе',
    'completed':   '✅ Пройдена',
}


async def ensure_media_items_status_column():
    """Миграция: добавляет колонку status в media_items если её нет."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем что таблица вообще существует
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='media_items'"
        )
        if not await cursor.fetchone():
            return  # таблица создастся в init_db()
        try:
            await db.execute("SELECT status FROM media_items LIMIT 1")
        except Exception:
            await db.execute(
                "ALTER TABLE media_items ADD COLUMN status TEXT NOT NULL DEFAULT 'planned'"
            )
            await db.execute(
                "UPDATE media_items SET status = 'completed' WHERE is_completed = 1"
            )
            await db.commit()


async def set_game_status(media_item_id: int, status: str) -> bool:
    """Меняет статус игры."""
    if status not in GAME_STATUSES:
        return False
    from tz import now as tz_now
    async with aiosqlite.connect(DB_PATH) as db:
        if status == 'completed':
            await db.execute("""
                UPDATE media_items SET status = ?, is_completed = 1, completed_at = ?
                WHERE id = ?
            """, (status, tz_now().strftime("%Y-%m-%d %H:%M"), media_item_id))
        else:
            await db.execute("""
                UPDATE media_items SET status = ?, is_completed = 0, completed_at = NULL
                WHERE id = ?
            """, (status, media_item_id))
        await db.commit()
    return True


async def get_all_media_items_with_status(type: str = 'game'):
    """Возвращает все media_items с полем status, отсортированные."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM media_items WHERE type = ?
            ORDER BY
                CASE status
                    WHEN 'in_progress' THEN 1
                    WHEN 'planned'     THEN 2
                    WHEN 'completed'   THEN 3
                    ELSE 4
                END,
                title COLLATE NOCASE
        """, (type,))
        return await cursor.fetchall()


async def add_media_item_manual(title: str, created_by: int, status: str = 'planned') -> int:
    """Добавляет игру в media_items вручную (без анонса)."""
    if status not in GAME_STATUSES:
        status = 'planned'
    db = await _get_db()
    try:
        cursor = await db.execute("""
            INSERT OR IGNORE INTO media_items (type, title, created_by, status)
            VALUES ('game', ?, ?, ?)
        """, (title, created_by, status))
        await db.commit()
        if cursor.lastrowid:
            return cursor.lastrowid
        cursor = await db.execute(
            "SELECT id FROM media_items WHERE type = 'game' AND title = ? COLLATE NOCASE",
            (title,)
        )
        row = await cursor.fetchone()
        return row['id']
    finally:
        await db.close()
