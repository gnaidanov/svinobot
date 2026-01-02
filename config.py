import os

# ---------- BOT ----------
API_TOKEN = os.getenv("API_TOKEN")

# ---------- GAME ----------
DROP_COOLDOWN = 6 * 60 * 60  # 6 часов

RARITIES = {
    "Common":      {"chance": 60, "points": 5,   "currency": 2},
    "Rare":        {"chance": 25, "points": 15,  "currency": 6},
    "Epic":        {"chance": 10, "points": 40,  "currency": 15},
    "Legendary":   {"chance": 4,  "points": 120, "currency": 50},
    "Limited":     {"chance": 1,  "points": 300, "currency": 150},
}

RARITY_RU_MAP = {
    "Common": "Обычная",
    "Rare": "Редкая",
    "Epic": "Эпическая",
    "Legendary": "Легендарная",
    "Limited": "Лимитированная",
}

# ---------- ADMIN ----------
ADMIN_IDS = {8101191178, 5295930709}
