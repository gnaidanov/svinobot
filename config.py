import os

# ---------- BOT ----------
API_TOKEN = os.getenv("API_TOKEN")

# ---------- GAME ----------
DROP_COOLDOWN = 6 * 60 * 60  # 6 часов

RARITIES = {
    "Common":      {"chance": 60},
    "Rare":        {"chance": 25},
    "Epic":        {"chance": 10},
    "Legendary":   {"chance": 4},
    "Limited":     {"chance": 1},
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
