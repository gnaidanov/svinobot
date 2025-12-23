import os
import time
import random
import asyncio

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile

from dotenv import load_dotenv
import database
from config import API_TOKEN, DROP_COOLDOWN, RARITIES, RARITY_RU_MAP, ADMIN_IDS

# ---------- INIT ----------
load_dotenv()
bot = Bot(API_TOKEN)
dp = Dispatcher()
CARDS_PER_PAGE = 25

# ---------- UTILS ----------
def roll_rarity() -> str:
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

def cards_keyboard(cards: list[dict], page: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    start = page * CARDS_PER_PAGE
    end = start + CARDS_PER_PAGE
    page_cards = cards[start:end]

    row = []
    for i, card in enumerate(page_cards, start=start + 1):
        row.append(
            InlineKeyboardButton(
                text=str(i),
                callback_data=f"card:{card['id']}"
            )
        )
        if len(row) == 5:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)

    pages = (len(cards) - 1) // CARDS_PER_PAGE + 1
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"cards_page:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="»", callback_data=f"cards_page:{page+1}"))
    if nav:
        kb.inline_keyboard.append(nav)
    return kb

# ---------- START ----------
@dp.message(Command("start"))
async def start(msg: types.Message):
    database.add_user(msg.from_user.id)
    await msg.answer(
        "🐾 СвиноКарточки\n\n"
        "/card — получить карту\n"
        "/cards — все карты\n"
        "/collection — коллекция\n"
        "/profile — профиль\n"
        "/top — рейтинг\n"
        "/setcard — установить карту на показ"
    )

# ---------- CARD DROP ----------
@dp.message(Command("card"))
async def card(msg: types.Message):
    user_id = msg.from_user.id
    now = int(time.time())

    database.add_user(user_id)
    user = database.get_user(user_id)

    if now - user["last_drop"] < DROP_COOLDOWN:
        remain = DROP_COOLDOWN - (now - user["last_drop"])
        hours = remain // 3600
        minutes = (remain % 3600) // 60
        await msg.answer(f"⏳ Подожди {hours} ч. {minutes} мин.")
        return

    card_obj = get_safe_random_card()
    if not card_obj:
        await msg.answer("❌ В базе нет доступных карт.")
        return

    database.give_card(user_id, card_obj["id"])
    database.add_rewards(user_id, card_obj["points"], card_obj["currency"])
    database.update_drop_time(user_id)

    if card_obj["rarity"] == "Limited":
        database.claim_limited(card_obj["id"])

    await msg.answer_photo(
        photo=card_obj["image"],  # file_id вместо локального файла
        caption=(
            f"💳 {card_obj['description']}\n\n"
            f"👑 Редкость: {RARITY_RU_MAP.get(card_obj['rarity'], card_obj['rarity'])}\n"
            f"🕶 +{card_obj['points']} очков | 🐽 +{card_obj['currency']} пяточек"
        )
    )

# ---------- PROFILE ----------
@dp.message(Command("profile"))
async def profile(msg: types.Message):
    user = database.get_user(msg.from_user.id)
    cards = database.get_collection(msg.from_user.id)
    total_cards = sum(c["count"] for c in cards)
    text = (
        f"👤 Профиль\n"
        f"🕶 Очки: {user['points']}\n"
        f"🐽 Пяточки: {user['currency']}\n"
        f"💳 Карточек: {total_cards}"
    )
    if user.get("showcase_card_id"):
        showcase = database.get_card_by_id(user["showcase_card_id"])
        if showcase:
            text += (
                f"\n\n🖼 На показ:\n"
                f"{showcase['description'].splitlines()[0][:30]} "
                f"[{RARITY_RU_MAP.get(showcase['rarity'], showcase['rarity'])}]"
            )
    await msg.answer(text)

# ---------- COLLECTION ----------
@dp.message(Command("collection"))
async def collection(msg: types.Message):
    cards = database.get_collection(msg.from_user.id)
    if not cards:
        await msg.answer("Коллекция пуста.")
        return
    text = "📚 Твоя коллекция:\n\n"
    for c in cards:
        text += (
            f"{c['description'].splitlines()[0][:30]} "
            f"[{RARITY_RU_MAP.get(c['rarity'], c['rarity'])}] ×{c['count']}\n"
        )
    await msg.answer(text)

# ---------- TOP ----------
@dp.message(Command("top"))
async def top(msg: types.Message):
    top_list = database.top_points()
    text = "🏆 Топ по очкам:\n\n"
    for i, u in enumerate(top_list, 1):
        text += f"{i}. {u['user_id']} — {u['points']}\n"
    await msg.answer(text)

# ---------- SET SHOWCASE ----------
@dp.message(Command("setcard"))
async def setcard(msg: types.Message):
    description = msg.text.replace("/setcard", "").strip()
    if not description:
        await msg.answer("❌ Укажи описание карты.")
        return
    card = database.user_has_card(msg.from_user.id, description)
    if not card:
        await msg.answer("❌ У тебя нет этой карты.")
        return
    database.set_showcase(msg.from_user.id, card["id"])
    await msg.answer("✅ Карта установлена на показ.")

# ---------- RUN ----------
async def main():
    print(f"Бот запущен. Карт в базе: {len(database.get_all_cards())}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
