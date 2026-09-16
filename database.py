import psycopg2
from psycopg2.extras import RealDictCursor
import os
import random
from datetime import datetime, timedelta

DATABASE_URL = os.getenv("DATABASE_URL")

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Таблица пользователей
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                last_card_time TIMESTAMP,
                message_count INTEGER DEFAULT 0,
                currency_balance REAL DEFAULT 0,
                showcase_card_id INTEGER,
                last_hunt_time TIMESTAMP
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id SERIAL PRIMARY KEY,
                description TEXT,
                rarity TEXT,
                points INTEGER,
                currency INTEGER,
                image TEXT,
                is_evolution BOOLEAN DEFAULT FALSE
            );
            """)

            # Связь: какие карты у каких пользователей
            cur.execute("""
            CREATE TABLE IF NOT EXISTS user_cards (
                user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                card_id INTEGER REFERENCES cards(id) ON DELETE CASCADE,
                count INTEGER NOT NULL DEFAULT 0,
                is_evolution BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (user_id, card_id)
            );
            """)

            # Таблица обменов (Trade)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                from_user BIGINT,
                to_user BIGINT,
                from_card INTEGER,
                to_card INTEGER,
                status TEXT DEFAULT 'pending'
            );
            """)

            # Таблица рынка (Listings)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id SERIAL PRIMARY KEY,
                seller_id BIGINT REFERENCES users(id),
                card_id INTEGER REFERENCES cards(id),
                price INTEGER,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)

            cur.execute('''
            CREATE TABLE IF NOT EXISTS hunt_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                weight REAL,
                item_id TEXT,
                rarity TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            ''')

            cur.execute('''
            CREATE TABLE IF NOT EXISTS hunt_stats (
                id SERIAL PRIMARY KEY,
                username TEXT,
                count INTEGER DEFAULT 0,
                period TEXT -- 'day', 'week', etc.
            );
            ''')

            # Таблица для инвентаря
            cur.execute('''
            CREATE TABLE IF NOT EXISTS inventories (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                item_name TEXT,
                quantity INTEGER DEFAULT 1
            );
            ''')

            cur.execute('''
            CREATE TABLE IF NOT EXISTS banned_chats (
                chat_id BIGINT PRIMARY KEY,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            ''')

            # Добавляем недостающие колонки в существующую таблицу
            cur.execute("ALTER TABLE inventories ADD COLUMN IF NOT EXISTS item_icon TEXT DEFAULT '🍄';")
            cur.execute("ALTER TABLE inventories ADD COLUMN IF NOT EXISTS weight FLOAT DEFAULT 0.0;")
            cur.execute("ALTER TABLE inventories ADD COLUMN IF NOT EXISTS is_rare BOOLEAN DEFAULT FALSE;")

# --- УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ---

def add_user(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
        conn.commit()

def get_user(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return cur.fetchone()

def increment_message_counter(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET message_count = message_count + 1 WHERE id = %s", (user_id,))
        conn.commit()

# --- РАБОТА С КАРТАМИ ---

def add_card(description, image, rarity, points, currency):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO cards (description, image, rarity, points, currency)
                VALUES (%s, %s, %s, %s, %s)
            """, (description, image, rarity, points, currency))
        conn.commit()

def delete_card(card_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cards WHERE id = %s", (card_id,))
        conn.commit()

def get_card_by_id(card_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
            return cur.fetchone()

def get_random_card():
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Исправляем запрос, чтобы он не падал, если колонки нет, 
            # или просто выбирал обычную карту
            cur.execute("SELECT * FROM cards WHERE is_evolution = FALSE ORDER BY RANDOM() LIMIT 1")
            return cur.fetchone()

def get_random_card_by_rarity(rarity):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM cards 
                WHERE rarity = %s AND is_evolution = FALSE 
                ORDER BY RANDOM() LIMIT 1
            """, (rarity,))
            return cur.fetchone()

def get_cards_by_rarity(rarity: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM cards WHERE rarity = %s ORDER BY id", (rarity,))
            return cur.fetchall()

# --- КОЛЛЕКЦИЯ ---

def give_card(user_id: int, card_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT currency FROM cards WHERE id = %s", (card_id,))
            card_data = cur.fetchone()
            currency_to_add = card_data['currency'] if card_data else 0

            cur.execute("""
                INSERT INTO user_cards (user_id, card_id, count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1
            """, (user_id, card_id))

            cur.execute("""
                UPDATE users 
                SET currency_balance = currency_balance + %s 
                WHERE id = %s
            """, (currency_to_add, user_id))
            
        conn.commit()

def get_collection(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.*, uc.count FROM user_cards uc
                JOIN cards c ON uc.card_id = c.id
                WHERE uc.user_id = %s AND uc.count > 0
                ORDER BY c.rarity, c.id
            """, (user_id,))
            return cur.fetchall()

def get_card_count(user_id: int, card_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count FROM user_cards WHERE user_id = %s AND card_id = %s", (user_id, card_id))
            res = cur.fetchone()
            return res['count'] if res else 0

def user_has_card(user_id: int, card_id: int) -> bool:
    return get_card_count(user_id, card_id) > 0

def get_total_cards(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT SUM(count) FROM user_cards WHERE user_id = %s", (user_id,))
            res = cur.fetchone()
            return res['sum'] if res and res['sum'] else 0

# --- КУЛДАУНЫ (Cooldowns) ---

def can_take_card(user_id: int):
    COOLDOWN_HOURS = 3 
    MESSAGES_NEEDED = 300

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT last_card_time, message_count FROM users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            
            if not user or not user['last_card_time']:
                return True, ""

            if user['message_count'] >= MESSAGES_NEEDED:
                return True, ""

            diff = datetime.now() - user['last_card_time']
            wait_time = timedelta(hours=COOLDOWN_HOURS)
            
            if diff >= wait_time:
                return True, ""
            
            # РАСЧЕТ КРАСИВОГО ВРЕМЕНИ
            remaining = wait_time - diff
            # Извлекаем часы, минуты и секунды
            total_seconds = int(remaining.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            
            time_str = f"{hours}:{minutes:02d}:{seconds:02d}" # Формат 1:01:39
            
            messages_left = MESSAGES_NEEDED - user['message_count']
            
            reason = (f"⏳ Осталось: {time_str}\n"
                      f"💬 или {messages_left} сообщений.")
            return False, reason

def reset_card_cooldown(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Сбрасываем и время, и счетчик сообщений
            cur.execute("""
                UPDATE users 
                SET last_card_time = NOW(), 
                    message_count = 0 
                WHERE id = %s
            """, (user_id,))
        conn.commit()

# --- ВИТРИНА (Showcase) ---

def set_showcase_card(user_id: int, card_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET showcase_card_id = %s WHERE id = %s", (card_id, user_id))
        conn.commit()

def get_showcase_card(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.* FROM cards c
                JOIN users u ON u.showcase_card_id = c.id
                WHERE u.id = %s
            """, (user_id,))
            return cur.fetchone()

# --- ТОПЫ ---

def top_points(limit: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uc.user_id, SUM(uc.count * c.points) as points
                FROM user_cards uc JOIN cards c ON uc.card_id = c.id
                GROUP BY uc.user_id ORDER BY points DESC LIMIT %s
            """, (limit,))
            return cur.fetchall()

def top_currency(limit: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id as user_id, currency_balance as currency FROM users ORDER BY currency DESC LIMIT %s", (limit,))
            return cur.fetchall()

def top_cards(limit: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, SUM(count) as cards FROM user_cards GROUP BY user_id ORDER BY cards DESC LIMIT %s", (limit,))
            return cur.fetchall()

# --- ОБМЕНЫ (Trades) ---

def create_trade(f_u, t_u, f_c, t_c):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO trades (from_user, to_user, from_card, to_card) VALUES (%s, %s, %s, %s) RETURNING id", (f_u, t_u, f_c, t_c))
            res = cur.fetchone()
            conn.commit()
            return res['id']

def get_trade(t_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM trades WHERE id = %s", (t_id,))
            return cur.fetchone()

def update_trade_status(t_id, status):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE trades SET status = %s WHERE id = %s", (status, t_id))
        conn.commit()

def swap_cards(u1, u2, c1, c2):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE user_cards SET count = count - 1 WHERE user_id=%s AND card_id=%s", (u1, c1))
            cur.execute("UPDATE user_cards SET count = count - 1 WHERE user_id=%s AND card_id=%s", (u2, c2))
            conn.commit()
    give_card(u1, c2)
    give_card(u2, c1)

# --- РЫНОК (Market) ---

def create_listing(seller_id, card_id, price):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO listings (seller_id, card_id, price) VALUES (%s, %s, %s) RETURNING id", (seller_id, card_id, price))
            res = cur.fetchone()
            conn.commit()
            return res['id']

def get_active_listings():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT l.*, c.rarity, c.points FROM listings l
                JOIN cards c ON l.card_id = c.id
                WHERE l.active = TRUE
            """)
            return cur.fetchall()

def get_listing(l_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT l.*, c.rarity, c.points FROM listings l JOIN cards c ON l.card_id = c.id WHERE l.id = %s", (l_id,))
            return cur.fetchone()

def is_card_listed(user_id, card_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM listings WHERE seller_id = %s AND card_id = %s AND active = TRUE", (user_id, card_id))
            return cur.fetchone() is not None

def buy_listing(buyer_id, listing_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM listings WHERE id = %s AND active = TRUE", (listing_id,))
            l = cur.fetchone()
            if not l: return False
            
            cur.execute("SELECT currency_balance FROM users WHERE id = %s", (buyer_id,))
            buyer = cur.fetchone()
            if buyer['currency_balance'] < l['price']: return False
            
            cur.execute("UPDATE users SET currency_balance = currency_balance - %s WHERE id = %s", (l['price'], buyer_id))
            cur.execute("UPDATE users SET currency_balance = currency_balance + %s WHERE id = %s", (l['price'], l['seller_id']))
            cur.execute("UPDATE listings SET active = FALSE WHERE id = %s", (listing_id,))
            cur.execute("UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s", (l['seller_id'], l['card_id']))
            conn.commit()
    give_card(buyer_id, l['card_id'])
    return True

def get_total_cards_count():
    """Считает общее кол-во уникальных карт, созданных в боте (для админов)"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as count FROM cards")
            res = cur.fetchone()
            return res['count'] if res else 0

def get_count_by_rarities():
    """Считает сколько карт каждой редкости существует в базе бота"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rarity, COUNT(*) as count FROM cards GROUP BY rarity")
            return {row['rarity']: row['count'] for row in cur.fetchall()}

def get_user_count_by_rarities(user_id: int):
    """Считает сколько уникальных карт каждой редкости у конкретного игрока"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.rarity, COUNT(DISTINCT uc.card_id) as count 
                FROM user_cards uc
                JOIN cards c ON uc.card_id = c.id
                WHERE uc.user_id = %s AND uc.count > 0
                GROUP BY c.rarity
            """, (user_id,))
            return {row['rarity']: row['count'] for row in cur.fetchall()}

def get_user_card(user_id: int, card_id: int):
    """Возвращает данные о карте игрока, если она у него есть"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uc.count, c.* FROM user_cards uc
                JOIN cards c ON uc.card_id = c.id
                WHERE uc.user_id = %s AND uc.card_id = %s AND uc.count > 0
            """, (user_id, card_id))
            return cur.fetchone()

def cancel_listing(listing_id: int, seller_id: int):
    """Снимает карту с продажи и возвращает её владельцу"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Сначала проверяем, активен ли еще лот
            cur.execute("SELECT card_id FROM listings WHERE id = %s AND seller_id = %s AND active = TRUE", (listing_id, seller_id))
            res = cur.fetchone()
            if not res:
                return False
            
            card_id = res['card_id']

            # 1. Помечаем лот неактивным
            cur.execute("UPDATE listings SET active = FALSE WHERE id = %s", (listing_id,))
            
            # 2. Возвращаем карту игроку (увеличиваем счетчик)
            cur.execute("""
                INSERT INTO user_cards (user_id, card_id, count) 
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, card_id) 
                DO UPDATE SET count = user_cards.count + 1
            """, (seller_id, card_id))
            
            conn.commit()
            return True

def add_evolution_link(base_card_id, result_card_id):
    """Связывает базовую карту с её эволюцией"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO evolutions (base_id, result_id) VALUES (%s, %s) ON CONFLICT (base_id) DO UPDATE SET result_id = %s", 
                        (base_card_id, result_card_id, result_card_id))
            # Помечаем карту как эволюционную, чтобы она не падала в рандоме
            cur.execute("UPDATE cards SET is_evolution = TRUE WHERE id = %s", (result_card_id,))
            conn.commit()

def get_evolution_result(card_id):
    """Проверяет, есть ли у карты эволюция"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT result_id FROM evolutions WHERE base_id = %s", (card_id,))
            res = cur.fetchone()
            return res['result_id'] if res else None

def process_evolution(user_id, base_id, result_id):
    """Возвращает: 'success', 'fail' или 'not_enough'"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count FROM user_cards WHERE user_id = %s AND card_id = %s", (user_id, base_id))
            res = cur.fetchone()
            if not res or res['count'] < 3:
                return 'not_enough'
            
            # Списываем 2 карты в любом случае
            cur.execute("UPDATE user_cards SET count = count - 2 WHERE user_id = %s AND card_id = %s", (user_id, base_id))
            
            # Шанс 25%
            if random.random() <= 0.25:
                cur.execute("""
                    INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1)
                    ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1
                """, (user_id, result_id))
                conn.commit()
                return 'success'
            else:
                conn.commit()
                return 'fail'

# Обнови функцию создания карты админом
def create_evolution_card(description, image_url, base_rarity):
    """Создает эволюционную карту с редкостью Evo_ и статами x2"""
    from config import RARITIES # Импорт внутри, чтобы избежать циклической зависимости
    
    # Формируем ключ новой редкости (например, Evo_Common)
    evo_rarity = f"Evo_{base_rarity}"
    
    # Берем статы из твоего словаря RARITIES
    stats = RARITIES.get(evo_rarity, {"points": 0, "currency": 0})

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO cards (description, image, rarity, points, currency, is_evolution)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                RETURNING id
            """, (description, image_url, evo_rarity, stats['points'], stats['currency']))
            new_id = cur.fetchone()['id']
            conn.commit()
            return new_id
            return new_id

def init_settings_tables():
    """Создает таблицы для настроек и алиасов"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Таблица для общих настроек (например, ID текущей группы)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """)
            # Таблица для коротких имен (алиасов) групп
            cur.execute("""
            CREATE TABLE IF NOT EXISTS group_aliases (
                name TEXT PRIMARY KEY,
                group_id BIGINT
            );
            """)
        conn.commit()

def set_setting(key, value):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO bot_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, str(value)))
        conn.commit()

def get_setting(key):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM bot_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            # Берем значение по ключу 'value' из словаря
            return row['value'] if row else None

def set_alias(name, group_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO group_aliases (name, group_id) VALUES (%s, %s) ON CONFLICT (name) DO UPDATE SET group_id = EXCLUDED.group_id", (name, group_id))
        conn.commit()

def get_alias_id(name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT group_id FROM group_aliases WHERE name = %s", (name,))
            row = cur.fetchone()
            # Берем значение по ключу 'group_id'
            return row['group_id'] if row else None

def delete_alias(name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM group_aliases WHERE name = %s", (name,))
        conn.commit()

def add_hunt_balance(user_id, amount):
    """Начисляет пятачки в общий баланс"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET currency_balance = currency_balance + %s WHERE id = %s", (amount, user_id))
        conn.commit()

def can_take_hunt(user_id: int):
    # Кулдаун на охоту (например, 1 час)
    HUNT_COOLDOWN = timedelta(minutes=10)
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT last_hunt_time FROM users WHERE id = %s", (user_id,))
            res = cur.fetchone()
            
            if not res or not res['last_hunt_time']:
                return True, ""

            diff = datetime.now() - res['last_hunt_time']
            if diff >= HUNT_COOLDOWN:
                return True, ""
            
            remaining = HUNT_COOLDOWN - diff
            total_seconds = int(remaining.total_seconds())
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return False, f"{minutes}м. {seconds}с."

def update_hunt_cooldown(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET last_hunt_time = NOW() WHERE id = %s", (user_id,))
        conn.commit()

def log_hunt(user_id, weight, item_name, rarity, price, item_icon="📦"):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # 1. Запись в логи охоты
            cur.execute("""
                INSERT INTO hunt_logs (user_id, weight, item_id, rarity, timestamp)
                VALUES (%s, %s, %s, %s, NOW())
            """, (user_id, weight, item_name, rarity))
            
            # 2. Начисление денег пользователю
            cur.execute("UPDATE users SET currency_balance = currency_balance + %s WHERE id = %s", (price, user_id))

            # 3. Добавление предмета в инвентарь
            # Определяем, является ли предмет редким для отображения в инвентаре
            is_rare = True if rarity in ['legendary', 'rare'] else False

            cur.execute("""
                INSERT INTO inventories (user_id, item_name, item_icon, quantity, weight, is_rare)
                VALUES (%s, %s, %s, 1, %s, %s)
            """, (user_id, item_name, item_icon, weight, is_rare))
            
        conn.commit()

def get_user_inventory_stats(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Агрегируем данные из логов охоты
            cur.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE rarity = 'legendary') as leg_count,
                    COALESCE(SUM(weight) FILTER (WHERE rarity = 'legendary'), 0) as leg_weight,
                    COUNT(*) FILTER (WHERE rarity != 'legendary') as common_count,
                    COALESCE(SUM(weight) FILTER (WHERE rarity != 'legendary'), 0) as common_weight
                FROM hunt_logs WHERE user_id = %s
            """, (user_id,))
            stats = cur.fetchone()
            
            # Получаем баланс для "Общей ценности" (или можно считать по прайсу из логов, если добавить колонку)
            cur.execute("SELECT currency_balance FROM users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            
            # Возвращаем четкий словарь, чтобы bot.py не ругался на list
            return {
                "leg_count": stats['leg_count'] or 0,
                "leg_weight": stats['leg_weight'] or 0,
                "common_count": stats['common_count'] or 0,
                "common_weight": stats['common_weight'] or 0,
                "total_value": int(user['currency_balance']) if user else 0
            }

def get_hunt_top(period, limit=10):
    with get_conn() as conn:
        # Используем RealDictCursor, чтобы обращаться к полям по именам: row['user_id']
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if period == 'day':
                interval = "1 day"
            elif period == 'week':
                interval = "7 days"
            else:
                interval = "100 years"

            cur.execute(f"""
                SELECT 
                    user_id, 
                    SUM(weight) as total_weight, 
                    COUNT(*) as total_count
                FROM hunt_logs
                WHERE timestamp > NOW() - INTERVAL '{interval}'
                GROUP BY user_id
                ORDER BY total_weight DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()

def clear_user_hunt_stats(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Удаляем записи из логов и инвентаря
            cur.execute("DELETE FROM hunt_logs WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM inventories WHERE user_id = %s", (user_id,))
        conn.commit()

def check_chat_banned(chat_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT EXISTS(SELECT 1 FROM banned_chats WHERE chat_id = %s)", (chat_id,))
            res = cur.fetchone()
            return res['exists'] if res else False

def remove_chat_from_banned(chat_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM banned_chats WHERE chat_id = %s", (chat_id,))
        conn.commit()

def add_chat_to_banned(chat_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO banned_chats (chat_id) VALUES (%s) ON CONFLICT DO NOTHING", (chat_id,))
        conn.commit()