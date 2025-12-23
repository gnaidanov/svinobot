import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не установлен")

conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode="require")
cursor = conn.cursor()

# ---------- TABLES ----------

cursor.execute("""
CREATE TABLE IF NOT EXISTS cards (
    id SERIAL PRIMARY KEY,
    description TEXT NOT NULL,
    rarity TEXT NOT NULL,
    image TEXT NOT NULL,
    points INTEGER NOT NULL,
    currency INTEGER NOT NULL,
    is_claimed BOOLEAN DEFAULT FALSE
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    points INTEGER DEFAULT 0,
    currency INTEGER DEFAULT 0,
    last_drop BIGINT DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_cards (
    user_id BIGINT,
    card_id INTEGER,
    count INTEGER DEFAULT 1,
    PRIMARY KEY (user_id, card_id)
)
""")

conn.commit()

# ---------- USERS ----------

def add_user(user_id: int):
    cursor.execute(
        "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
        (user_id,)
    )
    conn.commit()


def get_user(user_id: int):
    cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    user = cursor.fetchone()
    if not user:
        add_user(user_id)
        cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        user = cursor.fetchone()
    return user


def update_drop_time(user_id: int):
    cursor.execute(
        "UPDATE users SET last_drop=EXTRACT(EPOCH FROM NOW())::BIGINT WHERE user_id=%s",
        (user_id,)
    )
    conn.commit()


def add_rewards(user_id: int, points: int, currency: int):
    cursor.execute(
        "UPDATE users SET points = points + %s, currency = currency + %s WHERE user_id=%s",
        (points, currency, user_id)
    )
    conn.commit()

# ---------- CARDS ----------

def get_all_cards():
    cursor.execute("SELECT * FROM cards")
    return cursor.fetchall()

def add_card(description, rarity, image, points, currency):
    cursor.execute("""
        INSERT INTO cards (description, rarity, image, points, currency)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (description, rarity, image, points, currency))
    card_id = cursor.fetchone()["id"]
    conn.commit()
    return card_id


def get_card_by_id(card_id: int):
    cursor.execute("SELECT * FROM cards WHERE id=%s", (card_id,))
    return cursor.fetchone()


def get_cards_by_rarity(rarity: str):
    cursor.execute(
        "SELECT * FROM cards WHERE rarity=%s ORDER BY id",
        (rarity,)
    )
    return cursor.fetchall()


def get_random_card_by_rarity(rarity: str):
    if rarity == "Limited":
        cursor.execute("""
            SELECT * FROM cards
            WHERE rarity='Limited' AND is_claimed=FALSE
            ORDER BY RANDOM()
            LIMIT 1
        """)
    else:
        cursor.execute("""
            SELECT * FROM cards
            WHERE rarity=%s
            ORDER BY RANDOM()
            LIMIT 1
        """, (rarity,))
    return cursor.fetchone()


def give_card(user_id: int, card_id: int):
    cursor.execute("""
        INSERT INTO user_cards (user_id, card_id, count)
        VALUES (%s, %s, 1)
        ON CONFLICT (user_id, card_id)
        DO UPDATE SET count = user_cards.count + 1
    """, (user_id, card_id))
    conn.commit()

def get_collection(user_id: int):
    cursor.execute("""
        SELECT cards.id, cards.description, cards.rarity, user_cards.count
        FROM user_cards
        JOIN cards ON cards.id = user_cards.card_id
        WHERE user_id=%s
        ORDER BY cards.rarity, cards.id
    """, (user_id,))
    return cursor.fetchall()

def top_points():
    cursor.execute("""
        SELECT user_id, points
        FROM users
        ORDER BY points DESC
        LIMIT 10
    """)
    return cursor.fetchall()

def get_user_cards_by_rarity(user_id: int, rarity: str):
    cursor.execute(
        """
        SELECT c.*
        FROM user_cards uc
        JOIN cards c ON c.id = uc.card_id
        WHERE uc.user_id = %s AND c.rarity = %s
        ORDER BY c.id
        """,
        (user_id, rarity)
    )
    return cursor.fetchall()

def get_user_rarities(user_id: int):
    cursor.execute(
        """
        SELECT DISTINCT c.rarity
        FROM user_cards uc
        JOIN cards c ON c.id = uc.card_id
        WHERE uc.user_id = %s
        ORDER BY c.rarity
        """,
        (user_id,)
    )
    return [row["rarity"] for row in cursor.fetchall()]
