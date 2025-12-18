import sqlite3
import time
import threading

# ---------- DATABASE SETUP ----------
db_lock = threading.Lock()

conn = sqlite3.connect(
    "cards.db",
    check_same_thread=False,
    timeout=30
)
cursor = conn.cursor()

# ---------- TABLES ----------
with db_lock:
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT,
        rarity TEXT,
        image TEXT,
        points INTEGER,
        currency INTEGER,
        is_claimed INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        points INTEGER DEFAULT 0,
        currency INTEGER DEFAULT 0,
        last_drop INTEGER DEFAULT 0,
        showcase_card_id INTEGER
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_cards (
        user_id INTEGER,
        card_id INTEGER,
        count INTEGER,
        PRIMARY KEY (user_id, card_id)
    )
    """)

    conn.commit()

# ---------- USERS ----------
def add_user(user_id):
    with db_lock:
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()

def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    result = cursor.fetchone()
    if result is None:
        add_user(user_id)
        cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
    return result

def update_drop_time(user_id):
    with db_lock:
        cursor.execute("UPDATE users SET last_drop=? WHERE user_id=?", (int(time.time()), user_id))
        conn.commit()

def add_rewards(user_id, points, currency):
    with db_lock:
        cursor.execute("""
            UPDATE users
            SET points = points + ?, currency = currency + ?
            WHERE user_id=?
        """, (points, currency, user_id))
        conn.commit()

def set_showcase(user_id, card_id):
    with db_lock:
        cursor.execute("UPDATE users SET showcase_card_id=? WHERE user_id=?", (card_id, user_id))
        conn.commit()

# ---------- CARDS ----------
def add_card(description, rarity, image, points, currency):
    with db_lock:
        cursor.execute("""
        INSERT INTO cards (description, rarity, image, points, currency)
        VALUES (?, ?, ?, ?, ?)
        """, (description, rarity, image, points, currency))
        conn.commit()

def get_card_by_id(card_id):
    cursor.execute(
        "SELECT description, rarity, image, points, currency FROM cards WHERE id=?",
        (card_id,)
    )
    return cursor.fetchone()

def get_random_card_by_rarity(rarity):
    if rarity == "Limited":
        cursor.execute("SELECT * FROM cards WHERE rarity='Limited' AND is_claimed=0 ORDER BY RANDOM() LIMIT 1")
    else:
        cursor.execute("SELECT * FROM cards WHERE rarity=? ORDER BY RANDOM() LIMIT 1", (rarity,))
    return cursor.fetchone()

def claim_limited(card_id):
    with db_lock:
        cursor.execute("UPDATE cards SET is_claimed=1 WHERE id=?", (card_id,))
        conn.commit()

def give_card(user_id, card_id):
    with db_lock:
        cursor.execute("""
        INSERT INTO user_cards (user_id, card_id, count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, card_id)
        DO UPDATE SET count = count + 1
        """, (user_id, card_id))
        conn.commit()

def remove_card(user_id, card_id):
    with db_lock:
        cursor.execute("""
        UPDATE user_cards
        SET count = count - 1
        WHERE user_id=? AND card_id=? AND count > 0
        """, (user_id, card_id))
        cursor.execute("DELETE FROM user_cards WHERE count <= 0")
        conn.commit()

def user_has_card(user_id, first_line):
    cursor.execute("""
    SELECT cards.id, cards.rarity
    FROM user_cards
    JOIN cards ON cards.id = user_cards.card_id
    WHERE user_id=? AND cards.description LIKE ?
    """, (user_id, f"{first_line}%"))
    return cursor.fetchone()

def get_collection(user_id):
    cursor.execute("""
    SELECT cards.id, cards.description, cards.rarity, user_cards.count
    FROM user_cards
    JOIN cards ON cards.id = user_cards.card_id
    WHERE user_id=?
    """, (user_id,))
    return cursor.fetchall()

# ---------- LEADERBOARDS ----------
def top_points():
    cursor.execute("SELECT user_id, points FROM users ORDER BY points DESC LIMIT 10")
    return cursor.fetchall()

def get_all_cards():
    cursor.execute("SELECT id, description, rarity FROM cards ORDER BY rarity, description")
    return cursor.fetchall()

def delete_card_by_description(first_line):
    cursor.execute("SELECT id, image FROM cards WHERE description LIKE ?", (f"{first_line}%",))
    card = cursor.fetchone()
    if not card:
        return None
    card_id, image = card
    cursor.execute("DELETE FROM user_cards WHERE card_id=?", (card_id,))
    cursor.execute("DELETE FROM cards WHERE id=?", (card_id,))
    conn.commit()
    return image
