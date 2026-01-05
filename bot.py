import time
import random
import asyncio

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery

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

COOLDOWN_CHAT_ID = -1002336027168

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
        await msg.answer(f"❌ Карту пока нельзя получить\n{reason}")
        return

    card_obj = get_safe_random_card()
    if not card_obj:
        await msg.answer("❌ Нет карт.")
        return

    database.give_card(user_id, card_obj["id"])
    database.reset_card_cooldown(user_id)
    TOP_CACHE.clear()

    card_count = database.get_card_count(user_id, card_obj["id"])

    await msg.reply_photo(
        photo=card_obj["image"],
        caption=(
            f"💳 {card_obj['description']}\n\n"
            f"👑 {RARITY_RU_MAP.get(card_obj['rarity'])}\n"
            f"+{card_obj['points']} 🕶 | +{card_obj['currency']} 🐽\n\n"
            f"🃏 Кол-во копий: {card_count}\n"
            f"🆔 ID: {card_obj['id']}"
        )
    )

@dp.message(F.text, ~F.text.startswith("/"))
async def count_messages(message: Message):
    if message.chat.type == "private":
        return
    if message.chat.id != COOLDOWN_CHAT_ID:
        return
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

    card_count = database.get_card_count(owner_id, card_id)

    await cb.message.answer_photo(
        photo=card_obj["image"],
        caption=(
            f"💳 {card_obj['description']}\n\n"
            f"👑 {RARITY_RU_MAP.get(card_obj['rarity'])}\n"
            f"+{card_obj['points']} 🕶 | +{card_obj['currency']} 🐽\n\n"
            f"🃏 Кол-во копий: {card_count}\n"
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

    points = sum(c["count"] * c["points"] for c in cards)
    currency = sum(c["count"] * c["currency"] for c in cards)
    total_cards = sum(c["count"] for c in cards)

    chat = await bot.get_chat(user_id)
    full_name = chat.full_name  # имя игрока
    mention = f'<a href="tg://user?id={user_id}">{full_name}</a>'

    caption = (
        f"👤 Профиль {mention}\n"
        f"🕶 Очки: {points}\n"
        f"🐽 Пяточки: {currency}\n"
        f"💳 Карточек: {total_cards}"
    )

    showcase_card = database.get_showcase_card(user_id)

    if showcase_card:
        await msg.reply_photo(
            photo=showcase_card["image"],
            caption=caption,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    else:
        await msg.reply(
            text=caption,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

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

# ---------- TRADE ----------
@dp.message(Command("trade"))
async def trade_cmd(msg: Message):
    if not msg.reply_to_message:
        await msg.reply("❌ Команда должна быть ответом на сообщение игрока")
        return

    parts = msg.text.split()
    if len(parts) != 4 or parts[2].lower() != "for":
        await msg.reply("❌ Формат: /trade <твоя_карта_id> for <карта_игрока_id>")
        return

    try:
        from_card_id = int(args[1])
        to_card_id = int(args[3])
    except ValueError:
        return await message.reply("❌ ID карт должны быть числами")

    from_user = msg.from_user.id
    to_user = msg.reply_to_message.from_user.id

    if from_user == to_user:
        await msg.reply("❌ Нельзя обмениваться с самим собой")
        return

    # получаем карты
    from_card = database.get_user_card(from_user, from_card_id)
    to_card = database.get_user_card(to_user, to_card_id)

    if not from_card:
        await msg.reply("❌ У тебя нет такой карты")
        return

    if not to_card:
        await msg.reply("❌ У игрока нет такой карты")
        return

    if from_card["rarity"] != to_card["rarity"]:
        await msg.reply("❌ Можно обмениваться только картами одной редкости")
        return

    if from_card["rarity"] == "Limited" or to_card["rarity"] == "Limited":
        return await msg.reply("🚫 Лимитированные карты нельзя обменивать")

    trade_id = database.create_trade(
        from_user, to_user, from_card_id, to_card_id
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"trade_accept:{trade_id}"),
            InlineKeyboardButton(text="❌ Отказаться", callback_data=f"trade_decline:{trade_id}"),
            InlineKeyboardButton(text="↩️ Отменить", callback_data=f"trade_cancel:{trade_id}")
        ]
    ])

    await msg.reply_to_message.reply(
        f"🔄 **Запрос обмена карт**\n\n"
        f"Игрок предлагает обмен:\n"
        f"💳 {from_card_id} ↔ {to_card_id}\n"
        f"🎖 Редкость: {from_card['rarity']}",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data.startswith("trade_"))
async def trade_callback(cb: CallbackQuery):
    action, trade_id = cb.data.split(":")
    trade_id = int(trade_id)

    trade = database.get_trade(trade_id)
    if not trade or trade["status"] != "pending":
        await cb.answer("❌ Этот обмен недействителен", show_alert=True)
        return

    if cb.from_user.id != trade["to_user"]:
        await cb.answer("❌ Это не тебе адресовано", show_alert=True)
        return

    if action == "trade_decline":
        database.update_trade_status(trade_id, "declined")
        await cb.message.edit_text("❌ Обмен отклонён")
        await cb.answer()
        return

    # ACCEPT
    trade = database.get_trade(trade_id)

    if is_trade_expired(trade):
        database.update_trade_status(trade_id, "expired")
        return await cb.answer("⏳ Обмен просрочен", show_alert=True)

    database.swap_cards(
        trade["from_user"],
        trade["to_user"],
        trade["from_card"],
        trade["to_card"]
    )

    database.update_trade_status(trade_id, "accepted")

    await cb.message.edit_text("✅ Обмен успешно завершён")
    await cb.answer("Обмен выполнен")

@dp.callback_query(lambda c: c.data.startswith("trade_cancel:"))
async def trade_cancel_cb(cb: CallbackQuery):
    trade_id = int(cb.data.split(":")[1])
    user_id = cb.from_user.id

    trade = database.get_trade(trade_id)

    if not trade:
        return await cb.answer("Обмен не найден", show_alert=True)

    if trade["status"] != "pending":
        return await cb.answer("Обмен уже завершён", show_alert=True)

    if trade["from_user"] != user_id:
        return await cb.answer("Отменить может только инициатор", show_alert=True)

    database.update_trade_status(trade_id, "cancelled")

    await cb.message.edit_text("❌ Обмен отменён инициатором")
    await cb.answer("Обмен отменён")

# ---------- RUN ----------
async def main():
    database.init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
