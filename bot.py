import os
import time
import random
import asyncio

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile

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
        nav.append(
            InlineKeyboardButton(
                text="«",
                callback_data=f"cards_page:{page - 1}"
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
                callback_data=f"cards_page:{page + 1}"
            )
        )
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

    caption = (
        f"💳 {card_obj['description']}\n\n"
        f"👑 Редкость: {RARITY_RU_MAP.get(card_obj['rarity'], card_obj['rarity'])}\n"
        f"🕶 +{card_obj['points']} очков | 🐽 +{card_obj['currency']} пяточек"
        f"\n🆔 ID карты: {card_obj['id']}\n"
    )

    await msg.answer_photo(
        photo=FSInputFile(card_obj["image"]),
        caption=caption
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
    user_id = msg.from_user.id
    rarities = database.get_user_rarities(user_id)

    if not rarities:
        await msg.answer("📚 Твоя коллекция пуста.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=RARITY_RU_MAP.get(r, r),
                    callback_data=f"user_rarity:{r}"
                )
            ]
            for r in rarities
        ]
    )

    await msg.answer("📚 Твоя коллекция\nВыбери редкость:", reply_markup=kb)

@dp.callback_query(F.data.startswith("user_rarity:"))
async def user_cards_by_rarity(cb: types.CallbackQuery):
    rarity = cb.data.split(":", 1)[1]
    user_id = cb.from_user.id

    cards = database.get_user_cards_by_rarity(user_id, rarity)

    if not cards:
        await cb.answer("Нет карт этой редкости", show_alert=True)
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"ID {card['id']}",
                    callback_data=f"card:{card['id']}"
                )
            ]
            for card in cards
        ]
    )

    await cb.message.answer(
        f"Карты редкости {RARITY_RU_MAP.get(rarity, rarity)}:",
        reply_markup=kb
    )
    await cb.answer()

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


# ---------- ADMIN: ADD CARD ----------
@dp.message(Command("addcard"))
async def addcard(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа.")
        return

    src = msg.reply_to_message
    if not src or not src.photo or not src.caption:
        await msg.answer(
            "❌ Ответь командой /addcard на сообщение с фото и подписью.\n\n"
            "Правильный формат:\n"
            "::\n"
            "Описание карты (может быть в несколько строк)\n"
            "::\n"
            "Редкость (RU или EN)"
        )
        return

    caption = src.caption.strip()
    parts = caption.split("::")
    if len(parts) != 3:
        await msg.answer(
            "❌ Неверный формат подписи.\nИспользуй:\n"
            "::\nОписание карты\n::\nРедкость"
        )
        return

    description = parts[1].strip()
    rarity_raw = parts[2].strip()

    if not description or not rarity_raw:
        await msg.answer("❌ Описание или редкость пустые.")
        return

    # Нормализация редкости
    rarity_map = {v.lower(): k for k, v in RARITY_RU_MAP.items()}
    rarity_map.update({k.lower(): k for k in RARITY_RU_MAP.keys()})

    rarity_key = rarity_map.get(rarity_raw.lower())
    if not rarity_key:
        await msg.answer(
            "❌ Неизвестная редкость.\nДоступные редкости:\n" +
            "\n".join(f"- {ru} / {en}" for en, ru in RARITY_RU_MAP.items())
        )
        return

    rarity = rarity_key
    rarity_data = RARITIES[rarity]
    points = rarity_data["points"]
    currency = rarity_data["currency"]

    photo = src.photo[-1]
    file = await bot.get_file(photo.file_id)
    os.makedirs("images", exist_ok=True)
    filename = f"{int(time.time())}_{photo.file_id}.jpg"
    path = os.path.join("images", filename)
    await bot.download_file(file.file_path, path)

    database.add_card(description, rarity, path, points, currency)
    await msg.answer(
        f"✅ Карта добавлена\n"
        f"👑 Редкость: {RARITY_RU_MAP.get(rarity, rarity)}\n"
        f"🕶 Очки: {points}\n"
        f"🐽 Пяточки: {currency}"
    )


# ---------- /CARDS ----------
@dp.message(Command("cards"))
async def cards(msg: types.Message):
    all_cards = database.get_all_cards()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ru, callback_data=f"rarity:{en}")]
            for en, ru in RARITY_RU_MAP.items()
        ]
    )
    await msg.answer("Выбери редкость:", reply_markup=kb)


@dp.callback_query(F.data.startswith("rarity:"))
async def show_cards_by_rarity(cb: types.CallbackQuery):
    rarity = cb.data.split(":", 1)[1]
    all_cards = database.get_all_cards()
    cards = [c for c in all_cards if c["rarity"] == rarity]
    if not cards:
        await cb.message.answer("❌ Карт этой редкости пока нет.")
        await cb.answer()
        return
    kb = cards_keyboard(cards, page=0)
    await cb.message.answer(
        f"Карты редкости {RARITY_RU_MAP.get(rarity, rarity)}:",
        reply_markup=kb
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("card_"))
async def card_info_cb(cb: types.CallbackQuery):
    card_id = int(cb.data.split("_", 1)[1])
    card = database.get_card_by_id(card_id)

    if not card:
        await cb.answer("Карта не найдена.", show_alert=True)
        return

    text = (
        f"💳 {card['description']}\n\n"
        f"👑 Редкость: {RARITY_RU_MAP.get(card['rarity'], card['rarity'])}\n"
        f"🕶 Очки: {card['points']}\n"
        f"🐽 Пяточки: {card['currency']}\n"
        f"🆔 ID карты: {card['id']}"
    )

    await cb.message.answer_photo(
        photo=FSInputFile(card["image"]),
        caption=text
    )
    await cb.answer()

# ---------- RUN ----------
async def main():
    print(f"Бот запущен. Карт в базе: {len(database.get_all_cards())}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
