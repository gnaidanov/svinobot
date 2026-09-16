import os

# ---------- BOT ----------
API_TOKEN = os.getenv("API_TOKEN")

# ---------- GAME ----------
DROP_COOLDOWN = 3 * 60 * 60

RARITIES = {
    # Обычные (твои текущие)
    "Common":    {"chance": 500, "points": 5,   "currency": 2},
    "Rare":      {"chance": 250, "points": 15,  "currency": 6},
    "SuperRare": {"chance": 120, "points": 25,  "currency": 10},
    "Epic":      {"chance": 70,  "points": 50,  "currency": 20},
    "Mythic":    {"chance": 40,  "points": 85,  "currency": 35},
    "Legendary": {"chance": 15,  "points": 150, "currency": 60},
    "Limited":   {"chance": 5,   "points": 350, "currency": 150},
    
    # Эволюционные (шанс 0, награды x2)
    "Evo_Common":    {"chance": 0, "points": 10,  "currency": 4},
    "Evo_Rare":      {"chance": 0, "points": 30,  "currency": 12},
    "Evo_SuperRare": {"chance": 0, "points": 50,  "currency": 20},
    "Evo_Epic":      {"chance": 0, "points": 100, "currency": 40},
    "Evo_Mythic":    {"chance": 0, "points": 170, "currency": 70},
    "Evo_Legendary": {"chance": 0, "points": 300, "currency": 120},
    "Evo_Limited":   {"chance": 0, "points": 700, "currency": 300},
}

RARITY_RU_MAP = {
    "Common": "Обычная",
    "Rare": "Редкая",
    "SuperRare": "Сверхредкая", 
    "Epic": "Эпическая",
    "Mythic": "Мифическая",
    "Legendary": "Легендарная",
    "Limited": "Лимитированная",
    # Русские названия для новых типов
    "Evo_Common": "Эволюция: Обычная",
    "Evo_Rare": "Эволюция: Редкая",
    "Evo_SuperRare": "Эволюция: Сверхредкая",
    "Evo_Epic": "Эволюция: Эпическая",
    "Evo_Mythic": "Эволюция: Мифическая",
    "Evo_Legendary": "Эволюция: Легендарная",
    "Evo_Limited": "Эволюция: Лимитированная"
}

# ---------- ADMIN ----------
ADMIN_IDS = {8101191178, 5295930709}
