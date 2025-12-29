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
from config import API_TOKEN, DROP_COOLDOWN, RARITIES, RARITY_RU_MAP, ADMIN_IDS

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


def rarity_keyboard(prefix: str, rarities=None):
    if rarities is None:
        rarities = list(RARITIES.keys())
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=RARITY_RU_MAP.get(r, r), callback_data=f"{prefix}:{r}")]
            for r in rarities
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
        nav.append(
            InlineKeyboardButton(
                text="«",
                callback_data=f"{prefix}_page:{page-1}"
            )
        )

    nav.append(
        InlineKeyboardButton(
            text=f"{page+1}/{pages}",
            callback_data="noop"
        )
    )

    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="»",
                callback_data=f"{prefix}_page:{page+1}"
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
async def addcard(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа.")
        return

    if not msg.reply_to_message or not msg.reply_to_message.photo:
        await msg.answer("❌ Ответь на сообщение с фото карты.")
        return

    caption = msg.reply_to_message.caption
    if not caption:
        await msg.answer("❌ У фото должна быть подпись.")
        return

    parts = caption.strip().split("\n\n")
    if len(parts) < 2:
        await msg.answer("❌ Нужна пустая строка и редкость.")
        return

    description = parts[0].strip()
    rarity_raw = parts[1].strip().lower()

    rarity_map = {
        "обычная": "Common",
        "редкая": "Rare",
        "эпическая": "Epic",
        "легендарная": "Legendary",
        "лимитированная": "Limited",
        "common": "Common",
        "rare": "Rare",
        "epic": "Epic",
        "legendary": "Legendary",
        "limited": "Limited",
    }

    rarity = rarity_map.get(rarity_raw)
    if not rarity:
        await msg.answer("❌ Неизвестная редкость.")
        return

    database.add_card(
        description=description,
        image=msg.reply_to_message.photo[-1].file_id,
        rarity=rarity,
        points=RARITIES[rarity]["points"],
        currency=RARITIES[rarity]["currency"]
    )

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
            f"+{card_obj['points']} очков | +{card_obj['currency']} пяточек\n\n"
            f"🆔 ID: {card_obj['id']}"
        )
    )

# ---------- CARDS ----------
@dp.message(Command("cards"))
async def cards(msg: types.Message):
    await msg.answer("Выбери редкость:", reply_markup=rarity_keyboard("cards"))

@dp.callback_query(F.data.startswith("cards:"))
async def cards_by_rarity(cb: types.CallbackQuery):
    rarity = cb.data.split(":")[1]
    cards_list = database.get_cards_by_rarity(rarity)
    if not cards_list:
        await cb.message.answer("Нет карт этой редкости.")
        return
    await cb.message.answer(
        f"Карты ({RARITY_RU_MAP.get(rarity, rarity)}):",
        reply_markup=cards_keyboard(cards_list, 0, "cards")
    )

@dp.callback_query(F.data.startswith("cards_card:"))
async def show_card(cb: types.CallbackQuery):
    card_id = int(cb.data.split(":")[1])
    card_obj = database.get_card_by_id(card_id)
    if not card_obj:
        await cb.message.answer("❌ Карта не найдена.")
        return
    await cb.message.answer_photo(
        photo=card_obj["image"],
        caption=(
            f"💳 {card_obj['description']}\n\n"
            f"👑 {RARITY_RU_MAP.get(card_obj['rarity'])}\n"
            f"+{card_obj['points']} | +{card_obj['currency']}\n\n"
            f"🆔 ID: {card_obj['id']}"
        )
    )

# ---------- COLLECTION ----------
@dp.message(Command("collection"))
async def collection(msg: types.Message):
    user_id = msg.from_user.id
    user_cards = database.get_collection(user_id)
    if not user_cards:
        await msg.answer("Коллекция пуста.")
        return

    rarities = sorted({c["rarity"] for c in user_cards})
    kb = rarity_keyboard("col", rarities)
    await msg.answer("Выбери редкость:", reply_markup=kb)

@dp.callback_query(F.data.startswith("col:"))
async def collection_by_rarity(cb: types.CallbackQuery):
    rarity = cb.data.split(":")[1]
    user_id = cb.from_user.id
    cards_list = [c for c in database.get_collection(user_id) if c["rarity"] == rarity]
    if not cards_list:
        await cb.message.answer("Нет карт этой редкости.")
        return
    await cb.message.answer(
        f"Твои карты ({RARITY_RU_MAP.get(rarity, rarity)}):",
        reply_markup=cards_keyboard(cards_list, 0, "col")
    )

# ---------- SETCARD ----------
@dp.message(Command("setcard"))
async def setcard(msg: types.Message):
    if not msg.reply_to_message or not msg.reply_to_message.caption:
        await msg.answer("❌ Ответь на сообщение с картой.")
        return

    card_id = None
    for line in msg.reply_to_message.caption.splitlines():
        if line.startswith("🆔"):
            try:
                card_id = int(line.split(":")[1])
            except Exception:
                pass
            break

    if not card_id:
        await msg.answer("❌ Не найден ID карты.")
        return

    if not database.user_has_card(msg.from_user.id, card_id):
        await msg.answer("❌ У тебя нет этой карты.")
        return

    database.set_showcase_card(msg.from_user.id, card_id)
    await msg.answer("✅ Карта установлена на показ.")

# ---------- DEL ----------
@dp.message(Command("del"))
async def delete_card(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа.")
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
    top_list = database.top_points()
    text = "🏆 Топ:\n\n" + "\n".join(f"{i+1}. {u['user_id']} — {u['points']}" for i, u in enumerate(top_list))
    await msg.answer(text)

# ---------- RUN ----------
async def main():
    database.init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
