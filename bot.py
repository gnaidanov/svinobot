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


def cards_keyboard(cards: list[dict], rarity: str, page: int):
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
        nav.append(
            InlineKeyboardButton(
                text="«",
                callback_data=f"cards_page:{rarity}:{page - 1}"
            )
        )

    nav.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{pages}",
            callback_data="noop"
        )
    )

    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="»",
                callback_data=f"cards_page:{rarity}:{page + 1}"
            )
        )

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
        "/top — рейтинг"
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
        await msg.answer(f"⏳ Подожди {remain // 60} мин.")
        return

    card_obj = get_safe_random_card()
    if not card_obj:
        await msg.answer("❌ В базе нет доступных карт.")
        return

    database.give_card(user_id, card_obj["id"])
    database.add_rewards(user_id, card_obj["points"], card_obj["currency"])
    database.update_drop_time(user_id)

    caption = (
        f"💳 {card_obj['description']}\n\n"
        f"👑 Редкость: {RARITY_RU_MAP.get(card_obj['rarity'])}\n"
        f"🕶 +{card_obj['points']} | 🐽 +{card_obj['currency']}"
    )

    await msg.answer_photo(
        photo=card_obj["file_id"],
        caption=caption
    )


# ---------- /CARDS ----------

@dp.message(Command("cards"))
async def cards(msg: types.Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=ru,
                    callback_data=f"rarity:{en}"
                )
            ]
            for en, ru in RARITY_RU_MAP.items()
        ]
    )
    await msg.answer("Выбери редкость:", reply_markup=kb)


@dp.callback_query(F.data.startswith("rarity:"))
async def show_cards_by_rarity(cb: types.CallbackQuery):
    rarity = cb.data.split(":", 1)[1]
    cards = database.get_cards_by_rarity(rarity)

    if not cards:
        await cb.answer("Карт этой редкости нет", show_alert=True)
        return

    kb = cards_keyboard(cards, rarity, page=0)

    await cb.message.answer(
        f"Карты редкости {RARITY_RU_MAP.get(rarity)}:",
        reply_markup=kb
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("cards_page:"))
async def change_page(cb: types.CallbackQuery):
    _, rarity, page = cb.data.split(":")
    page = int(page)

    cards = database.get_cards_by_rarity(rarity)
    kb = cards_keyboard(cards, rarity, page)

    await cb.message.edit_reply_markup(reply_markup=kb)
    await cb.answer()


@dp.callback_query(F.data.startswith("card:"))
async def card_info(cb: types.CallbackQuery):
    card_id = int(cb.data.split(":", 1)[1])
    card = database.get_card_by_id(card_id)

    if not card:
        await cb.answer("Карта не найдена", show_alert=True)
        return

    text = (
        f"💳 {card['description']}\n\n"
        f"👑 Редкость: {RARITY_RU_MAP.get(card['rarity'])}\n"
        f"🕶 Очки: {card['points']}\n"
        f"🐽 Пяточки: {card['currency']}"
    )

    await cb.message.answer_photo(
        photo=card["file_id"],
        caption=text
    )
    await cb.answer()


# ---------- ADMIN: ADD CARD ----------

@dp.message(Command("addcard"))
async def addcard(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return

    src = msg.reply_to_message
    if not src or not src.photo or not src.caption:
        await msg.answer("Ответь фото с описанием карты")
        return

    lines = src.caption.strip().splitlines()

    description = []
    rarity_ru = None
    points = currency = None

    for line in lines:
        if line.startswith("💳"):
            description.append(line[1:].strip())
        elif line.startswith("👑"):
            rarity_ru = line.split(":")[-1].strip()
        elif line.startswith("🕶"):
            points = int("".join(filter(str.isdigit, line)))
        elif line.startswith("🐽"):
            currency = int("".join(filter(str.isdigit, line)))

    rarity = {v: k for k, v in RARITY_RU_MAP.items()}.get(rarity_ru)
    if not all([description, rarity, points is not None, currency is not None]):
        await msg.answer("Ошибка парсинга карты")
        return

    photo = src.photo[-1]

    database.add_card(
        description="\n".join(description),
        rarity=rarity,
        file_id=photo.file_id,
        points=points,
        currency=currency
    )

    await msg.answer("✅ Карта добавлена")


# ---------- RUN ----------

async def main():
    print("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
