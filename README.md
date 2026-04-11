# 🎮 Game Bot — Telegram бот для игровой группы

## Что умеет бот

- Создание анонсов игровых сессий с картинкой
- Выбор игры из базы (или добавление новой с эмодзи)
- Настройка времени с удобными кнопками +/- час/минуты
- Выбор участников (множественный выбор)
- Голосование ✅ Буду / ❌ Не смогу
- Автоматический перенос при нажатии ❌
- Шуточные сообщения о "виновнике торжества"
- Выбор новой даты с каруселью дат
- Автоматическая публикация нового анонса

---

## Установка на VPS

### 1. Подключись к серверу
```bash
ssh user@your-server-ip
```

### 2. Установи Python (если не установлен)
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
```

### 3. Создай папку и загрузи файлы
```bash
mkdir -p ~/game_bot
cd ~/game_bot
```
Скопируй все файлы проекта на сервер (через scp или вручную).

### 4. Создай виртуальное окружение
```bash
python3 -m venv venv
source venv/bin/activate
```

### 5. Установи зависимости
```bash
pip install -r requirements.txt
```

### 6. Настрой конфигурацию
Открой `config.py` и заполни:
```python
BOT_TOKEN = "123456:ABC-your-token"  # Токен от @BotFather
GROUP_CHAT_ID = -1001234567890       # ID твоей группы
ANNOUNCE_TOPIC_ID = 123              # ID топика "Анонсы" (или None)
```

**Как узнать ID группы:**
1. Добавь бота @getidsbot в группу
2. Он покажет Chat ID
3. Удали @getidsbot из группы

**Как узнать ID топика:**
- Если группа — форум с топиками, нажми на топик "Анонсы"
- В URL будет что-то вроде `?topic=123` — это и есть ID

### 7. Запусти бота
```bash
python bot.py
```

### 8. Настрой автозапуск (systemd)
Чтобы бот работал после перезагрузки:

```bash
sudo nano /etc/systemd/system/gamebot.service
```

Вставь:
```ini
[Unit]
Description=Game Telegram Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/game_bot
ExecStart=/home/YOUR_USERNAME/game_bot/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Замени `YOUR_USERNAME` на своё имя пользователя на сервере.

```bash
sudo systemctl daemon-reload
sudo systemctl enable gamebot
sudo systemctl start gamebot
```

Проверка статуса:
```bash
sudo systemctl status gamebot
```

Логи:
```bash
journalctl -u gamebot -f
```

---

## Первый запуск

1. Каждый участник группы должен написать боту в ЛС команду `/start`
2. Это зарегистрирует их в базе
3. После этого ты можешь создавать анонсы через `/announce` в ЛС бота

---

## Команды

| Команда | Описание |
|---------|----------|
| `/start` | Зарегистрироваться |
| `/announce` | Создать новый анонс |
| `/adduser` | Добавить себя в базу |
| `/users` | Показать список участников |
| `/games` | Показать список игр |
| `/removeuser @username` | Удалить участника |

---

## Структура проекта

```
game_bot/
├── bot.py              — Точка входа
├── config.py           — Настройки (токен, ID группы)
├── database.py         — Все операции с базой данных
├── requirements.txt    — Зависимости Python
├── handlers/
│   ├── announce.py     — Создание анонса (FSM)
│   ├── voting.py       — Голосование ✅/❌
│   └── reschedule.py   — Выбор новой даты + авто-анонс
└── keyboards/
    ├── announce_kb.py  — Клавиатуры выбора игры/времени/участников
    ├── voting_kb.py    — Кнопки голосования
    └── reschedule_kb.py — Кнопки переноса
```
