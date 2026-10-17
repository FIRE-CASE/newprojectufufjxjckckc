import logging
import sqlite3
import sys
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, LabeledPrice

# Настройка логирования
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# ТОКЕН БОТА (Замените на ваш реальный токен от @BotFather)
BOT_TOKEN = "8928950087:AAGFtUkiRgRZnZgMLNF1EJBKtU20xShhqyw"

# ПЛАТЕЖНЫЙ ТОКЕН (Получите в @BotFather через команду /payment или используйте тестовый токен от провайдера)
# Для Telegram Stars используется пустой провайдер или встроенные инструменты, для реальных карт — токен от ЮKassa/Сбер и т.д.
PAYMENT_PROVIDER_TOKEN = "PROVIDER_TOKEN_FROM_BOTFATHER" # Укажите токен провайдера платежей или оставьте тест для Stars

# ID администратора по умолчанию (замените на ваш Telegram ID)
DEFAULT_ADMIN_ID = 8106424143

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==========================================
# РАБОТА С БАЗОЙ ДАННЫХ (SQLite)
# ==========================================

def init_db():
    conn = sqlite3.connect("ad_exchange.db")
    cursor = conn.cursor()
    
    # Пользователи
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            role TEXT DEFAULT 'client', -- client, executor, admin
            balance REAL DEFAULT 0.0,
            rating REAL DEFAULT 5.0,
            reviews_count INTEGER DEFAULT 0,
            commission_rate REAL DEFAULT 10.0, -- индивидуальная комиссия (%)
            tags TEXT DEFAULT '', -- через запятую, например: "tg_ads,youtube"
            subscription_id INTEGER,
            subscription_expires TEXT,
            deals_left INTEGER DEFAULT 0,
            FOREIGN KEY (subscription_id) REFERENCES subscriptions(id)
        )
    """)
    
    # Тарифные планы подписок
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price REAL,
            duration_days INTEGER,
            deals_limit INTEGER
        )
    """)
    
    # Категории каталога услуг (разделы и подразделы)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER, -- NULL если это корневой раздел
            name TEXT,
            description TEXT,
            tag_slug TEXT -- уникальный тег для фильтрации исполнителей
        )
    """)
    
    # Тикеты (заказы клиентов)
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
            created_at TEXT
        )
    """)
    
    # Отзывы
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
    
    conn.commit()
    conn.close()

init_db()

# Вспомогательные функции для работы с БД
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
    cols = [desc[0] for desc in cursor.description] if hasattr(cursor, 'description') else \
           ['user_id', 'username', 'full_name', 'role', 'balance', 'rating', 'reviews_count', 
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
        """, (user_id, username, full_name, role))
        conn.commit()
    conn.close()

# ==========================================
# СОСТОЯНИЯ FSM (FSM States)
# ==========================================

class AdminStates(StatesGroup):
    waiting_for_sub_name = State()
    waiting_for_sub_price = State()
    waiting_for_sub_days = State()
    waiting_for_sub_deals = State()
    waiting_for_cat_name = State()
    waiting_for_cat_desc = State()
    waiting_for_cat_tag = State()
    waiting_for_user_commission = State()
    waiting_for_user_tags = State()

class ClientStates(StatesGroup):
    choosing_category = State()
    entering_title = State()
    entering_desc = State()
    entering_budget = State()

class ReviewStates(StatesGroup):
    entering_rating = State()
    entering_comment = State()

# ==========================================
# КЛАВИАТУРЫ (Keyboards)
# ==========================================

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
        [InlineKeyboardButton(text="👥 Управление пользователями", callback_data="adm_users")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ==========================================
# ОБРАБОТЧИКИ КОМАНД И ГЛАВНОГО МЕНЮ
# ==========================================

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    register_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    user = get_user(message.from_user.id)
    
    welcome_text = (
        f"👋 Привет, <b>{message.from_user.full_name}</b>!\n\n"
        f"Добро пожаловать в автоматизированную <b>Биржу Рекламы</b>.\n"
        f"Ваша текущая роль: <code>{user['role'].upper()}</code>\n\n"
        f"Используйте кнопки ниже для навигации:"
    )
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=main_menu_keyboard(user['role']))

@dp.message(F.text == "👤 Профиль")
async def profile_handler(message: types.Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start")
        return
    
    sub_info = "Отсутствует"
    if user['subscription_id']:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM subscriptions WHERE id = ?", (user['subscription_id'],))
        sub_row = cursor.fetchone()
        conn.close()
        sub_name = sub_row[0] if sub_row else "Неизвестно"
        sub_info = f"{sub_name} (Сделок осталось: {user['deals_left']}, до {user['subscription_expires']})"

    text = (
        f"👤 <b>Ваш профиль:</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"🏷 Роль: <code>{user['role'].upper()}</code>\n"
        f"💰 Баланс: <b>{user['balance']} руб.</b>\n"
        f"⭐ Рейтинг: <b>{user['rating']} / 5.0</b> (Отзывов: {user['reviews_count']})\n"
        f"📈 Ваша комиссия системы: <b>{user['commission_rate']}%</b>\n"
        f"🏷 Ваши теги доступа: <code>{user['tags'] or 'Нет тегов'}</code>\n"
        f"📦 Активная подписка: <b>{sub_info}</b>\n\n"
    )
    
    kb = []
    if user['role'] == 'client':
        kb.append([InlineKeyboardButton(text="🔄 Стать исполнителем", callback_data="become_executor")])
    
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None)

@dp.callback_query(F.data == "become_executor")
async def become_executor_callback(callback: types.CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = 'executor' WHERE user_id = ?", (callback.from_user.id,))
    conn.commit()
    conn.close()
    await callback.message.edit_text("🎉 Поздравляем! Теперь вы Исполнитель. Выберите подписку, чтобы получить доступ к заказам.")
    await callback.message.answer("Главное меню обновлено:", reply_markup=main_menu_keyboard('executor'))

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=main_menu_keyboard(user['role']))

# ==========================================
# КАТАЛОГ УСЛУГ И КЛИЕНТСКИЙ БЛОК (Создание тикетов)
# ==========================================

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
        kb.append([InlineKeyboardButton(text=f"📁 {cat_name}", callback_data=f"cat_view_{cat_id}")])
    
    await message.answer("<b>Выберите категорию рекламных услуг:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("cat_view_"))
async def category_view_callback(callback: types.CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT name, description, tag_slug FROM categories WHERE id = ?", (cat_id,))
    cat = cursor.fetchone()
    
    cursor.execute("SELECT id, name FROM categories WHERE parent_id = ?", (cat_id,))
    subcategories = cursor.fetchall()
    conn.close()
    
    if not cat:
        await callback.answer("Категория не найдена", show_alert=True)
        return
        
    name, desc, tag = cat
    text = f"📂 <b>{name}</b>\n\n{desc or 'Описание отсутствует.'}"
    
    kb = []
    if subcategories:
        text += "\n\n<b>Выберите подраздел:</b>"
        for sub_id, sub_name in subcategories:
            kb.append([InlineKeyboardButton(text=f"🔹 {sub_name}", callback_data=f"cat_view_{sub_id}")])
    else:
        kb.append([InlineKeyboardButton(text="📝 Создать тикет (заказ) в этой категории", callback_data=f"create_ticket_{cat_id}")])
        
    kb.append([InlineKeyboardButton(text="⬅️ Назад в каталог", callback_data="back_to_catalog")])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "back_to_catalog")
async def back_to_catalog_callback(callback: types.CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM categories WHERE parent_id IS NULL")
    categories = cursor.fetchall()
    conn.close()
    
    kb = [[InlineKeyboardButton(text=f"📁 {c[1]}", callback_data=f"cat_view_{c[0]}")] for c in categories]
    await callback.message.edit_text("<b>Выберите категорию рекламных услуг:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("create_ticket_"))
async def start_create_ticket(callback: types.CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[2])
    await state.update_data(category_id=cat_id)
    await state.set_state(ClientStates.entering_title)
    await callback.message.answer("Введите <b>название / заголовок</b> вашего заказа:", parse_mode="HTML")
    await callback.answer()

@dp.message(ClientStates.entering_title)
async def ticket_title_entered(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(ClientStates.entering_desc)
    await message.answer("Опишите подробнее задачу для исполнителя (требования, ссылки, дедлайны):")

@dp.message(ClientStates.entering_desc)
async def ticket_desc_entered(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(ClientStates.entering_budget)
    await message.answer("Укажите бюджет заказа в рублях (числом, например: 5000):")

@dp.message(ClientStates.entering_budget)
async def ticket_budget_entered(message: types.Message, state: FSMContext):
    try:
        budget = float(message.text)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число для бюджета.")
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
    await message.answer("✅ <b>Заказ успешно создан и отправлен исполнителям с соответствующими тегами!</b>", 
                         parse_mode="HTML", reply_markup=main_menu_keyboard('client'))

# ==========================================
# БЛОК ИСПОЛНИТЕЛЯ И ОПЛАТА ПОДПИСОК
# ==========================================

@dp.message(F.text == "💳 Моя подписка")
async def executor_subscriptions(message: types.Message):
    user = get_user(message.from_user.id)
    if user['role'] != 'executor':
        await message.answer("Этот раздел доступен только исполнителям.")
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, duration_days, deals_limit FROM subscriptions")
    subs = cursor.fetchall()
    conn.close()
    
    if not subs:
        await message.answer("💳 В данный момент администратор еще не добавил тарифные подписки.")
        return

    text = "💳 <b>Доступные тарифные планы подписок:</b>\n\nВыберите подписку для оплаты банковской картой или внутренним балансом:"
    
    for sub_id, name, price, days, deals in subs:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить картой ({price} руб.)", callback_data=f"pay_card_sub_{sub_id}")],
            [InlineKeyboardButton(text=f"💰 Списать с баланса ({price} руб.)", callback_data=f"pay_balance_sub_{sub_id}")]
        ])
        sub_text = f"📦 <b>{name}</b>\n💰 Стоимость: <b>{price} руб.</b>\n⏳ Срок: {days} дн.\n📊 Лимит сделок: {deals}"
        await message.answer(sub_text, parse_mode="HTML", reply_markup=kb)

# 1. Оплата подписки через встроенный платежный шлюз Telegram (Инвойс)
@dp.callback_query(F.data.startswith("pay_card_sub_"))
async def pay_card_subscription_callback(callback: types.CallbackQuery):
    sub_id = int(callback.data.split("_")[3])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, price, duration_days, deals_limit FROM subscriptions WHERE id = ?", (sub_id,))
    sub = cursor.fetchone()
    conn.close()
    
    if not sub:
        await callback.answer("Подписка не найдена", show_alert=True)
        return
        
    name, price, days, deals = sub
    amount_in_kopecks = int(price * 100) # Сумма в копейках/центах
    
    prices = [LabeledPrice(label=f"Подписка: {name}", amount=amount_in_kopecks)]
    
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Подписка: {name}",
        description=f"Доступ к заказам биржи рекламы на {days} дней. Лимит сделок: {deals}.",
        payload=f"sub_payment_{sub_id}",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter=f"subscription-{sub_id}"
    )
    await callback.answer()

# 2. Предварительная проверка платежа (обязательно для Telegram Payments)
@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# 3. Успешный платеж: активация подписки
@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):
    payment_info = message.successful_payment
    payload = payment_info.invoice_payload
    
    if payload.startswith("sub_payment_"):
        sub_id = int(payload.split("_")[2])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT duration_days, deals_limit FROM subscriptions WHERE id = ?", (sub_id,))
        sub = cursor.fetchone()
        
        if sub:
            days, deals = sub
            expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
            cursor.execute("""
                UPDATE users 
                SET subscription_id = ?, subscription_expires = ?, deals_left = ?
                WHERE user_id = ?
            """, (sub_id, expires, deals, message.from_user.id))
            conn.commit()
        conn.close()
        
        await message.answer("✅ <b>Оплата прошла успешно! Подписка активирована.</b>", parse_mode="HTML", reply_markup=main_menu_keyboard('executor'))

# 4. Оплата с внутреннего баланса пользователя
@dp.callback_query(F.data.startswith("pay_balance_sub_"))
async def pay_balance_subscription_callback(callback: types.CallbackQuery):
    sub_id = int(callback.data.split("_")[3])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT price, duration_days, deals_limit FROM subscriptions WHERE id = ?", (sub_id,))
    sub = cursor.fetchone()
    
    if not sub:
        conn.close()
        await callback.answer("Подписка не найдена", show_alert=True)
        return
        
    price, days, deals = sub
    user = get_user(callback.from_user.id)
    
    if user['balance'] < price:
        conn.close()
        await callback.answer(f"Недостаточно средств на балансе! Стоимость: {price} руб.", show_alert=True)
        return
        
    new_balance = user['balance'] - price
    expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    
    cursor.execute("""
        UPDATE users 
        SET balance = ?, subscription_id = ?, subscription_expires = ?, deals_left = ?
        WHERE user_id = ?
    """, (new_balance, sub_id, expires, deals, callback.from_user.id))
    conn.commit()
    conn.close()
    
    await callback.message.edit_text(f"✅ <b>Подписка успешно активирована за счет внутреннего баланса!</b>\nСрок действия до: {expires}\nЛимит сделок: {deals}")

# ==========================================
# РАБОТА С ЗАКАЗАМИ И АДМИН-ПАНЕЛЬЮ
# ==========================================

@dp.message(F.text == "💳 Моя подписка")
async def executor_subscriptions(message: types.Message):
    user = get_user(message.from_user.id)
    if user['role'] != 'executor':
        await message.answer("Этот раздел доступен только исполнителям.")
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, duration_days, deals_limit FROM subscriptions")
    subs = cursor.fetchall()
    conn.close()
    
    text = "💳 <b>Доступные тарифные планы подписок:</b>\n\nВыберите подписку для покупки, чтобы получать заказы:"
    kb = []
    for sub_id, name, price, days, deals in subs:
        kb.append([InlineKeyboardButton(text=f"📦 {name} — {price} руб. ({days} дн. / {deals} сделок)", callback_data=f"buy_sub_{sub_id}")])
        
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else types.InlineKeyboardMarkup(inline_keyboard=[]))

@dp.callback_query(F.data.startswith("buy_sub_"))
async def buy_subscription_callback(callback: types.CallbackQuery):
    sub_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT price, duration_days, deals_limit FROM subscriptions WHERE id = ?", (sub_id,))
    sub = cursor.fetchone()
    
    if not sub:
        conn.close()
        await callback.answer("Подписка не найдена", show_alert=True)
        return
        
    price, days, deals = sub
    user = get_user(callback.from_user.id)
    
    if user['balance'] < price:
        conn.close()
        await callback.answer(f"Недостаточно средств на балансе! Стоимость: {price} руб.", show_alert=True)
        return
        
    new_balance = user['balance'] - price
    expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    
    cursor.execute("""
        UPDATE users 
        SET balance = ?, subscription_id = ?, subscription_expires = ?, deals_left = ?
        WHERE user_id = ?
    """, (new_balance, sub_id, expires, deals, callback.from_user.id))
    conn.commit()
    conn.close()
    
    await callback.message.edit_text(f"✅ <b>Подписка успешно активирована!</b>\nСрок действия до: {expires}\nЛимит сделок: {deals}")

@dp.message(F.text == "📦 Доступные заказы")
async def available_tickets_handler(message: types.Message):
    user = get_user(message.from_user.id)
    if user['role'] != 'executor':
        await message.answer("Доступно только исполнителям.")
        return
        
    if not user['subscription_id'] or user['deals_left'] <= 0:
        await message.answer("⚠️ У вас нет активной подписки или закончился лимит сделок. Пожалуйста, оформите подписку в разделе «💳 Моя подписка».")
        return
        
    user_tags = [t.strip() for t in user['tags'].split(",") if t.strip()]
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, category_id, title, description, budget, created_at FROM tickets WHERE status = 'open'")
    all_tickets = cursor.fetchall()
    
    available = []
    for t_id, cat_id, title, desc, budget, created in all_tickets:
        cursor.execute("SELECT tag_slug FROM categories WHERE id = ?", (cat_id,))
        cat_tag_row = cursor.fetchone()
        cat_tag = cat_tag_row[0] if cat_tag_row else None
        
        if not cat_tag or cat_tag in user_tags:
            available.append((t_id, title, desc, budget, created))
            
    conn.close()
    
    if not available:
        await message.answer("📭 В данный момент нет открытых заказов, соответствующих вашим категориям/тегам.")
        return
        
    for t_id, title, desc, budget, created in available:
        text = (
            f"📌 <b>Заказ #{t_id}: {title}</b>\n\n"
            f"📝 Описание: {desc}\n"
            f"💰 Бюджет: <b>{budget} руб.</b>\n"
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
        await callback.answer("Заказ уже занят или удален.", show_alert=True)
        return
        
    client_id = ticket[1]
    
    cursor.execute("UPDATE tickets SET status = 'in_progress', executor_id = ? WHERE id = ?", (callback.from_user.id, t_id))
    cursor.execute("UPDATE users SET deals_left = deals_left - 1 WHERE user_id = ?", (callback.from_user.id,))
    conn.commit()
    conn.close()
    
    await callback.message.edit_text(f"✅ Вы успешно взяли заказ #{t_id} в работу! Свяжитесь с клиентом.")
    try:
        await bot.send_message(client_id, f"🎉 Ваш заказ #{t_id} взят в работу исполнителем @{callback.from_user.username or callback.from_user.full_name}!")
    except Exception:
        pass

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
        await message.answer("У вас пока нет активных или завершенных тикетов.")
        return
        
    for t in tickets:
        t_id, title, status, budget = t[0], t[1], t[2], t[3]
        text = f"📌 <b>Заказ #{t_id}: {title}</b>\nСтатус: <code>{status.upper()}</code>\nБюджет: {budget} руб."
        
        kb = []
        if user['role'] == 'client' and status == 'in_progress':
            kb.append([InlineKeyboardButton(text="✅ Подтвердить выполнение", callback_data=f"complete_ticket_{t_id}")])
            
        await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None)

@dp.callback_query(F.data.startswith("complete_ticket_"))
async def complete_ticket_callback(callback: types.CallbackQuery, state: FSMContext):
    t_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT executor_id, budget FROM tickets WHERE id = ? AND client_id = ?", (t_id, callback.from_user.id))
    ticket = cursor.fetchone()
    
    if not ticket:
        conn.close()
        await callback.answer("Заказ не найден", show_alert=True)
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
    await callback.message.answer("✅ Заказ отмечен как выполненный! Оцените работу исполнителя от 1 до 5 звезд:")

@dp.message(ReviewStates.entering_rating)
async def review_rating_entered(message: types.Message, state: FSMContext):
    try:
        rating = int(message.text)
        if not (1 <= rating <= 5):
            raise ValueError()
    except ValueError:
        await message.answer("Пожалуйста, введите целое число от 1 до 5.")
        return
        
    await state.update_data(rating=rating)
    await state.set_state(ReviewStates.entering_comment)
    await message.answer("Напишите текстовый отзыв о работе исполнителя:")

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
    await message.answer("⭐ Спасибо! Ваш отзыв успешно сохранен и учтен в рейтинге исполнителя.", reply_markup=main_menu_keyboard('client'))

# ==========================================
# АДМИН-ПАНЕЛЬ
# ==========================================

@dp.message(F.text == "⚙️ Админ-панель")
async def admin_panel_handler(message: types.Message):
    user = get_user(message.from_user.id)
    if not user or user['role'] != 'admin':
        await message.answer("У вас нет доступа к административной панели.")
        return
        
    await message.answer("⚙️ <b>Панель администратора биржи рекламы:</b>", parse_mode="HTML", reply_markup=admin_menu_keyboard())

@dp.callback_query(F.data == "adm_subs")
async def adm_subs_callback(callback: types.CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, duration_days, deals_limit FROM subscriptions")
    subs = cursor.fetchall()
    conn.close()
    
    text = "💼 <b>Управление тарифными подписками:</b>\n\n"
    kb = []
    for s_id, name, price, days, deals in subs:
        text += f"▪️ #{s_id} <b>{name}</b> — {price} руб. ({days} дн., {deals} сделок)\n"
        kb.append([InlineKeyboardButton(text=f"❌ Удалить подписку #{s_id}", callback_data=f"del_sub_{s_id}")])
        
    kb.append([InlineKeyboardButton(text="➕ Создать новую подписку", callback_data="add_sub")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад в админ-панель", callback_data="back_to_admin")])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin_callback(callback: types.CallbackQuery):
    await callback.message.edit_text("⚙️ <b>Панель администратора биржи рекламы:</b>", parse_mode="HTML", reply_markup=admin_menu_keyboard())

@dp.callback_query(F.data == "add_sub")
async def add_sub_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_sub_name)
    await callback.message.answer("Введите название нового тарифного плана:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_sub_name)
async def sub_name_entered(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AdminStates.waiting_for_sub_price)
    await message.answer("Введите стоимость подписки в рублях (число):")

@dp.message(AdminStates.waiting_for_sub_price)
async def sub_price_entered(message: types.Message, state: FSMContext):
    try:
        price = float(message.text)
    except ValueError:
        await message.answer("Введите корректное число.")
        return
    await state.update_data(price=price)
    await state.set_state(AdminStates.waiting_for_sub_days)
    await message.answer("Введите срок действия подписки в днях:")

@dp.message(AdminStates.waiting_for_sub_days)
async def sub_days_entered(message: types.Message, state: FSMContext):
    try:
        days = int(message.text)
    except ValueError:
        await message.answer("Введите целое число дней.")
        return
    await state.update_data(days=days)
    await state.set_state(AdminStates.waiting_for_sub_deals)
    await message.answer("Введите лимит сделок по данной подписке:")

@dp.message(AdminStates.waiting_for_sub_deals)
async def sub_deals_entered(message: types.Message, state: FSMContext):
    try:
        deals = int(message.text)
    except ValueError:
        await message.answer("Введите целое число сделок.")
        return
        
    data = await state.get_data()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO subscriptions (name, price, duration_days, deals_limit)
        VALUES (?, ?, ?, ?)
    """, (data['name'], data['price'], data['days'], deals))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ Подписка успешно создана!")

@dp.callback_query(F.data.startswith("del_sub_"))
async def delete_sub_callback(callback: types.CallbackQuery):
    sub_id = int(callback.data.split("_")[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
    conn.commit()
    conn.close()
    await callback.answer("Подписка удалена!")
    await adm_subs_callback(callback)

@dp.callback_query(F.data == "adm_catalog")
async def adm_catalog_callback(callback: types.CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, tag_slug FROM categories")
    cats = cursor.fetchall()
    conn.close()
    
    text = "📂 <b>Управление структурой каталога:</b>\n\n"
    kb = []
    for c_id, name, tag in cats:
        text += f"▪️ #{c_id} <b>{name}</b> (Тег: <code>{tag or 'нет'}</code>)\n"
        
    kb.append([InlineKeyboardButton(text="➕ Добавить категорию/раздел", callback_data="add_cat")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад в админ-панель", callback_data="back_to_admin")])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "add_cat")
async def add_cat_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_cat_name)
    await callback.message.answer("Введите название нового раздела/подраздела:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_cat_name)
async def cat_name_entered(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AdminStates.waiting_for_cat_desc)
    await message.answer("Введите описание раздела:")

@dp.message(AdminStates.waiting_for_cat_desc)
async def cat_desc_entered(message: types.Message, state: FSMContext):
    await state.update_data(desc=message.text)
    await state.set_state(AdminStates.waiting_for_cat_tag)
    await message.answer("Введите уникальный хештег/slug для ограничения исполнителей (например: tg_ads):")

@dp.message(AdminStates.waiting_for_cat_tag)
async def cat_tag_entered(message: types.Message, state: FSMContext):
    tag = message.text.strip()
    data = await state.get_data()
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO categories (name, description, tag_slug)
        VALUES (?, ?, ?)
    """, (data['name'], data['desc'], tag))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ Категория успешно добавлена в каталог!")

@dp.callback_query(F.data == "adm_users")
async def adm_users_callback(callback: types.CallbackQuery):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, full_name, role, commission_rate, tags FROM users")
    users = cursor.fetchall()
    conn.close()
    
    text = "👥 <b>Управление пользователями и комиссиями:</b>\n\n"
    kb = []
    for u_id, name, role, comm, tags in users[:10]:
        text += f"▪️ {name} (ID: <code>{u_id}</code>) | Роль: <b>{role}</b> | Ком.: {comm}% | Теги: {tags}\n"
        kb.append([InlineKeyboardButton(text=f"⚙️ Изменить комиссию/теги ID {u_id}", callback_data=f"edit_usr_{u_id}")])
        
    kb.append([InlineKeyboardButton(text="⬅️ Назад в админ-панель", callback_data="back_to_admin")])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("edit_usr_"))
async def edit_user_callback(callback: types.CallbackQuery, state: FSMContext):
    u_id = int(callback.data.split("_")[2])
    await state.update_data(target_user_id=u_id)
    await state.set_state(AdminStates.waiting_for_user_commission)
    await callback.message.answer("Введите новый процент комиссии для этого пользователя (например, 7.5):")
    await callback.answer()

@dp.message(AdminStates.waiting_for_user_commission)
async def user_commission_entered(message: types.Message, state: FSMContext):
    try:
        comm = float(message.text)
    except ValueError:
        await message.answer("Введите число.")
        return
    await state.update_data(commission=comm)
    await state.set_state(AdminStates.waiting_for_user_tags)
    await message.answer("Введите через запятую теги доступа для исполнителя (например: tg_ads,youtube):")

@dp.message(AdminStates.waiting_for_user_tags)
async def user_tags_entered(message: types.Message, state: FSMContext):
    tags = message.text.strip()
    data = await state.get_data()
    target_id = data['target_user_id']
    comm = data['commission']
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET commission_rate = ?, tags = ? WHERE user_id = ?
    """, (comm, tags, target_id))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("✅ Данные пользователя успешно обновлены!")

# ==========================================
# ЗАПУСК БОТА
# ==========================================

async def main():
    print("Бот «Биржа рекламы» с платежами успешно запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        import asyncio
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
