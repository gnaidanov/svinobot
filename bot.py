import os
import time
import random
import asyncio

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from dotenv import load_dotenv
import database

# ---------- CONFIG ----------
load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")

DROP_COOLDOWN = 6 * 60 * 60  # 6 часов

RARITIES = {
    "Common": {"chance": 60},
    "Rare": {"chance": 30},
    "Epic": {"chance": 9},
    "Legendary": {"chance": 1},
}

RARITY_RU_MAP = {
    "Common": "Обычная",
    "Rare": "Редкая",
    "Epic": "Эпическая",
    "Legendary": "Легендарная",
}

ADMIN_IDS = {123456789}  # <-- ЗАМЕНИ НА СВОЙ TELEGRAM ID

CARDS_PER_PAGE = 25

# ---------- INIT ----------
bot = Bot(API_TOKEN)
dp = Dispatcher()

# ---------- FSM ----------
class AddCardState(StatesGroup):
    waiting_for_photo = State()

# ---------- UTILS ----------
def roll_rarity():
    pool = []
    for rarity, data in RARITIES.items():
        pool.extend([rarity] * data["chance"])
    return random.choice(pool)

def get_safe_random_card():
    for _ in range(10):
        rarity = roll_rarity()
        card = database.get_random_card_by_rarity(rarity)
        if card:
            return card
    return None

# ---------- START ----------
@dp.message(Command("start"))
async def start(msg: types.Message):
    database.add_user(msg.from_user.id)
    await msg.answer(
        "🐾 СвиноКарточки\n\n"
        "/card — получить карту\n"
        "/collection — коллекция\n"
        "/profile — профиль\n"
        "/top — рейтинг\n\n"
        "Админ:\n"
        "/addcard — добавить карту"
    )

# ---------- ADD CARD (ADMIN) ----------
@dp.message(Command("addcard"))
async def addcard_start(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа.")
        return

    await msg.answer(
        "📸 Отправь фото карты с подписью:\n\n"
        "Описание карты\n"
        "rarity=Rare\n"
        "points=10\n"
        "currency=5"
    )
    await state.set_state(AddCardState.waiting_for_photo)

@dp.message(AddCardState.waiting_for_photo, F.photo)
async def addcard_photo(msg: types.Message, state: FSMContext):
    caption = msg.caption
    if not caption:
        await msg.answer("❌ Нужна подпись.")
        return

    lines = caption.splitlines()
    description = lines[0].strip()

    data = {}
    for line in lines[1:]:
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()

    try:
        rarity = data["rarity"]
        points = int(data["points"])
        currency = int(data["currency"])
    except Exception:
        await msg.answer("❌ Ошибка формата.")
        return

    file_id = msg.photo[-1].file_id

    database.add_card(
        description=description,
        image=file_id,
        rarity=rarity,
        points=points,
        currency=currency
    )

    await state.clear()
    await msg.answer("✅ Карта добавлена.")

@dp.message(AddCardState.waiting_for_photo)
async def addcard_invalid(msg: types.Message):
    await msg.answer("❌ Нужно фото карты.")

# ---------- CARD DROP ----------
@dp.message(Command("card"))
async def card(msg: types.Message):
    user_id = msg.from_user.id
    now = int(time.time())

    database.add_user(user_id)
    user = database.get_user(user_id)

    if now - user["last_drop"] < DROP_COOLDOWN:
        remain = DROP_COOLDOWN - (now - user["last_drop"])
        await msg.answer(f"⏳ Подожди {remain // 60} минут.")
        return

    card_obj = get_safe_random_card()
    if not card_obj:
        await msg.answer("❌ Нет карт.")
        return

    database.give_card(user_id, card_obj["id"])
    database.add_rewards(user_id, card_obj["points"], card_obj["currency"])
    database.update_drop_time(user_id)

    await msg.answer_photo(
        photo=card_obj["image"],
        caption=(
            f"💳 {card_obj['description']}\n\n"
            f"👑 {RARITY_RU_MAP.get(card_obj['rarity'])}\n"
            f"+{card_obj['points']} очков | +{card_obj['currency']} пяточек"
        )
    )

# ---------- PROFILE ----------
@dp.message(Command("profile"))
async def profile(msg: types.Message):
    user = database.get_user(msg.from_user.id)
    cards = database.get_collection(msg.from_user.id)
    total = sum(c["count"] for c in cards)

    await msg.answer(
        f"👤 Профиль\n"
        f"🕶 Очки: {user['points']}\n"
        f"🐽 Пяточки: {user['currency']}\n"
        f"💳 Карточек: {total}"
    )

# ---------- COLLECTION ----------
@dp.message(Command("collection"))
async def collection(msg: types.Message):
    cards = database.get_collection(msg.from_user.id)
    if not cards:
        await msg.answer("Коллекция пуста.")
        return

    text = "📚 Коллекция:\n\n"
    for c in cards:
        text += f"{c['description']} [{c['rarity']}] ×{c['count']}\n"

    await msg.answer(text)

# ---------- TOP ----------
@dp.message(Command("top"))
async def top(msg: types.Message):
    top_list = database.top_points()
    text = "🏆 Топ:\n\n"
    for i, u in enumerate(top_list, 1):
        text += f"{i}. {u['user_id']} — {u['points']}\n"
    await msg.answer(text)

# ---------- RUN ----------
async def main():
    database.init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
