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
        CREATE TABLE IF NOT EXISTS market (
            id SERIAL PRIMARY KEY,
            seller_id BIGINT,
            card_id INTEGER,
            price INTEGER,
            created_at TIMESTAMP,
            status TEXT
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
    )
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

    cooldown = timedelta(seconds=DROP_COOLDOWN)

    # проверка по времени
    if now - last_card_at >= cooldown:
        return True, ""

    # проверка по сообщениям
    if msg_count >= 300:
        return True, ""

    remaining_time = cooldown - (now - last_card_at)
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

def get_card(card_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM cards WHERE id = %s",
            (card_id,)
        )
        return cur.fetchone()

def get_total_cards(user_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(count), 0) AS total FROM user_cards WHERE user_id = %s",
            (user_id,)
        )
        return cur.fetchone()["total"]

def add_currency(user_id: int, amount: int):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET currency_balance = currency_balance + %s WHERE user_id = %s",
            (amount, user_id)
        )

def create_listing(seller_id: int, card_id: int, price: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market_listings (seller_id, card_id, price)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (seller_id, card_id, price)
        )
        listing_id = cur.fetchone()["id"]
        return listing_id

def is_card_listed(seller_id: int, card_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM market_listings
            WHERE seller_id = %s
              AND card_id = %s
              AND status = 'active'
            """,
            (seller_id, card_id)
        )
        return cur.fetchone() is not None

def get_active_listings(limit: int = 5):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ml.id AS listing_id,
                ml.card_id,
                ml.price,
                ml.seller_id,
                c.rarity,
                c.points
            FROM market_listings ml
            JOIN cards c ON c.id = ml.card_id
            WHERE ml.status = 'active'
            ORDER BY ml.created_at ASC
            LIMIT %s
            """,
            (limit,)
        )
        return cur.fetchall()

def get_listing(listing_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ml.*,
                c.image,
                c.description,
                c.rarity,
                c.points
            FROM market_listings ml
            JOIN cards c ON c.id = ml.card_id
            WHERE ml.id = %s
            """,
            (listing_id,)
        )
        return cur.fetchone()

def get_balance(user_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT currency FROM users WHERE user_id = %s",
            (user_id,)
        )
        row = cur.fetchone()
        return row["currency"] if row else 0

def change_balance(user_id: int, amount: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET currency = currency + %s
            WHERE user_id = %s
            """,
            (amount, user_id)
        )

def buy_listing(buyer_id: int, listing_id: int) -> bool:
    with conn.cursor() as cur:
        # блокируем лот
        cur.execute(
            """
            SELECT * FROM market_listings
            WHERE id = %s AND status = 'active'
            FOR UPDATE
            """,
            (listing_id,)
        )
        listing = cur.fetchone()
        if not listing:
            return False

        seller_id = listing["seller_id"]
        card_id = listing["card_id"]
        price = listing["price"]

        if seller_id == buyer_id:
            return False

        # проверяем баланс
        cur.execute(
            "SELECT currency FROM users WHERE user_id = %s",
            (buyer_id,)
        )
        buyer = cur.fetchone()
        if not buyer or buyer["currency"] < price:
            return False

        # проверяем карту у продавца
        cur.execute(
            """
            SELECT count FROM user_cards
            WHERE user_id = %s AND card_id = %s AND count > 0
            FOR UPDATE
            """,
            (seller_id, card_id)
        )
        row = cur.fetchone()
        if not row:
            return False

        # списываем валюту
        cur.execute(
            "UPDATE users SET currency = currency - %s WHERE user_id = %s",
            (price, buyer_id)
        )
        cur.execute(
            "UPDATE users SET currency = currency + %s WHERE user_id = %s",
            (price, seller_id)
        )

        # перенос карты
        cur.execute(
            "UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s",
            (seller_id, card_id)
        )
        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (buyer_id, card_id)
        )

        # закрываем лот
        cur.execute(
            "UPDATE market_listings SET status = 'sold' WHERE id = %s",
            (listing_id,)
        )
        return True

def cancel_listing(listing_id: int, seller_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE market_listings
            SET status = 'cancelled'
            WHERE id = %s AND seller_id = %s AND status = 'active'
            """,
            (listing_id, seller_id)
        )
        if cur.rowcount == 0:
            return False
        conn.commit()
        return True

def create_trade_offer(from_id, to_id, offer_type, card_id, price):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trade_offers (from_user_id, to_user_id, type, card_id, price)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (from_id, to_id, offer_type, card_id, price)
        )
        return cur.fetchone()["id"]

def get_trade_offer(offer_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT o.*, c.name, c.rarity, c.points
            FROM trade_offers o
            JOIN cards c ON c.id = o.card_id
            WHERE o.id = %s
            """,
            (offer_id,)
        )
        return cur.fetchone()

def accept_trade_offer(offer_id: int) -> bool:
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM trade_offers WHERE id = %s FOR UPDATE",
                (offer_id,)
            )
            o = cur.fetchone()
            if not o:
                return False

            buyer = o["from_user_id"] if o["type"] == "buy" else o["to_user_id"]
            seller = o["to_user_id"] if o["type"] == "buy" else o["from_user_id"]

            card_id = o["card_id"]
            price = o["price"]

            # проверка денег
            cur.execute(
                "SELECT currency FROM users WHERE user_id = %s",
                (buyer,)
            )
            if cur.fetchone()["currency"] < price:
                return False

            # проверка карты
            cur.execute(
                """
                SELECT count FROM user_cards
                WHERE user_id = %s AND card_id = %s
                """,
                (seller, card_id)
            )
            row = cur.fetchone()
            if not row or row["count"] <= 0:
                return False

            # перевод денег
            cur.execute(
                "UPDATE users SET currency = currency - %s WHERE user_id = %s",
                (price, buyer)
            )
            cur.execute(
                "UPDATE users SET currency = currency + %s WHERE user_id = %s",
                (price, seller)
            )

            # перенос карты
            cur.execute(
                "UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s",
                (seller, card_id)
            )
            cur.execute(
                """
                INSERT INTO user_cards (user_id, card_id, count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, card_id)
                DO UPDATE SET count = user_cards.count + 1
                """,
                (buyer, card_id)
            )

            # удаляем оффер
            cur.execute(
                "DELETE FROM trade_offers WHERE id = %s",
                (offer_id,)
            )
            return True