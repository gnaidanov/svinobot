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
    ADMIN_IDS
)

# ---------- INIT ----------
load_dotenv()

bot = Bot(API_TOKEN)
dp = Dispatcher()

CARDS_PER_PAGE = 25


# ---------- UTILS ----------
def roll_rarity():
    pool = []
    for rarity, data in RARITIES.items():
        pool.extend([rarity] * data["chance"])
    return random.choice(pool)


def format_card_caption(card):
    return (
        f"💳 {card['description']}\n\n"
        f"👑 {RARITY_RU_MAP.get(card['rarity'], card['rarity'])}\n"
        f"⭐ Очки: {card['points']}\n"
        f"🐽 Валюта: {card['currency']}\n\n"
        f"🆔 ID карты: {card['id']}"
    )


def rarity_keyboard(prefix: str):
    buttons = [
        InlineKeyboardButton(
            text=RARITY_RU_MAP.get(r, r),
            callback_data=f"{prefix}:rarity:{r}:1"
        )
        for r in RARITIES.keys()
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i+2] for i in range(0, len(buttons), 2)])


def cards_keyboard(cards, prefix, rarity, page):
    kb = []
    row = []

    for c in cards:
        row.append(
            InlineKeyboardButton(
                text=str(c["id"]),
                callback_data=f"{prefix}:card:{c['id']}"
            )
        )
        if len(row) == 5:
            kb.append(row)
            row = []

    if row:
        kb.append(row)

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"{prefix}:rarity:{rarity}:{page-1}"))
    nav.append(InlineKeyboardButton("➡️", callback_data=f"{prefix}:rarity:{rarity}:{page+1}"))
    kb.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=kb)


# ---------- START ----------
@dp.message(Command("start"))
async def start(msg: types.Message):
    database.add_user(msg.from_user.id)
    await msg.answer(
        "🐾 СвиноКарточки\n\n"
        "/card — получить карту\n"
        "/cards — карты в боте\n"
        "/collection — коллекция\n"
        "/profile — профиль\n"
        "/top — рейтинг\n\n"
        "Админ:\n"
        "/addcard — добавить карту\n"
        "/del — удалить карту"
    )


# ---------- CARD DROP ----------
@dp.message(Command("card"))
async def card(msg: types.Message):
    user_id = msg.from_user.id
    now = int(time.time())

    database.add_user(user_id)
    user = database.get_user(user_id)

    if now - user["last_drop"] < DROP_COOLDOWN:
        await msg.answer("⏳ Подожди перед следующим дропом.")
        return

    card = database.get_random_card_by_rarity(roll_rarity())
    if not card:
        await msg.answer("❌ Нет карт.")
        return

    database.give_card(user_id, card["id"])
    database.add_rewards(user_id, card["points"], card["currency"])
    database.update_drop_time(user_id)

    await msg.answer_photo(
        photo=card["image"],
        caption=format_card_caption(card)
    )


# ---------- PROFILE ----------
@dp.message(Command("profile"))
async def profile(msg: types.Message):
    target_id = msg.reply_to_message.from_user.id if msg.reply_to_message else msg.from_user.id

    user = database.get_user(target_id)
    cards = database.get_collection(target_id)

    await msg.answer(
        f"👤 Профиль\n"
        f"🕶 Очки: {user['points']}\n"
        f"🐽 Пяточки: {user['currency']}\n"
        f"💳 Карточек: {sum(c['count'] for c in cards)}"
    )


# ---------- /CARDS ----------
@dp.message(Command("cards"))
async def cards(msg: types.Message):
    await msg.answer("Выбери редкость:", reply_markup=rarity_keyboard("cards"))


@dp.callback_query(F.data.startswith("cards:rarity:"))
async def cards_by_rarity(call: types.CallbackQuery):
    _, _, rarity, page = call.data.split(":")
    page = int(page)

    cards = database.get_cards_by_rarity(rarity, page, CARDS_PER_PAGE)
    if not cards:
        await call.answer("Нет карт.")
        return

    await call.message.edit_text(
        f"📇 Карты ({RARITY_RU_MAP.get(rarity, rarity)})",
        reply_markup=cards_keyboard(cards, "cards", rarity, page)
    )


@dp.callback_query(F.data.startswith("cards:card:"))
async def cards_show(call: types.CallbackQuery):
    card_id = int(call.data.split(":")[2])
    card = database.get_card_by_id(card_id)

    if not card:
        await call.answer("Карта не найдена.")
        return

    await call.message.answer_photo(
        photo=card["image"],
        caption=format_card_caption(card)
    )


# ---------- /COLLECTION ----------
@dp.message(Command("collection"))
async def collection(msg: types.Message):
    await msg.answer("Выбери редкость:", reply_markup=rarity_keyboard("col"))


@dp.callback_query(F.data.startswith("col:rarity:"))
async def collection_by_rarity(call: types.CallbackQuery):
    _, _, rarity, page = call.data.split(":")
    page = int(page)
    user_id = call.from_user.id

    cards = database.get_user_cards_by_rarity(user_id, rarity, page, CARDS_PER_PAGE)
    if not cards:
        await call.answer("Нет карт.")
        return

    await call.message.edit_text(
        f"📚 Коллекция ({RARITY_RU_MAP.get(rarity, rarity)})",
        reply_markup=cards_keyboard(cards, "col", rarity, page)
    )


@dp.callback_query(F.data.startswith("col:card:"))
async def collection_show(call: types.CallbackQuery):
    card_id = int(call.data.split(":")[2])
    card = database.get_card_by_id(card_id)

    if not card:
        await call.answer("Карта не найдена.")
        return

    await call.message.answer_photo(
        photo=card["image"],
        caption=format_card_caption(card)
    )


# ---------- /SETCARD ----------
@dp.message(Command("setcard"))
async def setcard(msg: types.Message):
    if msg.reply_to_message and msg.reply_to_message.photo:
        if "ID карты:" not in msg.reply_to_message.caption:
            await msg.answer("❌ Ответь на карту.")
            return

        card_id = int(msg.reply_to_message.caption.split("ID карты:")[-1])
    else:
        await msg.answer("❌ Используй ответом на карту.")
        return

    if not database.user_has_card(msg.from_user.id, card_id):
        await msg.answer("❌ У тебя нет этой карты.")
        return

    database.set_showcase_card(msg.from_user.id, card_id)
    await msg.answer("✅ Карта установлена в профиль.")


# ---------- /DEL ----------
@dp.message(Command("del"))
async def delete_card(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа.")
        return

    if not msg.reply_to_message or not msg.reply_to_message.photo:
        await msg.answer("❌ Ответь на карту.")
        return

    card_id = int(msg.reply_to_message.caption.split("ID карты:")[-1])
    database.delete_card(card_id)
    await msg.answer("🗑 Карта удалена.")


# ---------- TOP ----------
@dp.message(Command("top"))
async def top(msg: types.Message):
    top_users = database.top_points(limit=10)

    if not top_users:
        await msg.answer("Рейтинг пуст.")
        return

    text = "🏆 Топ игроков:\n\n"
    for i, u in enumerate(top_users, start=1):
        text += f"{i}. ID {u['user_id']} — {u['points']} очков\n"

    await msg.answer(text)


# ---------- RUN ----------
async def main():
    database.init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
