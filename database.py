import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from config import DROP_COOLDOWN

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не задан")

conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
conn.autocommit = True

# ---------- INIT ----------
def init_db():
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            points INTEGER NOT NULL DEFAULT 0,
            currency INTEGER NOT NULL DEFAULT 0,
            currency_balance INTEGER NOT NULL DEFAULT 0,
            last_drop BIGINT DEFAULT 0,
            last_card_at TIMESTAMP NULL,
            messages_since_card INTEGER NOT NULL DEFAULT 0,
            showcase_card_id INTEGER DEFAULT NULL
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id SERIAL PRIMARY KEY,
            description TEXT NOT NULL,
            image TEXT NOT NULL,
            rarity TEXT NOT NULL,
            points INTEGER NOT NULL,
            currency INTEGER NOT NULL
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_cards (
            user_id BIGINT NOT NULL,
            card_id INTEGER NOT NULL,
            count INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, card_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE CASCADE
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            from_user BIGINT NOT NULL,
            to_user BIGINT NOT NULL,
            from_card INTEGER NOT NULL,
            to_card INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS market_listings (
            id SERIAL PRIMARY KEY,
            seller_id BIGINT NOT NULL,
            card_id INTEGER NOT NULL,
            price INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_offers (
            id SERIAL PRIMARY KEY,
            from_user_id BIGINT NOT NULL,
            to_user_id BIGINT NOT NULL,
            type TEXT CHECK (type IN ('buy','sell')) NOT NULL,
            card_id INT NOT NULL,
            price INT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

# ---------- USERS ----------
def add_user(user_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (user_id,)
        )

def get_user(user_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        return cur.fetchone()

def get_user_card(user_id: int, card_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT uc.card_id, uc.count, c.id, c.rarity, c.points, c.currency
            FROM user_cards uc
            JOIN cards c ON c.id = uc.card_id
            WHERE uc.user_id = %s AND uc.card_id = %s
            """,
            (user_id, card_id)
        )
        return cur.fetchone()

def update_drop_time(user_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET last_drop = EXTRACT(EPOCH FROM NOW()) WHERE user_id = %s",
            (user_id,)
        )

def set_showcase_card(user_id, card_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET showcase_card_id = %s WHERE user_id = %s", (card_id, user_id))

# ---------- CARDS ----------
def add_card(description: str, image: str, rarity: str, points: int, currency: int):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cards (description, image, rarity, points, currency) VALUES (%s, %s, %s, %s, %s)",
            (description, image, rarity, points, currency)
        )

def delete_card(card_id: int):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM cards WHERE id = %s", (card_id,))

def get_card_by_id(card_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
        return cur.fetchone()

def get_random_card_by_rarity(rarity: str):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM cards WHERE rarity = %s ORDER BY RANDOM() LIMIT 1", (rarity,))
        return cur.fetchone()

def get_cards_by_rarity(rarity: str, limit=25, offset=0):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM cards WHERE rarity = %s ORDER BY id LIMIT %s OFFSET %s", (rarity, limit, offset))
        return cur.fetchall()

# ---------- COLLECTION ----------
def give_card(user_id: int, card_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user_id, card_id)
        )

def user_has_card(user_id: int, card_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM user_cards WHERE user_id = %s AND card_id = %s", (user_id, card_id))
        return cur.fetchone() is not None

def get_collection(user_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.*, uc.count
            FROM user_cards uc
            JOIN cards c ON c.id = uc.card_id
            WHERE uc.user_id = %s
            ORDER BY c.rarity, c.id
            """,
            (user_id,)
        )
        return cur.fetchall()

def get_showcase_card(user_id: int):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.*
            FROM users u
            JOIN cards c ON c.id = u.showcase_card_id
            WHERE u.user_id = %s
        """, (user_id,))
        return cur.fetchone()

# ---------- COOLDOWN & STATS ----------
def increment_message_counter(user_id: int):
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET messages_since_card = messages_since_card + 1 WHERE user_id = %s", (user_id,))

def can_take_card(user_id: int) -> tuple[bool, str]:
    row = get_user(user_id)
    if not row: return True, ""
    last_card_at = row["last_card_at"]
    msg_count = row["messages_since_card"]
    if last_card_at is None: return True, ""
    cooldown = timedelta(seconds=DROP_COOLDOWN)
    now = datetime.now()
    if now - last_card_at >= cooldown: return True, ""
    if msg_count >= 300: return True, ""
    rem = cooldown - (now - last_card_at)
    secs = int(rem.total_seconds())
    return False, f"⏳ {secs//3600}ч {(secs%3600)//60}м или {300-msg_count} сообщ."

def reset_card_cooldown(user_id: int):
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET last_card_at = NOW(), messages_since_card = 0 WHERE user_id = %s", (user_id,))

def get_card_count(user_id: int, card_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count FROM user_cards WHERE user_id = %s AND card_id = %s", (user_id, card_id))
        row = cur.fetchone()
        return row["count"] if row else 0

def get_total_cards(user_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(count), 0) AS total FROM user_cards WHERE user_id = %s", (user_id,))
        return cur.fetchone()["total"]

# ---------- TRADE & MARKET ----------
def create_trade(from_user, to_user, from_card, to_card):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO trades (from_user, to_user, from_card, to_card) VALUES (%s, %s, %s, %s) RETURNING id", (from_user, to_user, from_card, to_card))
        return cur.fetchone()["id"]

def get_trade(trade_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM trades WHERE id = %s", (trade_id,))
        return cur.fetchone()

def update_trade_status(trade_id, status):
    with conn.cursor() as cur:
        cur.execute("UPDATE trades SET status = %s WHERE id = %s", (status, trade_id))

def swap_cards(u1, u2, c1, c2):
    with conn.cursor() as cur:
        cur.execute("UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s", (u1, c1))
        cur.execute("UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s", (u2, c2))
        cur.execute("DELETE FROM user_cards WHERE count <= 0")
        give_card(u1, c2)
        give_card(u2, c1)

def create_listing(seller_id, card_id, price):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO market_listings (seller_id, card_id, price) VALUES (%s, %s, %s) RETURNING id", (seller_id, card_id, price))
        return cur.fetchone()["id"]

def is_card_listed(seller_id, card_id):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM market_listings WHERE seller_id=%s AND card_id=%s AND status='active'", (seller_id, card_id))
        return cur.fetchone() is not None

def get_active_listings(limit=10):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                ml.id,
                ml.seller_id,
                ml.card_id,
                ml.price,
                c.rarity,
                c.points
            FROM market_listings ml
            JOIN cards c ON c.id = ml.card_id
            WHERE ml.status = 'active'
            ORDER BY ml.created_at DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()

def get_listing(listing_id: int):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                ml.id,
                ml.seller_id,
                ml.card_id,
                ml.price,
                c.rarity,
                c.points,
                c.image,
                c.description
            FROM market_listings ml
            JOIN cards c ON c.id = ml.card_id
            WHERE ml.id = %s AND ml.status = 'active'
        """, (listing_id,))
        return cur.fetchone()

def buy_listing(buyer_id, listing_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM market_listings WHERE id=%s AND status='active' FOR UPDATE", (listing_id,))
        l = cur.fetchone()
        if not l or l["seller_id"] == buyer_id: return False
        cur.execute("SELECT currency_balance FROM users WHERE user_id=%s", (buyer_id,))
        if cur.fetchone()["currency_balance"] < l["price"]: return False
        cur.execute("UPDATE users SET currency_balance = currency_balance - %s WHERE user_id=%s", (l["price"], buyer_id))
        cur.execute("UPDATE users SET currency_balance = currency_balance + %s WHERE user_id=%s", (l["price"], l["seller_id"]))
        cur.execute("UPDATE user_cards SET count = count - 1 WHERE user_id=%s AND card_id=%s", (l["seller_id"], l["card_id"]))
        give_card(buyer_id, l["card_id"])
        cur.execute("UPDATE market_listings SET status='sold' WHERE id=%s", (listing_id,))
        return True

# ---------- TOP ----------
def top_points(limit=10):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT u.user_id, COALESCE(SUM(uc.count * c.points), 0) AS points 
            FROM users u LEFT JOIN user_cards uc ON uc.user_id = u.user_id 
            LEFT JOIN cards c ON c.id = uc.card_id GROUP BY u.user_id ORDER BY points DESC LIMIT %s
        """, (limit,))
        return cur.fetchall()

def top_currency(limit=10):
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, currency_balance FROM users ORDER BY currency_balance DESC LIMIT %s", (limit,))
        return cur.fetchall()

def top_cards(limit=10):
    with conn.cursor() as cur:
        cur.execute("SELECT u.user_id, COALESCE(SUM(uc.count), 0) AS cards FROM users u LEFT JOIN user_cards uc ON uc.user_id = u.user_id GROUP BY u.user_id ORDER BY cards DESC LIMIT %s", (limit,))
        return cur.fetchall()import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from config import DROP_COOLDOWN

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не задан")

conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
conn.autocommit = True

# ---------- INIT ----------
def init_db():
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            points INTEGER NOT NULL DEFAULT 0,
            currency INTEGER NOT NULL DEFAULT 0,
            currency_balance INTEGER NOT NULL DEFAULT 0,
            last_drop BIGINT DEFAULT 0,
            last_card_at TIMESTAMP NULL,
            messages_since_card INTEGER NOT NULL DEFAULT 0,
            showcase_card_id INTEGER DEFAULT NULL
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id SERIAL PRIMARY KEY,
            description TEXT NOT NULL,
            image TEXT NOT NULL,
            rarity TEXT NOT NULL,
            points INTEGER NOT NULL,
            currency INTEGER NOT NULL
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_cards (
            user_id BIGINT NOT NULL,
            card_id INTEGER NOT NULL,
            count INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, card_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE CASCADE
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            from_user BIGINT NOT NULL,
            to_user BIGINT NOT NULL,
            from_card INTEGER NOT NULL,
            to_card INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS market_listings (
            id SERIAL PRIMARY KEY,
            seller_id BIGINT NOT NULL,
            card_id INTEGER NOT NULL,
            price INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_offers (
            id SERIAL PRIMARY KEY,
            from_user_id BIGINT NOT NULL,
            to_user_id BIGINT NOT NULL,
            type TEXT CHECK (type IN ('buy','sell')) NOT NULL,
            card_id INT NOT NULL,
            price INT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

# ---------- USERS ----------
def add_user(user_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (user_id,)
        )

def get_user(user_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        return cur.fetchone()

def get_user_card(user_id: int, card_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT uc.card_id, uc.count, c.id, c.rarity, c.points, c.currency
            FROM user_cards uc
            JOIN cards c ON c.id = uc.card_id
            WHERE uc.user_id = %s AND uc.card_id = %s
            """,
            (user_id, card_id)
        )
        return cur.fetchone()

def update_drop_time(user_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET last_drop = EXTRACT(EPOCH FROM NOW()) WHERE user_id = %s",
            (user_id,)
        )

def set_showcase_card(user_id, card_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET showcase_card_id = %s WHERE user_id = %s", (card_id, user_id))

# ---------- CARDS ----------
def add_card(description: str, image: str, rarity: str, points: int, currency: int):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cards (description, image, rarity, points, currency) VALUES (%s, %s, %s, %s, %s)",
            (description, image, rarity, points, currency)
        )

def delete_card(card_id: int):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM cards WHERE id = %s", (card_id,))

def get_card_by_id(card_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
        return cur.fetchone()

def get_random_card_by_rarity(rarity: str):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM cards WHERE rarity = %s ORDER BY RANDOM() LIMIT 1", (rarity,))
        return cur.fetchone()

def get_cards_by_rarity(rarity: str, limit=25, offset=0):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM cards WHERE rarity = %s ORDER BY id LIMIT %s OFFSET %s", (rarity, limit, offset))
        return cur.fetchall()

# ---------- COLLECTION ----------
def give_card(user_id: int, card_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user_id, card_id)
        )

def user_has_card(user_id: int, card_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM user_cards WHERE user_id = %s AND card_id = %s", (user_id, card_id))
        return cur.fetchone() is not None

def get_collection(user_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.*, uc.count
            FROM user_cards uc
            JOIN cards c ON c.id = uc.card_id
            WHERE uc.user_id = %s
            ORDER BY c.rarity, c.id
            """,
            (user_id,)
        )
        return cur.fetchall()

def get_showcase_card(user_id: int):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.*
            FROM users u
            JOIN cards c ON c.id = u.showcase_card_id
            WHERE u.user_id = %s
        """, (user_id,))
        return cur.fetchone()

# ---------- COOLDOWN & STATS ----------
def increment_message_counter(user_id: int):
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET messages_since_card = messages_since_card + 1 WHERE user_id = %s", (user_id,))

def can_take_card(user_id: int) -> tuple[bool, str]:
    row = get_user(user_id)
    if not row: return True, ""
    last_card_at = row["last_card_at"]
    msg_count = row["messages_since_card"]
    if last_card_at is None: return True, ""
    cooldown = timedelta(seconds=DROP_COOLDOWN)
    now = datetime.now()
    if now - last_card_at >= cooldown: return True, ""
    if msg_count >= 300: return True, ""
    rem = cooldown - (now - last_card_at)
    secs = int(rem.total_seconds())
    return False, f"⏳ {secs//3600}ч {(secs%3600)//60}м или {300-msg_count} сообщ."

def reset_card_cooldown(user_id: int):
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET last_card_at = NOW(), messages_since_card = 0 WHERE user_id = %s", (user_id,))

def get_card_count(user_id: int, card_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count FROM user_cards WHERE user_id = %s AND card_id = %s", (user_id, card_id))
        row = cur.fetchone()
        return row["count"] if row else 0

def get_total_cards(user_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(count), 0) AS total FROM user_cards WHERE user_id = %s", (user_id,))
        return cur.fetchone()["total"]

# ---------- TRADE & MARKET ----------
def create_trade(from_user, to_user, from_card, to_card):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO trades (from_user, to_user, from_card, to_card) VALUES (%s, %s, %s, %s) RETURNING id", (from_user, to_user, from_card, to_card))
        return cur.fetchone()["id"]

def get_trade(trade_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM trades WHERE id = %s", (trade_id,))
        return cur.fetchone()

def update_trade_status(trade_id, status):
    with conn.cursor() as cur:
        cur.execute("UPDATE trades SET status = %s WHERE id = %s", (status, trade_id))

def swap_cards(u1, u2, c1, c2):
    with conn.cursor() as cur:
        cur.execute("UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s", (u1, c1))
        cur.execute("UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s", (u2, c2))
        cur.execute("DELETE FROM user_cards WHERE count <= 0")
        give_card(u1, c2)
        give_card(u2, c1)

def create_listing(seller_id, card_id, price):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO market_listings (seller_id, card_id, price) VALUES (%s, %s, %s) RETURNING id", (seller_id, card_id, price))
        return cur.fetchone()["id"]

def is_card_listed(seller_id, card_id):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM market_listings WHERE seller_id=%s AND card_id=%s AND status='active'", (seller_id, card_id))
        return cur.fetchone() is not None

def get_active_listings(limit=10):
    with conn.cursor() as cur:
        cur.execute("SELECT ml.*, c.rarity, c.points FROM market_listings ml JOIN cards c ON c.id = ml.card_id WHERE ml.status = 'active' LIMIT %s", (limit,))
        return cur.fetchall()

def buy_listing(buyer_id, listing_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM market_listings WHERE id=%s AND status='active' FOR UPDATE", (listing_id,))
        l = cur.fetchone()
        if not l or l["seller_id"] == buyer_id: return False
        cur.execute("SELECT currency_balance FROM users WHERE user_id=%s", (buyer_id,))
        if cur.fetchone()["currency_balance"] < l["price"]: return False
        cur.execute("UPDATE users SET currency_balance = currency_balance - %s WHERE user_id=%s", (l["price"], buyer_id))
        cur.execute("UPDATE users SET currency_balance = currency_balance + %s WHERE user_id=%s", (l["price"], l["seller_id"]))
        cur.execute("UPDATE user_cards SET count = count - 1 WHERE user_id=%s AND card_id=%s", (l["seller_id"], l["card_id"]))
        give_card(buyer_id, l["card_id"])
        cur.execute("UPDATE market_listings SET status='sold' WHERE id=%s", (listing_id,))
        return True

# ---------- TOP ----------
def top_points(limit=10):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT u.user_id, COALESCE(SUM(uc.count * c.points), 0) AS points 
            FROM users u LEFT JOIN user_cards uc ON uc.user_id = u.user_id 
            LEFT JOIN cards c ON c.id = uc.card_id GROUP BY u.user_id ORDER BY points DESC LIMIT %s
        """, (limit,))
        return cur.fetchall()

def top_currency(limit=10):
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, currency_balance FROM users ORDER BY currency_balance DESC LIMIT %s", (limit,))
        return cur.fetchall()

def top_cards(limit=10):
    with conn.cursor() as cur:
        cur.execute("SELECT u.user_id, COALESCE(SUM(uc.count), 0) AS cards FROM users u LEFT JOIN user_cards uc ON uc.user_id = u.user_id GROUP BY u.user_id ORDER BY cards DESC LIMIT %s", (limit,))
        return cur.fetchall()