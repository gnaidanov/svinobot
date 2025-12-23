import time
import random
import asyncio

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from dotenv import load_dotenv

import database
from config import (
    API_TOKEN,
    DROP_COOLDOWN,
    RARITIES,
    RARITY_RU_MAP,
    ADMIN_IDS,
)

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


def cards_keyboard(cards: list[dict]):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=str(c["id"]), callback_data=f"card:{c['id']}")]
            for c in cards
        ]
    )
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
        await msg.answer(f"⏳ Подожди {remain // 3600} ч. {(remain % 3600) // 60} мин.")
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

    text = (
        f"💳 {card_obj['description']}\n\n"
        f"👑 Редкость: {RARITY_RU_MAP.get(card_obj['rarity'], card_obj['rarity'])}\n"
        f"🕶 +{card_obj['points']} | 🐽 +{card_obj['currency']}\n"
        f"🆔 ID карты: {card_obj['id']}"
    )

    await msg.answer_photo(
        photo=card_obj["image"],  # file_id
        caption=text
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
        card = database.get_card_by_id(user["showcase_card_id"])
        if card:
            text += (
                f"\n\n🖼 На показ:\n"
                f"{card['description'].splitlines()[0][:30]} "
                f"[{RARITY_RU_MAP.get(card['rarity'], card['rarity'])}]"
            )

    await msg.answer(text)


# ---------- COLLECTION ----------
@dp.message(Command("collection"))
async def collection(msg: types.Message):
    cards = database.get_collection(msg.from_user.id)
    if not cards:
        await msg.answer("Коллекция пуста.")
        return

    rarities = sorted({c["rarity"] for c in cards})
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=RARITY_RU_MAP[r], callback_data=f"collection:{r}")]
            for r in rarities
        ]
    )
    await msg.answer("Выбери редкость:", reply_markup=kb)


@dp.callback_query(F.data.startswith("collection:"))
async def collection_rarity(cb: types.CallbackQuery):
    rarity = cb.data.split(":", 1)[1]
    cards = [
        c for c in database.get_collection(cb.from_user.id)
        if c["rarity"] == rarity
    ]

    await cb.message.answer(
        f"Карты редкости {RARITY_RU_MAP.get(rarity, rarity)}:",
        reply_markup=cards_keyboard(cards)
    )
    await cb.answer()


# ---------- ALL CARDS ----------
@dp.message(Command("cards"))
async def cards(msg: types.Message):
    cards = database.get_all_cards()
    if not cards:
        await msg.answer("Карт пока нет.")
        return

    rarities = sorted({c["rarity"] for c in cards})
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=RARITY_RU_MAP[r], callback_data=f"cards:{r}")]
            for r in rarities
        ]
    )
    await msg.answer("Выбери редкость:", reply_markup=kb)


@dp.callback_query(F.data.startswith("cards:"))
async def cards_rarity(cb: types.CallbackQuery):
    rarity = cb.data.split(":", 1)[1]
    cards = [
        c for c in database.get_all_cards()
        if c["rarity"] == rarity
    ]

    await cb.message.answer(
        f"Карты редкости {RARITY_RU_MAP.get(rarity, rarity)}:",
        reply_markup=cards_keyboard(cards)
    )
    await cb.answer()


# ---------- SHOW CARD ----------
@dp.callback_query(F.data.startswith("card:"))
async def show_card(cb: types.CallbackQuery):
    card_id = int(cb.data.split(":", 1)[1])
    card = database.get_card_by_id(card_id)

    if not card:
        await cb.answer("Карта не найдена", show_alert=True)
        return

    text = (
        f"💳 {card['description']}\n\n"
        f"👑 Редкость: {RARITY_RU_MAP.get(card['rarity'], card['rarity'])}\n"
        f"🕶 Очки: {card['points']}\n"
        f"🐽 Пяточки: {card['currency']}\n"
        f"🆔 ID карты: {card['id']}"
    )
    print("IMAGE =", card["image"])
    await cb.message.answer_photo(
        photo=card["image"],  # file_id
        caption=text
    )
    await cb.answer()


# ---------- TOP ----------
@dp.message(Command("top"))
async def top(msg: types.Message):
    text = "🏆 Топ по очкам:\n\n"
    for i, u in enumerate(database.top_points(), 1):
        text += f"{i}. {u['user_id']} — {u['points']}\n"
    await msg.answer(text)


# ---------- SET SHOWCASE ----------
@dp.message(Command("setcard"))
async def setcard(msg: types.Message):
    card_id = msg.text.replace("/setcard", "").strip()
    if not card_id.isdigit():
        await msg.answer("❌ Укажи ID карты.")
        return

    card = database.user_has_card(msg.from_user.id, int(card_id))
    if not card:
        await msg.answer("❌ У тебя нет этой карты.")
        return

    database.set_showcase(msg.from_user.id, int(card_id))
    await msg.answer("✅ Карта установлена на показ.")


# ---------- ADMIN: ADD CARD ----------
@dp.message(Command("addcard"))
async def addcard(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа.")
        return

    src = msg.reply_to_message
    if not src or not src.photo or not src.caption:
        await msg.answer("Ответь на сообщение с фото и подписью.")
        return

    parts = src.caption.split("::")
    if len(parts) != 3:
        await msg.answer("Формат:\n::\nОписание\n::\nРедкость")
        return

    description = parts[1].strip()
    rarity_raw = parts[2].strip().lower()

    rarity_map = {v.lower(): k for k, v in RARITY_RU_MAP.items()}
    rarity_map.update({k.lower(): k for k in RARITY_RU_MAP})

    rarity = rarity_map.get(rarity_raw)
    if not rarity:
        await msg.answer("Неизвестная редкость.")
        return

    photo = src.photo[-1]
    database.add_card(
        description,
        rarity,
        photo.file_id,  # ← ВАЖНО
        RARITIES[rarity]["points"],
        RARITIES[rarity]["currency"]
    )

    await msg.answer("✅ Карта добавлена.")


# ---------- RUN ----------
async def main():
    print(f"Бот запущен. Карт в базе: {len(database.get_all_cards())}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
