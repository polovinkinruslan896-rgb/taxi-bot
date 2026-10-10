import asyncio
import aiosqlite
import os
from datetime import datetime
import pytz
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

TOKEN = os.getenv("TOKEN") or "8986833195:AAFcNf2c7Ql-0DwWnLZa7SYqxinu8uM_1N4"
ADMIN_ID = 7165265831
DB_NAME = "taxi.db"
DRIVER_FOUND_GIF = "CgACAgQAAxkBAAIDD2rJ6hcW4ftuAAEUgt5rfRzWQ2ToSQACdQUAAmX85FGeInNVf6Sy6z0E"
RATING_1_3_GIF = "CgACAgQAAxkBAAIDs2rJ8XNEse_hmSLOVu7IwBcNLrG9AAKrCwACo6VUUukknLXb5eUQPQQ"
RATING_4_GIF = "CgACAgQAAxkBAAID42rJ8m9oHjcyL3kiqjPUZC4ER-AMAAKVBwAChvrMUfVXY6aj64RmPQQ"
RATING_5_GIF = "CgACAgQAAxkBAAIEDWrJ831riLB2ha0GvaNIb2yhZ_rSAAKBBgACHUy9U7Rb0eYjVF2XPQQ"
CONTACT_GIF = "CgACAgQAAxkBAAIEY2rJ9oR-5lZ4Wh-W2fb4F_oOcu-eAAJPDAACv_vsUSrHcLB45HyYPQQ"

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

active_orders = {}

class OrderTaxi(StatesGroup):
    choosing_village = State()
    choosing_other_village = State()
    waiting_custom_village = State()
    waiting_street = State()
    waiting_destination = State()
    waiting_phone = State()
    confirming_address = State()
    searching = State()
    waiting_rating = State()

class AdminState(StatesGroup):
    waiting_driver_data = State()
    waiting_blacklist_id = State()
    waiting_blacklist_remove = State()

# ================== БАЗА ==================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS drivers (
                id INTEGER PRIMARY KEY,
                name TEXT, phone TEXT, car TEXT, color TEXT, number TEXT,
                free INTEGER DEFAULT 1,
                orders_today INTEGER DEFAULT 0,
                total_rating REAL DEFAULT 0,
                rating_count INTEGER DEFAULT 0,
                last_date TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS passengers (
                id INTEGER PRIMARY KEY,
                name TEXT, phone TEXT,
                orders_count INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id INTEGER PRIMARY KEY,
                type TEXT,
                reason TEXT,
                added_date TEXT
            )
        """)
        await db.commit()

        drivers_to_add = [
            (7165265831, "Investor", "+79277511560", "Mercedes-Benz G-Класс AMG", "чёрный", "А001АА 63"),
            (8053756093, "Водитель 2", "+79000000000", "Kia Rio", "белый", "А123БВ 63"),
        ]
        for d in drivers_to_add:
            await db.execute(
                "INSERT OR IGNORE INTO drivers (id, name, phone, car, color, number, free, orders_today, total_rating, rating_count, last_date) VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0, 0, ?)",
                (*d, datetime.now().strftime("%Y-%m-%d"))
            )
        await db.commit()

async def is_blacklisted(user_id: int, type_: str = None) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        if type_:
            cursor = await db.execute("SELECT 1 FROM blacklist WHERE user_id = ? AND type = ?", (user_id, type_))
        else:
            cursor = await db.execute("SELECT 1 FROM blacklist WHERE user_id = ?", (user_id,))
        return await cursor.fetchone() is not None

async def get_passenger(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM passengers WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def save_or_update_passenger(user_id: int, name: str, phone: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        existing = await get_passenger(user_id)
        if existing:
            if phone:
                await db.execute("UPDATE passengers SET name = ?, phone = ?, orders_count = orders_count + 1 WHERE id = ?", (name, phone, user_id))
            else:
                await db.execute("UPDATE passengers SET name = ?, orders_count = orders_count + 1 WHERE id = ?", (name, user_id))
        else:
            await db.execute("INSERT INTO passengers (id, name, phone, orders_count) VALUES (?, ?, ?, 1)", (user_id, name, phone or ""))
        await db.commit()

async def get_all_passengers():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM passengers ORDER BY orders_count DESC")
        return [dict(r) for r in await cursor.fetchall()]

async def get_free_drivers():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM drivers WHERE free = 1")
        drivers = [dict(r) for r in await cursor.fetchall()]
        result = []
        for d in drivers:
            if not await is_blacklisted(d["id"], "driver"):
                result.append(d)
        return result

async def get_driver(driver_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_all_drivers():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM drivers")
        drivers = [dict(r) for r in await cursor.fetchall()]
        return [d for d in drivers if not await is_blacklisted(d["id"], "driver")]

async def set_driver_free(driver_id: int, free: bool):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE drivers SET free = ? WHERE id = ?", (1 if free else 0, driver_id))
        await db.commit()

async def free_all_drivers():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE drivers SET free = 1")
        await db.commit()

async def increase_driver_orders(driver_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE drivers 
            SET orders_today = CASE WHEN last_date = ? THEN orders_today + 1 ELSE 1 END,
                last_date = ?
            WHERE id = ?
        """, (today, today, driver_id))
        await db.commit()

async def add_rating(driver_id: int, rating: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE drivers 
            SET total_rating = total_rating + ?, rating_count = rating_count + 1 
            WHERE id = ?
        """, (rating, driver_id))
        await db.commit()

async def add_to_blacklist(user_id: int, type_: str, reason: str = ""):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO blacklist (user_id, type, reason, added_date) VALUES (?, ?, ?, ?)",
            (user_id, type_, reason, datetime.now().strftime("%Y-%m-%d"))
        )
        await db.commit()

async def remove_from_blacklist(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_blacklist(type_: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        if type_:
            cursor = await db.execute("SELECT * FROM blacklist WHERE type = ?", (type_,))
        else:
            cursor = await db.execute("SELECT * FROM blacklist")
        return [dict(r) for r in await cursor.fetchall()]

def calculate_price(village: str):
    moscow = pytz.timezone("Europe/Moscow")
    now = datetime.now(moscow)
    hour = now.hour
    is_night = hour >= 23 or hour < 6
    v = village.lower().strip()

    if v == "богатое":
        return 250 if is_night else 150
    if v in {"аверьяновка", "арзамасовка", "беловка"}:
        return 550 if is_night else 400
    return None

# ================== КЛАВИАТУРЫ ==================
def main_kb(user_id: int):
    buttons = [
        [KeyboardButton(text="🚕 Заказать такси")],
        [KeyboardButton(text="📞 Связаться с создателем")]
    ]
    if user_id == ADMIN_ID:
        buttons.append([KeyboardButton(text="🛠 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def village_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🏘 Богатое")],
        [KeyboardButton(text="🌍 Другое")],
        [KeyboardButton(text="❌ Отменить")]
    ], resize_keyboard=True)

def other_villages_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🏡 Аверьяновка"), KeyboardButton(text="🏡 Арзамасовка")],
        [KeyboardButton(text="🏡 Беловка"), KeyboardButton(text="🌍 Другое")],
        [KeyboardButton(text="❌ Отменить")]
    ], resize_keyboard=True)

def cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отменить")]], resize_keyboard=True)

def phone_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📱 Отправить номер", request_contact=True)],
        [KeyboardButton(text="❌ Отменить")]
    ], resize_keyboard=True)

def confirm_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="✅ Всё верно")],
        [KeyboardButton(text="✏️ Изменить")]
    ], resize_keyboard=True)

def searching_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отменить заказ")]], resize_keyboard=True)

def finish_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⭐ Оценить поездку")],
        [KeyboardButton(text="🏠 В меню")]
    ], resize_keyboard=True)

def rating_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="1️⃣"), KeyboardButton(text="2️⃣"), KeyboardButton(text="3️⃣")],
        [KeyboardButton(text="4️⃣"), KeyboardButton(text="5️⃣")]
    ], resize_keyboard=True)

# ================== КОМАНДЫ ==================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if await is_blacklisted(message.from_user.id, "passenger"):
        await message.answer("🚫 К сожалению, ты в чёрном списке. Заказать такси не получится.")
        return
    await message.answer(
        "👋 Привет!\n\n"
        "🚕 Я бот такси села <b>Богатое</b>\n"
        "Готов быстро найти тебе машину 😉",
        reply_markup=main_kb(message.from_user.id),
        parse_mode="HTML"
    )

@dp.message(Command("free"))
async def cmd_free(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await free_all_drivers()
    await message.answer("✅ Все водители снова свободны")

@dp.message(F.animation)
async def get_gif_id(message: types.Message):
    file_id = message.animation.file_id
    print("FILE_ID:", file_id)
    await message.answer(
        f"✅ file_id гифки:\n\n<code>{file_id}</code>",
        parse_mode="HTML"
    )

@dp.message(F.text == "📞 Связаться с создателем")
async def contact_owner(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="@investeq", url="https://t.me/investeq")]
    ])
    await message.answer_animation(
        animation=CONTACT_GIF,
        caption=(
            "Если хочешь что-то предложить, пожаловаться или просто написать — "
            "жми на кнопку ниже 👇"
        ),
        reply_markup=kb
    )
# ================== АДМИН ==================
@dp.message(F.text == "🛠 Админ-панель")
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🛠 Админ-панель", reply_markup=ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Водители")],
        [KeyboardButton(text="👤 Пассажиры"), KeyboardButton(text="🚫 Чёрный список")],
        [KeyboardButton(text="➕ Добавить водителя")],
        [KeyboardButton(text="◀️ Назад")]
    ], resize_keyboard=True))

@dp.message(F.text == "◀️ Назад")
async def admin_back(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Главное меню", reply_markup=main_kb(ADMIN_ID))

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    drivers = await get_all_drivers()
    total = sum(d["orders_today"] for d in drivers)
    text = f"📊 <b>Статистика за сегодня</b>\n\nВсего заказов: <b>{total}</b>\n\n"
    for d in drivers:
        avg = round(d["total_rating"] / d["rating_count"], 1) if d["rating_count"] else "—"
        text += f"• {d['name']}: {d['orders_today']} | ⭐ {avg}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "👥 Водители")
async def admin_drivers(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    drivers = await get_all_drivers()
    if not drivers:
        await message.answer("Активных водителей нет")
        return
    for d in drivers:
        avg = round(d["total_rating"] / d["rating_count"], 1) if d["rating_count"] else "нет"
        status = "🟢 Свободен" if d["free"] else "🔴 Занят"
        text = (
            f"👤 <b>{d['name']}</b>\n"
            f"{status}\n"
            f"🚗 {d['car']} | {d['color']}\n"
            f"🔢 {d['number']}\n"
            f"📞 {d['phone']}\n"
            f"📦 {d['orders_today']} | ⭐ {avg}\n"
            f"ID: <code>{d['id']}</code>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🚫 В ЧС", callback_data=f"bl_driver_{d['id']}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_driver_{d['id']}")
        ]])
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.message(F.text == "👤 Пассажиры")
async def admin_passengers(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    passengers = await get_all_passengers()
    text = "👤 <b>Пассажиры</b>\n\n"
    shown = 0
    for p in passengers:
        if await is_blacklisted(p["id"], "passenger"):
            continue
        text += (
            f"• <b>{p['name']}</b>\n"
            f"  📞 {p['phone'] or 'нет'}\n"
            f"  📦 {p['orders_count']}\n"
            f"  ID: <code>{p['id']}</code>\n\n"
        )
        shown += 1
    await message.answer(text if shown else "Пока никого нет", parse_mode="HTML")

@dp.message(F.text == "➕ Добавить водителя")
async def admin_add_driver(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Формат:\n<code>ID | Имя | Телефон | Машина | Цвет | Номер</code>", parse_mode="HTML")
    await state.set_state(AdminState.waiting_driver_data)

@dp.message(AdminState.waiting_driver_data)
async def process_new_driver(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = [p.strip() for p in message.text.split("|")]
        driver_id = int(parts[0])
        name, phone, car, color, number = parts[1:6]
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR REPLACE INTO drivers (id, name, phone, car, color, number, free, orders_today, total_rating, rating_count, last_date) VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0, 0, ?)",
                (driver_id, name, phone, car, color, number, datetime.now().strftime("%Y-%m-%d"))
            )
            await db.commit()
        await message.answer(f"✅ {name} добавлен!", reply_markup=main_kb(ADMIN_ID))
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()

@dp.message(F.text == "🚫 Чёрный список")
async def admin_blacklist(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🚫 Чёрный список", reply_markup=ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🚫 Пассажиры в ЧС"), KeyboardButton(text="🚫 Водители в ЧС")],
        [KeyboardButton(text="➕ Добавить в ЧС"), KeyboardButton(text="➖ Убрать из ЧС")],
        [KeyboardButton(text="◀️ Назад")]
    ], resize_keyboard=True))

@dp.message(F.text == "🚫 Пассажиры в ЧС")
async def bl_passengers(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    items = await get_blacklist("passenger")
    text = "🚫 Пассажиры в ЧС:\n\n" + ("\n".join(f"• <code>{i['user_id']}</code>" for i in items) if items else "Пусто")
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "🚫 Водители в ЧС")
async def bl_drivers(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    items = await get_blacklist("driver")
    text = "🚫 Водители в ЧС:\n\n" + ("\n".join(f"• <code>{i['user_id']}</code>" for i in items) if items else "Пусто")
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "➕ Добавить в ЧС")
async def bl_add(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Формат: <code>ID passenger</code> или <code>ID driver</code>", parse_mode="HTML")
    await state.set_state(AdminState.waiting_blacklist_id)

@dp.message(AdminState.waiting_blacklist_id)
async def process_blacklist_add(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.strip().lower().split()
        await add_to_blacklist(int(parts[0]), parts[1])
        await message.answer("✅ Добавлен в ЧС")
    except:
        await message.answer("❌ Неверный формат")
    await state.clear()

@dp.message(F.text == "➖ Убрать из ЧС")
async def bl_remove(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Отправь только ID:")
    await state.set_state(AdminState.waiting_blacklist_remove)

@dp.message(AdminState.waiting_blacklist_remove)
async def process_blacklist_remove(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        await remove_from_blacklist(int(message.text.strip()))
        await message.answer("✅ Убран из ЧС")
    except:
        await message.answer("❌ Нужен только ID")
    await state.clear()

# ================== ЗАКАЗ ==================
@dp.message(F.text == "🚕 Заказать такси")
async def start_order(message: types.Message, state: FSMContext):
    if await is_blacklisted(message.from_user.id, "passenger"):
        await state.clear()
        await message.answer("🚫 К сожалению, ты в чёрном списке.")
        return
    await state.clear()
    await message.answer("📍 Откуда тебя забрать?", reply_markup=village_kb())
    await state.set_state(OrderTaxi.choosing_village)

@dp.message(F.text.in_({"❌ Отменить", "❌ Отменить заказ"}))
async def cancel_any(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in active_orders:
        driver_id = active_orders[user_id].get("driver_id")
        if driver_id:
            await set_driver_free(driver_id, True)
        del active_orders[user_id]
    await state.clear()
    await message.answer("❌ Окей, заказ отменён", reply_markup=main_kb(user_id))

@dp.message(OrderTaxi.choosing_village, F.text == "🏘 Богатое")
async def village_bogatoe(message: types.Message, state: FSMContext):
    await state.update_data(village="Богатое")
    await message.answer("📍 Откуда забрать? Напиши улицу и дом:", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_street)

@dp.message(OrderTaxi.choosing_village, F.text == "🌍 Другое")
async def village_other(message: types.Message, state: FSMContext):
    await message.answer("🌍 Выбери село:", reply_markup=other_villages_kb())
    await state.set_state(OrderTaxi.choosing_other_village)

@dp.message(OrderTaxi.choosing_other_village, F.text.in_({"🏡 Аверьяновка", "🏡 Арзамасовка", "🏡 Беловка"}))
async def other_village_selected(message: types.Message, state: FSMContext):
    village = message.text.replace("🏡 ", "")
    await state.update_data(village=village)
    await message.answer("📍 Откуда забрать? Напиши улицу и дом:", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_street)

@dp.message(OrderTaxi.choosing_other_village, F.text == "🌍 Другое")
async def other_village_custom(message: types.Message, state: FSMContext):
    await message.answer("📍 Напиши название села:", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_custom_village)

@dp.message(OrderTaxi.waiting_custom_village)
async def custom_village_input(message: types.Message, state: FSMContext):
    if message.text in {"❌ Отменить", "❌ Отменить заказ"}:
        await cancel_any(message, state)
        return
    await state.update_data(village=message.text.strip())
    await message.answer("📍 Откуда забрать? Напиши улицу и дом:", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_street)

@dp.message(OrderTaxi.waiting_street)
async def process_street(message: types.Message, state: FSMContext):
    if message.text in {"❌ Отменить", "❌ Отменить заказ"}:
        await cancel_any(message, state)
        return
    await state.update_data(street=message.text.strip())
    await message.answer("🏁 Куда поедем? Напиши улицу и дом:", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_destination)

@dp.message(OrderTaxi.waiting_destination)
async def process_destination(message: types.Message, state: FSMContext):
    if message.text in {"❌ Отменить", "❌ Отменить заказ"}:
        await cancel_any(message, state)
        return
    await state.update_data(destination=message.text.strip())

    passenger = await get_passenger(message.from_user.id)
    if passenger and passenger.get("phone"):
        await state.update_data(phone=passenger["phone"])
        await show_confirmation(message, state)
    else:
        await message.answer(
            "📱 Напиши свой номер\n"
            "Или просто нажми кнопку «Отправить номер»",
            reply_markup=phone_kb()
        )
        await state.set_state(OrderTaxi.waiting_phone)

@dp.message(OrderTaxi.waiting_phone, F.contact)
async def process_phone_contact(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await state.update_data(phone=phone)
    await show_confirmation(message, state)

@dp.message(OrderTaxi.waiting_phone)
async def process_phone_text(message: types.Message, state: FSMContext):
    if message.text in {"❌ Отменить", "❌ Отменить заказ"}:
        await cancel_any(message, state)
        return
    phone = message.text.strip()
    if phone.isdigit() and not phone.startswith("+"):
        phone = "+" + phone
    await state.update_data(phone=phone)
    await show_confirmation(message, state)

async def show_confirmation(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = (
        f"📋 <b>Проверь, всё ли правильно</b>\n\n"
        f"🚏 Откуда: <b>{data.get('village')}, {data.get('street')}</b>\n"
        f"🏁 Куда: <b>{data.get('destination')}</b>\n\n"
        f"Всё ок?"
    )
    await message.answer(text, reply_markup=confirm_kb(), parse_mode="HTML")
    await state.set_state(OrderTaxi.confirming_address)

@dp.message(OrderTaxi.confirming_address, F.text == "✅ Всё верно")
async def confirm_address(message: types.Message, state: FSMContext):
    if await is_blacklisted(message.from_user.id, "passenger"):
        await state.clear()
        await message.answer("🚫 Ты в чёрном списке.")
        return

    data = await state.get_data()
    village = data.get("village")
    street = data.get("street")
    phone = data.get("phone")
    destination = data.get("destination")
    user = message.from_user
    price = calculate_price(village)

    await save_or_update_passenger(user.id, user.full_name, phone)

    order_id = user.id
    active_orders[order_id] = {
        "village": village,
        "street": street,
        "destination": destination,
        "passenger_name": user.full_name,
        "passenger_phone": phone,
        "driver_id": None,
        "price": price
    }

    price_text = "Уточнить у водителя" if price is None else f"{price} ₽"

    await message.answer(
        f"✅ <b>Заказ принят</b>\n\n"
        f"🏘 {village}\n"
        f"🛣 {street}\n"
        f"🏁 {destination}\n"
        f"💰 {price_text}\n\n"
        f"🔍 Ищем свободную машину...\n"
        f"⏱ Обычно это 2–5 минут, подожди чуть-чуть 🙌",
        parse_mode="HTML",
        reply_markup=searching_kb()
    )

    await state.set_state(OrderTaxi.searching)
    await send_order_to_drivers(order_id)

@dp.message(OrderTaxi.confirming_address, F.text == "✏️ Изменить")
async def change_address(message: types.Message, state: FSMContext):
    await message.answer("📍 Откуда забрать? Напиши улицу и дом:", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_street)

async def send_order_to_drivers(order_id: int):
    if order_id not in active_orders:
        return
    order = active_orders[order_id]
    free_drivers = await get_free_drivers()

    print(f"=== ОТПРАВКА ЗАКАЗА ===")
    print(f"Свободных водителей: {len(free_drivers)}")
    for d in free_drivers:
        print(f"  → ID: {d['id']} | {d['name']}")

    if not free_drivers:
        try:
            await bot.send_message(order_id, "😔 Сейчас все заняты. Попробуй чуть позже", reply_markup=main_kb(order_id))
        except:
            pass
        if order_id in active_orders:
            del active_orders[order_id]
        return

    price = order["price"]
    price_line = "" if price is None else f"💰 {price} ₽\n"

    order_text = (
        f"🆕 <b>Новый заказ</b>\n\n"
        f"🏘 {order['village']}\n"
        f"🛣 {order['street']}\n"
        f"🏁 {order['destination']}\n"
        f"{price_line}"
        f"👤 {order['passenger_name']}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Взять заказ", callback_data=f"take_{order_id}")]
    ])
    for d in free_drivers:
        try:
            await bot.send_message(d["id"], order_text, reply_markup=kb, parse_mode="HTML")
            print(f"  ✅ Отправлено: {d['id']}")
        except Exception as e:
            print(f"  ❌ Ошибка {d['id']}: {e}")

@dp.callback_query(F.data.startswith("take_"))
async def take_order(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    driver_id = callback.from_user.id

    if await is_blacklisted(driver_id, "driver"):
        await callback.answer("Ты в чёрном списке", show_alert=True)
        return
    if order_id not in active_orders:
        await callback.answer("Заказ уже недоступен", show_alert=True)
        return
    driver = await get_driver(driver_id)
    if not driver or not driver["free"]:
        await callback.answer("Ты уже занят", show_alert=True)
        return
    if active_orders[order_id]["driver_id"]:
        await callback.answer("Уже взяли", show_alert=True)
        return

    active_orders[order_id]["driver_id"] = driver_id
    await set_driver_free(driver_id, False)
    await increase_driver_orders(driver_id)

    price = active_orders[order_id]["price"]
    phone = active_orders[order_id]["passenger_phone"]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"driver_cancel_{order_id}")]
    ])
    await callback.message.edit_text(callback.message.text + "\n\n✅ Ты взял заказ!", reply_markup=kb)
    await callback.answer("Поехали!")

    free_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я освободился", callback_data=f"driver_free_{driver_id}")]
    ])
    await bot.send_message(
        driver_id,
        f"📞 Пассажир: <b>{phone}</b>\n\nПосле поездки нажми кнопку:",
        reply_markup=free_kb,
        parse_mode="HTML"
    )

    price_text = "Уточнить у водителя" if price is None else f"{price} ₽"

    # Гифка + сообщение пассажиру
    await bot.send_animation(
        order_id,
        animation=DRIVER_FOUND_GIF,
        caption=(
            f"🚗 <b>Водитель уже едет к тебе!</b>\n\n"
            f"👤 {driver['name']}\n"
            f"🚙 {driver['car']} • {driver['color']}\n"
            f"🔢 {driver['number']}\n"
            f"📞 {driver['phone']}\n"
            f"💰 {price_text}"
        ),
        parse_mode="HTML",
        reply_markup=finish_kb()
    )

    for d in await get_free_drivers():
        if d["id"] != driver_id:
            try:
                await bot.send_message(d["id"], "❌ Заказ уже забрали")
            except:
                pass

@dp.callback_query(F.data.startswith("driver_cancel_"))
async def driver_cancel(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    driver_id = callback.from_user.id
    if order_id not in active_orders or active_orders[order_id].get("driver_id") != driver_id:
        await callback.answer("Это не твой заказ", show_alert=True)
        return
    await set_driver_free(driver_id, True)
    active_orders[order_id]["driver_id"] = None
    await callback.message.edit_text(callback.message.text + "\n\n❌ Ты отменил заказ")
    await callback.answer("Отменено")
    try:
        await bot.send_message(order_id, "😔 Водитель отменил заказ. Ищем другого...")
    except:
        pass
    await send_order_to_drivers(order_id)

@dp.callback_query(F.data.startswith("driver_free_"))
async def driver_free(callback: types.CallbackQuery):
    driver_id = int(callback.data.split("_")[2])
    if callback.from_user.id != driver_id:
        await callback.answer("Не твоя кнопка", show_alert=True)
        return
    await set_driver_free(driver_id, True)
    await callback.message.edit_text(callback.message.text + "\n\n✅ Ты снова свободен!")
    await callback.answer("Свободен!")

@dp.callback_query(F.data.startswith("bl_driver_"))
async def bl_driver_cb(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await add_to_blacklist(int(callback.data.split("_")[2]), "driver")
    await callback.answer("Добавлен в ЧС")

@dp.callback_query(F.data.startswith("del_driver_"))
async def del_driver_cb(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM drivers WHERE id = ?", (int(callback.data.split("_")[2]),))
        await db.commit()
    await callback.answer("Удалён")

@dp.message(F.text == "⭐ Оценить поездку")
async def ask_rating(message: types.Message, state: FSMContext):
    await message.answer("⭐ Как тебе поездка? Поставь оценку:", reply_markup=rating_kb())
    await state.set_state(OrderTaxi.waiting_rating)

@dp.message(F.text.in_({"1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "1", "2", "3", "4", "5"}))
async def process_rating(message: types.Message, state: FSMContext):
    text = message.text.strip()
    rating_map = {"1️⃣": 1, "2️⃣": 2, "3️⃣": 3, "4️⃣": 4, "5️⃣": 5}
    rating = rating_map.get(text, int(text) if text.isdigit() else 0)
    if rating not in range(1, 6):
        return

    user_id = message.from_user.id
    driver_id = None
    if user_id in active_orders:
        driver_id = active_orders[user_id].get("driver_id")
        if driver_id:
            await set_driver_free(driver_id, True)
            await add_rating(driver_id, rating)
        del active_orders[user_id]

    if driver_id:
        try:
            await bot.send_message(driver_id, f"⭐ Пассажир поставил тебе {rating}")
        except:
            pass

    if rating == 5:
        gif = RATING_5_GIF
        caption = "🌟 Спасибо большое! Рады, что всё понравилось 💛"
    elif rating == 4:
        gif = RATING_4_GIF
        caption = "🙏 Спасибо за честную оценку, мы будем стараться на 5+"
    else:
        gif = RATING_1_3_GIF
        caption = "🙏 Спасибо за честную оценку!"

    await message.answer_animation(
        animation=gif,
        caption=caption,
        reply_markup=main_kb(user_id)
    )
    await state.clear()
@dp.message(F.text == "🏠 В меню")
async def go_menu(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in active_orders:
        driver_id = active_orders[user_id].get("driver_id")
        if driver_id:
            await set_driver_free(driver_id, True)
        del active_orders[user_id]
    await state.clear()
    await message.answer("🏠 Главное меню", reply_markup=main_kb(user_id))

async def main():
    await init_db()
    print("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())