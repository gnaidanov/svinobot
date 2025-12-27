import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
conn.autocommit = True

# ---------- INIT ----------
def init_db():
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            points INT DEFAULT 0,
            currency INT DEFAULT 0,
            last_drop BIGINT DEFAULT 0
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id SERIAL PRIMARY KEY,
            description TEXT NOT NULL,
            image TEXT NOT NULL,
            rarity TEXT NOT NULL,
            points INT NOT NULL,
            currency INT NOT NULL
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_cards (
            user_id BIGINT,
            card_id INT,
            count INT DEFAULT 1,
            PRIMARY KEY (user_id, card_id)
        );
        """)

# ---------- USERS ----------
def add_user(user_id):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (user_id,)
        )

def get_user(user_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        return cur.fetchone()

def update_drop_time(user_id):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET last_drop=EXTRACT(EPOCH FROM NOW()) WHERE user_id=%s",
            (user_id,)
        )

def add_rewards(user_id, points, currency):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET points=points+%s, currency=currency+%s WHERE user_id=%s",
            (points, currency, user_id)
        )

# ---------- CARDS ----------
def add_card(description, image, rarity, points, currency):
    with conn.cursor() as cur:
        cur.execute("""
        INSERT INTO cards (description, image, rarity, points, currency)
        VALUES (%s, %s, %s, %s, %s)
        """, (description, image, rarity, points, currency))

def get_random_card_by_rarity(rarity):
    with conn.cursor() as cur:
        cur.execute("""
        SELECT * FROM cards
        WHERE rarity=%s
        ORDER BY RANDOM()
        LIMIT 1
        """, (rarity,))
        return cur.fetchone()

def get_card_by_id(card_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM cards WHERE id=%s", (card_id,))
        return cur.fetchone()

# ---------- COLLECTION ----------
def give_card(user_id, card_id):
    with conn.cursor() as cur:
        cur.execute("""
        INSERT INTO user_cards (user_id, card_id, count)
        VALUES (%s, %s, 1)
        ON CONFLICT (user_id, card_id)
        DO UPDATE SET count = user_cards.count + 1
        """, (user_id, card_id))

def get_collection(user_id):
    with conn.cursor() as cur:
        cur.execute("""
        SELECT c.description, c.rarity, uc.count
        FROM user_cards uc
        JOIN cards c ON c.id = uc.card_id
        WHERE uc.user_id=%s
        """, (user_id,))
        return cur.fetchall()

# ---------- TOP ----------
def top_points():
    with conn.cursor() as cur:
        cur.execute("""
        SELECT user_id, points
        FROM users
        ORDER BY points DESC
        LIMIT 10
        """)
        return cur.fetchall()
