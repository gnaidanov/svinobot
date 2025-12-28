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
        card = database.get_random_card_by_rarity(roll_rarity())
        if card:
            return card
    return None


def rarity_keyboard(prefix: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=RARITY_RU_MAP[r], callback_data=f"{prefix}:{r}")]
            for r in RARITIES.keys()
        ]
    )


def cards_keyboard(cards, page: int, prefix: str):
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    start = page * CARDS_PER_PAGE
    end = start + CARDS_PER_PAGE

    row = []
    for card in cards[start:end]:
        row.append(
            InlineKeyboardButton(
                text=str(card["id"]),
                callback_data=f"{prefix}_card:{card['id']}"
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
        nav.append(InlineKeyboardButton("«", callback_data=f"{prefix}_page:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("»", callback_data=f"{prefix}_page:{page+1}"))
    kb.inline_keyboard.append(nav)

    return kb


# ---------- START ----------
@dp.message(Command("start"))
async def start(msg: types.Message):
    database.add_user(msg.from_user.id)
    await msg.answer(
        "🐾 СвиноКарточки\n\n"
        "/card — получить карту\n"
        "/cards — все карты бота\n"
        "/collection — твоя коллекция\n"
        "/profile — профиль\n"
        "/top — рейтинг\n\n"
        "Админ:\n"
        "/addcard — добавить карту\n"
        "/del — удалить карту"
    )


# ---------- ADD CARD ----------
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
    lines = msg.caption.splitlines() if msg.caption else []
    if len(lines) < 4:
        await msg.answer("❌ Неверный формат.")
        return

    description = lines[0]
    data = dict(line.split("=", 1) for line in lines[1:])

    try:
        rarity = data["rarity"]
        points = int(data["points"])
        currency = int(data["currency"])
    except Exception:
        await msg.answer("❌ Ошибка данных.")
        return

    database.add_card(
        description=description,
        image=msg.photo[-1].file_id,
        rarity=rarity,
        points=points,
        currency=currency
    )

    await state.clear()
    await msg.answer("✅ Карта добавлена.")


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

    card = get_safe_random_card()
    if not card:
        await msg.answer("❌ Нет карт.")
        return

    database.give_card(user_id, card["id"])
    database.add_rewards(user_id, card["points"], card["currency"])
    database.update_drop_time(user_id)

    await msg.answer_photo(
        photo=card["image"],
        caption=(
            f"💳 {card['description']}\n\n"
            f"👑 {RARITY_RU_MAP.get(card['rarity'])}\n"
            f"+{card['points']} очков | +{card['currency']} пяточек\n\n"
            f"🆔 ID: {card['id']}"
        )
    )


# ---------- CARDS ----------
@dp.message(Command("cards"))
async def cards(msg: types.Message):
    await msg.answer("Выбери редкость:", reply_markup=rarity_keyboard("cards"))


@dp.callback_query(F.data.startswith("cards:"))
async def cards_by_rarity(cb: types.CallbackQuery):
    rarity = cb.data.split(":")[1]
    cards = database.get_cards_by_rarity(rarity)
    if not cards:
        await cb.message.answer("Нет карт этой редкости.")
        return
    await cb.message.answer(
        f"Карты ({RARITY_RU_MAP[rarity]}):",
        reply_markup=cards_keyboard(cards, 0, "cards")
    )


@dp.callback_query(F.data.startswith("cards_card:"))
async def show_card(cb: types.CallbackQuery):
    card_id = int(cb.data.split(":")[1])
    card = database.get_card_by_id(card_id)
    await cb.message.answer_photo(
        photo=card["image"],
        caption=(
            f"💳 {card['description']}\n\n"
            f"👑 {RARITY_RU_MAP.get(card['rarity'])}\n"
            f"+{card['points']} | +{card['currency']}\n\n"
            f"🆔 ID: {card['id']}"
        )
    )


# ---------- COLLECTION ----------
@dp.message(Command("collection"))
async def collection(msg: types.Message):
    await msg.answer("Выбери редкость:", reply_markup=rarity_keyboard("col"))


@dp.callback_query(F.data.startswith("col:"))
async def collection_by_rarity(cb: types.CallbackQuery):
    rarity = cb.data.split(":")[1]
    cards = database.get_user_cards_by_rarity(cb.from_user.id, rarity)
    if not cards:
        await cb.message.answer("Нет карт этой редкости.")
        return
    await cb.message.answer(
        "Твои карты:",
        reply_markup=cards_keyboard(cards, 0, "col")
    )


# ---------- SETCARD ----------
@dp.message(Command("setcard"))
async def setcard(msg: types.Message):
    if not msg.reply_to_message or not msg.reply_to_message.caption:
        await msg.answer("❌ Ответь на сообщение с картой.")
        return

    for line in msg.reply_to_message.caption.splitlines():
        if line.startswith("🆔"):
            card_id = int(line.split(":")[1])
            break
    else:
        await msg.answer("❌ Не найден ID карты.")
        return

    if not database.user_has_card(msg.from_user.id, card_id):
        await msg.answer("❌ У тебя нет этой карты.")
        return

    database.set_showcase(msg.from_user.id, card_id)
    await msg.answer("✅ Карта установлена на показ.")


# ---------- DEL ----------
@dp.message(Command("del"))
async def delete_card(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    try:
        card_id = int(msg.text.split()[1])
    except Exception:
        await msg.answer("Используй: /del ID")
        return
    database.delete_card(card_id)
    await msg.answer("🗑 Карта удалена.")


# ---------- PROFILE ----------
@dp.message(Command("profile"))
async def profile(msg: types.Message):
    user_id = msg.reply_to_message.from_user.id if msg.reply_to_message else msg.from_user.id
    user = database.get_user(user_id)
    cards = database.get_collection(user_id)

    await msg.answer(
        f"👤 Профиль\n"
        f"🕶 Очки: {user['points']}\n"
        f"🐽 Пяточки: {user['currency']}\n"
        f"💳 Карточек: {sum(c['count'] for c in cards)}"
    )


# ---------- TOP ----------
@dp.message(Command("top"))
async def top(msg: types.Message):
    top = database.top_points()
    await msg.answer(
        "🏆 Топ:\n\n" +
        "\n".join(f"{i+1}. {u['user_id']} — {u['points']}" for i, u in enumerate(top))
    )


# ---------- RUN ----------
async def main():
    database.init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
