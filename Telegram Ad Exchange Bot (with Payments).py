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

# CRYPTO BOT API TOKEN
CRYPTO_BOT_TOKEN = "638874:AAVjxZ91qLrkMIl3GFXCvfZvYjr4BlCC6Yq"

# Default Admin Telegram ID
DEFAULT_ADMIN_ID = 8106424143

# Default images for post categories
DEFAULT_IMAGE_URL = "https://i.postimg.cc/x1bmDmVC/Picsart-26-09-26-09-06-01-420.jpg"
PROFILE_IMAGE_URL = "https://i.postimg.cc/x1bmDmVC/Picsart-26-09-26-09-06-01-420.jpg"
CATALOG_IMAGE_URL = "https://i.postimg.cc/x1bmDmVC/Picsart-26-09-26-09-06-01-420.jpg"
SUB_IMAGE_URL = "https://i.postimg.cc/x1bmDmVC/Picsart-26-09-26-09-06-01-420.jpg"
ADMIN_IMAGE_URL = "https://i.postimg.cc/x1bmDmVC/Picsart-26-09-26-09-06-01-420.jpg"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

def init_db():
    conn = sqlite3.connect("ad_exchange.db")
    cursor = conn.cursor()
    
    # System settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('default_commission', '10.0')")
    
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
            commission_discount REAL DEFAULT 0.0
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
    
    # Executor Listings (Goods / Services published by executors) table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS executor_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            executor_id INTEGER,
            category_id INTEGER,
            title TEXT,
            description TEXT,
            price REAL,
            status TEXT DEFAULT 'pending', -- pending, active, rejected
            created_at TEXT,
            FOREIGN KEY (executor_id) REFERENCES users(user_id),
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
        )
    """)
    
    # Orders / Tickets table (unified for custom tickets and purchased listings)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            category_id INTEGER,
            title TEXT,
            description TEXT,
            budget REAL,
            status TEXT DEFAULT 'open', -- open, in_progress, completed, cancelled
            executor_id INTEGER,
            listing_id INTEGER DEFAULT NULL,
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
            type TEXT, -- 'subscription' or 'deposit'
            target_id INTEGER DEFAULT 0,
            amount REAL,
            status TEXT DEFAULT 'active'
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

def get_db():
    return sqlite3.connect("ad_exchange.db")

def get_setting(key: str, default: str = "0"):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    cols = ['user_id', 'username', 'full_name', 'role', 'balance', 'rating', 'reviews_count', 
            'commission_rate', 'tags', 'subscription_id', 'subscription_expires']
    return dict(zip(cols, row))

def register_user(user_id: int, username: str, full_name: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        role = 'admin' if user_id == DEFAULT_ADMIN_ID else 'client'
        def_comm = float(get_setting("default_commission", "10.0"))
        cursor.execute("""
            INSERT INTO users (user_id, username, full_name, role, commission_rate)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username or "User", full_name, role, def_comm))
        conn.commit()
    conn.close()

class AdminStates(StatesGroup):
    waiting_for_sub_name = State()
    waiting_for_sub_price = State()
    waiting_for_sub_days = State()
    waiting_for_sub_comm = State()
    
    waiting_for_cat_parent = State()
    waiting_for_cat_name = State()
    waiting_for_cat_desc = State()
    waiting_for_cat_tag = State()

    waiting_for_global_comm = State()
    
    waiting_for_give_balance_uid = State()
    waiting_for_give_balance_amount = State()

class ClientStates(StatesGroup):
    entering_title = State()
    entering_desc = State()
    entering_budget = State()

class ListingStates(StatesGroup):
    choosing_category = State()
    entering_title = State()
    entering_desc = State()
    entering_price = State()

class DepositStates(StatesGroup):
    entering_deposit_amount = State()

class WithdrawStates(StatesGroup):
    entering_withdraw_amount = State()

class ExecutorApplicationStates(StatesGroup):
    waiting_for_role = State()
    waiting_for_comment = State()

class ReviewStates(StatesGroup):
    entering_rating = State()
    entering_comment = State()

class ChatStates(StatesGroup):
    in_chat = State()

async def create_crypto_invoice(amount: float, description: str):
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
    payload = {
        "asset": "USDT",
        "amount": str(amount),
        "description": description,
        "paid_btn_name": "openBot",
        "paid_btn_url": "https://t.me/"
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

async def transfer_crypto_user(user_telegram_id: int, amount: float):
    url = "https://pay.crypt.bot/api/transfer"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
    payload = {
        "user_id": user_telegram_id,
        "asset": "USDT",
        "amount": str(amount),
        "spend_id": f"withdraw_{user_telegram_id}_{int(datetime.now().timestamp())}"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json()
                return data
    except Exception as e:
        logger.error(f"Transfer CryptoBot Error: {e}")
        return None

def main_menu_keyboard(role: str):
    kb = [
        [KeyboardButton(text="📁 Каталог услуг / Заказать"), KeyboardButton(text="👤 Профиль")]
    ]
    if role in ('executor', 'admin'):
        kb.append([KeyboardButton(text="💼 Мои заказы / Тикеты")])
        
    if role == 'executor':
        kb.append([KeyboardButton(text="📦 Мои товары/услуги"), KeyboardButton(text="➕ Опубликовать услугу")])
        kb.append([KeyboardButton(text="📦 Доступные заказы"), KeyboardButton(text="💳 Моя подписка")])
    elif role == 'admin':
        kb.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def admin_menu_keyboard():
    kb = [
        [InlineKeyboardButton(text="📂 Управление каталогом", callback_data="adm_catalog")],
        [InlineKeyboardButton(text="🛍 Модерация товаров", callback_data="adm_listings")],
        [InlineKeyboardButton(text="💼 Управление подписками", callback_data="adm_subs")],
        [InlineKeyboardButton(text="📊 Настройка комиссий", callback_data="adm_commissions")],
        [InlineKeyboardButton(text="💰 Выдать / Списать баланс", callback_data="adm_give_balance")],
        [InlineKeyboardButton(text="📋 Заявки на исполнителя", callback_data="adm_applications")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
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
    effective_comm = user['commission_rate']
    
    if user['subscription_id']:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name, commission_discount FROM subscriptions WHERE id = ?", (user['subscription_id'],))
        sub_row = cursor.fetchone()
        conn.close()
        if sub_row:
            sub_name, comm_disc = sub_row
            sub_info = f"<b>{sub_name}</b>\n └ ⏳ Истекает: <code>{user['subscription_expires']}</code>"
            effective_comm = comm_disc

    text = (
        f"👤 <b>Ваш личный профиль</b>\n\n"
        f"🆔 <b>ID:</b> <code>{user['user_id']}</code>\n"
        f"🎭 <b>Роль:</b> <code>{user['role'].upper()}</code>\n"
        f"💰 <b>Баланс:</b> <b>{user['balance']:.2f} USDT</b>\n"
        f"⭐ <b>Рейтинг:</b> <b>{user['rating']} / 5.0</b> (Отзывов: {user['reviews_count']})\n"
        f"📈 <b>Комиссия системы:</b> <b>{effective_comm}%</b>\n\n"
        f"📦 <b>Подписка:</b>\n{sub_info}\n"
    )
    
    kb = [
        [InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="deposit_balance"), InlineKeyboardButton(text="💸 Вывести средства", callback_data="withdraw_balance")]
    ]
    if user['role'] == 'client':
        kb.append([InlineKeyboardButton(text="📝 Подать заявку на Исполнителя", callback_data="apply_executor")])
        
    await message.answer_photo(
        photo=URLInputFile(PROFILE_IMAGE_URL),
        caption=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

@dp.callback_query(F.data == "deposit_balance")
async def deposit_balance_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(DepositStates.entering_deposit_amount)
    await callback.message.answer("💳 <b>Введите сумму пополнения в USDT (например: 50):</b>", parse_mode="HTML")
    await callback.answer()

@dp.message(DepositStates.entering_deposit_amount)
async def deposit_amount_entered(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError()
    except ValueError:
        await message.answer("❌ Введите корректное положительное число.")
        return
        
    invoice = await create_crypto_invoice(amount, f"Пополнение баланса пользователя {message.from_user.id}")
    if not invoice:
        await message.answer("❌ Ошибка создания счета CryptoBot.")
        await state.clear()
        return
        
    inv_id = invoice['invoice_id']
    pay_url = invoice['bot_invoice_url']
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO crypto_invoices (invoice_id, user_id, type, amount, status)
        VALUES (?, ?, 'deposit', ?, 'active')
    """, (inv_id, message.from_user.id, amount))
    conn.commit()
    conn.close()
    
    await state.clear()
    kb = [
        [InlineKeyboardButton(text="🔗 Оплатить через CryptoBot", url=pay_url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_inv_{inv_id}")]
    ]
    await message.answer(f"🧾 <b>Счет на пополнение баланса создан!</b>\n\nСумма: <b>{amount} USDT</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "withdraw_balance")
async def withdraw_balance_start(callback: types.CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    if user['balance'] <= 0:
        await callback.answer("❌ На вашем балансе нет средств для вывода.", show_alert=True)
        return
        
    await state.set_state(WithdrawStates.entering_withdraw_amount)
    await callback.message.answer(f"💸 <b>Доступно к выводу: {user['balance']:.2f} USDT</b>\n\nВведите сумму вывода на ваш CryptoBot:", parse_mode="HTML")
    await callback.answer()

@dp.message(WithdrawStates.entering_withdraw_amount)
async def withdraw_amount_entered(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError()
    except ValueError:
        await message.answer("❌ Введите корректное число.")
        return
        
    user = get_user(message.from_user.id)
    if amount > user['balance']:
        await message.answer("❌ Недостаточно средств на балансе.")
        return
        
    res = await transfer_crypto_user(message.from_user.id, amount)
    if res and res.get("ok"):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, message.from_user.id))
        conn.commit()
        conn.close()
        await message.answer(f"✅ <b>Успешно переведено {amount} USDT на ваш аккаунт CryptoBot!</b>", parse_mode="HTML")
    else:
        err_msg = res.get("error", {}).get("name", "Unknown error") if res else "Connection error"
        await message.answer(f"⚠️ Ошибка автоматического вывода CryptoBot ({err_msg}). Запрос передан администратору.")
        
    await state.clear()

@dp.callback_query(F.data == "apply_executor")
async def start_executor_application(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ExecutorApplicationStates.waiting_for_role)
    await callback.message.answer("📝 <b>Укажите желаемую специализацию / роль (например: Блогер, Таргетолог):</b>", parse_mode="HTML")
    await callback.answer()

@dp.message(ExecutorApplicationStates.waiting_for_role)
async def app_role_entered(message: types.Message, state: FSMContext):
    await state.update_data(requested_role=message.text)
    await state.set_state(ExecutorApplicationStates.waiting_for_comment)
    await message.answer("✍️ <b>Напишите комментарий о вашем опыте или прикрепите портфолио/ссылки:</b>", parse_mode="HTML")

@dp.message(ExecutorApplicationStates.waiting_for_comment)
async def app_comment_entered(message: types.Message, state: FSMContext):
    comment = message.text
    data = await state.get_data()
    role = data['requested_role']
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO executor_applications (user_id, requested_role, comment, created_at)
        VALUES (?, ?, ?, ?)
    """, (message.from_user.id, role, comment, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ <b>Ваша заявка успешно отправлена на рассмотрение администратору!</b>", parse_mode="HTML")

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
    cursor.execute("SELECT id, name FROM categories WHERE parent_id = ?", (cat_id,))
    subcategories = cursor.fetchall()
    
    # Fetch active executor listings in this category
    cursor.execute("""
        SELECT el.id, el.title, el.price, u.full_name, u.rating, u.user_id 
        FROM executor_listings el
        JOIN users u ON el.executor_id = u.user_id
        WHERE el.category_id = ? AND el.status = 'active'
    """, (cat_id,))
    listings = cursor.fetchall()
    conn.close()

    text = f"📁 <b>Раздел: {name}</b>\n\n{desc or 'Выберите подраздел или просмотрите готовые предложения исполнителей ниже:'}"
    kb = []

    if subcategories:
        for sub_id, sub_name in subcategories:
            kb.append([InlineKeyboardButton(text=f"🔹 {sub_name}", callback_data=f"user_cat_{sub_id}")])
            
    if listings:
        text += "\n\n🛍 <b>Готовые предложения исполнителей в этом разделе:</b>"
        for l_id, l_title, l_price, exec_name, exec_rating, exec_id in listings:
            kb.append([InlineKeyboardButton(text=f"⭐ {exec_rating} | {l_title} — {l_price} USDT", callback_data=f"view_listing_{l_id}")])

    kb.append([InlineKeyboardButton(text="📝 Создать индивидуальный заказ", callback_data=f"create_ticket_{cat_id}")])

    if parent_id:
        kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"user_cat_{parent_id}")])
    else:
        kb.append([InlineKeyboardButton(text="⬅️ В корневой каталог", callback_data="back_to_catalog_root")])

    await callback.message.edit_caption(
        caption=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

@dp.callback_query(F.data.startswith("view_listing_"))
async def view_listing_callback(callback: types.CallbackQuery):
    l_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT el.title, el.description, el.price, u.full_name, u.rating, u.user_id 
        FROM executor_listings el
        JOIN users u ON el.executor_id = u.user_id
        WHERE el.id = ? AND el.status = 'active'
    """, (l_id,))
    listing = cursor.fetchone()
    conn.close()
    
    if not listing:
        await callback.answer("Предложение не найдено или снято с публикации.", show_alert=True)
        return
        
    title, desc, price, exec_name, exec_rating, exec_id = listing
    text = (
        f"🛍 <b>Предложение: {title}</b>\n\n"
        f"👤 <b>Исполнитель:</b> {exec_name} (Рейтинг: ⭐ {exec_rating})\n"
        f"💰 <b>Стоимость:</b> <b>{price} USDT</b>\n\n"
        f"📝 <b>Описание:</b>\n{desc}"
    )
    kb = [
        [InlineKeyboardButton(text="🤝 Заказать у исполнителя", callback_data=f"buy_listing_{l_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_catalog_root")]
    ]
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_listing_"))
async def buy_listing_callback(callback: types.CallbackQuery, state: FSMContext):
    l_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT executor_id, category_id, title, price FROM executor_listings WHERE id = ?", (l_id,))
    listing = cursor.fetchone()
    
    if not listing:
        conn.close()
        await callback.answer("Предложение не найдено.", show_alert=True)
        return
        
    exec_id, cat_id, title, price = listing
    user = get_user(callback.from_user.id)
    
    if user['balance'] < price:
        conn.close()
        await callback.answer(f"❌ Недостаточно средств на балансе. Требуется {price} USDT.", show_alert=True)
        return
        
    # Deduct balance & create an active ticket entry mapped to this listing for unified chat & completion workflow
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, callback.from_user.id))
    cursor.execute("""
        INSERT INTO tickets (client_id, category_id, title, description, budget, status, executor_id, listing_id, created_at)
        VALUES (?, ?, ?, ?, ?, 'in_progress', ?, ?, ?)
    """, (callback.from_user.id, cat_id, f"Покупка товара: {title}", f"Автозаказ по опубликованному предложению #{l_id}", price, exec_id, l_id, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()
    
    await callback.message.answer(
        f"✅ <b>Заказ по товару успешно создан и передан исполнителю в работу!</b>\n"
        f"Средства зарезервированы. Перейдите в раздел <b>«Мои заказы / Тикеты»</b> для открытия чата с исполнителем и контроля сдачи.",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(exec_id, f"🎉 <b>У вас новый заказ по вашему товару «{title}»!</b>\nПерейдите в раздел «Мои заказы / Тикеты» для общения с клиентом.", parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()

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

@dp.message(F.text == "➕ Опубликовать услугу")
async def publish_listing_start(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if user['role'] != 'executor':
        await message.answer("⚠️ Публикация товаров и услуг доступна только исполнителям.")
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM categories")
    categories = cursor.fetchall()
    conn.close()
    
    if not categories:
        await message.answer("❌ Каталог еще не настроен администратором.")
        return
        
    kb = []
    for c_id, c_name in categories:
        kb.append([InlineKeyboardButton(text=f"📁 {c_name}", callback_data=f"pub_cat_{c_id}")])
        
    await state.set_state(ListingStates.choosing_category)
    await message.answer("📦 <b>Выберите категорию, в которой хотите опубликовать свой товар или услугу:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(ListingStates.choosing_category, F.data.startswith("pub_cat_"))
async def pub_cat_selected(callback: types.CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[2])
    await state.update_data(category_id=cat_id)
    await state.set_state(ListingStates.entering_title)
    await callback.message.answer("✍️ <b>Введите название вашего товара или услуги:</b>", parse_mode="HTML")
    await callback.answer()

@dp.message(ListingStates.entering_title)
async def pub_title_entered(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(ListingStates.entering_desc)
    await message.answer("📝 <b>Подробно опишите вашу услугу / товар, условия и сроки выполнения:</b>", parse_mode="HTML")

@dp.message(ListingStates.entering_desc)
async def pub_desc_entered(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(ListingStates.entering_price)
    await message.answer("💰 <b>Укажите фиксированную стоимость в USDT (например: 50):</b>", parse_mode="HTML")

@dp.message(ListingStates.entering_price)
async def pub_price_entered(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0: raise ValueError()
    except ValueError:
        await message.answer("❌ Введите корректное положительное число для стоимости.")
        return
        
    data = await state.get_data()
    cat_id = data['category_id']
    title = data['title']
    desc = data['description']
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO executor_listings (executor_id, category_id, title, description, price, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
    """, (message.from_user.id, cat_id, title, desc, price, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()
    
    await state.clear()
    user = get_user(message.from_user.id)
    await message.answer("✅ <b>Ваш товар успешно отправлен на модерацию администратору!</b>\nПосле проверки он появится в соответствующем разделе каталога.", parse_mode="HTML", reply_markup=main_menu_keyboard(user['role']))
    
    try:
        await bot.send_message(DEFAULT_ADMIN_ID, f"🔔 <b>Новая заявка на публикацию товара от ID {message.from_user.id}!</b>\nПроверьте в админ-панели.", parse_mode="HTML")
    except Exception:
        pass

@dp.message(F.text == "📦 Мои товары/услуги")
async def my_listings_handler(message: types.Message):
    user = get_user(message.from_user.id)
    if user['role'] != 'executor':
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, price, status FROM executor_listings WHERE executor_id = ?", (message.from_user.id,))
    listings = cursor.fetchall()
    conn.close()
    
    if not listings:
        await message.answer("📭 У вас пока нет опубликованных товаров или услуг.")
        return
        
    for l_id, title, price, status in listings:
        status_text = {"pending": "⏳ На модерации", "active": "🟢 Активен", "rejected": "❌ Отклонен"}.get(status, status)
        text = f"🛍 <b>#{l_id} {title}</b>\n💰 Цена: <b>{price} USDT</b>\nСтатус: <code>{status_text}</code>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить товар", callback_data=f"del_listing_{l_id}")]
        ])
        await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("del_listing_"))
async def delete_listing_callback(callback: types.CallbackQuery):
    l_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM executor_listings WHERE id = ? AND executor_id = ?", (l_id, callback.from_user.id))
    conn.commit()
    conn.close()
    await callback.answer("Товар удален.", show_alert=True)
    await callback.message.delete()

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
        if budget <= 0: raise ValueError()
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное число для бюджета.")
        return
        
    user = get_user(message.from_user.id)
    if user['balance'] < budget:
        await message.answer(f"❌ <b>Недостаточно средств на балансе!</b>\nСтоимость: {budget} USDT\nВаш баланс: {user['balance']:.2f} USDT\n\nПополните баланс в профиле.", parse_mode="HTML")
        await state.clear()
        return

    data = await state.get_data()
    cat_id = data['category_id']
    title = data['title']
    description = data['description']
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (budget, message.from_user.id))
    cursor.execute("""
        INSERT INTO tickets (client_id, category_id, title, description, budget, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'open', ?)
    """, (message.from_user.id, cat_id, title, description, budget, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ <b>Ваш заказ успешно создан, средства зарезервированы и заказ доступен для исполнителей!</b>", parse_mode="HTML")

@dp.message(F.text == "💼 Мои заказы / Тикеты")
async def my_tickets_handler(message: types.Message):
    user = get_user(message.from_user.id)
    
    conn = get_db()
    cursor = conn.cursor()
    
    if user['role'] == 'executor':
        cursor.execute("SELECT id, title, status, budget, client_id FROM tickets WHERE executor_id = ?", (message.from_user.id,))
    elif user['role'] == 'client':
        cursor.execute("SELECT id, title, status, budget, client_id FROM tickets WHERE client_id = ?", (message.from_user.id,))
    else: # admin
        cursor.execute("SELECT id, title, status, budget, client_id FROM tickets")
        
    tickets = cursor.fetchall()
    conn.close()
    
    if not tickets:
        await message.answer("📭 У вас пока нет активных или завершенных заказов.")
        return
        
    for t in tickets:
        t_id, title, status, budget, client_id = t[0], t[1], t[2], t[3], t[4]
        status_display = {"open": "🟢 Открыт", "in_progress": "⏳ В работе", "completed": "✅ Завершен", "cancelled": "❌ Отменен"}.get(status, status)
        text = f"📌 <b>Заказ #{t_id}: {title}</b>\nСтатус: <code>{status_display}</code>\nБюджет: <b>{budget} USDT</b>"
        
        kb = []
        if status == 'in_progress':
            kb.append([InlineKeyboardButton(text="💬 Открыть чат по заказу", callback_data=f"open_chat_{t_id}")])
            if message.from_user.id == client_id or user['role'] == 'admin':
                kb.append([InlineKeyboardButton(text="✅ Подтвердить и сдать работу", callback_data=f"complete_ticket_{t_id}")])
                
        await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None)

@dp.message(F.text == "📦 Доступные заказы")
async def available_tickets_handler(message: types.Message):
    user = get_user(message.from_user.id)
    if user['role'] != 'executor':
        await message.answer("Раздел доступен только исполнителям.")
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
    conn.commit()
    conn.close()
    
    await callback.message.edit_text(f"✅ Вы успешно взяли заказ #{t_id} в работу!\nОткройте «Мои заказы», чтобы общаться с клиентом в чате.")
    try:
        await bot.send_message(client_id, f"🎉 <b>Ваш заказ #{t_id} взят в работу исполнителем!</b>\nПерейдите в тикеты для общения в чате.", parse_mode="HTML")
    except Exception:
        pass

@dp.callback_query(F.data.startswith("open_chat_"))
async def open_chat_callback(callback: types.CallbackQuery, state: FSMContext):
    t_id = int(callback.data.split("_")[2])
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT client_id, executor_id, title FROM tickets WHERE id = ?", (t_id,))
    ticket = cursor.fetchone()
    conn.close()
    
    if not ticket:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
        
    client_id, exec_id, title = ticket
    user_id = callback.from_user.id
    
    if user_id not in (client_id, exec_id):
        await callback.answer("Вы не участник этого заказа.", show_alert=True)
        return
        
    target_id = exec_id if user_id == client_id else client_id
    
    await state.set_state(ChatStates.in_chat)
    await state.update_data(chat_ticket_id=t_id, chat_target_id=target_id)
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Выйти из чата")]], resize_keyboard=True)
    await callback.message.answer(f"💬 <b>Чат по заказу #{t_id} ({title}) открыт!</b>\nВсе отправленные сюда сообщения будут переданы собеседнику.", parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.message(ChatStates.in_chat, F.text == "❌ Выйти из чата")
async def exit_chat_handler(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    await state.clear()
    await message.answer("🚪 Вы вышли из чата тикета.", reply_markup=main_menu_keyboard(user['role']))

@dp.message(ChatStates.in_chat)
async def process_chat_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    t_id = data.get("chat_ticket_id")
    target_id = data.get("chat_target_id")
    
    prefix = f"💬 <b>[Чат Заказа #{t_id}]:</b>\n"
    try:
        if message.text:
            await bot.send_message(target_id, prefix + message.text, parse_mode="HTML")
        elif message.photo:
            await bot.send_photo(target_id, message.photo[-1].file_id, caption=prefix + (message.caption or ""), parse_mode="HTML")
        elif message.document:
            await bot.send_document(target_id, message.document.file_id, caption=prefix + (message.caption or ""), parse_mode="HTML")
        await message.answer("✅ <i>Сообщение отправлено</i>", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Не удалось доставить сообщение собеседнику: {e}")

@dp.callback_query(F.data.startswith("complete_ticket_"))
async def complete_ticket_callback(callback: types.CallbackQuery, state: FSMContext):
    t_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT executor_id, budget, client_id FROM tickets WHERE id = ?", (t_id,))
    ticket = cursor.fetchone()
    
    if not ticket:
        conn.close()
        await callback.answer("Заказ не найден.", show_alert=True)
        return
        
    exec_id, budget, client_id = ticket
    if callback.from_user.id != client_id and callback.from_user.id != DEFAULT_ADMIN_ID:
        conn.close()
        await callback.answer("Только заказчик может подтвердить выполнение сделки.", show_alert=True)
        return
        
    cursor.execute("UPDATE tickets SET status = 'completed' WHERE id = ?", (t_id,))
    
    cursor.execute("SELECT subscription_id, commission_rate FROM users WHERE user_id = ?", (exec_id,))
    exec_user = cursor.fetchone()
    
    effective_comm = exec_user[1] if exec_user else 10.0
    if exec_user and exec_user[0]:
        cursor.execute("SELECT commission_discount FROM subscriptions WHERE id = ?", (exec_user[0],))
        sub_comm = cursor.fetchone()
        if sub_comm:
            effective_comm = sub_comm[0]
            
    payout = budget * (1 - effective_comm / 100.0)
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (payout, exec_id))
    conn.commit()
    conn.close()
    
    try:
        await bot.send_message(exec_id, f"🎉 <b>Заказ #{t_id} подтвержден!</b>\nНа ваш баланс зачислено <b>{payout:.2f} USDT</b> (Комиссия: {effective_comm}%).", parse_mode="HTML")
    except Exception:
        pass
        
    await state.update_data(review_executor_id=exec_id, review_ticket_id=t_id)
    await state.set_state(ReviewStates.entering_rating)
    await callback.message.answer("✅ <b>Сделка подтверждена! Оцените работу исполнителя (от 1 до 5):</b>", parse_mode="HTML")

@dp.message(ReviewStates.entering_rating)
async def review_rating_entered(message: types.Message, state: FSMContext):
    try:
        rating = int(message.text)
        if not (1 <= rating <= 5): raise ValueError()
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
        )

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, duration_days, commission_discount FROM subscriptions")
    subs = cursor.fetchall()
    conn.close()

    text = f"💳 <b>Информация о подписке:</b>\n\n{sub_info}\n\n👇 <b>Выберите тариф для покупки:</b>"
    kb = []
    for s_id, name, price, days, comm in subs:
        kb.append([InlineKeyboardButton(text=f"💎 {name} - {price} USDT ({days} дн. / Ком.: {comm}%)", callback_data=f"sub_choice_{s_id}")])

    await message.answer_photo(
        photo=URLInputFile(SUB_IMAGE_URL),
        caption=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None
    )

@dp.callback_query(F.data.startswith("sub_choice_"))
async def sub_choice_callback(callback: types.CallbackQuery):
    sub_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, price FROM subscriptions WHERE id = ?", (sub_id,))
    sub = cursor.fetchone()
    conn.close()
    
    if not sub:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
        
    sub_name, price = sub
    kb = [
        [InlineKeyboardButton(text="💰 Оплатить с баланса", callback_data=f"buy_sub_bal_{sub_id}")],
        [InlineKeyboardButton(text="🔗 Оплатить через CryptoBot", callback_data=f"buy_sub_crypto_{sub_id}")]
    ]
    await callback.message.answer(f"💎 <b>Оплата подписки {sub_name}</b>\nСтоимость: <b>{price} USDT</b>\n\nВыберите способ оплаты:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_sub_bal_"))
async def buy_sub_balance_callback(callback: types.CallbackQuery):
    sub_id = int(callback.data.split("_")[3])
    user = get_user(callback.from_user.id)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT price, duration_days FROM subscriptions WHERE id = ?", (sub_id,))
    sub = cursor.fetchone()
    
    if not sub:
        conn.close()
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
        
    price, days = sub
    if user['balance'] < price:
        conn.close()
        await callback.answer(f"❌ Недостаточно средств на балансе ({user['balance']:.2f} USDT).", show_alert=True)
        return
        
    expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    cursor.execute("UPDATE users SET balance = balance - ?, subscription_id = ?, subscription_expires = ? WHERE user_id = ?", (price, sub_id, expires, callback.from_user.id))
    conn.commit()
    conn.close()
    
    await callback.message.edit_text(f"🎉 <b>Подписка успешно куплена с баланса!</b>\nДействует до: {expires}", parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_sub_crypto_"))
async def buy_sub_crypto_callback(callback: types.CallbackQuery):
    sub_id = int(callback.data.split("_")[3])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, price FROM subscriptions WHERE id = ?", (sub_id,))
    sub = cursor.fetchone()
    conn.close()
    
    if not sub:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
        
    sub_name, price = sub
    invoice = await create_crypto_invoice(price, f"Оплата подписки {sub_name}")
    if not invoice:
        await callback.answer("Ошибка генерации счета CryptoBot.", show_alert=True)
        return
        
    inv_id = invoice['invoice_id']
    pay_url = invoice['bot_invoice_url']
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO crypto_invoices (invoice_id, user_id, type, target_id, amount, status)
        VALUES (?, ?, 'subscription', ?, ?, 'active')
    """, (inv_id, callback.from_user.id, sub_id, price))
    conn.commit()
    conn.close()
    
    kb = [
        [InlineKeyboardButton(text="🔗 Оплатить через CryptoBot", url=pay_url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_inv_{inv_id}")]
    ]
    await callback.message.answer(
        f"🧾 <b>Счет на оплату подписки {sub_name} создан!</b>\n\nСумма: <b>{price} USDT</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("check_inv_"))
async def check_invoice_callback(callback: types.CallbackQuery):
    inv_id = int(callback.data.split("_")[2])
    status = await check_crypto_invoice(inv_id)
    
    if status == 'paid':
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, type, target_id, amount, status FROM crypto_invoices WHERE invoice_id = ?", (inv_id,))
        inv_row = cursor.fetchone()
        
        if inv_row and inv_row[4] == 'active':
            u_id, inv_type, target_id, amount = inv_row[0], inv_row[1], inv_row[2], inv_row[3]
            
            if inv_type == 'subscription':
                cursor.execute("SELECT duration_days FROM subscriptions WHERE id = ?", (target_id,))
                sub = cursor.fetchone()
                if sub:
                    expires = (datetime.now() + timedelta(days=sub[0])).strftime("%Y-%m-%d %H:%M")
                    cursor.execute("UPDATE users SET subscription_id = ?, subscription_expires = ? WHERE user_id = ?", (target_id, expires, u_id))
            elif inv_type == 'deposit':
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, u_id))
                
            cursor.execute("UPDATE crypto_invoices SET status = 'paid' WHERE invoice_id = ?", (inv_id,))
            conn.commit()
            
        conn.close()
        await callback.message.edit_text("🎉 <b>Оплата подтверждена! Баланс/подписка успешно обновлены!</b>", parse_mode="HTML")
    else:
        await callback.answer("⏳ Оплата еще не поступила или находится в обработке.", show_alert=True)

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

@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    await callback.message.answer("🏠 <b>Главное меню:</b>", parse_mode="HTML", reply_markup=main_menu_keyboard(user['role']))
    await callback.answer()

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: types.CallbackQuery):
    await callback.message.edit_caption(
        caption="⚙️ <b>Панель управления администратора:</b>",
        parse_mode="HTML",
        reply_markup=admin_menu_keyboard()
    )

@dp.callback_query(F.data == "adm_listings")
async def adm_listings_view(callback: types.CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT el.id, el.title, el.price, u.full_name, el.executor_id 
        FROM executor_listings el
        JOIN users u ON el.executor_id = u.user_id
        WHERE el.status = 'pending'
    """)
    listings = cursor.fetchall()
    conn.close()
    
    text = "🛍 <b>Модерация товаров и услуг:</b>\n\n"
    kb = []
    if not listings:
        text += "Нет товаров, ожидающих модерации."
    else:
        for l_id, title, price, exec_name, exec_id in listings:
            text += f"📦 <b>#{l_id} {title}</b> — {price} USDT\n └ Исполнитель: {exec_name} (ID: <code>{exec_id}</code>)\n\n"
            kb.append([
                InlineKeyboardButton(text=f"✅ Одобрить #{l_id}", callback_data=f"approve_listing_{l_id}"),
                InlineKeyboardButton(text=f"❌ Отклонить #{l_id}", callback_data=f"reject_listing_{l_id}")
            ])
            
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")])
    await callback.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("approve_listing_"))
async def approve_listing_callback(callback: types.CallbackQuery):
    l_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT executor_id, title FROM executor_listings WHERE id = ?", (l_id,))
    item = cursor.fetchone()
    
    if item:
        exec_id, title = item[0], item[1]
        cursor.execute("UPDATE executor_listings SET status = 'active' WHERE id = ?", (l_id,))
        conn.commit()
        try:
            await bot.send_message(exec_id, f"🎉 <b>Ваш товар «{title}» успешно прошел модерацию и опубликован в каталоге!</b>", parse_mode="HTML")
        except Exception:
            pass
            
    conn.close()
    await callback.answer("Товар одобрен и опубликован!")
    await adm_listings_view(callback)

@dp.callback_query(F.data.startswith("reject_listing_"))
async def reject_listing_callback(callback: types.CallbackQuery):
    l_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT executor_id, title FROM executor_listings WHERE id = ?", (l_id,))
    item = cursor.fetchone()
    
    if item:
        exec_id, title = item[0], item[1]
        cursor.execute("UPDATE executor_listings SET status = 'rejected' WHERE id = ?", (l_id,))
        conn.commit()
        try:
            await bot.send_message(exec_id, f"❌ <b>К сожалению, ваш товар «{title}» был отклонен модератором.</b>", parse_mode="HTML")
        except Exception:
            pass
            
    conn.close()
    await callback.answer("Товар отклонен.")
    await adm_listings_view(callback)

@dp.callback_query(F.data == "adm_commissions")
async def adm_commissions_view(callback: types.CallbackQuery):
    def_comm = get_setting("default_commission", "10.0")
    text = (
        f"📊 <b>Управление процентом комиссии:</b>\n\n"
        f"📈 <b>Общий процент комиссии по умолчанию:</b> <code>{def_comm}%</code>\n\n"
        f"Для изменения общего процента нажмите кнопку ниже 👇"
    )
    kb = [
        [InlineKeyboardButton(text="✏️ Изменить общий процент", callback_data="change_global_comm")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]
    ]
    await callback.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "change_global_comm")
async def change_global_comm_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_global_comm)
    await callback.message.answer("✍️ <b>Введите новый общий процент комиссии (например: 8.5):</b>", parse_mode="HTML")
    await callback.answer()

@dp.message(AdminStates.waiting_for_global_comm)
async def global_comm_entered(message: types.Message, state: FSMContext):
    try:
        comm = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")
        return
        
    set_setting("default_commission", str(comm))
    await state.clear()
    await message.answer(f"✅ <b>Общий процент комиссии системы успешно установлен на {comm}%!</b>", parse_mode="HTML")

@dp.callback_query(F.data == "adm_give_balance")
async def adm_give_balance_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_give_balance_uid)
    await callback.message.answer("✍️ <b>Введите Telegram ID пользователя:</b>", parse_mode="HTML")
    await callback.answer()

@dp.message(AdminStates.waiting_for_give_balance_uid)
async def give_balance_uid_entered(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
    except ValueError:
        await message.answer("Введите корректный числовой Telegram ID.")
        return
        
    user = get_user(uid)
    if not user:
        await message.answer("❌ Пользователь не найден в базе данных.")
        return
        
    await state.update_data(target_uid=uid)
    await state.set_state(AdminStates.waiting_for_give_balance_amount)
    await message.answer(f"💰 <b>Пользователь:</b> {user['full_name']} (Баланс: {user['balance']:.2f} USDT)\n\nВведите сумму изменения баланса (положительное число для зачисления, отрицательное для списания):", parse_mode="HTML")

@dp.message(AdminStates.waiting_for_give_balance_amount)
async def give_balance_amount_entered(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Введите число.")
        return
        
    data = await state.get_data()
    uid = data['target_uid']
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, uid))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ <b>Баланс пользователя {uid} успешно изменен на {amount} USDT!</b>", parse_mode="HTML")

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

@dp.callback_query(F.data == "add_cat_start")
async def add_cat_start(callback: types.CallbackQuery, state: FSMContext):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM categories WHERE parent_id IS NULL")
    parents = cursor.fetchall()
    conn.close()
    
    kb = [[InlineKeyboardButton(text="📁 Создать как корневой раздел", callback_data="set_parent_none")]]
    for p_id, p_name in parents:
        kb.append([InlineKeyboardButton(text=f"└ 🔹 Вложить в {p_name}", callback_data=f"set_parent_{p_id}")])
        
    await state.set_state(AdminStates.waiting_for_cat_parent)
    await callback.message.answer("📁 <b>Выберите родительскую категорию для нового раздела:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("set_parent_"))
async def cat_parent_selected(callback: types.CallbackQuery, state: FSMContext):
    raw_id = callback.data.split("_")[2]
    parent_id = None if raw_id == "none" else int(raw_id)
    
    await state.update_data(parent_id=parent_id)
    await state.set_state(AdminStates.waiting_for_cat_name)
    await callback.message.answer("✍️ <b>Введите название раздела/подраздела:</b>", parse_mode="HTML")
    await callback.answer()

@dp.message(AdminStates.waiting_for_cat_name)
async def cat_name_entered(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AdminStates.waiting_for_cat_desc)
    await message.answer("📝 <b>Введите описание раздела:</b>", parse_mode="HTML")

@dp.message(AdminStates.waiting_for_cat_desc)
async def cat_desc_entered(message: types.Message, state: FSMContext):
    await state.update_data(desc=message.text)
    await state.set_state(AdminStates.waiting_for_cat_tag)
    await message.answer("🏷 <b>Введите тег раздела (slug, например: telegram_ads):</b>", parse_mode="HTML")

@dp.message(AdminStates.waiting_for_cat_tag)
async def cat_tag_entered(message: types.Message, state: FSMContext):
    tag = message.text.strip()
    data = await state.get_data()
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO categories (parent_id, name, description, tag_slug)
        VALUES (?, ?, ?, ?)
    """, (data['parent_id'], data['name'], data['desc'], tag))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ <b>Раздел успешно добавлен в каталог!</b>", parse_mode="HTML")

@dp.callback_query(F.data == "adm_subs")
async def adm_subs_view(callback: types.CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, duration_days, commission_discount FROM subscriptions")
    subs = cursor.fetchall()
    conn.close()
    
    text = "💼 <b>Управление тарифными планами:</b>\n\n"
    kb = []
    if subs:
        for s_id, name, price, days, comm in subs:
            text += f"💎 <b>#{s_id} {name}</b> — {price} USDT ({days} дней, комиссия: {comm}%)\n"
            kb.append([InlineKeyboardButton(text=f"❌ Удалить #{s_id}", callback_data=f"del_sub_{s_id}")])
    else:
        text += "Подписки отсутствуют."
        
    kb.append([InlineKeyboardButton(text="➕ Создать новый тариф", callback_data="add_sub_start")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")])
    
    await callback.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "add_sub_start")
async def add_sub_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_sub_name)
    await callback.message.answer("✍️ <b>Введите название тарифа:</b>", parse_mode="HTML")
    await callback.answer()

@dp.message(AdminStates.waiting_for_sub_name)
async def sub_name_entered(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AdminStates.waiting_for_sub_price)
    await message.answer("💰 <b>Введите стоимость тарифа в USDT:</b>", parse_mode="HTML")

@dp.message(AdminStates.waiting_for_sub_price)
async def sub_price_entered(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")
        return
    await state.update_data(price=price)
    await state.set_state(AdminStates.waiting_for_sub_days)
    await message.answer("⏳ <b>Укажите срок действия в днях:</b>", parse_mode="HTML")

@dp.message(AdminStates.waiting_for_sub_days)
async def sub_days_entered(message: types.Message, state: FSMContext):
    try:
        days = int(message.text)
    except ValueError:
        await message.answer("Пожалуйста, введите целое число.")
        return
    await state.update_data(days=days)
    await state.set_state(AdminStates.waiting_for_sub_comm)
    await message.answer("📊 <b>Укажите процент комиссии по этой подписке (например: 5.0):</b>", parse_mode="HTML")

@dp.message(AdminStates.waiting_for_sub_comm)
async def sub_comm_entered(message: types.Message, state: FSMContext):
    try:
        comm = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")
        return
        
    data = await state.get_data()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO subscriptions (name, price, duration_days, commission_discount)
        VALUES (?, ?, ?, ?)
    """, (data['name'], data['price'], data['days'], comm))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ <b>Тариф успешно добавлен!</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("del_sub_"))
async def del_sub_callback(callback: types.CallbackQuery):
    s_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM subscriptions WHERE id = ?", (s_id,))
    conn.commit()
    conn.close()
    await callback.answer("Тариф удален.", show_alert=True)
    await adm_subs_view(callback)

@dp.callback_query(F.data == "adm_applications")
async def adm_applications_view(callback: types.CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, requested_role, comment, created_at FROM executor_applications WHERE status = 'pending'")
    apps = cursor.fetchall()
    conn.close()
    
    text = "📋 <b>Заявки на статус Исполнителя:</b>\n\n"
    if not apps:
        text += "Нет новых нерассмотренных заявок."
        
    kb = []
    for a_id, u_id, role, comment, created in apps:
        text += f"🆔 <b>Заявка #{a_id}</b> от ID <code>{u_id}</code>\n └ Роль: <b>{role}</b>\n └ Комментарий: {comment}\n\n"
        kb.append([
            InlineKeyboardButton(text=f"✅ Одобрить #{a_id}", callback_data=f"approve_app_{a_id}"),
            InlineKeyboardButton(text=f"❌ Отклонить #{a_id}", callback_data=f"reject_app_{a_id}")
        ])
        
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")])
    await callback.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("approve_app_"))
async def approve_app_callback(callback: types.CallbackQuery):
    a_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM executor_applications WHERE id = ?", (a_id,))
    app = cursor.fetchone()
    
    if app:
        u_id = app[0]
        cursor.execute("UPDATE executor_applications SET status = 'approved' WHERE id = ?", (a_id,))
        cursor.execute("UPDATE users SET role = 'executor' WHERE user_id = ?", (u_id,))
        conn.commit()
        
        try:
            await bot.send_message(u_id, "🎉 <b>Поздравляем! Ваша заявка на статус Исполнителя одобрена!</b>\nОтправьте /start для обновления меню.", parse_mode="HTML")
        except Exception:
            pass

    conn.close()
    await callback.answer("Заявка одобрена!")
    await adm_applications_view(callback)

@dp.callback_query(F.data.startswith("reject_app_"))
async def reject_app_callback(callback: types.CallbackQuery):
    a_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM executor_applications WHERE id = ?", (a_id,))
    app = cursor.fetchone()
    
    if app:
        u_id = app[0]
        cursor.execute("UPDATE executor_applications SET status = 'rejected' WHERE id = ?", (a_id,))
        conn.commit()
        
        try:
            await bot.send_message(u_id, "❌ <b>К сожалению, ваша заявка на статус Исполнителя была отклонена.</b>", parse_mode="HTML")
        except Exception:
            pass

    conn.close()
    await callback.answer("Заявка отклонена!")
    await adm_applications_view(callback)

async def main():
    print("🚀 Bot started successfully with unified chat and listing purchase workflow!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
