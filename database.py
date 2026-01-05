import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta

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
            SELECT
                uc.card_id,
                uc.count,
                c.id,
                c.rarity,
                c.points,
                c.currency
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
        try:
            cur.execute(
                "UPDATE users SET showcase_card_id = %s WHERE user_id = %s",
                (card_id, user_id)
            )
            conn.commit()
        except Exception as e:
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


def get_showcase_card(user_id: int):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.*
            FROM users u
            JOIN cards c ON c.id = u.showcase_card_id
            WHERE u.user_id = %s
        """, (user_id,))
        return cur.fetchone()

# ---------- TOP ----------
def top_points(limit=10):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              u.user_id,
              COALESCE(SUM(uc.count * c.points), 0) AS points
            FROM users u
            LEFT JOIN user_cards uc ON uc.user_id = u.user_id
            LEFT JOIN cards c ON c.id = uc.card_id
            GROUP BY u.user_id
            ORDER BY points DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def top_currency(limit=10):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              u.user_id,
              COALESCE(SUM(uc.count * c.currency), 0) AS currency
            FROM users u
            LEFT JOIN user_cards uc ON uc.user_id = u.user_id
            LEFT JOIN cards c ON c.id = uc.card_id
            GROUP BY u.user_id
            ORDER BY currency DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def top_cards(limit=10):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              u.user_id,
              COALESCE(SUM(uc.count), 0) AS cards
            FROM users u
            LEFT JOIN user_cards uc ON uc.user_id = u.user_id
            GROUP BY u.user_id
            ORDER BY cards DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def increment_message_counter(user_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET messages_since_card = messages_since_card + 1
            WHERE user_id = %s
            """,
            (user_id,)
        )

def can_take_card(user_id: int) -> tuple[bool, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT last_card_at, messages_since_card
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )
        row = cur.fetchone()

    if not row:
        return True, ""

    last_card_at = row["last_card_at"]
    msg_count = row["messages_since_card"]
    now = datetime.utcnow()

    if last_card_at is None:
        return True, ""

    # 6 часов
    if now - last_card_at >= timedelta(hours=6):
        return True, ""

    # 300 сообщений
    if msg_count >= 300:
        return True, ""

    remaining_time = timedelta(hours=6) - (now - last_card_at)
    total_seconds = int(remaining_time.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60

    return False, f"⏳ Осталось {hours}ч {minutes}м или {300 - msg_count} сообщений"

def reset_card_cooldown(user_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET last_card_at = NOW(),
                messages_since_card = 0
            WHERE user_id = %s
            """,
            (user_id,)
        )

def get_card_count(user_id: int, card_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count
            FROM user_cards
            WHERE user_id = %s AND card_id = %s
            """,
            (user_id, card_id)
        )
        row = cur.fetchone()
        return row["count"] if row else 0


def create_trade(from_user, to_user, from_card, to_card):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trades (from_user, to_user, from_card, to_card)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (from_user, to_user, from_card, to_card)
        )
        return cur.fetchone()["id"]


def get_trade(trade_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM trades WHERE id = %s",
            (trade_id,)
        )
        return cur.fetchone()


def update_trade_status(trade_id, status):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE trades SET status = %s WHERE id = %s",
            (status, trade_id)
        )


def swap_cards(user1, user2, card1, card2):
    with conn.cursor() as cur:
        # уменьшаем количество
        cur.execute(
            "UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s",
            (user1, card1)
        )
        cur.execute(
            "UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s",
            (user2, card2)
        )

        # чистим нули
        cur.execute(
            "DELETE FROM user_cards WHERE count <= 0"
        )

        # добавляем полученные
        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user1, card2)
        )
        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user2, card1)
        )

def is_trade_expired(trade):
    return trade["status"] == "pending" and (
        trade["created_at"] < datetime.utcnow() - timedelta(minutes=3)
    )

def get_card(card_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM cards WHERE id = %s",
            (card_id,)
        )
        return cur.fetchone()

def update_trade_status(trade_id, status):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE trades SET status = %s WHERE id = %s",
            (status, trade_id)
        )
