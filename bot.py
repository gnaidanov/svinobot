import database
import random
import time
import asyncio
import os
from aiogram.types import FSInputFile
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram import F
from config import ADMIN_IDS, API_TOKEN, DROP_COOLDOWN, RARITIES

bot = Bot(API_TOKEN)
dp = Dispatcher()

# Русские названия редкостей → внутренние ключи
RARITY_RU_MAP = {
    "Обычная": "Common",
    "Редкая": "Rare",
    "Эпическая": "Epic",
    "Легендарная": "Legendary",
    "Лимитированная": "Limited"
}

# ---------- UTILS ----------

def roll_rarity():
    pool = []
    for r, data in RARITIES.items():
        pool.extend([r] * data["chance"])
    return random.choice(pool)

def get_safe_random_card():
    """
    Защита от пустых редкостей и законченных Limited
    """
    for _ in range(10):
        rarity = roll_rarity()
        card = database.get_random_card_by_rarity(rarity)
        if card:
            return card
    return None

# ---------- ADMIN ----------

@dp.message(Command("addcard"))
async def addcard(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа.")
        return

    if not msg.reply_to_message:
        await msg.answer("❌ Ответь командой /addcard на сообщение с картой.")
        return

    src = msg.reply_to_message

    if not src.photo or not src.caption:
        await msg.answer("❌ В сообщении должно быть фото с текстом.")
        return

    text = src.caption.strip().splitlines()

    description_lines = []
    rarity_ru = None
    points = None
    currency = None

    for line in text:
        line = line.strip()

        if line.startswith("💳"):
            description_lines.append(line.replace("💳", "").strip())
        elif description_lines and not line.startswith(("👑", "🕶", "🐽")):
            description_lines.append(line)

        elif line.startswith("👑"):
            rarity_ru = line.split(":")[-1].strip()

        elif line.startswith("🕶"):
            points = int("".join(filter(str.isdigit, line)))

        elif line.startswith("🐽"):
            currency = int("".join(filter(str.isdigit, line)))

    if not all([description_lines, rarity_ru, points is not None, currency is not None]):
        await msg.answer("❌ Не удалось разобрать текст карты.")
        return

    if rarity_ru not in RARITY_RU_MAP:
        await msg.answer("❌ Неизвестная редкость.")
        return

    rarity = RARITY_RU_MAP[rarity_ru]

    # ---------- Сохранение фото ----------
    photo = src.photo[-1]
    file = await bot.get_file(photo.file_id)

    filename = f"{int(time.time())}_{photo.file_id}.jpg"
    path = f"images/{filename}"

    await bot.download_file(file.file_path, path)

    description = "\n".join(description_lines)
    name = description.split("\n")[0][:50]  # имя = первая строка

    try:
        database.add_card(
            description=description,
            rarity=rarity,
            image=path,
            points=points,
            currency=currency
        )
    except Exception as e:
        await msg.answer(f"❌ Ошибка БД: {e}")
        return

    await msg.answer(f"✅ Карта «{name}» добавлена ({rarity_ru})")

# ---------- COMMANDS ----------

@dp.message(Command("cards"))
async def cards(msg: types.Message):
    cards = database.get_all_cards()
    if not cards:
        await msg.answer("❌ В базе нет карт.")
        return

    keyboard = []
    for card_id, name, rarity in cards:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{name} [{rarity}]",
                callback_data=f"card_{card_id}"
            )
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)

    await msg.answer("🗂 Все карты в боте:", reply_markup=kb)

@dp.callback_query(F.data.startswith("card_"))
async def card_info(cb: types.CallbackQuery):
    card_id = int(cb.data.split("_")[1])
    card = database.get_card_by_id(card_id)

    if not card:
        await cb.answer("Карта не найдена.", show_alert=True)
        return

    name, desc, rarity, image, pts, cur = card

    text = (
        f"💳 {desc}\n\n"
        f"👑 Редкость: {rarity}\n"
        f"🕶 Очки: {pts}\n"
        f"🐽 Пяточки: {cur}"
    )

    await cb.message.answer_photo(
        photo=FSInputFile(image),
        caption=text
    )
    await cb.answer()

@dp.message(Command("start"))
async def start(msg: types.Message):
    database.add_user(msg.from_user.id)
    await msg.answer(
        "🐾 Карточный бот\n"
        "/card — получить карту\n"
        "/collection — коллекция\n"
        "/profile — профиль\n"
        "/top — рейтинг"
    )

@dp.message(Command("card"))
async def card(msg: types.Message):
    user_id = msg.from_user.id
    now = int(time.time())

    database.add_user(user_id)
    user = database.get_user(user_id)

    if now - user[3] < DROP_COOLDOWN:
        remain = DROP_COOLDOWN - (now - user[3])
        hours = remain // 3600
        await msg.answer(f"⏳ Подожди {hours} ч.")
        return

    card = get_safe_random_card()

    if not card:
        await msg.answer("❌ В базе нет доступных карт.")
        return

    card_id, name, desc, rarity, image, pts, cur, claimed = card

    database.give_card(user_id, card_id)
    database.add_rewards(user_id, pts, cur)
    database.update_drop_time(user_id)

    if rarity == "Limited":
        database.claim_limited(card_id)

    caption = (
        f"💳 {desc}\n\n"
        f"👑 Редкость: {rarity}\n"
        f"🕶 +{pts} очков | +{cur} валюты"
    )

    photo = FSInputFile(image)
    await msg.answer_photo(photo=photo, caption=caption)

@dp.message(Command("collection"))
async def collection(msg: types.Message):
    cards = database.get_collection(msg.from_user.id)
    if not cards:
        await msg.answer("Коллекция пуста.")
        return

    text = "📚 Твоя коллекция:\n\n"
    for name, rarity, count in cards:
        text += f"{name} [{rarity}] ×{count}\n"

    await msg.answer(text)

@dp.message(Command("profile"))
async def profile(msg: types.Message):
    user = database.get_user(msg.from_user.id)
    cards = database.get_collection(msg.from_user.id)

    text = (
        f"👤 Профиль\n"
        f"🕶 Очки: {user[1]}\n"
        f"🐽 Пяточки: {user[2]}\n"
        f"💳 Карточек: {sum(c[2] for c in cards)}\n"
    )

    if user[4]:
        cursor = database.cursor
        cursor.execute("SELECT name, rarity FROM cards WHERE id=?", (user[4],))
        c = cursor.fetchone()
        if c:
            text += f"\n🖼 На показ:\n{c[0]} [{c[1]}]"

    await msg.answer(text)

@dp.message(Command("setcard"))
async def setcard(msg: types.Message):
    name = msg.text.replace("/setcard", "").strip()
    card = database.user_has_card(msg.from_user.id, name)
    if not card:
        await msg.answer("❌ У тебя нет этой карты.")
        return

    database.set_showcase(msg.from_user.id, card[0])
    await msg.answer(f"✅ Карта «{name}» установлена на показ.")

@dp.message(Command("top"))
async def top(msg: types.Message):
    top = database.top_points()
    text = "🏆 Топ по очкам:\n\n"
    for i, (uid, pts) in enumerate(top, 1):
        text += f"{i}. {uid} — {pts}\n"
    await msg.answer(text)

@dp.message(Command("del"))
async def delete_card(msg: types.Message):
    # Только админы
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа.")
        return

    # Команда должна быть ответом
    if not msg.reply_to_message:
        await msg.answer("❌ Ответь этой командой на карту бота.")
        return

    replied = msg.reply_to_message

    # Проверяем, что это сообщение бота с фото
    if not replied.photo or not replied.caption:
        await msg.answer("❌ Это не карта.")
        return

    # Извлекаем название карты (первая строка после 💳)
    first_line = replied.caption.splitlines()[0]
    if not first_line.startswith("💳"):
        await msg.answer("❌ Не удалось определить карту.")
        return

    card_name = first_line.replace("💳", "").strip()

    image = database.delete_card_by_name(card_name)
    if not image:
        await msg.answer("❌ Карта не найдена в базе.")
        return

    # Удаляем файл изображения (если существует)
    try:
        image_path = os.path.join(BASE_DIR, image)
        if os.path.exists(image_path):
            os.remove(image_path)
    except Exception as e:
        print(f"[WARN] Не удалось удалить файл: {e}")

    await msg.answer(f"🗑 Карта «{card_name}» удалена.")

# ---------- START ----------

async def main():
    # Лог базы данных
    database.cursor.execute("SELECT COUNT(*) FROM cards")
    count = database.cursor.fetchone()[0]
    print(f"Бот запущен, база данных готова, карт в базе: {count}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
