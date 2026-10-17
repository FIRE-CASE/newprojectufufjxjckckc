import logging
import sqlite3
import sys
import asyncio
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, URLInputFile

# Logging setup
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# BOT TOKEN
BOT_TOKEN = "8928950087:AAGFtUkiRgRZnZgMLNF1EJBKtU20xShhqyw"

# CRYPTO BOT API TOKEN (Get from @CryptoBot on Telegram)
CRYPTO_BOT_TOKEN = "638874:AAVjxZ91qLrkMIl3GFXCvfZvYjr4BlCC6Yq" # Fill in your Crypto Pay API Token

# Default Admin Telegram ID
DEFAULT_ADMIN_ID = 8106424143

# Default images for post categories
DEFAULT_IMAGE_URL = "https://i.postimg.cc/x1bmDmVC/Picsart-26-09-26-09-06-01-420.jpg"
PROFILE_IMAGE_URL = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=1200&q=80"
CATALOG_IMAGE_URL = "https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=1200&q=80"
SUB_IMAGE_URL = "https://images.unsplash.com/photo-1559526324-4b87b5e36e44?auto=format&fit=crop&w=1200&q=80"
ADMIN_IMAGE_URL = "https://images.unsplash.com/photo-1551836022-d5d88e9218df?auto=format&fit=crop&w=1200&q=80"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

def init_db():
    conn = sqlite3.connect("ad_exchange.db")
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            role TEXT DEFAULT 'client', -- client, executor, admin
            balance REAL DEFAULT 0.0,
            rating REAL DEFAULT 5.0,
            reviews_count INTEGER DEFAULT 0,
            commission_rate REAL DEFAULT 10.0,
            tags TEXT DEFAULT '',
            subscription_id INTEGER,
            subscription_expires TEXT,
            deals_left INTEGER DEFAULT 0,
            FOREIGN KEY (subscription_id) REFERENCES subscriptions(id)
        )
    """)
    
    # Subscription plans table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price REAL,
            duration_days INTEGER,
            deals_limit INTEGER
        )
    """)
    
    # Categories and subcategories table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER DEFAULT NULL,
            name TEXT,
            description TEXT,
            tag_slug TEXT,
            FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE CASCADE
        )
    """)
    
    # Orders / Tickets table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            category_id INTEGER,
            title TEXT,
            description TEXT,
            budget REAL,
            status TEXT DEFAULT 'open',
            executor_id INTEGER,
            created_at TEXT
        )
    """)
    
    # Executor Applications table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS executor_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            requested_role TEXT,
            comment TEXT,
            status TEXT DEFAULT 'pending', -- pending, approved, rejected
            created_at TEXT
        )
    """)

    # Reviews table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER,
            executor_id INTEGER,
            client_id INTEGER,
            rating INTEGER,
            comment TEXT
        )
    """)
    
    # CryptoBot Invoices Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crypto_invoices (
            invoice_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            subscription_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'active'
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

def get_db():
    return sqlite3.connect("ad_exchange.db")

def get_user(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    cols = ['user_id', 'username', 'full_name', 'role', 'balance', 'rating', 'reviews_count', 
            'commission_rate', 'tags', 'subscription_id', 'subscription_expires', 'deals_left']
    return dict(zip(cols, row))

def register_user(user_id: int, username: str, full_name: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        role = 'admin' if user_id == DEFAULT_ADMIN_ID else 'client'
        cursor.execute("""
            INSERT INTO users (user_id, username, full_name, role)
            VALUES (?, ?, ?, ?)
        """, (user_id, username or "User", full_name, role))
        conn.commit()
    conn.close()

class AdminStates(StatesGroup):
    waiting_for_sub_name = State()
    waiting_for_sub_price = State()
    waiting_for_sub_days = State()
    waiting_for_sub_deals = State()
    
    waiting_for_cat_parent = State()
    waiting_for_cat_name = State()
    waiting_for_cat_desc = State()
    waiting_for_cat_tag = State()

class ClientStates(StatesGroup):
    entering_title = State()
    entering_desc = State()
    entering_budget = State()

class ExecutorApplicationStates(StatesGroup):
    waiting_for_role = State()
    waiting_for_comment = State()

class ReviewStates(StatesGroup):
    entering_rating = State()
    entering_comment = State()

async def create_crypto_invoice(amount: float, description: str):
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
    payload = {
        "asset": "USDT",
        "amount": str(amount),
        "description": description,
        "paid_btn_name": "openBot",
        "paid_btn_url": "https://t.me/YourBotUsername"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return data["result"]
                else:
                    logger.error(f"CryptoBot Error: {data}")
                    return None
    except Exception as e:
        logger.error(f"Failed to connect to CryptoBot: {e}")
        return None

async def check_crypto_invoice(invoice_id: int):
    url = f"https://pay.crypt.bot/api/getInvoices?invoice_ids={invoice_id}"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                if data.get("ok") and data["result"]["items"]:
                    return data["result"]["items"][0]["status"]
                return None
    except Exception as e:
        logger.error(f"Check invoice error: {e}")
        return None

def main_menu_keyboard(role: str):
    kb = [
        [KeyboardButton(text="📁 Каталог услуг / Заказать"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="💼 Мои заказы / Тикеты")]
    ]
    if role == 'executor':
        kb.append([KeyboardButton(text="📦 Доступные заказы"), KeyboardButton(text="💳 Моя подписка")])
    elif role == 'admin':
        kb.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def admin_menu_keyboard():
    kb = [
        [InlineKeyboardButton(text="📂 Управление каталогом", callback_data="adm_catalog")],
        [InlineKeyboardButton(text="💼 Управление подписками", callback_data="adm_subs")],
        [InlineKeyboardButton(text="📋 Заявки на исполнителя", callback_data="adm_applications")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    register_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    user = get_user(message.from_user.id)
    
    welcome_text = (
        f"👋 <b>Добро пожаловать, {message.from_user.full_name}!</b>\n\n"
        f"Рады видеть вас в нашей авто-бирже рекламы Telegram!\n\n"
        f"🔑 <b>Ваш статус:</b> <code>{user['role'].upper()}</code>\n"
        f"💡 Здесь вы можете заказывать рекламу или зарабатывать, выполняя заказы.\n\n"
        f"Воспользуйтесь меню ниже для перехода по разделам 👇"
    )
    
    await message.answer_photo(
        photo=URLInputFile(DEFAULT_IMAGE_URL),
        caption=welcome_text,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(user['role'])
    )

@dp.message(F.text == "👤 Профиль")
async def profile_handler(message: types.Message):
    user = get_user(message.from_user.id)
    
    sub_info = "❌ Нет активной подписки"
    if user['subscription_id']:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM subscriptions WHERE id = ?", (user['subscription_id'],))
        sub_row = cursor.fetchone()
        conn.close()
        sub_name = sub_row[0] if sub_row else "Неизвестно"
        sub_info = f"<b>{sub_name}</b>\n └ ⏳ Истекает: <code>{user['subscription_expires']}</code>\n └ 📊 Осталось сделок: <code>{user['deals_left']}</code>"

    text = (
        f"👤 <b>Ваш личный профиль</b>\n\n"
        f"🆔 <b>ID:</b> <code>{user['user_id']}</code>\n"
        f"🎭 <b>Роль:</b> <code>{user['role'].upper()}</code>\n"
        f"💰 <b>Баланс:</b> <b>{user['balance']} USDT</b>\n"
        f"⭐ <b>Рейтинг:</b> <b>{user['rating']} / 5.0</b> (Отзывов: {user['reviews_count']})\n"
        f"📈 <b>Комиссия системы:</b> <b>{user['commission_rate']}%</b>\n\n"
        f"📦 <b>Подписка:</b>\n{sub_info}\n"
    )
    
    kb = []
    if user['role'] == 'client':
        kb.append([InlineKeyboardButton(text="📝 Подать заявку на Исполнителя", callback_data="apply_executor")])
        
    await message.answer_photo(
        photo=URLInputFile(PROFILE_IMAGE_URL),
        caption=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None
    )

@dp.message(F.text == "📁 Каталог услуг / Заказать")
async def catalog_handler(message: types.Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM categories WHERE parent_id IS NULL")
    categories = cursor.fetchall()
    conn.close()
    
    if not categories:
        await message.answer("📂 Каталог услуг пока пуст. Администратор еще не добавил разделы.")
        return
        
    kb = []
    for cat_id, cat_name in categories:
        kb.append([InlineKeyboardButton(text=f"📁 {cat_name}", callback_data=f"user_cat_{cat_id}")])
    
    await message.answer_photo(
        photo=URLInputFile(CATALOG_IMAGE_URL),
        caption="📂 <b>Выберите интересующую категорию услуг:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

@dp.callback_query(F.data.startswith("user_cat_"))
async def user_category_view(callback: types.CallbackQuery):
    cat_id = int(callback.data.split("_")[2])
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description, parent_id FROM categories WHERE id = ?", (cat_id,))
    cat = cursor.fetchone()
    
    if not cat:
        conn.close()
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    c_id, name, desc, parent_id = cat
    
    # Fetch subcategories
    cursor.execute("SELECT id, name FROM categories WHERE parent_id = ?", (cat_id,))
    subcategories = cursor.fetchall()
    conn.close()

    text = f"📁 <b>Раздел: {name}</b>\n\n{desc or 'Выберите нужную услугу или подраздел ниже:'}"
    kb = []

    if subcategories:
        for sub_id, sub_name in subcategories:
            kb.append([InlineKeyboardButton(text=f"🔹 {sub_name}", callback_data=f"user_cat_{sub_id}")])
    else:
        # Final leaf category: allow creating a ticket
        kb.append([InlineKeyboardButton(text="📝 Создать заказ в этой категории", callback_data=f"create_ticket_{cat_id}")])

    if parent_id:
        kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"user_cat_{parent_id}")])
    else:
        kb.append([InlineKeyboardButton(text="⬅️ В корневой каталог", callback_data="back_to_catalog_root")])

    await callback.message.edit_caption(
        caption=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

@dp.callback_query(F.data == "back_to_catalog_root")
async def back_to_catalog_root(callback: types.CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM categories WHERE parent_id IS NULL")
    categories = cursor.fetchall()
    conn.close()

    kb = [[InlineKeyboardButton(text=f"📁 {c[1]}", callback_data=f"user_cat_{c[0]}")] for c in categories]
    await callback.message.edit_caption(
        caption="📂 <b>Выберите интересующую категорию услуг:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

@dp.callback_query(F.data.startswith("create_ticket_"))
async def start_create_ticket(callback: types.CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[2])
    await state.update_data(category_id=cat_id)
    await state.set_state(ClientStates.entering_title)
    await callback.message.answer("✍️ <b>Введите заголовок для вашего заказа:</b>", parse_mode="HTML")
    await callback.answer()

@dp.message(ClientStates.entering_title)
async def ticket_title_entered(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(ClientStates.entering_desc)
    await message.answer("📝 <b>Опишите подробнее вашу задачу (требования, дедлайн, ссылки):</b>", parse_mode="HTML")

@dp.message(ClientStates.entering_desc)
async def ticket_desc_entered(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(ClientStates.entering_budget)
    await message.answer("💰 <b>Укажите бюджет заказа в USDT (например: 100):</b>", parse_mode="HTML")

@dp.message(ClientStates.entering_budget)
async def ticket_budget_entered(message: types.Message, state: FSMContext):
    try:
        budget = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное число для бюджета.")
        return
        
    data = await state.get_data()
    cat_id = data['category_id']
    title = data['title']
    description = data['description']
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tickets (client_id, category_id, title, description, budget, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'open', ?)
    """, (message.from_user.id, cat_id, title, description, budget, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ <b>Ваш заказ успешно создан и доступен для исполнителей!</b>", parse_mode="HTML")

@dp.message(F.text == "💼 Мои заказы / Тикеты")
async def my_tickets_handler(message: types.Message):
    user = get_user(message.from_user.id)
    conn = get_db()
    cursor = conn.cursor()
    
    if user['role'] == 'client':
        cursor.execute("SELECT id, title, status, budget, executor_id FROM tickets WHERE client_id = ?", (message.from_user.id,))
    elif user['role'] == 'executor':
        cursor.execute("SELECT id, title, status, budget, client_id FROM tickets WHERE executor_id = ?", (message.from_user.id,))
    else:
        cursor.execute("SELECT id, title, status, budget, client_id FROM tickets")
        
    tickets = cursor.fetchall()
    conn.close()
    
    if not tickets:
        await message.answer("📭 У вас пока нет активных или завершенных заказов.")
        return
        
    for t in tickets:
        t_id, title, status, budget = t[0], t[1], t[2], t[3]
        text = f"📌 <b>Заказ #{t_id}: {title}</b>\nСтатус: <code>{status.upper()}</code>\nБюджет: <b>{budget} USDT</b>"
        
        kb = []
        if user['role'] == 'client' and status == 'in_progress':
            kb.append([InlineKeyboardButton(text="✅ Подтвердить выполнение", callback_data=f"complete_ticket_{t_id}")])
            
        await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None)

@dp.message(F.text == "📦 Доступные заказы")
async def available_tickets_handler(message: types.Message):
    user = get_user(message.from_user.id)
    if user['role'] != 'executor':
        await message.answer("Раздел доступен только исполнителям.")
        return
        
    if not user['subscription_id'] or user['deals_left'] <= 0:
        await message.answer("⚠️ У вас нет активной подписки или исчерпан лимит сделок.")
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, description, budget, created_at FROM tickets WHERE status = 'open'")
    available = cursor.fetchall()
    conn.close()
    
    if not available:
        await message.answer("📭 В данный момент нет открытых заказов.")
        return
        
    for t_id, title, desc, budget, created in available:
        text = (
            f"📌 <b>Заказ #{t_id}: {title}</b>\n\n"
            f"📝 Описание: {desc}\n"
            f"💰 Бюджет: <b>{budget} USDT</b>\n"
            f"🕒 Создан: {created}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤝 Взять заказ в работу", callback_data=f"take_ticket_{t_id}")]
        ])
        await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("take_ticket_"))
async def take_ticket_callback(callback: types.CallbackQuery):
    t_id = int(callback.data.split("_")[2])
    user = get_user(callback.from_user.id)
    
    if user['deals_left'] <= 0:
        await callback.answer("У вас исчерпан лимит сделок по подписке!", show_alert=True)
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT status, client_id FROM tickets WHERE id = ?", (t_id,))
    ticket = cursor.fetchone()
    
    if not ticket or ticket[0] != 'open':
        conn.close()
        await callback.answer("Заказ уже недоступен.", show_alert=True)
        return
        
    client_id = ticket[1]
    cursor.execute("UPDATE tickets SET status = 'in_progress', executor_id = ? WHERE id = ?", (callback.from_user.id, t_id))
    cursor.execute("UPDATE users SET deals_left = deals_left - 1 WHERE user_id = ?", (callback.from_user.id,))
    conn.commit()
    conn.close()
    
    await callback.message.edit_text(f"✅ Вы успешно взяли заказ #{t_id} в работу!")
    try:
        await bot.send_message(client_id, f"🎉 Ваш заказ #{t_id} взят в работу исполнителем!")
    except Exception:
        pass

@dp.callback_query(F.data.startswith("complete_ticket_"))
async def complete_ticket_callback(callback: types.CallbackQuery, state: FSMContext):
    t_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT executor_id, budget FROM tickets WHERE id = ? AND client_id = ?", (t_id, callback.from_user.id))
    ticket = cursor.fetchone()
    
    if not ticket:
        conn.close()
        await callback.answer("Заказ не найден.", show_alert=True)
        return
        
    exec_id, budget = ticket
    cursor.execute("UPDATE tickets SET status = 'completed' WHERE id = ?", (t_id,))
    
    cursor.execute("SELECT commission_rate FROM users WHERE user_id = ?", (exec_id,))
    comm_row = cursor.fetchone()
    comm_rate = comm_row[0] if comm_row else 10.0
    
    payout = budget * (1 - comm_rate / 100.0)
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (payout, exec_id))
    conn.commit()
    conn.close()
    
    await state.update_data(review_executor_id=exec_id, review_ticket_id=t_id)
    await state.set_state(ReviewStates.entering_rating)
    await callback.message.answer("✅ <b>Заказ выполнен! Оцените работу исполнителя (от 1 до 5):</b>", parse_mode="HTML")

@dp.message(ReviewStates.entering_rating)
async def review_rating_entered(message: types.Message, state: FSMContext):
    try:
        rating = int(message.text)
        if not (1 <= rating <= 5):
            raise ValueError()
    except ValueError:
        await message.answer("Пожалуйста, введите число от 1 до 5.")
        return
        
    await state.update_data(rating=rating)
    await state.set_state(ReviewStates.entering_comment)
    await message.answer("✍️ <b>Напишите ваш отзыв об исполнителе:</b>", parse_mode="HTML")

@dp.message(ReviewStates.entering_comment)
async def review_comment_entered(message: types.Message, state: FSMContext):
    comment = message.text
    data = await state.get_data()
    exec_id = data['review_executor_id']
    t_id = data['review_ticket_id']
    rating = data['rating']
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reviews (ticket_id, executor_id, client_id, rating, comment)
        VALUES (?, ?, ?, ?, ?)
    """, (t_id, exec_id, message.from_user.id, rating, comment))
    
    cursor.execute("SELECT rating, reviews_count FROM users WHERE user_id = ?", (exec_id,))
    user_row = cursor.fetchone()
    if user_row:
        current_rating, count = user_row
        new_count = count + 1
        new_rating = round(((current_rating * count) + rating) / new_count, 2)
        cursor.execute("UPDATE users SET rating = ?, reviews_count = ? WHERE user_id = ?", (new_rating, new_count, exec_id))
        
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("⭐ <b>Спасибо за отзыв!</b>", parse_mode="HTML")

@dp.message(F.text == "💳 Моя подписка")
async def my_subscription_handler(message: types.Message):
    user = get_user(message.from_user.id)
    if user['role'] != 'executor':
        await message.answer("Раздел подписок доступен только исполнителям.")
        return

    sub_info = "❌ Нет активной подписки."
    if user['subscription_id']:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM subscriptions WHERE id = ?", (user['subscription_id'],))
        sub_row = cursor.fetchone()
        conn.close()
        sub_name = sub_row[0] if sub_row else "Тариф"
        sub_info = (
            f"✅ <b>Текущий активный тариф: {sub_name}</b>\n"
            f"⏳ <b>Действительна до:</b> <code>{user['subscription_expires']}</code>\n"
            f"📊 <b>Осталось доступных сделок:</b> <code>{user['deals_left']}</code>\n"
        )

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, duration_days, deals_limit FROM subscriptions")
    subs = cursor.fetchall()
    conn.close()

    text = f"💳 <b>Информация о подписке:</b>\n\n{sub_info}\n\n👇 <b>Выберите тариф для покупки/продления через CryptoBot:</b>"
    kb = [[InlineKeyboardButton(text=f"💎 {name} - {price} USDT ({days} дн. / {deals} сделок)", callback_data=f"buy_crypto_{s_id}")] for s_id, name, price, days, deals in subs]

    await message.answer_photo(
        photo=URLInputFile(SUB_IMAGE_URL),
        caption=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None
    )

@dp.message(F.text == "⚙️ Админ-панель")
async def admin_panel(message: types.Message):
    user = get_user(message.from_user.id)
    if not user or user['role'] != 'admin':
        await message.answer("Отказано в доступе.")
        return
        
    await message.answer_photo(
        photo=URLInputFile(ADMIN_IMAGE_URL),
        caption="⚙️ <b>Панель управления администратора:</b>",
        parse_mode="HTML",
        reply_markup=admin_menu_keyboard()
    )

@dp.callback_query(F.data == "adm_catalog")
async def adm_catalog_view(callback: types.CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, parent_id FROM categories")
    cats = cursor.fetchall()
    conn.close()
    
    text = "📂 <b>Структура каталога:</b>\n\n"
    if not cats:
        text += "Каталог пуст."
    else:
        for c_id, name, parent in cats:
            prefix = " └ 🔹 " if parent else "📁 "
            text += f"{prefix}#{c_id} <b>{name}</b>\n"
            
    kb = [
        [InlineKeyboardButton(text="➕ Добавить раздел / подраздел", callback_data="add_cat_start")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]
    ]
    await callback.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: types.CallbackQuery):
    await callback.message.edit_caption(
        caption="⚙️ <b>Панель управления администратора:</b>",
        parse_mode="HTML",
        reply_markup=admin_menu_keyboard()
    )

async def main():
    print("🚀 Bot started successfully with all fixes applied!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
```
