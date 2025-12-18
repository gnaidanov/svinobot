API_TOKEN = "8435382422:AAF0Cjs56uD2sQpcQ1YyOieCYlPibnVZJYc"

DROP_COOLDOWN = 6*60*60  # 12 часов

RARITIES = {
    "Common":      {"chance": 60, "points": 5,   "currency": 2},
    "Rare":        {"chance": 25, "points": 15,  "currency": 6},
    "Epic":        {"chance": 10, "points": 40,  "currency": 15},
    "Legendary":   {"chance": 4,  "points": 120, "currency": 50},
    "Limited":     {"chance": 1,  "points": 300, "currency": 150},
}

ADMIN_IDS = [8101191178]

RARITY_RU_MAP = {
    "Обычная": "Common",
    "Редкая": "Rare",
    "Эпическая": "Epic",
    "Легендарная": "Legendary",
    "Лимитированная": "Limited"
}