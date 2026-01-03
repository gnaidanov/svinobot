import time
import random
import asyncio

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

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

TOP_CACHE = {}
TOP_CACHE_TTL = 30  # секунд

# ---------- FSM ----------
class AddCardState(StatesGroup):
    waiting_for_photo = State()

# ---------- UTILS ----------
def get_cached_top(key, builder):
    now = time.time()
    cached = TOP_CACHE.get(key)

    if cached and now - cached["time"] < TOP_CACHE_TTL:
        return cached["data"]

    data = builder()
    TOP_CACHE[key] = {
        "time": now,
        "data": data
    }
    return data


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


def rarity_keyboard(prefix: str, user_id: int, rarities=None):
    if rarities is None:
        rarities = list(RARITIES.keys())

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=RARITY_RU_MAP.get(r, r),
                    callback_data=f"{prefix}:{r}:{user_id}"
                )
            ]
            for r in rarities
        ]
    )


def cards_keyboard(cards, page: int, prefix: str, user_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    start = page * CARDS_PER_PAGE
    end = start + CARDS_PER_PAGE

    row = []
    for card in cards[start:end]:
        row.append(
            InlineKeyboardButton(
                text=str(card["id"]),
                callback_data=f"{prefix}_card:{card['id']}:{user_id}"
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
                callback_data=f"{prefix}_page:{page-1}:{user_id}"
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
                callback_data=f"{prefix}_page:{page+1}:{user_id}"
            )
        )

    kb.inline_keyboard.append(nav)
    return kb


def check_owner(cb: types.CallbackQuery, owner_id: int) -> bool:
    if cb.from_user.id != owner_id:
        asyncio.create_task(
            cb.answer("❌ Это не твоя кнопка", show_alert=True)
        )
        return False
    return True


def top_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕶 Очки", callback_data="top:points")],
        [InlineKeyboardButton(text="🐽 Пяточки", callback_data="top:currency")],
        [InlineKeyboardButton(text="💳 Карты", callback_data="top:cards")],
    ])

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

    if not msg.reply_to_message:
        await msg.answer("❌ Команда должна быть ответом на сообщение с фото карты.")
        return

    reply = msg.reply_to_message

    if not reply.photo:
        await msg.answer("❌ В сообщении должен быть фото.")
        return

    if not reply.caption:
        await msg.answer("❌ У фото должна быть подпись (описание карты).")
        return

    args = msg.text.split(maxsplit=1)
    if len(args) < 2:
        await msg.answer("❌ Укажи редкость: /addcard legendary")
        return

    rarity_raw = args[1].strip().lower()

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
        await msg.answer(f"❌ Неизвестная редкость: {rarity_raw}")
        return

    rarity_data = RARITIES.get(rarity)

    if not isinstance(rarity_data, dict):
        await msg.answer(
            f"❌ Ошибка конфигурации редкости\n"
            f"RARITIES['{rarity}'] = {rarity_data}"
        )
        return

    database.add_card(
        description=reply.caption.strip(),
        image=reply.photo[-1].file_id,
        rarity=rarity,
        points=rarity_data["points"],
        currency=rarity_data["currency"],
    )
    TOP_CACHE.clear()

    await msg.answer(
        "✅ Карта добавлена\n"
        f"Редкость: {rarity}\n"
        f"Очки: {rarity_data['points']}\n"
        f"Пяточки: {rarity_data['currency']}"
    )

# ---------- CARD DROP ----------
@dp.message(Command("card"))
async def card(msg: types.Message):
    user_id = msg.from_user.id

    can_take, reason = database.can_take_card(user_id)
    if not can_take:
        await msg.answer(
            f"❌ Карту пока нельзя получить\n{reason}"
        )
        return

    now = int(time.time())

    database.add_user(user_id)
    user = database.get_user(user_id)

    remaining = DROP_COOLDOWN - (now - user["last_drop"])

    if remaining > 0:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        seconds = remaining % 60

        await msg.answer(
            "⏳ Ты уже получал карту.\n"
            f"⏱ Осталось ждать: {hours:02d}:{minutes:02d}:{seconds:02d}\n"
        )
        return

    card_obj = get_safe_random_card()
    if not card_obj:
        await msg.answer("❌ Нет карт.")
        return

    database.give_card(user_id, card_obj["id"])
    TOP_CACHE.clear()
    database.add_rewards(user_id, card_obj["points"], card_obj["currency"])
    database.update_drop_time(user_id)
    database.reset_card_cooldown(user_id)

    await msg.answer_photo(
        photo=card_obj["image"],
        caption=(
            f"💳 {card_obj['description']}\n\n"
            f"👑 {RARITY_RU_MAP.get(card_obj['rarity'])}\n"
            f"+{card_obj['points']} 🕶 | +{card_obj['currency']} 🐽\n\n"
            f"🆔 ID: {card_obj['id']}"
        )
    )

@dp.message(F.text, ~F.text.startswith("/"))
async def count_messages(message: Message):
    user_id = message.from_user.id
    database.add_user(user_id)
    database.increment_message_counter(user_id)

# ---------- CARDS ----------
@dp.message(Command("cards"))
async def cards(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа.")
        return

    await msg.answer(
        "Выбери редкость:",
        reply_markup=rarity_keyboard("cards", msg.from_user.id)
    )

@dp.callback_query(F.data.startswith("cards:"))
async def cards_by_rarity(cb: types.CallbackQuery):
    _, rarity, owner_id = cb.data.split(":")
    owner_id = int(owner_id)

    if cb.from_user.id != owner_id:
        await cb.answer("❌ Это не твоя кнопка", show_alert=True)
        return

    cards_list = database.get_cards_by_rarity(rarity)
    if not cards_list:
        await cb.message.answer("Нет карт этой редкости.")
        return

    await cb.message.answer(
        f"Карты ({RARITY_RU_MAP.get(rarity, rarity)}):",
        reply_markup=cards_keyboard(cards_list, 0, "cards", owner_id)
    )

@dp.callback_query(F.data.contains("_card:"))
async def show_card(cb: types.CallbackQuery):
    _, rest = cb.data.split("_card:")
    card_id, owner_id = map(int, rest.split(":"))

    if cb.from_user.id != owner_id:
        await cb.answer("❌ Это не твоя кнопка", show_alert=True)
        return

    card_obj = database.get_card_by_id(card_id)
    if not card_obj:
        await cb.message.answer("❌ Карта не найдена.")
        return

    await cb.message.answer_photo(
        photo=card_obj["image"],
        caption=(
            f"💳 {card_obj['description']}\n\n"
            f"👑 {RARITY_RU_MAP.get(card_obj['rarity'])}\n"
            f"+{card_obj['points']} 🕶 | +{card_obj['currency']} 🐽\n\n"
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
    await msg.answer(
        "Выбери редкость:",
        reply_markup=rarity_keyboard("col", user_id, rarities)
    )

@dp.callback_query(F.data.startswith("col:"))
async def collection_by_rarity(cb: types.CallbackQuery):
    _, rarity, owner_id = cb.data.split(":")
    owner_id = int(owner_id)

    if cb.from_user.id != owner_id:
        await cb.answer("❌ Это не твоя кнопка", show_alert=True)
        return

    user_id = cb.from_user.id
    cards_list = [
        c for c in database.get_collection(user_id)
        if c["rarity"] == rarity
    ]

    if not cards_list:
        await cb.message.answer("Нет карт этой редкости.")
        return

    await cb.message.answer(
        f"Твои карты ({RARITY_RU_MAP.get(rarity, rarity)}):",
        reply_markup=cards_keyboard(cards_list, 0, "col", owner_id)
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
    if not user:
        await msg.answer("❌ Пользователь не найден.")
        return

    cards = database.get_collection(user_id)
    total_cards = sum(c["count"] for c in cards)

    caption = (
        "👤 Профиль\n"
        f"🕶 Очки: {user['points']}\n"
        f"🐽 Пяточки: {user['currency']}\n"
        f"💳 Карточек: {total_cards}"
    )

    showcase_card = database.get_showcase_card(user_id)

    if showcase_card:
        await msg.answer_photo(
            photo=showcase_card["image"],
            caption=caption
        )
    else:
        await msg.answer(caption)

# ---------- TOP ----------
@dp.message(Command("top"))
async def top(msg: types.Message):
    await msg.answer(
        "🏆 Выбери рейтинг:",
        reply_markup=top_keyboard()
    )

@dp.callback_query(F.data.startswith("top:"))
async def top_by_type(cb: types.CallbackQuery):
    mode = cb.data.split(":")[1]

    if mode == "points":
        rows = get_cached_top(
            "points",
            lambda: database.top_points(10)
        )
        title = "🕶 Топ по очкам"
        value_key = "points"

    elif mode == "currency":
        rows = get_cached_top(
            "currency",
            lambda: database.top_currency(10)
        )
        title = "🐽 Топ по пяточкам"
        value_key = "currency"

    elif mode == "cards":
        rows = get_cached_top(
            "cards",
            lambda: database.top_cards(10)
        )
        title = "💳 Топ по картам"
        value_key = "cards"

    else:
        await cb.answer("❌ Неизвестный рейтинг")
        return

    if not rows:
        await cb.message.answer(f"{title}\n\nПока нет данных.")
        return

    lines = []
    for i, row in enumerate(rows, start=1):
        user_id = row["user_id"]
        value = row[value_key]

        try:
            chat = await cb.bot.get_chat(user_id)
            name = chat.full_name
        except Exception:
            name = str(user_id)

        lines.append(f"{i}. {name} — {value}")

    await cb.message.answer(
        f"{title}\n\n" + "\n".join(lines)
    )

# ---------- RUN ----------
async def main():
    database.init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
