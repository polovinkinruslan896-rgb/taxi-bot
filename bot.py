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

TOKEN = os.getenv("TOKEN") or "8866234378:AAEiOj8fN9k-jdS7F-FFnZZIddr-Ms2YxPM"
ADMIN_ID = 7165265831
DB_NAME = "taxi.db"

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
                free INTEGER DEFAULT 1, orders_today INTEGER DEFAULT 0,
                total_rating REAL DEFAULT 0, rating_count INTEGER DEFAULT 0, last_date TEXT
            )""")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS passengers (
                id INTEGER PRIMARY KEY, name TEXT, phone TEXT, orders_count INTEGER DEFAULT 0
            )""")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id INTEGER PRIMARY KEY, type TEXT, reason TEXT, added_date TEXT
            )""")
        await db.commit()

        cursor = await db.execute("SELECT COUNT(*) FROM drivers")
        if (await cursor.fetchone())[0] == 0:
            defaults = [
                (7165265831, "Investor", "+79277511560", "Mercedes-Benz G-Класс AMG", "чёрный", "А001АА 63"),
                (111111111, "Алексей", "+79001112233", "Kia Rio", "белый", "А123БВ 63"),
                (222222222, "Дмитрий", "+79002223344", "Hyundai Solaris", "серый", "В456ГД 63"),
            ]
            for d in defaults:
                await db.execute(
                    "INSERT INTO drivers (id, name, phone, car, color, number, free, orders_today, total_rating, rating_count, last_date) VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0, 0, ?)",
                    (*d, datetime.now().strftime("%Y-%m-%d"))
                )
            await db.commit()

async def is_blacklisted(user_id: int, type_: str = None) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        if type_:
            cur = await db.execute("SELECT 1 FROM blacklist WHERE user_id = ? AND type = ?", (user_id, type_))
        else:
            cur = await db.execute("SELECT 1 FROM blacklist WHERE user_id = ?", (user_id,))
        return await cur.fetchone() is not None

async def get_passenger(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM passengers WHERE id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def save_or_update_passenger(user_id: int, name: str, phone: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        existing = await get_passenger(user_id)
        if existing:
            if phone:
                await db.execute("UPDATE passengers SET name=?, phone=?, orders_count=orders_count+1 WHERE id=?", (name, phone, user_id))
            else:
                await db.execute("UPDATE passengers SET name=?, orders_count=orders_count+1 WHERE id=?", (name, user_id))
        else:
            await db.execute("INSERT INTO passengers (id, name, phone, orders_count) VALUES (?, ?, ?, 1)", (user_id, name, phone or ""))
        await db.commit()

async def get_all_passengers():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM passengers ORDER BY orders_count DESC")
        return [dict(r) for r in await cur.fetchall()]

async def get_free_drivers():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM drivers WHERE free = 1")
        drivers = [dict(r) for r in await cur.fetchall()]
        return [d for d in drivers if not await is_blacklisted(d["id"], "driver")]

async def get_driver(driver_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def get_all_drivers():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM drivers")
        drivers = [dict(r) for r in await cur.fetchall()]
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
            UPDATE drivers SET orders_today = CASE WHEN last_date = ? THEN orders_today + 1 ELSE 1 END, last_date = ? WHERE id = ?
        """, (today, today, driver_id))
        await db.commit()

async def add_rating(driver_id: int, rating: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE drivers SET total_rating = total_rating + ?, rating_count = rating_count + 1 WHERE id = ?", (rating, driver_id))
        await db.commit()

async def add_to_blacklist(user_id: int, type_: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO blacklist (user_id, type, reason, added_date) VALUES (?, ?, '', ?)",
                         (user_id, type_, datetime.now().strftime("%Y-%m-%d")))
        await db.commit()

async def remove_from_blacklist(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_blacklist(type_: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        if type_:
            cur = await db.execute("SELECT * FROM blacklist WHERE type = ?", (type_,))
        else:
            cur = await db.execute("SELECT * FROM blacklist")
        return [dict(r) for r in await cur.fetchall()]

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
    kb = [[KeyboardButton(text="🚕 Заказать такси")]]
    if user_id == ADMIN_ID:
        kb.append([KeyboardButton(text="🛠 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Водители")],
        [KeyboardButton(text="👤 Пассажиры"), KeyboardButton(text="🚫 Чёрный список")],
        [KeyboardButton(text="➕ Добавить водителя")],
        [KeyboardButton(text="◀️ Назад")]
    ], resize_keyboard=True)

def blacklist_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🚫 Пассажиры в ЧС"), KeyboardButton(text="🚫 Водители в ЧС")],
        [KeyboardButton(text="➕ Добавить в ЧС"), KeyboardButton(text="➖ Убрать из ЧС")],
        [KeyboardButton(text="◀️ Назад в админку")]
    ], resize_keyboard=True)

def village_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Богатое")],
        [KeyboardButton(text="Другое")],
        [KeyboardButton(text="❌ Отменить")]
    ], resize_keyboard=True)

def other_villages_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Аверьяновка"), KeyboardButton(text="Арзамасовка")],
        [KeyboardButton(text="Беловка"), KeyboardButton(text="Другое")],
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
        [KeyboardButton(text="✅ Верно")],
        [KeyboardButton(text="✏️ Изменить")]
    ], resize_keyboard=True)

def searching_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отменить заказ")]], resize_keyboard=True)

def finish_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⭐ Оценить заказ")],
        [KeyboardButton(text="🏠 Меню")]
    ], resize_keyboard=True)

def rating_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="1"), KeyboardButton(text="2"), KeyboardButton(text="3")],
        [KeyboardButton(text="4"), KeyboardButton(text="5")]
    ], resize_keyboard=True)

# ================== КОМАНДЫ ==================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if await is_blacklisted(message.from_user.id, "passenger"):
        await message.answer("🚫 Вы в чёрном списке. Заказ невозможен.")
        return
    await message.answer("👋 Добро пожаловать!\nЯ бот такси села Богатое.", reply_markup=main_kb(message.from_user.id))

@dp.message(Command("free"))
async def cmd_free(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await free_all_drivers()
    await message.answer("✅ Все водители освобождены")

# ================== АДМИН ==================
@dp.message(F.text == "🛠 Админ-панель")
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛠 Админ-панель", reply_markup=admin_kb())

@dp.message(F.text == "◀️ Назад")
async def admin_back(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Главное меню", reply_markup=main_kb(ADMIN_ID))

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    drivers = await get_all_drivers()
    total = sum(d["orders_today"] for d in drivers)
    text = f"📊 <b>Статистика</b>\n\nВсего заказов: <b>{total}</b>\n\n"
    for d in drivers:
        avg = round(d["total_rating"] / d["rating_count"], 1) if d["rating_count"] else "—"
        text += f"• {d['name']}: {d['orders_today']} | ⭐ {avg}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "👥 Водители")
async def admin_drivers(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    drivers = await get_all_drivers()
    if not drivers:
        await message.answer("Активных водителей нет")
        return
    for d in drivers:
        avg = round(d["total_rating"] / d["rating_count"], 1) if d["rating_count"] else "нет"
        status = "🟢 Свободен" if d["free"] else "🔴 Занят"
        text = f"👤 <b>{d['name']}</b>\n{status}\n🚗 {d['car']} | {d['color']}\n🔢 {d['number']}\n📞 {d['phone']}\n📦 {d['orders_today']} | ⭐ {avg}"
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
    if not passengers:
        await message.answer("Пассажиров пока нет")
        return

    text = "👤 <b>Пассажиры</b>\n\n"
    shown = 0
    for p in passengers:
        # Не показываем тех, кто в ЧС
        if await is_blacklisted(p["id"], "passenger"):
            continue
        text += (
            f"• <b>{p['name']}</b>\n"
            f"  📞 {p['phone'] or 'нет'}\n"
            f"  📦 Заказов: {p['orders_count']}\n"
            f"  ID: <code>{p['id']}</code>\n\n"
        )
        shown += 1

    if shown == 0:
        await message.answer("Нет активных пассажиров")
    else:
        await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "➕ Добавить водителя")
async def admin_add_driver(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Формат:\n<code>ID | Имя | Телефон | Машина | Цвет | Номер</code>", parse_mode="HTML")
    await state.set_state(AdminState.waiting_driver_data)

@dp.message(AdminState.waiting_driver_data)
async def process_new_driver(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
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
        await message.answer(f"✅ {name} добавлен", reply_markup=admin_kb())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()

@dp.message(F.text == "🚫 Чёрный список")
async def admin_blacklist(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🚫 Чёрный список", reply_markup=blacklist_kb())

@dp.message(F.text == "◀️ Назад в админку")
async def back_to_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛠 Админ-панель", reply_markup=admin_kb())

@dp.message(F.text == "🚫 Пассажиры в ЧС")
async def bl_passengers(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    items = await get_blacklist("passenger")
    text = "🚫 Пассажиры в ЧС:\n\n" + ("\n".join(f"• <code>{i['user_id']}</code>" for i in items) if items else "Пусто")
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "🚫 Водители в ЧС")
async def bl_drivers(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    items = await get_blacklist("driver")
    text = "🚫 Водители в ЧС:\n\n" + ("\n".join(f"• <code>{i['user_id']}</code>" for i in items) if items else "Пусто")
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "➕ Добавить в ЧС")
async def bl_add(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Формат: <code>ID passenger</code> или <code>ID driver</code>", parse_mode="HTML")
    await state.set_state(AdminState.waiting_blacklist_id)

@dp.message(AdminState.waiting_blacklist_id)
async def process_blacklist_add(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.strip().lower().split()
        await add_to_blacklist(int(parts[0]), parts[1])
        await message.answer("✅ Добавлен в ЧС", reply_markup=blacklist_kb())
    except:
        await message.answer("❌ Неверный формат")
    await state.clear()

@dp.message(F.text == "➖ Убрать из ЧС")
async def bl_remove(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Отправьте только ID:")
    await state.set_state(AdminState.waiting_blacklist_remove)

@dp.message(AdminState.waiting_blacklist_remove)
async def process_blacklist_remove(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try:
        await remove_from_blacklist(int(message.text.strip()))
        await message.answer("✅ Убран из ЧС", reply_markup=blacklist_kb())
    except:
        await message.answer("❌ Нужен только ID")
    await state.clear()

# ================== ЗАКАЗ ==================
@dp.message(F.text == "🚕 Заказать такси")
async def start_order(message: types.Message, state: FSMContext):
    # Жёсткая проверка
    if await is_blacklisted(message.from_user.id, "passenger"):
        await state.clear()
        await message.answer("🚫 Вы находитесь в чёрном списке. Заказ невозможен.")
        return

    await state.clear()
    await message.answer("📍 Откуда вас забрать?", reply_markup=village_kb())
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
    await message.answer("❌ Заказ отменён", reply_markup=main_kb(user_id))

@dp.message(OrderTaxi.choosing_village, F.text == "Богатое")
async def village_bogatoe(message: types.Message, state: FSMContext):
    await state.update_data(village="Богатое")
    await message.answer("🛣 Откуда забрать (улица и дом):", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_street)

@dp.message(OrderTaxi.choosing_village, F.text == "Другое")
async def village_other(message: types.Message, state: FSMContext):
    await message.answer("📍 Выберите село:", reply_markup=other_villages_kb())
    await state.set_state(OrderTaxi.choosing_other_village)

@dp.message(OrderTaxi.choosing_other_village, F.text.in_({"Аверьяновка", "Арзамасовка", "Беловка"}))
async def other_village_selected(message: types.Message, state: FSMContext):
    await state.update_data(village=message.text)
    await message.answer("🛣 Откуда забрать (улица и дом):", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_street)

@dp.message(OrderTaxi.choosing_other_village, F.text == "Другое")
async def other_village_custom(message: types.Message, state: FSMContext):
    await message.answer("📍 Напишите название села:", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_custom_village)

@dp.message(OrderTaxi.waiting_custom_village)
async def custom_village_input(message: types.Message, state: FSMContext):
    if message.text in {"❌ Отменить", "❌ Отменить заказ"}:
        await cancel_any(message, state)
        return
    await state.update_data(village=message.text.strip())
    await message.answer("🛣 Откуда забрать (улица и дом):", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_street)

@dp.message(OrderTaxi.waiting_street)
async def process_street(message: types.Message, state: FSMContext):
    if message.text in {"❌ Отменить", "❌ Отменить заказ"}:
        await cancel_any(message, state)
        return

    await state.update_data(street=message.text.strip())
    await message.answer("🏁 Куда поедем? (улица и дом):", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_destination)

@dp.message(OrderTaxi.waiting_destination)
async def process_destination(message: types.Message, state: FSMContext):
    if message.text in {"❌ Отменить", "❌ Отменить заказ"}:
        await cancel_any(message, state)
        return

    await state.update_data(destination=message.text.strip())

    # Проверяем, есть ли уже сохранённый номер
    passenger = await get_passenger(message.from_user.id)
    if passenger and passenger.get("phone"):
        await state.update_data(phone=passenger["phone"])
        await show_confirmation(message, state)
    else:
        await message.answer(
            "📱 Укажите номер телефона\n"
            "Можно написать вручную или нажать кнопку «Отправить номер»",
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
        f"📍 <b>Проверьте адрес</b>\n\n"
        f"🚏 Откуда: <b>{data.get('village')}, {data.get('street')}</b>\n"
        f"🏁 Куда: <b>{data.get('destination')}</b>\n\n"
        f"Всё верно?"
    )
    await message.answer(text, reply_markup=confirm_kb(), parse_mode="HTML")
    await state.set_state(OrderTaxi.confirming_address)

@dp.message(OrderTaxi.confirming_address, F.text == "✅ Верно")

async def confirm_address(message: types.Message, state: FSMContext):
    if await is_blacklisted(message.from_user.id, "passenger"):
        await state.clear()
        await message.answer("🚫 Вы находитесь в чёрном списке. Заказ невозможен.")
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
        "village": village, "street": street, "destination": destination,
        "passenger_name": user.full_name, "passenger_phone": phone,
        "driver_id": None, "price": price
    }

    price_text = "Уточнить у водителя" if price is None else f"{price} ₽"
    summary = (
        f"✅ <b>Заказ принят</b>\n\n"
        f"🏘 {village}\n"
        f"🛣 {street}\n"
        f"🏁 {destination}\n"
        f"💰 {price_text}\n\n"
        f"⏳ Ищем машину..."
    )
    await message.answer(summary, reply_markup=searching_kb(), parse_mode="HTML")
    await state.set_state(OrderTaxi.searching)
    await send_order_to_drivers(order_id)

@dp.message(OrderTaxi.confirming_address, F.text == "✏️ Изменить")
async def change_address(message: types.Message, state: FSMContext):
    await message.answer("🛣 Откуда забрать (улица и дом):", reply_markup=cancel_kb())
    await state.set_state(OrderTaxi.waiting_street)

async def send_order_to_drivers(order_id: int):
    if order_id not in active_orders:
        return
    order = active_orders[order_id]
    free_drivers = await get_free_drivers()

    if not free_drivers:
        try:
            await bot.send_message(order_id, "😔 Сейчас нет свободных машин", reply_markup=main_kb(order_id))
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
        except:
            pass

@dp.callback_query(F.data.startswith("take_"))
async def take_order(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    driver_id = callback.from_user.id

    if await is_blacklisted(driver_id, "driver"):
        await callback.answer("Вы в чёрном списке", show_alert=True)
        return
    if order_id not in active_orders:
        await callback.answer("Заказ недоступен", show_alert=True)
        return
    driver = await get_driver(driver_id)
    if not driver or not driver["free"]:
        await callback.answer("Вы уже заняты", show_alert=True)
        return
    if active_orders[order_id]["driver_id"]:
        await callback.answer("Заказ уже взят", show_alert=True)
        return

    active_orders[order_id]["driver_id"] = driver_id
    await set_driver_free(driver_id, False)
    await increase_driver_orders(driver_id)

    price = active_orders[order_id]["price"]
    phone = active_orders[order_id]["passenger_phone"]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"driver_cancel_{order_id}")]
    ])
    await callback.message.edit_text(callback.message.text + "\n\n✅ Вы взяли заказ", reply_markup=kb)
    await callback.answer("Заказ ваш!")

    free_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я освободился", callback_data=f"driver_free_{driver_id}")]
    ])
    await bot.send_message(driver_id, f"📞 Пассажир: <b>{phone}</b>\n\nПосле поездки нажмите кнопку:", reply_markup=free_kb, parse_mode="HTML")

    price_text = "Уточнить у водителя" if price is None else f"{price} ₽"
    text = (
        f"🚗 <b>Водитель найден</b>\n\n"
        f"👤 {driver['name']}\n"
        f"🚙 {driver['car']} | {driver['color']}\n"
        f"🔢 {driver['number']}\n"
        f"📞 {driver['phone']}\n"
        f"💰 {price_text}"
    )
    await bot.send_message(order_id, text, reply_markup=finish_kb(), parse_mode="HTML")

    for d in await get_free_drivers():
        if d["id"] != driver_id:
            try:
                await bot.send_message(d["id"], "❌ Заказ уже взят")
            except:
                pass

@dp.callback_query(F.data.startswith("driver_cancel_"))
async def driver_cancel(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    driver_id = callback.from_user.id
    if order_id not in active_orders or active_orders[order_id].get("driver_id") != driver_id:
        await callback.answer("Это не ваш заказ", show_alert=True)
        return
    await set_driver_free(driver_id, True)
    active_orders[order_id]["driver_id"] = None
    await callback.message.edit_text(callback.message.text + "\n\n❌ Вы отменили заказ")
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
        await callback.answer("Не ваша кнопка", show_alert=True)
        return
    await set_driver_free(driver_id, True)
    await callback.message.edit_text(callback.message.text + "\n\n✅ Вы снова свободны")
    await callback.answer("Свободны!")

@dp.callback_query(F.data.startswith("bl_driver_"))
async def bl_driver_cb(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    driver_id = int(callback.data.split("_")[2])
    await add_to_blacklist(driver_id, "driver")
    await callback.answer("Добавлен в ЧС")

@dp.callback_query(F.data.startswith("del_driver_"))
async def del_driver_cb(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    driver_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM drivers WHERE id = ?", (driver_id,))
        await db.commit()
    await callback.answer("Удалён")

@dp.message(F.text == "⭐ Оценить заказ")
async def ask_rating(message: types.Message, state: FSMContext):
    await message.answer("⭐ Оцените от 1 до 5:", reply_markup=rating_kb())
    await state.set_state(OrderTaxi.waiting_rating)

@dp.message(F.text.in_({"1", "2", "3", "4", "5"}))
async def process_rating(message: types.Message, state: FSMContext):
    rating = int(message.text)
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
            await bot.send_message(driver_id, f"⭐ Вам поставили {rating}")
        except:
            pass

    if rating == 5:
        text = "🌟 Спасибо за высокую оценку!"
    elif rating == 4:
        text = "👍 Спасибо! Будем стараться на 5+"
    elif rating == 3:
        text = "👍 Спасибо! Будем стараться на 5+"
    elif rating == 2:
        text = "👍 Спасибо за честность! Будем стараться на 5+"
    elif rating == 1:
        text = "👍 Спасибо за честность! Будем стараться на 5+"
    else:
        text = "🙏 Спасибо за оценку"

    await message.answer(text, reply_markup=main_kb(user_id))
    await state.clear()

@dp.message(F.text == "🏠 Меню")
async def go_menu(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in active_orders:
        driver_id = active_orders[user_id].get("driver_id")
        if driver_id:
            await set_driver_free(driver_id, True)
        del active_orders[user_id]
    await state.clear()
    await message.answer("Главное меню", reply_markup=main_kb(user_id))

async def main():
    await init_db()
    print("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())