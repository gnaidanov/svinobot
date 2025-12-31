import os
import psycopg2
from psycopg2.extras import RealDictCursor

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
            points INTEGER DEFAULT 0,
            currency INTEGER DEFAULT 0,
            last_drop BIGINT DEFAULT 0,
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


def update_drop_time(user_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET last_drop = EXTRACT(EPOCH FROM NOW()) WHERE user_id = %s",
            (user_id,)
        )


def add_rewards(user_id: int, points: int, currency: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET points = points + %s,
                currency = currency + %s
            WHERE user_id = %s
            """,
            (points, currency, user_id)
        )


def set_showcase_card(user_id, card_id):
    try:
        cur.execute(
            "UPDATE users SET showcase_card_id = %s WHERE user_id = %s",
            (card_id, user_id)
        )
        conn.commit()
    except Exception as e:
        print("DB error in set_showcase_card:", e)
        conn.rollback()


# ---------- CARDS ----------
def add_card(description: str, image: str, rarity: str, points: int, currency: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cards (description, image, rarity, points, currency)
            VALUES (%s, %s, %s, %s, %s)
            """,
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
        cur.execute(
            """
            SELECT * FROM cards
            WHERE rarity = %s
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (rarity,)
        )
        return cur.fetchone()


def get_cards_by_rarity(rarity: str, limit=25, offset=0):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM cards
            WHERE rarity = %s
            ORDER BY id
            LIMIT %s OFFSET %s
            """,
            (rarity, limit, offset)
        )
        return cur.fetchall()


def count_cards_by_rarity(rarity: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS count FROM cards WHERE rarity = %s",
            (rarity,)
        )
        return cur.fetchone()["count"]


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
        cur.execute(
            "SELECT 1 FROM user_cards WHERE user_id = %s AND card_id = %s",
            (user_id, card_id)
        )
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


def get_collection_by_rarity(user_id: int, rarity: str, limit=25, offset=0):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.*, uc.count
            FROM user_cards uc
            JOIN cards c ON c.id = uc.card_id
            WHERE uc.user_id = %s AND c.rarity = %s
            ORDER BY c.id
            LIMIT %s OFFSET %s
            """,
            (user_id, rarity, limit, offset)
        )
        return cur.fetchall()


def count_collection_by_rarity(user_id: int, rarity: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM user_cards uc
            JOIN cards c ON c.id = uc.card_id
            WHERE uc.user_id = %s AND c.rarity = %s
            """,
            (user_id, rarity)
        )
        return cur.fetchone()["count"]


# ---------- TOP ----------
def top_points(limit=10):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT user_id, points
            FROM users
            ORDER BY points DESC
            LIMIT %s
            """,
            (limit,)
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


