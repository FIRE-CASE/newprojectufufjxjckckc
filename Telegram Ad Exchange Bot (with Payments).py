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
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, FSInputFile, URLInputFile

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
DEFAULT_IMAGE_URL = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1200&q=80"
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
    
    # Category state
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

async def create_crypto_invoice(amount: float, description: str):
    """Creates an invoice via Crypto Pay API (@CryptoBot)."""
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
    payload = {
        "asset": "USDT", # Primary currency
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
    """Checks invoice status from Crypto Pay API."""
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
        [InlineKeyboardButton(text="📂 Управление каталогом (Разделы/Подразделы)", callback_data="adm_catalog")],
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
        f"💰 <b>Баланс:</b> <b>{user['balance']} USDT / руб.</b>\n"
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

@dp.callback_query(F.data == "apply_executor")
async def start_executor_application(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ExecutorApplicationStates.waiting_for_role)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рекламодатель / Блогер", callback_data="role_blogger")],
        [InlineKeyboardButton(text="🎨 Дизайнер / Копирайтер", callback_data="role_creator")],
        [InlineKeyboardButton(text="🚀 Менеджер каналов", callback_data="role_manager")]
    ])
    await callback.message.answer("🎯 <b>Выберите специализацию (роль) исполнителя:</b>", parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("role_"))
async def role_selected(callback: types.CallbackQuery, state: FSMContext):
    role_map = {
        "role_blogger": "Блогер/Владелец канала",
        "role_creator": "Креативщик/Дизайнер",
        "role_manager": "Менеджер каналов"
    }
    selected_role = role_map.get(callback.data, "Исполнитель")
    await state.update_data(requested_role=selected_role)
    
    await state.set_state(ExecutorApplicationStates.waiting_for_comment)
    await callback.message.answer("✍️ <b>Опишите ваш опыт, прикрепите ссылки на кейсы или каналы:</b>", parse_mode="HTML")
    await callback.answer()

@dp.message(ExecutorApplicationStates.waiting_for_comment)
async def comment_entered(message: types.Message, state: FSMContext):
    data = await state.get_data()
    role = data['requested_role']
    comment = message.text
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO executor_applications (user_id, requested_role, comment, created_at)
        VALUES (?, ?, ?, ?)
    """, (message.from_user.id, role, comment, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ <b>Ваша заявка отправлена администраторам на рассмотрение!</b>\nОжидайте уведомления.", parse_mode="HTML")

@dp.message(F.text == "💳 Моя подписка")
async def my_subscription_handler(message: types.Message):
    user = get_user(message.from_user.id)
    if user['role'] != 'executor':
        await message.answer("Раздел подписок доступен только исполнителям.")
        return

    # Check existing subscription info
    sub_info = "❌ У вас нет активной подписки."
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

    # Fetch all available plans
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, duration_days, deals_limit FROM subscriptions")
    subs = cursor.fetchall()
    conn.close()

    text = f"💳 <b>Информация о подписке:</b>\n\n{sub_info}\n\n👇 <b>Выберите тариф для покупки/продления через CryptoBot:</b>"
    
    kb = []
    for s_id, name, price, days, deals in subs:
        kb.append([InlineKeyboardButton(text=f"💎 {name} - {price} USDT ({days} дн. / {deals} сделок)", callback_data=f"buy_crypto_{s_id}")])

    await message.answer_photo(
        photo=URLInputFile(SUB_IMAGE_URL),
        caption=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None
    )

@dp.callback_query(F.data.startswith("buy_crypto_"))
async def process_crypto_buy(callback: types.CallbackQuery):
    sub_id = int(callback.data.split("_")[2])
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, price FROM subscriptions WHERE id = ?", (sub_id,))
    sub = cursor.fetchone()
    conn.close()
    
    if not sub:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
        
    name, price = sub
    
    # Create invoice via CryptoBot
    invoice = await create_crypto_invoice(price, f"Подписка {name}")
    
    if not invoice:
        # Fallback simulation mode if API Token is default/invalid
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT duration_days, deals_limit FROM subscriptions WHERE id = ?", (sub_id,))
        days, deals = cursor.fetchone()
        expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        
        cursor.execute("""
            UPDATE users SET subscription_id = ?, subscription_expires = ?, deals_left = ?
            WHERE user_id = ?
        """, (sub_id, expires, deals, callback.from_user.id))
        conn.commit()
        conn.close()
        
        await callback.message.answer(f"🎉 <b>[Тестовый режим] Подписка «{name}» успешно активирована!</b>\nИстекает: {expires}", parse_mode="HTML")
        await callback.answer()
        return

    # Store invoice record
    inv_id = invoice["invoice_id"]
    pay_url = invoice["bot_invoice_url"]
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO crypto_invoices (invoice_id, user_id, subscription_id, amount) VALUES (?, ?, ?, ?)",
                   (inv_id, callback.from_user.id, sub_id, price))
    conn.commit()
    conn.close()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Оплатить через CryptoBot", url=pay_url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_pay_{inv_id}")]
    ])
    
    await callback.message.answer(f"💳 <b>Счет на оплату подписки «{name}» создана!</b>\nСумма: <b>{price} USDT</b>", parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("check_pay_"))
async def check_payment_callback(callback: types.CallbackQuery):
    inv_id = int(callback.data.split("_")[2])
    status = await check_crypto_invoice(inv_id)
    
    if status == "paid":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, subscription_id FROM crypto_invoices WHERE invoice_id = ?", (inv_id,))
        rec = cursor.fetchone()
        
        if rec:
            u_id, sub_id = rec
            cursor.execute("SELECT duration_days, deals_limit FROM subscriptions WHERE id = ?", (sub_id,))
            days, deals = cursor.fetchone()
            expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
            
            cursor.execute("UPDATE users SET subscription_id = ?, subscription_expires = ?, deals_left = ? WHERE user_id = ?", 
                           (sub_id, expires, deals, u_id))
            cursor.execute("UPDATE crypto_invoices SET status = 'paid' WHERE invoice_id = ?", (inv_id,))
            conn.commit()
            
        conn.close()
        await callback.message.answer("🎉 <b>Оплата прошла успешно! Подписка активирована.</b>", parse_mode="HTML")
    else:
        await callback.answer("⏳ Оплата еще не зафиксирована. Попробуйте снова через минуту.", show_alert=True)

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

@dp.callback_query(F.data == "add_cat_start")
async def add_category_step1(callback: types.CallbackQuery, state: FSMContext):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM categories WHERE parent_id IS NULL")
    parents = cursor.fetchall()
    conn.close()
    
    kb = [[InlineKeyboardButton(text="📁 Создать КОРНЕВОЙ раздел", callback_data="parent_none")]]
    for p_id, p_name in parents:
        kb.append([InlineKeyboardButton(text=f"└ Подраздел для: {p_name}", callback_data=f"parent_{p_id}")])
        
    await state.set_state(AdminStates.waiting_for_cat_parent)
    await callback.message.answer("<b>Выберите родительский раздел (или создайте корневой):</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("parent_"))
async def parent_selected(callback: types.CallbackQuery, state: FSMContext):
    parent_val = callback.data.split("_")[1]
    parent_id = None if parent_val == "none" else int(parent_val)
    
    await state.update_data(parent_id=parent_id)
    await state.set_state(AdminStates.waiting_for_cat_name)
    await callback.message.answer("Введите название нового раздела/подраздела:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_cat_name)
async def cat_name_entered(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AdminStates.waiting_for_cat_desc)
    await message.answer("Введите описание элемента каталога:")

@dp.message(AdminStates.waiting_for_cat_desc)
async def cat_desc_entered(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO categories (parent_id, name, description)
        VALUES (?, ?, ?)
    """, (data.get('parent_id'), data['name'], message.text))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ <b>Раздел / подраздел успешно создан!</b>", parse_mode="HTML")

@dp.callback_query(F.data == "adm_applications")
async def adm_applications_list(callback: types.CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, requested_role, comment FROM executor_applications WHERE status = 'pending'")
    apps = cursor.fetchall()
    conn.close()
    
    if not apps:
        await callback.answer("Новых заявок нет.", show_alert=True)
        return
        
    for app_id, u_id, role, comment in apps:
        text = f"📋 <b>Заявка #{app_id}</b>\n👤 Пользователь: ID <code>{u_id}</code>\n🎯 Роль: <b>{role}</b>\n💬 Комментарий: {comment}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"app_approve_{app_id}_{u_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"app_reject_{app_id}_{u_id}")
            ]
        ])
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("app_approve_"))
async def approve_app(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    app_id, u_id = int(parts[2]), int(parts[3])
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = 'executor' WHERE user_id = ?", (u_id,))
    cursor.execute("UPDATE executor_applications SET status = 'approved' WHERE id = ?", (app_id,))
    conn.commit()
    conn.close()
    
    await callback.message.edit_text(f"✅ Заявка #{app_id} одобрена! Пользователь стал исполнителем.")
    try:
        await bot.send_message(u_id, "🎉 <b>Ваша заявка на роль Исполнителя была одобрена!</b>", parse_mode="HTML")
    except Exception:
        pass

@dp.callback_query(F.data.startswith("app_reject_"))
async def reject_app(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    app_id, u_id = int(parts[2]), int(parts[3])
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE executor_applications SET status = 'rejected' WHERE id = ?", (app_id,))
    conn.commit()
    conn.close()
    
    await callback.message.edit_text(f"❌ Заявка #{app_id} отклонена.")

async def main():
    print("🚀 Bot starting with complete features!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
