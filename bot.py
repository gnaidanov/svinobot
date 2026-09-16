import time
import random
import asyncio
import os
import aiohttp
from aiohttp import web
import re

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery, ReplyParameters, LabeledPrice, PreCheckoutQuery

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from dotenv import load_dotenv

import database
from config import API_TOKEN, DROP_COOLDOWN, RARITIES, RARITY_RU_MAP, ADMIN_IDS

from items import HUNT_ITEMS
from aiogram.types import BufferedInputFile, TelegramObject

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus

from aiogram import BaseMiddleware

from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
import logging

# ---------- MIDDLEWARE ----------
class BannedChatsMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        chat_id = None
        message = None

        if isinstance(event, Message):
            chat_id = event.chat.id
            message = event
        elif isinstance(event, CallbackQuery):
            chat_id = event.message.chat.id
            message = event.message

        if not chat_id or chat_id > 0:
            return await handler(event, data)

        # Вызываем твою новую функцию из database.py
        if database.check_chat_banned(chat_id):
            bot = data['bot']
            try:
                m = await bot.get_chat_member(chat_id, bot.id)
                is_admin = m.status in ["administrator", "creator"]
                
                rights = {
                    "delete": is_admin and m.can_delete_messages,
                    "restrict": is_admin and m.can_restrict_members,
                    "pin": is_admin and m.can_pin_messages,
                    "promote": is_admin and m.can_promote_members
                }

                if all(rights.values()):
                    database.remove_chat_from_banned(chat_id) # Удаляем из БД
                    await message.answer("✅ <b>Все права получены!</b> Чат автоматически разблокирован.")
                    return await handler(event, data)

                # Твой красивый текст с динамическими иконками
                get_icon = lambda x: "✅" if x else "❌"
                response_text = (
                    "⚠️ <b>Внимание: Ограничение доступа</b>\n\n"
                    "Владелец бота добавил этот чат в список <b>ЧС</b> 🚫\n"
                    "Для активации бота требуется предоставить ему следующие права администратора:\n\n"
                    f"— Удаление сообщений {get_icon(rights['delete'])}\n"
                    f"— Блокировка пользователей {get_icon(rights['restrict'])}\n"
                    f"— Закрепление сообщений {get_icon(rights['pin'])}\n"
                    f"— Выбор администраторов {get_icon(rights['promote'])}\n\n"
                    "<i>Если у вас нет полномочий предоставить боту данные права, "
                    "попросите об этом <a href='tg://user?id=5295930709'>@Бр</a>, тегнув его под данным соо.</i>"
                )

                if (isinstance(event, Message) and event.text and event.text.startswith("/")) or isinstance(event, CallbackQuery):
                    await message.reply(response_text, parse_mode="HTML")
                    if isinstance(event, CallbackQuery): await event.answer()
                    return 

            except Exception as e:
                print(f"Ошибка: {e}")
                return

        return await handler(event, data)

# ---------- INIT ----------
load_dotenv()
bot = Bot(API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
dp.message.outer_middleware(BannedChatsMiddleware())
dp.callback_query.outer_middleware(BannedChatsMiddleware())
PORT = int(os.getenv("PORT", 8080))

CARDS_PER_PAGE = 25

TOP_CACHE = {}
TOP_CACHE_TTL = 30  # секунд

COOLDOWN_CHAT_IDS = [-1003675923986, -1003709715734, -1002933218446, -1003708004442]
VIDEO_ALLOWED_CHATS = [-1003708004442, -1002933218446]

MY_ID = 8101191178

ADMIN_RIGHTS_MAP = {
    "can_change_info": "Изменение профиля",      # Изменение описания
    "can_delete_messages": "Удаление сообщ.",   # Удаление сообщений
    "can_restrict_members": "Бан/Мут",          # Блокировка пользователей
    "can_invite_users": "Приглашения",          # Пригласительные ссылки
    "can_pin_messages": "Закреп",               # Закрепление сообщений
    "can_post_stories": "Истории",              # Управление историями 3/3
    "can_manage_video_chats": "Видеочаты",      # Управление видеочатами
    "can_promote_members": "Выбор админов",     # Выбор администраторов
    "can_manage_topics": "Управление темами",   # Только для групп-форумов
}

# ---------- FSM ----------
class AddCardState(StatesGroup):
    waiting_for_photo = State()
    waiting_for_re_content = State()
    last_msg_id = State()

# ---------- UTILS ----------
def is_chat_allowed(chat_id: int) -> bool:
    return chat_id in COOLDOWN_CHAT_IDS

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


def rarity_keyboard(prefix: str, user_id: int, counts_dict: dict = None):
    # Если словарь не передан, создаем пустой, чтобы код не упал
    if counts_dict is None:
        counts_dict = {}
        
    rarities = list(RARITIES.keys())

    buttons = []
    for r in rarities:
        # Получаем цифру из словаря, если её нет — ставим 0
        count = counts_dict.get(r, 0)
        ru_name = RARITY_RU_MAP.get(r, r)
        
        buttons.append([
            InlineKeyboardButton(
                text=f"{ru_name} ({count})", 
                callback_data=f"{prefix}:{r}:{user_id}"
            )
        ])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cards_keyboard(cards, page: int, prefix: str, user_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    start = page * CARDS_PER_PAGE
    end = start + CARDS_PER_PAGE

    row = []
    for card in cards[start:end]:
        # Если префикс 'col' (коллекция) и есть данные о количестве, пишем ID(копии)
        if prefix == "col" and "count" in card:
            btn_text = f"{card['id']}({card['count']})"
        else:
            btn_text = str(card["id"])

        row.append(
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"{prefix}_card:{card['id']}:{user_id}"
            )
        )
        if len(row) == 5:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)

    pages = (len(cards) - 1) // CARDS_PER_PAGE + 1
    # Навигация (остается без изменений)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"{prefix}_page:{page-1}:{user_id}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="»", callback_data=f"{prefix}_page:{page+1}:{user_id}"))
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
        [InlineKeyboardButton(text="🌲 Улов (Охота)", callback_data="top_hunt:day")] # Новая кнопка
    ])

def parse_tg_link(link: str):
    try:
        parts = link.split('/')
        if len(parts) < 3: return None, None
        
        msg_id = int(parts[-1])
        if 't.me/c/' in link:
            # Закрытый канал/чат
            chat_id = int("-100" + parts[-2])
        else:
            # Публичный канал
            chat_id = parts[-2]
            # Если это не число, добавим @, если его нет
            if not chat_id.replace('-', '').isdigit():
                if not chat_id.startswith('@'):
                    chat_id = "@" + chat_id
            else:
                chat_id = int(chat_id)
                
        return chat_id, msg_id
    except:
        return None, None

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

# ---------- ALIASES ----------
@dp.message(Command("alias"), F.chat.type == "private", F.from_user.id == MY_ID)
async def manage_alias(msg: Message):
    args = msg.text.split()
    if len(args) == 3 and args[1] == "del":
        database.delete_alias(args[2])
        await msg.answer(f"🗑 Алиас `{args[2]}` удален.")
        return
    if len(args) == 3:
        try:
            group_id = int(args[1])
            database.set_alias(args[2], group_id)
            await msg.answer(f"✅ Установлен алиас: `{args[2]}` → `{group_id}`")
        except ValueError:
            await msg.answer("❌ ID группы должен быть числом.")
        return
    await msg.answer("Использование:\n`/alias <id> <name>`\n`/alias del <name>`")

# ---------- SET DEFAULT GROUP ----------
@dp.message(Command("gid"), F.chat.type == "private", F.from_user.id == MY_ID)
async def set_default_group(msg: Message):
    args = msg.text.split()
    if len(args) < 2:
        current = database.get_setting("default_group")
        await msg.answer(f"Текущий ID: `{current}`")
        return

    target = args[1]
    alias_id = database.get_alias_id(target)
    
    if alias_id:
        database.set_setting("default_group_id", alias_id)
        await msg.answer(f"🎯 Переключено на алиас `{target}` (ID: {alias_id})")
    else:
        try:
            group_id = int(target)
            database.set_setting("default_group_id", group_id)
            await msg.answer(f"✅ ID установлен напрямую: `{group_id}`")
        except ValueError:
            await msg.answer(f"❌ `{target}` не найден в алиасах и не является числом.")

# ---------- DEL ----------
@dp.message(Command("del"), F.chat.type == "private", F.from_user.id == MY_ID)
async def cmd_delete_msg(msg: Message):
    args = msg.text.split()
    
    chat_id = None
    msg_id = None
    remove_reaction_only = False

    # 1. Определяем, что именно и где удаляем
    if len(args) > 1:
        # Проверяем, не флаг ли это реакции "/del r"
        if args[1].lower() == "r":
            remove_reaction_only = True
            chat_id = database.get_setting("default_group_id")
            saved_id = database.get_setting("last_sent_msg_id")
            msg_id = int(saved_id) if saved_id else None
        # Проверяем, не ссылка ли это
        elif "t.me" in args[1]:
            chat_id, msg_id = parse_tg_link(args[1])
        else:
            await msg.answer("📝 Использование:\n`/del` — удалить последнее моё соо\n`/del r` — убрать последнюю реакцию\n`/del <ссылка>` — по ссылке")
            return
    else:
        # Просто "/del" без параметров — берем последнее из базы
        chat_id = database.get_setting("default_group_id")
        saved_id = database.get_setting("last_sent_msg_id")
        msg_id = int(saved_id) if saved_id else None

    if not chat_id or not msg_id:
        await msg.answer("❌ Не найдено сообщение (база пуста или ссылка неверна).")
        return

    # Подготавливаем ID чата (число или username)
    target_chat = int(chat_id) if str(chat_id).replace('-', '').isdigit() else chat_id

    # 2. Выполняем действие
    if remove_reaction_only:
        # Только убираем реакцию
        try:
            await bot.set_message_reaction(chat_id=target_chat, message_id=msg_id, reaction=[])
            await msg.answer("🗑 Реакция убрана.")
        except Exception as e:
            await msg.answer(f"❌ Не удалось убрать реакцию: {e}")
    else:
        # Пытаемся удалить сообщение полностью
        try:
            await bot.delete_message(chat_id=target_chat, message_id=msg_id)
            await msg.answer("🗑 Сообщение удалено.")
        except Exception:
            # Если удалить нельзя (чужое или старое), пробуем убрать реакцию
            try:
                await bot.set_message_reaction(chat_id=target_chat, message_id=msg_id, reaction=[])
                await msg.answer("⚡️ Удалить соо нельзя (не моё или старое), убрал только реакции.")
            except Exception as e:
                await msg.answer(f"❌ Ошибка при попытке удаления/снятия реакции: {e}")

# ---------- BLOCK CHAT ----------
@dp.message(Command("brpatapim"))
async def block_this_chat(message: Message):
    ALLOWED_ADMIN_CHATS = [-1002933218446, -1003709715734]
    
    if message.chat.id not in ALLOWED_ADMIN_CHATS:
        return 

    if message.from_user.id in [MY_ID, 5295930709]:
        database.add_chat_to_banned(message.chat.id) 
        await message.answer("😹 Что то проимзошло.")

# ---------- CHECK USER ----------
@dp.message(Command("check_user"), F.from_user.id.in_([MY_ID, 5295930709]))
async def check_user_status(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply("❌ Введи ID пользователя. Пример: <code>/check_user 12345678</code>", parse_mode="HTML")
        return
    
    try:
        target_id = int(args[1])
    except ValueError:
        await message.reply("❌ ID должен быть числом.")
        return

    # Проверяем статус ЛС (отправляем невидимый статус "печатает")
    try:
        await bot.send_chat_action(chat_id=target_id, action="typing")
        pm_status = "🟢 <b>Открыто / Запущен</b> (Бот может писать в ЛС)"
    except TelegramForbiddenError:
        pm_status = "🔴 <b>Заблокировано / Не запущен</b> (Пользователь остановил бота или не писал в ЛС)"
    except TelegramBadRequest:
        pm_status = "❌ <b>Чат не найден</b> (Возможно, неверный ID или аккаунт удален)"
    except Exception as e:
        pm_status = f"⚠️ <b>Ошибка проверки:</b> {e}"

    # Красивый чистый отчет без баланса и счетчика сообщений
    await message.reply(
        f"👤 <b>Данные пользователя:</b>\n\n"
        f"🆔 ID: <code>{target_id}</code>\n\n"
        f"📬 <b>Статус ЛС бота:</b>\n{pm_status}", 
        parse_mode="HTML"
    )

# ---------- PM ----------
@dp.message(Command("pm"), F.from_user.id.in_([MY_ID, 5295930709]))
async def send_to_user_pm(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("❌ Формат: <code>/send ID_пользователя текст</code>", parse_mode="HTML")
        return
    
    try:
        target_user_id = int(args[1])
    except ValueError:
        await message.reply("❌ Неверный формат ID.")
        return
        
    text_to_send = args[2]
    
    try:
        # Отправляем сообщение в ЛС. 
        # Добавляем скрытую ссылку-информатор в конец текста, чтобы связать reply
        hidden_marker = f'<a href="tg://user?id={message.chat.id}">\u200b</a>'
        
        await bot.send_message(
            chat_id=target_user_id,
            text=f"{text_to_send}{hidden_marker}",
            parse_mode="HTML"
        )
        await message.reply("✅ Сообщение успешно доставлено пользователю в ЛС.")
    except Exception as e:
        await message.reply(f"❌ Не удалось отправить сообщение: {e}")

# Укажи здесь ID группы, куда бот должен присылать ответы пользователей
LOG_ADMIN_CHAT_ID = -1002933218446  # Замени на свой ID чата для ответов

@dp.message(F.chat.type == "private", F.reply_to_message)
async def handle_user_replies(message: Message):
    # Игнорируем админов, чтобы бот не пересылал ваши же команды /pm или /check_user
    if message.from_user.id in [MY_ID, 5295930709]:
        return

    # Проверяем, что пользователь сделал именно ОТВЕТ (reply) на сообщение бота
    if message.reply_to_message and message.reply_to_message.from_user.id == bot.id:
        user = message.from_user
        
        info_header = (
            f"📩 <b>Получен ответ в ЛС!</b>\n"
            f"👤 От: {user.mention_html()} | 🆔 ID: <code>{user.id}</code>\n"
            f"───────────────────"
        )
        
        try:
            # 1. Сначала шлем красивую плашку-уведомление
            await bot.send_message(chat_id=LOG_ADMIN_CHAT_ID, text=info_header, parse_mode="HTML")
            
            # 2. Безопасно копируем сообщение (работает даже при скрытом аккаунте!)
            await message.copy_to(chat_id=LOG_ADMIN_CHAT_ID)
            
        except Exception as e:
            # Если опять не отправит — ошибка намертво запишется в логи Fly.io, и мы её увидим
            logging.error(f"Ошибка при пересылке сообщения из ЛС в админ-чат: {e}")

# ---------- ADD CARD ----------
@dp.message(Command("addcard"), F.chat.type.in_({"group", "supergroup"}))
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
        "сверхредкая": "SuperRare",
        "эпическая": "Epic",
        "мифическая": "Mythic",
        "легендарная": "Legendary",
        "лимитированная": "Limited",
        "common": "Common",
        "rare": "Rare",
        "superrare": "SuperRare",
        "epic": "Epic",
        "mythic": "Mythic",
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

# ---------- ADD EVOLUTION ----------
@dp.message(Command("addevol"), F.chat.type.in_({"group", "supergroup"}))
async def addevol_smart(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    if not msg.reply_to_message:
        return await msg.reply("❌ Ответь этой командой на сообщение с новой картой!")

    args = msg.text.split()
    if len(args) < 2: return await msg.reply("❌ Укажи ID базовой карты: /addevol <id>")
    
    try:
        base_id = int(args[1])
        base_card = database.get_card_by_id(base_id) # Получаем инфо о базовой карте
        
        if not base_card:
            return await msg.reply("❌ Базовая карта с таким ID не найдена!")

        reply = msg.reply_to_message
        description = reply.caption or reply.text or "Эволюция"
        image_id = reply.photo[-1].file_id if reply.photo else None
        
        # Создаем карту, передавая редкость базовой (например, 'Common')
        new_card_id = database.create_evolution_card(
            description=description, 
            image_url=image_id, 
            base_rarity=base_card['rarity']
        )
        
        database.add_evolution_link(base_id, new_card_id)
        
        await msg.reply(f"✅ Создана эволюция 🆔 {new_card_id} для карты 🆔 {base_id}\nРедкость: Evo_{base_card['rarity']}")
    except Exception as e:
        await msg.reply(f"❌ Ошибка: {e}")

# ---------- ADMIN ----------
TARGET_GROUP_ID = -1003709715734
@dp.message(Command("admin"))
async def cmd_promote_request(message: Message):
    # 1. Только ты можешь юзать команду
    if message.from_user.id != MY_ID:
        return

    # 2. Только в ЛС или в этой конкретной группе
    if message.chat.type != "private" and message.chat.id != TARGET_GROUP_ID:
        return

    # 3. Определяем, кого мучаем
    if message.chat.type == "private":
        target_user = message.from_user  # В ЛС меняем права себе
    else:
        if not message.reply_to_message:
            await message.answer("Ответь на сообщение счастливчика в группе!")
            return
        target_user = message.reply_to_message.from_user

    builder = InlineKeyboardBuilder()
    
    # Кнопки прав (по умолчанию выключены ❌)
    for code, name in ADMIN_RIGHTS_MAP.items():
        builder.row(InlineKeyboardButton(
            text=f"❌ {name}", 
            callback_data=f"adm:{target_user.id}:{code}:0")
        )
    
    builder.row(InlineKeyboardButton(text="✅ ПРИМЕНИТЬ ✅", callback_data=f"adm_apply:{target_user.id}"))
    builder.row(InlineKeyboardButton(text="🚫 СНЯТЬ АДМИНА 🚫", callback_data=f"adm_demote:{target_user.id}"))

    await message.answer(
        f"🛠 <b>Настройка прав для {target_user.full_name}</b>\n"
        f"Целевая группа: <code>{TARGET_GROUP_ID}</code>\n"
        f"Выбери права:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("adm:"))
async def toggle_admin_right(callback: CallbackQuery):
    if callback.from_user.id != MY_ID:
        return await callback.answer("Это только для владельца!", show_alert=True)

    data = callback.data.split(":")
    target_id, right_code, current_state = data[1], data[2], data[3]
    new_state = "1" if current_state == "0" else "0"
    
    builder = InlineKeyboardBuilder()
    
    # Проходим по всем кнопкам старой клавиатуры
    for row in callback.message.reply_markup.inline_keyboard:
        btn = row[0]
        
        # Если это та самая кнопка, которую нажали — меняем её
        if btn.callback_data == callback.data:
            new_emoji = "✅" if new_state == "1" else "❌"
            builder.row(InlineKeyboardButton(
                text=f"{new_emoji} {ADMIN_RIGHTS_MAP[right_code]}",
                callback_data=f"adm:{target_id}:{right_code}:{new_state}")
            )
        else:
            # ДЛЯ ВСЕХ ОСТАЛЬНЫХ КНОПОК:
            # Создаем НОВЫЙ объект кнопки, а не копируем старый!
            # Это лечит ошибку "cannot pickle"
            builder.row(InlineKeyboardButton(
                text=btn.text,
                callback_data=btn.callback_data
            ))

    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_apply:"))
async def apply_admin_rights(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != MY_ID: return

    target_id = int(callback.data.split(":")[1])
    
    # Собираем все права из кнопок в один словарь
    rights_dict = {}
    for row in callback.message.reply_markup.inline_keyboard:
        btn = row[0]
        if btn.callback_data and btn.callback_data.startswith("adm:"):
            _, _, key, val = btn.callback_data.split(":")
            rights_dict[key] = (val == "1")

    try:
        # Распаковываем словарь (**) прямо в аргументы функции
        # Это лечит ошибку с ChatPrivileges
        await bot.promote_chat_member(
            chat_id=TARGET_GROUP_ID,
            user_id=target_id,
            **rights_dict
        )
        await callback.message.edit_text(f"✨ <b>Готово!</b> Права пользователя <code>{target_id}</code> обновлены.", parse_mode="HTML")
    except Exception as e:
        await callback.message.answer(f"⚠️ Ошибка при выдаче: {e}")
    
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_demote:"))
async def demote_admin(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != MY_ID: return

    target_id = int(callback.data.split(":")[1])
    
    # Создаем словарь, где все возможные права = False
    demote_all = {key: False for key in ADMIN_RIGHTS_MAP.keys()}

    try:
        await bot.promote_chat_member(
            chat_id=TARGET_GROUP_ID,
            user_id=target_id,
            **demote_all
        )
        await callback.message.edit_text(f"🚫 Пользователь <code>{target_id}</code> полностью разжалован.", parse_mode="HTML")
    except Exception as e:
        await callback.message.answer(f"⚠️ Ошибка при снятии: {e}")
    
    await callback.answer()

@dp.message(F.text.lower().in_(["охота", "hunt", "копать", "хрю"]))
async def cmd_hunt(message: Message):
    user_id = message.from_user.id
    database.add_user(user_id) 

    # 1. Проверка кулдауна
    can_hunt, time_left = database.can_take_hunt(user_id)
    if not can_hunt:
        await message.answer(f"🐽 Твоя свинья устала и спит. Приходи через **{time_left}**", parse_mode="Markdown")
        return

    # 2. Эффект ожидания
    waiting = await message.answer("🐽 *Свинья начала копать землю...*", parse_mode="Markdown")
    await asyncio.sleep(2) 

    # 3. Генерация предмета
    import random
    rand = random.random()
    
    if rand < 0.02: 
        category = "legendary"
    elif rand < 0.12: 
        category = "rare"
    elif rand < 0.30: 
        category = "junk"
    else: 
        category = "common"
    
    item = random.choice(HUNT_ITEMS[category])
    weight = round(random.uniform(item["weight"][0], item["weight"][1]), 3)
    total_price = round(weight * item["price"], 2)
    
    if total_price == 0 and item["price"] > 0:
        total_price = 1

    # 4. Сохранение (теперь всё внутри одной функции)
    # Передаем иконку сразу, чтобы database.py сам всё записал в инвентарь
    database.log_hunt(user_id, weight, item["name"], category, total_price, item.get("icon", "📦"))
    database.update_hunt_cooldown(user_id)
    
    # 5. Ответ пользователю
    await waiting.delete()
    sticker_msg = await message.reply_sticker(item["sticker"])
    await sticker_msg.reply(
        f"🌳 **Результат охоты:**\n\n"
        f"Найдено: *{item['name']}*\n"
        f"Вес: `{weight} кг`\n"
        f"Добыча оценена в: `{total_price} пятачков` {item['price']}/кг",
        parse_mode="Markdown"
    )

@dp.message(Command("scan"))
async def cmd_scan(message: Message):
    if message.from_user.id != MY_ID: return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Введи ссылку на пак")
        return

    pack_name = args[1].replace("https://t.me/addstickers/", "").replace("t.me/addstickers/", "")
    status_msg = await message.answer(f"⏳ Начинаю глубокое сканирование пака `{pack_name}`...\nЭто займет время, так как я пересоздаю каждый стикер.")

    try:
        sticker_set = await bot.get_sticker_set(name=pack_name)
        result_text = "```python\n# Группируй их по редкости в items.py\n"
        
        for i, sticker in enumerate(sticker_set.stickers, 1):
            # 1. Скачиваем стикер в память (BytesIO)
            file_info = await bot.get_file(sticker.file_id)
            sticker_bytes = await bot.download_file(file_info.file_path)
            
            # 2. Отправляем его как "новый" файл обратно самому себе
            # Мы используем BufferedInputFile, чтобы не сохранять на диск
            input_file = BufferedInputFile(sticker_bytes.getvalue(), filename=f"item_{i}.webp")
            sent_sticker = await bot.send_sticker(chat_id=MY_ID, sticker=input_file)
            
            # 3. Получаем "чистый" ID
            clean_id = sent_sticker.sticker.file_id
            
            line = f'{{"name": "Гриб #{i}", "sticker": "{clean_id}", "price": 15, "weight": (0.1, 0.5)}},\n'
            result_text += line
            
            # Небольшая пауза, чтобы Telegram не забанил за спам файлами
            await asyncio.sleep(0.5)

        result_text += "```"
        await message.answer(result_text, parse_mode="Markdown")
        await status_msg.delete()

    except Exception as e:
        await message.answer(f"❌ Ошибка сканирования: {e}")

#

@dp.message(Command("info"))
async def cmd_info(message: Message, bot: Bot):
    member = await bot.get_chat_member(chat_id=message.chat.id, user_id=bot.id)
    
    if member.status not in ["administrator", "creator"]:
        await message.answer("ℹ️ **Статус бота:** Я обычный участник.")
        return

    # Расширенный список прав согласно Telegram Bot API
    rights = [
        ("Изменение профиля/настроек", getattr(member, 'can_change_info', False)),
        ("Удаление сообщений", getattr(member, 'can_delete_messages', False)),
        ("Бан/Ограничение прав", getattr(member, 'can_restrict_members', False)),
        ("Пригласительные ссылки", getattr(member, 'can_invite_users', False)),
        ("Закреп сообщений", getattr(member, 'can_pin_messages', False)),
        ("Управление историями", getattr(member, 'can_post_stories', False)), # Новое
        ("Управление видеочатами", getattr(member, 'can_manage_video_chats', False)),
        ("Назначение новых админов", getattr(member, 'can_promote_members', False)), # Это "Выбор администраторов"
        ("Управление темами", getattr(member, 'can_manage_topics', False)),
        ("Анонимность", getattr(member, 'is_anonymous', False)),
    ]

    text = "🛡 **Все админ-права бота в этом чате:**\n\n"
    for name, has_right in rights:
        status_emoji = "✅" if has_right else "❌"
        text += f"{status_emoji} {name}\n"

    await message.answer(text, parse_mode="Markdown")

# ---------- CARD DROP ----------
@dp.message(Command("card"), F.chat.type.in_({"group", "supergroup"}))
async def card(msg: types.Message):
    if not is_chat_allowed(msg.chat.id):
        return # Бот просто промолчит в чужом чате
        
    user_id = msg.from_user.id
    database.add_user(user_id)
    
    can_take, reason = database.can_take_card(user_id)
    if not can_take:
        await msg.answer(f"❌ Карту пока нельзя получить\n{reason}")
        return

    card_obj = get_safe_random_card()
    if not card_obj:
        await msg.answer("❌ Нет карт.")
        return

    # Выдаем карту и сбрасываем КД
    database.give_card(user_id, card_obj["id"])
    database.reset_card_cooldown(user_id)
    TOP_CACHE.clear()

    # Получаем актуальное кол-во копий
    card_count = database.get_card_count(user_id, card_obj["id"])
    
    # --- ЛОГИКА КНОПКИ ЭВОЛЮЦИИ ---
    reply_markup = None
    # Проверяем, есть ли эволюция для этой карты в базе
    evo_result_id = database.get_evolution_result(card_obj["id"])
    
    # Если есть эволюция и у игрока 3 или более копий
    if evo_result_id and card_count >= 3:
        keyboard = [
            [
                InlineKeyboardButton(
                    text="🧬 Эволюционировать (2 шт)", 
                    callback_data=f"evolve:{card_obj['id']}:{user_id}"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    # ------------------------------

    await msg.reply_photo(
        photo=card_obj["image"],
        caption=(
            f"💳 {card_obj['description']}\n\n"
            f"👑 {RARITY_RU_MAP.get(card_obj['rarity'])}\n"
            f"+{card_obj['points']} 🕶 | +{card_obj['currency']} 🐽\n\n"
            f"🃏 Кол-во копий: {card_count}\n"
            f"🆔 ID: {card_obj['id']}"
        ),
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

# ---------- CARDS ----------
@dp.message(Command("cards"), F.chat.type.in_({"group", "supergroup"}))
async def cards(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS: return
    
    total = database.get_total_cards_count()
    counts = database.get_count_by_rarities()
    
    await msg.answer(
        f"🗂 **Все карты бота** (Всего: {total})\nВыбери редкость:",
        reply_markup=rarity_keyboard("cards", msg.from_user.id, counts),
        parse_mode="Markdown"
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
    
    # --- ЛОГИКА ЭВОЛЮЦИИ ---
    evo_result_id = database.get_evolution_result(card_id)
    
    keyboard_list = []
    
    # Кнопка появится только если есть куда расти и есть 3+ копии
    if evo_result_id and card_count >= 3:
        keyboard_list.append([
            InlineKeyboardButton(
                text="🧬 Эволюционировать (2 шт)", 
                callback_data=f"evolve:{card_id}:{owner_id}"
            )
        ])
    
    # Кнопка возврата (подставь свою редкость или просто 'назад')
    keyboard_list.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"col:{card_obj['rarity']}:{owner_id}")
    ])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard_list)
    # -----------------------

    await cb.message.answer_photo(
        photo=card_obj["image"],
        caption=(
            f"💳 {card_obj['description']}\n\n"
            f"👑 {RARITY_RU_MAP.get(card_obj['rarity'])}\n"
            f"+{card_obj['points']} 🕶 | +{card_obj['currency']} 🐽\n\n"
            f"🃏 Кол-во копий: {card_count}\n"
            f"🆔 ID: {card_obj['id']}"
        ),
        reply_markup=reply_markup, # Добавляем кнопки
        parse_mode="HTML" # Чтобы теги <b> или <i> работали
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("evolve:"))
async def do_evolution(cb: types.CallbackQuery):
    _, card_id, owner_id = cb.data.split(":")
    card_id, owner_id = int(card_id), int(owner_id)

    if cb.from_user.id != owner_id:
        await cb.answer("❌ Это не твоя магия!", show_alert=True)
        return

    result_id = database.get_evolution_result(card_id)
    if not result_id:
        await cb.answer("❌ У этой карты нет эволюционной формы!", show_alert=True)
        return

    # Запускаем процесс с шансом 25%
    status = database.process_evolution(owner_id, card_id, result_id)
    
    if status == 'success':
        new_card = database.get_card_by_id(result_id)
        await cb.message.delete()
        await cb.message.answer_photo(
            photo=new_card["image"],
            caption=(
                f"🧬 <b>Эволюция успешна! (Шанс 25% сработал)</b>\n\n"
                f"✨ Получена новая форма: <b>{new_card['description']}</b>\n"
                f"👑 Редкость: {RARITY_RU_MAP.get(new_card['rarity'])}\n"
                f"🆔 ID: {new_card['id']}"
            ),
            parse_mode="HTML"
        )
    elif status == 'fail':
        await cb.message.delete()
        await cb.message.answer(
            f"🧬 <b>Эволюция провалилась!</b>\n\n"
            f"К сожалению, синтез не удался. Две копии карты ID {card_id} были безвозвратно утеряны. "
            f"Шанс на успех был 25%. Попробуйте еще раз!"
        )
    else:
        await cb.answer("❌ Ошибка: нужно минимум 3 копии, чтобы 1 осталась!", show_alert=True)

# ---------- COLLECTION ----------
@dp.message(Command("collection"), F.chat.type.in_({"group", "supergroup"}))
async def collection(msg: types.Message):
    user_id = msg.from_user.id
    user_cards = database.get_collection(user_id)
    
    if not user_cards:
        await msg.answer("Коллекция пуста.")
        return

    total_unique = len(user_cards)
    total_all = sum(c['count'] for c in user_cards)
    counts = database.get_user_count_by_rarities(user_id)

    await msg.answer(
        f"🎒 **Твоя коллекция**\nУникальных: {total_unique} | Всего: {total_all}\nВыбери редкость:",
        reply_markup=rarity_keyboard("col", user_id, counts),
        parse_mode="Markdown"
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
@dp.message(Command("setcard"), F.chat.type.in_({"group", "supergroup"}))
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
@dp.message(Command("del"), F.chat.type.in_({"group", "supergroup"}))
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
@dp.message(Command("profile"), F.chat.type.in_({"group", "supergroup"}))
async def profile(msg: types.Message):
    user_id = msg.reply_to_message.from_user.id if msg.reply_to_message else msg.from_user.id

    user = database.get_user(user_id)
    if not user:
        await msg.answer("❌ Пользователь не найден.")
        return

    cards = database.get_collection(user_id)

    points = sum(c["count"] * c["points"] for c in cards)
    currency = user["currency_balance"]
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
@dp.message(Command("top"), F.chat.type.in_({"group", "supergroup"}))
async def top(msg: types.Message):
    # Первое сообщение с выбором
    await msg.answer(
        "🏆 **Рейтинг игроков**\n\nВыбери категорию ниже, чтобы посмотреть топ-10:",
        reply_markup=top_keyboard(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("top:"))
async def top_by_type(cb: types.CallbackQuery):
    mode = cb.data.split(":")[1]
    
    # Словарь для заголовков
    titles = {
        "points": ("🕶 Топ по очкам", "points"),
        "currency": ("🐽 Топ по пяточкам", "currency"),
        "cards": ("💳 Топ по количеству карт", "cards"),
        "hunt": ("🌲 Топ по количеству улова", "hunt")
    }
    
    title_text, value_key = titles.get(mode)

    # Получаем данные через кеш
    rows = get_cached_top(
        mode,
        lambda: getattr(database, f"top_{mode}")(10)
    )

    if not rows:
        content = f"{title_text}\n\nПока нет данных."
    else:
        lines = []
        for i, row in enumerate(rows, start=1):
            user_id = row["user_id"]
            value = row[value_key]
            try:
                # Получаем имя пользователя (может быть медленно, если много новых юзеров)
                chat = await cb.bot.get_chat(user_id)
                name = chat.full_name
            except Exception:
                name = f"ID: {user_id}"
            lines.append(f"**{i}.** {name} — `{value}`")
        
        content = f"{title_text}\n\n" + "\n".join(lines)

    # Редактируем текущее сообщение вместо отправки нового
    try:
        await cb.message.edit_text(
            content,
            reply_markup=top_keyboard(),
            parse_mode="Markdown"
        )
    except Exception as e:
        # Если текст топа не изменился (кеш тот же), телеграм выдаст ошибку, просто игнорим её
        await cb.answer()

@dp.callback_query(F.data.startswith("top_hunt:"))
async def top_hunt_handler(cb: CallbackQuery):
    # Извлекаем текущий открытый период: day, week или all
    current_period = cb.data.split(":")[1]
    
    # Заголовки секций
    periods = {
        "day": "☀️ За сутки",
        "week": "📅 За неделю",
        "all": "🌎 За все время"
    }

    full_text = "🏆 **Рейтинг охотников**\n\n"

    for period_key, period_name in periods.items():
        if current_period == period_key:
            # Если период выбран, «разворачиваем» его (запрашиваем данные из БД)
            # Примечание: тебе нужно будет добавить метод get_hunt_top в database.py
            rows = database.get_hunt_top(period_key, limit=10) 
            
            full_text += f"**{period_name}** 🔽\n"
            if not rows:
                full_text += "_Данных пока нет_\n"
            else:
                for i, row in enumerate(rows, start=1):
                    # --- ВСТАВЛЯЕМ СЮДА ---
                    user_id = row['user_id']
                    try:
                        # Пытаемся получить актуальное имя пользователя через Telegram API
                        # Обратите внимание: метод get_chat — асинхронный (await)
                        user_chat = await cb.bot.get_chat(user_id)
                        name = user_chat.full_name
                    except Exception:
                        # Если не удалось найти (пользователь удалил аккаунт или забанил бота)
                        name = f"ID: {user_id}"

                    full_text += f"{i}. {name}: {row['total_weight']:.2f} кг ({row['total_count']} шт)\n"

        else:
            # Если период не выбран, он остается «свернутым» (просто заголовок)
            full_text += f"**{period_name}**\n"
        
        full_text += "\n"

    # Кнопки для переключения периодов
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сутки", callback_data="top_hunt:day"),
            InlineKeyboardButton(text="Неделя", callback_data="top_hunt:week"),
            InlineKeyboardButton(text="Все", callback_data="top_hunt:all")
        ],
        [InlineKeyboardButton(text="⬅️ Назад к общему топу", callback_data="top_back")]
    ])

    await cb.message.edit_text(full_text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "top_back")
async def top_back_handler(cb: CallbackQuery):
    await cb.message.edit_text(
        "🏆 **Рейтинг игроков**\n\nВыбери категорию ниже, чтобы посмотреть топ-10:",
        reply_markup=top_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(Command("clearhuntstats"))
async def cmd_clear_stats(message: Message):
    user_id = message.from_user.id
    
    # Можно добавить проверку на подтверждение, но пока просто удаляем
    database.clear_user_hunt_stats(user_id)
    
    await message.answer("🧹 **Твоя история охоты и инвентарь полностью очищены!**", parse_mode="Markdown")

@dp.message(Command("inventory"))
async def show_inventory(message: types.Message):
    user_id = message.from_user.id
    
    try:
        with database.get_conn() as conn:
            with conn.cursor() as cur:
                # Мы используем AS (алиасы), чтобы точно знать имена ключей
                cur.execute("""
                    SELECT 
                        item_icon, 
                        item_name, 
                        SUM(quantity) AS total_count, 
                        SUM(weight) AS total_weight, 
                        is_rare 
                    FROM inventories 
                    WHERE user_id = %s 
                    GROUP BY item_name, item_icon, is_rare
                """, (user_id,))
                
                rows = cur.fetchall()

        if not rows:
            await message.answer("🌲 Твой рюкзак пока пуст. Пора на охоту!")
            return

        rare_text = ""
        common_text = ""
        total_items_count = 0
        total_items_weight = 0.0

        for row in rows:
            # Обращаемся по ИМЕНАМ (ключам), так как у вас DictCursor
            icon = row.get('item_icon') or '📦'
            name = row.get('item_name') or 'Неизвестно'
            
            # Обрабатываем суммы (PostgreSQL может вернуть None, если записей нет)
            count = int(row.get('total_count') or 0)
            weight = float(row.get('total_weight') or 0.0)
            is_rare = row.get('is_rare', False)

            # Считаем общие итоги
            total_items_count += count
            total_items_weight += weight

            # Формируем строку
            item_line = f"{icon} {name} — <b>{count} шт.</b> (<i>{weight:.3f} кг</i>)\n"

            if is_rare:
                rare_text += item_line
            else:
                common_text += item_line

        # Сборка сообщения
        text = f"🎒 <b>Инвентарь</b>\n"
        text += f"<b>ИТОГО</b> — {total_items_count} шт · <i>{total_items_weight:.2f} кг</i>\n\n\n"

        if rare_text:
            text += "💎 <b>Легендарные находки</b>\n"
            text += f"<blockquote expandable>{rare_text}</blockquote>\n\n"

        if common_text:
            text += "🌲 <b>Собрано в лесу</b>\n"
            text += f"<blockquote expandable>{common_text}</blockquote>"

        await message.reply(text, parse_mode="HTML")

    except Exception as e:
        import traceback
        traceback.print_exc() # Это выведет подробности ошибки в консоль Fly.io
        await message.answer(f"❌ Ошибка при чтении инвентаря: {e}")

# ---------- TRADE ----------
TRADE_TIMEOUT = 300  # секунд
active_trades = {}   # runtime_id -> dict


async def trade_timeout(runtime_id: str):
    await asyncio.sleep(TRADE_TIMEOUT)

    trade = active_trades.get(runtime_id)
    if not trade:
        return

    # блокируем кнопки
    try:
        await bot.edit_message_reply_markup(
            chat_id=trade["chat_id"],
            message_id=trade["message_id"],
            reply_markup=None
        )
    except Exception:
        pass

    database.update_trade_status(trade["db_id"], "expired")

    await bot.send_message(
        trade["from_user"],
        "⏱ Обмен был автоматически отменён (время истекло)."
    )

    active_trades.pop(runtime_id, None)


@dp.message(Command("trade"), F.chat.type.in_({"group", "supergroup"}))
async def trade_cmd(msg: Message):
    if not msg.reply_to_message:
        return await msg.reply("❌ Команда должна быть ответом на сообщение игрока")

    parts = msg.text.split()
    if len(parts) != 4 or parts[2].lower() != "for":
        return await msg.reply("❌ Формат: /trade <твоя_id> for <его_id>")

    try:
        from_card_id = int(parts[1])
        to_card_id = int(parts[3])
    except ValueError:
        return await msg.reply("❌ ID карт должны быть числами")

    from_user = msg.from_user.id
    to_user = msg.reply_to_message.from_user.id

    if from_user == to_user:
        return await msg.reply("❌ Нельзя обмениваться с самим собой")

    from_card = database.get_user_card(from_user, from_card_id)
    to_card = database.get_user_card(to_user, to_card_id)

    if not from_card:
        return await msg.reply("❌ У тебя нет этой карты")

    if not to_card:
        return await msg.reply("❌ У игрока нет этой карты")

    if from_card["rarity"] != to_card["rarity"]:
        return await msg.reply("❌ Можно обмениваться только картами одной редкости")

    if from_card["rarity"] == "Limited":
        return await msg.reply("🚫 Лимитированные карты нельзя обменивать")

    if database.get_total_cards(from_user) <= 1:
        return await msg.reply("❌ Нельзя отдать последнюю карту")

    # создаём трейд в БД
    db_trade_id = database.create_trade(
        from_user, to_user, from_card_id, to_card_id
    )

    runtime_id = f"{from_user}:{to_user}:{from_card_id}:{to_card_id}:{db_trade_id}"

    from_chat = await bot.get_chat(from_user)
    to_chat = await bot.get_chat(to_user)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Принять",
                callback_data=f"trade_accept:{db_trade_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отказаться",
                callback_data=f"trade_decline:{db_trade_id}"
            ),
            InlineKeyboardButton(
                text="↩️ Отменить",
                callback_data=f"trade_cancel:{db_trade_id}"
            )
        ]
    ])

    sent = await msg.reply_to_message.reply(
        (
            "🔄 <b>Предложение обмена</b>\n\n"
            f"👤 <b>От:</b> <a href=\"tg://user?id={from_user}\">{from_chat.full_name}</a>\n"
            f"🃏 Карта: <code>{from_card_id}</code>\n\n"
            f"👤 <b>Кому:</b> <a href=\"tg://user?id={to_user}\">{to_chat.full_name}</a>\n"
            f"🃏 В обмен на: <code>{to_card_id}</code>"
        ),
        reply_markup=kb,
        parse_mode="HTML"
    )

    active_trades[runtime_id] = {
        "db_id": db_trade_id,
        "from_user": from_user,
        "chat_id": sent.chat.id,
        "message_id": sent.message_id
    }

    asyncio.create_task(trade_timeout(runtime_id))


@dp.callback_query(F.data.startswith(("trade_accept:", "trade_decline:", "trade_cancel:")))
async def trade_callback(cb: CallbackQuery):
    action, trade_id = cb.data.split(":")
    trade_id = int(trade_id)

    trade = database.get_trade(trade_id)
    if not trade or trade["status"] != "pending":
        return await cb.answer("❌ Обмен недействителен", show_alert=True)

    runtime_id = None
    for k, v in active_trades.items():
        if v["db_id"] == trade_id:
            runtime_id = k
            break

    # анти-двойной клик
    if runtime_id is None:
        return await cb.answer("⏳ Обмен уже обработан", show_alert=True)

    if action == "trade_cancel":
        if cb.from_user.id != trade["from_user"]:
            return await cb.answer("❌ Отменить может только инициатор", show_alert=True)

        database.update_trade_status(trade_id, "cancelled")
        active_trades.pop(runtime_id, None)
        await cb.message.edit_text("❌ Обмен отменён инициатором")
        return await cb.answer()

    if cb.from_user.id != trade["to_user"]:
        return await cb.answer("❌ Это не тебе адресовано", show_alert=True)

    if action == "trade_decline":
        database.update_trade_status(trade_id, "declined")
        active_trades.pop(runtime_id, None)
        await cb.message.edit_text("❌ Обмен отклонён")
        return await cb.answer()

    # ACCEPT
    database.swap_cards(
        trade["from_user"],
        trade["to_user"],
        trade["from_card"],
        trade["to_card"]
    )
    database.update_trade_status(trade_id, "accepted")
    active_trades.pop(runtime_id, None)

    await cb.message.edit_text("✅ Обмен успешно завершён")
    await cb.answer("Готово")

# ---------- SELL ----------
@dp.message(Command("sell"), F.chat.type.in_({"group", "supergroup"}))
async def sell_cmd(msg: Message):
    parts = msg.text.split()
    if len(parts) != 3:
        return await msg.reply("❌ Формат: /sell <card_id> <price>")

    try:
        card_id = int(parts[1])
        price = int(parts[2])
    except ValueError:
        return await msg.reply("❌ ID карты и цена должны быть числами")

    if price <= 0:
        return await msg.reply("❌ Цена должна быть больше нуля")

    user_id = msg.from_user.id

    # есть ли карта
    card = database.get_user_card(user_id, card_id)
    if not card:
        return await msg.reply("❌ У тебя нет этой карты")

    # нельзя продать последнюю карту
    if database.get_total_cards(user_id) <= 1:
        return await msg.reply("❌ Нельзя продать последнюю карту")

    # карта уже продаётся?
    if database.is_card_listed(user_id, card_id):
        return await msg.reply("❌ Эта карта уже выставлена на продажу")

    # создаём лот
    listing_id = database.create_listing(
        seller_id=user_id,
        card_id=card_id,
        price=price
    )

    await msg.reply(
        "✅ Карта выставлена на продажу\n\n"
        f"🆔 Карта: {card_id}\n"
        f"💰 Цена: {price} 🐽\n"
        f"📦 ID лота: {listing_id}"
    )

# ---------- BUY ----------
def buy_list_kb(listings, user_id):
    buttons = [
        [
            InlineKeyboardButton(
                text=str(l["card_id"]),
                callback_data=f"buy_select:{l['id']}:{user_id}"
            )
        ]
        for l in listings
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("buy"), F.chat.type.in_({"group", "supergroup"}))
async def buy_cmd(msg: Message):
    listings = database.get_active_listings()
    if not listings:
        return await msg.reply("🛒 Сейчас нет карт в продаже")

    text = "🛒 **Карты в продаже:**\n\n"
    for l in listings:
        seller = f"<a href='tg://user?id={l['seller_id']}'>продавец</a>"
        text += (
            f"🆔 {l['card_id']} | "
            f"⭐ {l['rarity']} | "
            f"🎯 {l['points']} | "
            f"💰 {l['price']} 🐽 | "
            f"👤 {seller}\n"
        )

    await msg.reply(
        text,
        reply_markup=buy_list_kb(listings, msg.from_user.id),
        parse_mode="HTML",
        disable_web_page_preview=True
    )

@dp.callback_query(F.data.startswith("buy_select:"))
async def buy_select(cb: CallbackQuery):
    _, listing_id, owner_id = cb.data.split(":")
    if cb.from_user.id != int(owner_id):
        return await cb.answer("❌ Не для тебя", show_alert=True)

    listing = database.get_listing(int(listing_id))
    if not listing:
        return await cb.answer("❌ Лот недоступен", show_alert=True)

    # Проверяем, является ли текущий пользователь продавцом этого лота
    is_seller = cb.from_user.id == listing['seller_id']

    buttons = [
        [InlineKeyboardButton(text="🔍 Предпросмотр", callback_data=f"buy_preview:{listing_id}:{owner_id}")]
    ]

    if is_seller:
        # Если нажал сам продавец — даем кнопку удаления
        buttons.append([InlineKeyboardButton(text="🗑 Снять с продажи", callback_data=f"sell_cancel:{listing_id}:{owner_id}")])
    else:
        # Если нажал покупатель — даем кнопку покупки
        buttons.append([InlineKeyboardButton(text="💰 Купить", callback_data=f"buy_confirm:{listing_id}:{owner_id}")])

    buttons.append([InlineKeyboardButton(text="⬅ Назад", callback_data=f"buy_back:{owner_id}")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await cb.message.edit_text(
        f"🃏 Карта {listing['card_id']} {'(ВАША)' if is_seller else ''}\n"
        f"⭐ Редкость: {listing['rarity']}\n"
        f"🎯 Очки: {listing['points']}\n"
        f"💰 Цена: {listing['price']} 🐽",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("buy_confirm:"))
async def buy_confirm(cb: CallbackQuery):
    _, listing_id, owner_id = cb.data.split(":")
    if cb.from_user.id != int(owner_id):
        return await cb.answer("❌ Не для тебя", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"buy_do:{listing_id}:{owner_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"buy_back:{owner_id}")]
    ])

    await cb.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_do:"))
async def buy_do(cb: CallbackQuery):
    _, listing_id, owner_id = cb.data.split(":")
    if cb.from_user.id != int(owner_id):
        return await cb.answer("❌ Не для тебя", show_alert=True)

    success = database.buy_listing(cb.from_user.id, int(listing_id))
    
    # Если это было фото (предпросмотр), edit_text не сработает.
    # Поэтому мы либо редактируем подпись к фото, либо удаляем старое и пишем новое.
    try:
        if not success:
            await cb.message.answer("❌ Покупка не удалась (недостаточно средств или лот удален)")
        else:
            await cb.message.answer("✅ Покупка успешна! Карта добавлена в вашу коллекцию.")
        
        # Удаляем старое меню выбора/предпросмотра, чтобы не засорять чат
        await cb.message.delete()
    except Exception as e:
        print(f"Error in buy_do UI: {e}")
    
    await cb.answer()

@dp.callback_query(F.data.startswith("buy_preview_close:"))
async def buy_preview_close(cb: CallbackQuery):
    _, owner_id = cb.data.split(":")
    owner_id = int(owner_id)

    if cb.from_user.id != owner_id:
        return await cb.answer("❌ Это не твоя кнопка", show_alert=True)

    await cb.message.delete()

async def auto_delete(msg: Message, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass

@dp.callback_query(F.data.startswith("buy_preview:"))
async def buy_preview(cb: CallbackQuery):
    _, listing_id, owner_id = cb.data.split(":")
    owner_id = int(owner_id)

    if cb.from_user.id != owner_id:
        return await cb.answer("❌ Это не твоя кнопка", show_alert=True)

    listing = database.get_listing(int(listing_id))
    if not listing:
        return await cb.answer("❌ Лот недоступен", show_alert=True)

    card = database.get_card_by_id(listing["card_id"])
    if not card:
        return await cb.answer("❌ Карта не найдена", show_alert=True)

    await cb.message.answer_photo(
        photo=card["image"],
        caption=(
            f"💳 {card['description']}\n\n"
            f"👑 {RARITY_RU_MAP.get(card['rarity'], card['rarity'])}\n"
            f"+{card['points']} 🕶 | +{card['currency']} 🐽\n\n"
            f"💰 Цена: {listing['price']} 🐽\n"
            f"🆔 ID: {card['id']}"
        ),
        reply_markup=buy_preview_kb(int(listing_id), owner_id)
    )

    await cb.answer()

@dp.callback_query(F.data.startswith("buy_back:"))
async def buy_back(cb: CallbackQuery):
    _, owner_id = cb.data.split(":")
    if cb.from_user.id != int(owner_id):
        return await cb.answer("❌ Не для тебя", show_alert=True)

    listings = database.get_active_listings()
    if not listings:
        return await cb.message.edit_text("🛒 Сейчас нет карт в продаже")

    text = "🛒 **Карты в продаже:**\n\n"
    for l in listings:
        seller = f"<a href='tg://user?id={l['seller_id']}'>продавец</a>"
        text += (
            f"🆔 {l['card_id']} | "
            f"⭐ {l['rarity']} | "
            f"🎯 {l['points']} | "
            f"💰 {l['price']} 🐽 | "
            f"👤 {seller}\n"
        )

    await cb.message.edit_text(
        text,
        reply_markup=buy_list_kb(listings, cb.from_user.id),
        parse_mode="HTML",
        disable_web_page_preview=True
    )

@dp.callback_query(F.data.startswith("sell_cancel:"))
async def sell_cancel_done(cb: CallbackQuery):
    _, listing_id, owner_id = cb.data.split(":")
    
    # 1. Проверка прав
    if cb.from_user.id != int(owner_id):
        return await cb.answer("❌ Не для тебя", show_alert=True)

    # 2. Получаем данные лота
    listing = database.get_listing(int(listing_id))
    if not listing or not listing['active'] or listing['seller_id'] != cb.from_user.id:
        return await cb.answer("❌ Лот уже недействителен", show_alert=True)

    # 3. Возвращаем карту и деактивируем лот
    # Мы вызываем специальную функцию в БД, которую создадим ниже
    success = database.cancel_listing(int(listing_id), cb.from_user.id)
    
    if success:
        await cb.answer("✅ Карта снята с продажи и возвращена в инвентарь", show_alert=True)
    else:
        await cb.answer("❌ Произошла ошибка при возврате карты", show_alert=True)

    # 4. Обновляем интерфейс
    # Если это было фото, его лучше удалить и отправить список заново
    if cb.message.photo:
        await cb.message.delete()
        # Отправляем новое сообщение со списком (вызываем buy_cmd вручную или аналогичную логику)
        await buy_cmd(cb.message) 
    else:
        # Если был просто текст, возвращаемся назад
        await buy_back(cb)

# ---------- OFFERS ----------
@dp.message(Command("offer"), F.chat.type.in_({"group", "supergroup"}))
async def offer_cmd(msg: types.Message):
    args = msg.text.split()

    if len(args) != 4:
        await msg.answer("Использование: /offer <buy|sell> <card_id> <price>")
        return

    offer_type, card_id, price = args[1], int(args[2]), int(args[3])
    from_user = msg.from_user.id

    reply = msg.reply_to_message
    if not reply:
        await msg.answer("❌ Ответь на сообщение игрока, которому делаешь предложение")
        return

    to_user = reply.from_user.id

    offer_id = database.create_trade_offer(
        from_user, to_user, offer_type, card_id, price
    )

    text = (
        f"📨 Торговое предложение\n\n"
        f"От: {msg.from_user.full_name}\n"
        f"Кому: {reply.from_user.full_name}\n"
        f"Тип: {offer_type.upper()}\n"
        f"🆔 Карта: {card_id}\n"
        f"💰 Цена: {price} 🐽"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять", callback_data=f"offer_accept:{offer_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"offer_decline:{offer_id}")
    ]])

    await msg.answer(text, reply_markup=kb, reply_to_message_id=reply.message_id)

@dp.callback_query(F.data.startswith("offer_accept:"))
async def offer_accept(cb: types.CallbackQuery):
    offer_id = int(cb.data.split(":")[1])
    offer = database.get_trade_offer(offer_id)

    if cb.from_user.id != offer["to_user_id"]:
        await cb.answer("❌ Это предложение не для тебя", show_alert=True)
        return

    database.complete_trade_offer(offer_id)

    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text("✅ Сделка принята")

@dp.callback_query(F.data.startswith("offer_decline:"))
async def offer_decline(cb: types.CallbackQuery):
    offer_id = int(cb.data.split(":")[1])
    offer = database.get_trade_offer(offer_id)

    if cb.from_user.id != offer["to_user_id"]:
        await cb.answer("❌ Это предложение не для тебя", show_alert=True)
        return

    database.cancel_trade_offer(offer_id)

    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text("❌ Сделка отклонена")

# ---------- UNIVERSAL GIVE CARD (ADMIN ONLY) ----------
@dp.message(Command("givecard"), F.chat.type.in_({"group", "supergroup"}))
async def give_card_admin(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return

    if not msg.reply_to_message:
        await msg.answer("❌ Ответьте этой командой на сообщение игрока.")
        return

    target_user_id = msg.reply_to_message.from_user.id
    database.add_user(target_user_id)
    
    parts = msg.text.split()
    card_obj = None

    if len(parts) == 1:
        # Полный рандом
        from bot import roll_rarity 
        r_rarity = roll_rarity()
        card_obj = database.get_random_card_by_rarity(r_rarity)
        
    elif len(parts) == 2:
        arg = parts[1]
        if arg.isdigit():
            card_obj = database.get_card_by_id(int(arg))
        else:
            # Пытаемся сопоставить ввод с ключами в RARITIES (без учета регистра)
            rarity_key = next((k for k in RARITIES.keys() if k.lower() == arg.lower()), None)
            if rarity_key:
                card_obj = database.get_random_card_by_rarity(rarity_key)
            else:
                await msg.answer(f"❌ Редкость '{arg}' не найдена.\nДоступные: {', '.join(RARITIES.keys())}")
                return

    if not card_obj:
        await msg.answer("❌ Карта не найдена в базе для этой редкости или ID.")
        return

    database.give_card(target_user_id, card_id=card_obj['id'])
    
    card_count = database.get_card_count(target_user_id, card_obj['id'])
    
    if 'TOP_CACHE' in globals():
        TOP_CACHE.clear()

    rarity_ru = RARITY_RU_MAP.get(card_obj['rarity'], card_obj['rarity'])
    
    caption = (
        f"🎁 <b>Админ выдал карту игроку {msg.reply_to_message.from_user.first_name}!</b>\n\n"
        f"💳 {card_obj['description']}\n\n"
        f"👑 {rarity_ru}\n"
        f"+{card_obj['points']} 🕶 | +{card_obj['currency']} 🐽\n\n"
        f"🃏 Кол-во копий: {card_count}\n"
        f"🆔 ID: {card_obj['id']}"
    )

    if card_obj.get('image'):
        await msg.answer_photo(photo=card_obj['image'], caption=caption, parse_mode="HTML")
    else:
        await msg.answer(caption, parse_mode="HTML")

# ---------- VIDEO ----------
@dp.message(Command("freegaysexvideo"), F.chat.type.in_({"group", "supergroup"}))
async def send_video_command(msg: Message):
    # Проверяем, разрешен ли этот чат
    if msg.chat.id not in VIDEO_ALLOWED_CHATS:
        await msg.answer("❌ В этом чате команда недоступна.")
        return

    video_id = "BAACAgIAAxkBAAIG-2m8JiHqMqwFPqBcr7Gyl4HBybl3AAKgYAACraNRSKYSXjXd1d-KOgQ"
    try:
        await msg.answer_video(
            video=video_id,
        )
    except Exception as e:
        await msg.answer(f"❌ Ошибка при отправке видео: {e}")

# ---------- ОБЪЕДИНЕННЫЙ ID ПОЛУЧАТЕЛЬ ----------
@dp.message(Command("id"), F.from_user.id.in_([MY_ID, 5295930709]))
async def get_any_file_id(message: Message):
    # 1. Проверяем, что команда отправлена в ответ
    if not message.reply_to_message:
        await message.answer("❌ Ответь этой командой на сообщение с <b>фото</b> или <b>стикером</b>.", parse_mode="HTML")
        return

    target = message.reply_to_message

    # 2. ЕСЛИ ЭТО ФОТО
    if target.photo:
        file_id = target.photo[-1].file_id
        await message.answer(f"✅ <b>ID Фото:</b>\n<code>{file_id}</code>", parse_mode="HTML")
        return

    # 3. ЕСЛИ ЭТО СТИКЕР
    elif target.sticker:
        status_msg = await message.answer("🔄 Генерирую отчет по стикеру...")
        
        # Шаг А: Запоминаем оригинальный ID стикера (с паком)
        sticker_id = f"<code>{target.sticker.file_id}</code>"
        
        try:
            # Шаг Б: Просим Telegram переслать его
            msg_doc = await bot.send_document(
                chat_id=message.chat.id, 
                document=target.sticker.file_id
            )
            
            # Шаг В: Вытаскиваем сгенерированный ID. 
            # Поскольку Telegram вернул объект стикера, берем его из .sticker
            if msg_doc.sticker:
                doc_id = f"<code>{msg_doc.sticker.file_id}</code>"
            elif msg_doc.document:
                doc_id = f"<code>{msg_doc.document.file_id}</code>"
            else:
                doc_id = "<i>Не удалось сгенерировать</i>"
            
            # Удаляем статусную плашку и выводим твой красивый отчет
            await status_msg.delete()
            await message.answer(
                f"📊 <b>Итоговый отчет по стикеру:</b>\n\n"
                f"✅ <b>ID стикера (с паком):</b>\n{sticker_id}\n\n"
                f"📄 <b>ID документа (без пака):</b>\n{doc_id}",
                parse_mode="HTML"
            )
            
        except Exception as e:
            await status_msg.edit_text(f"❌ Ошибка при генерации ID документа: {e}")
        return

    # 4. ЕСЛИ ЭТО ЧТО-ТО ДРУГОЕ
    else:
        await message.answer("⚠️ Бот не нашел фото или стикера в сообщении, на которое ты ответил.")

# ---------- 67 ----------
RANDOM_PHOTOS = [
    "AgACAgQAAyEFAATdA6haAALFy2ng_hFPj4Tq3CdrrECi5BqsK7BoAAJHDGsbD3wJU49ycclK32URAQADAgADbQADOwQ",
    "AgACAgQAAyEFAATdA6haAALFz2ng_l8jEaNEPiM36fhNfj7ZuQj5AAJIDGsbD3wJU12Cug3ReCRoAQADAgADbQADOwQ",
    "AgACAgQAAyEFAASu1VyOAAICbWnhBYNNDtEufrZVHa1ztNcruOPjAAJ7DGsbFe8IU8xrLpFbQ37CAQADAgADbQADOwQ",
    "AgACAgQAAyEFAASu1VyOAAICbmnhBaHvd4POxfzl5WeuzTKtPCjiAAJ8DGsbFe8IUyUeDKkiMkskAQADAgADbQADOwQ",
    "AgACAgQAAyEFAASu1VyOAAICb2nhBc96g5C3TRLXJY9S-hN_F2XeAAJ9DGsbFe8IU4xl5Huk88MtAQADAgADbQADOwQ",
    "AgACAgQAAyEFAASu1VyOAAICi2nlGaRJkSzUS5GO5_8dBexdaveWAAJSDWsbeMcoU_j-qCC0wFuBAQADAgADeQADOwQ",
    "AgACAgQAAyEFAASu1VyOAAICjmnlGcoDh4icw80B6_MPz__NKGqsAAJTDWsbeMcoUzDBbUyLsIerAQADAgADeAADOwQ",
    "AgACAgIAAyEFAATbGiYSAAEImclp_dKc9pu9-qQMNCyeWwAB7waFwBwAAvcVaxtn6_FLSxt0NWzSij4BAAMCAAN4AAM7BA",
    "AgACAgQAAyEFAASu1VyOAAIGEmoS0znD4n-oPnpqPFRxoFUS8yzVAALvDWsb9B-ZUL9j1DDDmbuoAQADAgADeQADOwQ"
]

def buy_preview_kb(listing_id: int, user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"buy_preview_close:{user_id}")]
    ])

# 1. При перехвате "67" проверяем доступ
@dp.message(F.text.lower().contains("67"))
async def photo_quote_reply(msg: Message):
    print(">>> РАБОТАЕТ НОВЫЙ ХЭНДЛЕР 67 <<<")
    if not msg.text:
        return

    text_lower = msg.text.lower()
    match = re.search(r"67", text_lower)
    if not match or not RANDOM_PHOTOS:
        return

    # Извлекаем слово сразу до проверки доступа, чтобы оно вычислялось для всех веток
    start_pos = match.start()
    original_word = msg.text[start_pos : match.end()]

    user_id = msg.from_user.id
    chat_id = msg.chat.id

    # Если доступ есть — отправляем фото
    if database.has_67_access(user_id, chat_id):
        try:
            reply_params = ReplyParameters(
                message_id=msg.message_id,
                chat_id=msg.chat.id,
                quote=original_word,
                quote_offset=start_pos
            )
            await msg.answer_photo(
                photo=random.choice(RANDOM_PHOTOS),
                reply_parameters=reply_params
            )
        except Exception as e:
            print(f"Ошибка при отправке фото: {e}")
            await msg.reply_photo(photo=random.choice(RANDOM_PHOTOS))
        return

    # Если доступа НЕТ — отправляем сообщение с кнопкой выбора
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Разблокировать для себя [1 ⭐️]", callback_data="buy_67_user")],
        [InlineKeyboardButton(text="🌟 Разблокировать для чата [67 ⭐️]", callback_data="buy_67_chat")]
    ])

    await msg.reply(
        "🔒 **Эта функция теперь платная!**\n\n"
        "Чтобы использовать триггер «67», выберите вариант оплаты:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

    # 1.1. ОТДЕЛЬНО отправляем уведомление
    try:
        if msg.chat.id != MY_ID:
            chat_id_str = str(msg.chat.id)
            if chat_id_str.startswith("-100"):
                clean_chat_id = chat_id_str.replace("-100", "")
            else:
                clean_chat_id = chat_id_str.lstrip("-")
            
            msg_link = f"https://t.me/c/{clean_chat_id}/{msg.message_id}"
            
            def safe_html(text):
                return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            user_name = safe_html(msg.from_user.full_name)
            chat_title = safe_html(msg.chat.title or "Группа")
            
            notification_text = (
                f"🎯 <b>Бот ответил на слово '{original_word}'</b>\n\n"
                f"👤 <b>Отправитель:</b> {user_name}\n"
                f"💬 <b>Чат:</b> {chat_title}\n"
                f"🔗 <a href='{msg_link}'>Перейти к сообщению</a>"
            )
            
            await bot.send_message(
                MY_ID, 
                notification_text, 
                parse_mode="HTML",
                disable_web_page_preview=False
            )
    except Exception as e:
        print(f"Ошибка уведомления: {e}")

# 2. Вызов нативного инвойса Telegram (Скриншот 2)
@dp.callback_query(F.data == "buy_67_user")
async def process_buy_user(call: CallbackQuery, bot: Bot):
    await call.answer()
    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title="Доступ к «67» (личный)",
        description="Разблокировка триггера 67 во всех чатах лично для вас.",
        payload=f"pay_67_user_{call.from_user.id}",
        provider_token="",  # Для Telegram Stars оставляем ПУСТОЙ строкой
        currency="XTR",     # Код валюты Telegram Stars
        prices=[LabeledPrice(label="1 Звезда", amount=1)],
        reply_to_message_id=call.message.message_id
    )


@dp.callback_query(F.data == "buy_67_chat")
async def process_buy_chat(call: CallbackQuery, bot: Bot):
    await call.answer()
    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title="Доступ к «67» (для чата)",
        description="Разблокировка триггера 67 для всех участников этого чата.",
        payload=f"pay_67_chat_{call.message.chat.id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="67 Звезд", amount=67)],
        reply_to_message_id=call.message.message_id
    )


# 3. Подтверждение валидности покупки (Обязательно!)
@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


# 4. Начисление доступа после подтверждения (Скриншот 3)
@dp.message(F.successful_payment)
async def process_successful_payment(msg: Message):
    payload = msg.successful_payment.invoice_payload

    if payload.startswith("pay_67_user_"):
        user_id = int(payload.replace("pay_67_user_", ""))
        database.add_paid_user(user_id)
        await msg.reply("🎉 **Оплата прошла успешно!** Теперь вы можете использовать триггер 67 во всех чатах.")

    elif payload.startswith("pay_67_chat_"):
        chat_id = int(payload.replace("pay_67_chat_", ""))
        database.add_paid_chat(chat_id)
        await msg.reply("🎉 **Оплата прошла успешно!** Функция 67 разблокирована для всех участников чата.")

# ---------- CLEAR ----------
@dp.message(Command("clear"), F.chat.type == "private", F.from_user.id == MY_ID)
async def cmd_clear_state(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        await msg.answer("🧼 Очередь ожидания очищена. Теперь сообщения будут просто пересылаться.")
    else:
        await msg.answer("ℹ️ Бот и так ни в каком режиме не находится.")

# 2. Единый хэндлер для лички (Реакции, Ссылки, Пересылка)
# Работает ТОЛЬКО в приватном чате и ТОЛЬКО для тебя, игнорируя команды
@dp.message(F.chat.type == "private", F.from_user.id == MY_ID, ~F.text.startswith("/"))
async def unified_forwarder(msg: Message, state: FSMContext):
    content = msg.text or msg.caption or ""

    is_escaped = content.startswith("\\")
    clean_text = content[1:] if is_escaped else content

    # --- ЛОГИКА ТОЧКИ (РЕАКЦИИ) ---
    if content.startswith(".") and not is_escaped:
        reaction_emoji = content[1:].strip()
        data = await state.get_data()
        
        target_chat = data.get("re_chat_id") or database.get_setting("default_group_id")
        saved_id = database.get_setting("last_sent_msg_id")
        target_msg = data.get("re_msg_id") or (int(saved_id) if saved_id else None)

        if target_chat and target_msg:
            try:
                from aiogram.types import ReactionTypeEmoji
                r_list = [ReactionTypeEmoji(emoji=reaction_emoji)] if reaction_emoji else []
                
                # Обработка ID (число или username)
                if isinstance(target_chat, str) and target_chat.replace('-', '').isdigit():
                    final_chat_id = int(target_chat)
                else:
                    final_chat_id = target_chat
                
                await bot.set_message_reaction(
                    chat_id=final_chat_id,
                    message_id=int(target_msg),
                    reaction=r_list
                )
                await msg.answer(f"✅ Реакция {reaction_emoji} поставлена!")
                if data.get("re_chat_id"): await state.clear()
                return 
            except Exception as e:
                await msg.answer(f"❌ Ошибка реакции: {e}")
                return

    # --- ЛОГИКА ССЫЛКИ ---
    chat_id, msg_id = parse_tg_link(content)
    if chat_id and msg_id and not is_escaped:
        await state.update_data(re_chat_id=chat_id, re_msg_id=msg_id)
        await state.set_state(AddCardState.waiting_for_re_content)
        await msg.answer("🔗 Ссылка принята. Жду текст ответа или .эмодзи")
        return

    # --- ЛОГИКА ОТВЕТА (REPLY) ---
    current_state = await state.get_state()
    if current_state == AddCardState.waiting_for_re_content:
        data = await state.get_data()
        try:
            await msg.copy_to(chat_id=data['re_chat_id'], reply_to_message_id=data['re_msg_id'])
            await msg.answer("✅ Ответ отправлен!")
            await state.clear()
            return
        except Exception as e:
            await msg.answer(f"❌ Ошибка реплая: {e}")
            await state.clear()
            return

    # --- ОБЫЧНАЯ ПЕРЕСЫЛКА ---
    target_id = database.get_setting("default_group_id")
    if target_id:
        try:
            dest_chat = int(target_id)
            if is_escaped:
                sent_msg = await bot.send_message(chat_id=dest_chat, text=clean_text)
            else:
                sent_msg = await msg.copy_to(chat_id=dest_chat)
            
            database.set_setting("last_sent_msg_id", sent_msg.message_id)
        except Exception as e:
            await msg.answer(f"❌ Ошибка пересылки: {e}")

@dp.message(F.chat.type.in_({"group", "supergroup"}), ~F.text.startswith("/"))
async def group_message_handler(message: Message):
    # 1. Счетчик сообщений
    if is_chat_allowed(message.chat.id):
        user_id = message.from_user.id
        database.add_user(user_id)
        database.increment_message_counter(user_id)
    
    # 2. Трекинг ID для реакций
    current_dflt = database.get_setting("default_group_id")
    if current_dflt:
        try:
            if int(message.chat.id) == int(current_dflt):
                database.set_setting("last_sent_msg_id", message.message_id)
        except:
            pass

# ---------- KEEP ALIVE ----------
async def keep_alive():
    url = "https://tgbot1.fly.dev/"
    await asyncio.sleep(10)
    
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(url) as resp:
                    print(f"保持 (Keep-alive) ping sent to {url}, status: {resp.status}")
            except Exception as e:
                print(f"Self-ping error: {e}")
            
            await asyncio.sleep(300)

# ---------- WEB SERVER ----------
async def handle(request):
    return web.Response(text="Bot is running!")

async def start_web():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web server started on port {PORT}")

# ---------- MAIN ----------
async def main():
    database.init_db()
    database.init_settings_tables()
    await start_web()

    asyncio.create_task(keep_alive())

    print("Бот запущен и задача keep-alive активирована.")

    # Перед самым запуском поллинга очищаем очередь:
    await bot.delete_webhook(drop_pending_updates=True) # Самый надежный сброс очереди
    
    # Запускаем бота с пропуском старых апдейтов
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")