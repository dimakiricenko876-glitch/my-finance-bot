import logging
import sqlite3
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web  # Добавили для обмана Render

# 🔑 ТОКЕН ИЗ BOTFATHER
TOKEN = "8838512329:AAGzohl24qnx5X2_qurny0obXcpGNC5PEQU"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

EXPENSE_CATEGORIES = ["🛒 Продукты", "🚗  Транспорт", "🏠 Жилье", "🍔 Кафе/Еда", "🎬 Развлечения", "📦 Другое"]
INCOME_CATEGORIES = ["💰 Зарплата", "💼 Фриланс", "🎁 Подарок", "📈 Инвестиции"]

class FinanceStates(StatesGroup):
    choosing_category = State()

def init_db():
    with sqlite3.connect("finance.db") as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                category TEXT,
                date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

init_db()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 **Привет! Я твой финансовый трекер.**\n\n"
        "✏️ **Как записать операцию?**\n"
        "Отправь мне число со знаком:\n"
        "• `-350` — записать расход\n"
        "• `+45000` — записать доход\n\n"
        "📊 Посмотреть отчет: /stats"
    )

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    user_id = message.from_user.id
    with sqlite3.connect("finance.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT category, SUM(amount) FROM transactions WHERE user_id=? AND type='income' GROUP BY category", (user_id,))
        incomes = cur.fetchall()
        cur.execute("SELECT category, SUM(amount) FROM transactions WHERE user_id=? AND type='expense' GROUP BY category", (user_id,))
        expenses = cur.fetchall()

    total_income = sum(item for item in incomes) if incomes else 0
    total_expense = sum(item for item in expenses) if expenses else 0
    balance = total_income - total_expense

    text = "📊 **ВАША СТАТИСТИКА**\n─────────────────────\n\n🟢 **ДОХОДЫ:**\n"
    if incomes:
        for cat, amt in incomes: text += f"• {cat}: {amt:.2f}\n"
    else: text += "• Данных нет\n"
    text += f"👉 **Всего:** {total_income:.2f}\n\n🔴 **РАСХОДЫ:**\n"
    if expenses:
        for cat, amt in expenses: text += f"• {cat}: {amt:.2f}\n"
    else: text += "• Данных нет\n"
    text += f"👉 **Всего:** {total_expense:.2f}\n─────────────────────\n💰 **БАЛАНС: {balance:.2f}**"
    await message.answer(text)

@dp.callback_query(F.data == "cancel_action", FinanceStates.choosing_category)
async def process_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Запись операции отменена.")
    await callback.answer()

@dp.message(F.text)
async def process_amount_input(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not (text.startswith('-') or text.startswith('+')):
        await message.answer("⚠️ Ошибка! Начни сообщение с плюса или минуса. Пример: `-250` или `+1500` ")
        return
    try:
        t_type = "expense" if text.startswith('-') else "income"
        amount = float(text.replace('-', '').replace('+', '').replace(',', '.'))
        if amount <= 0:
            await message.answer("⚠️ Сумма должна быть больше нуля!")
            return
            
        await state.update_data(amount=amount, type=t_type)
        categories = EXPENSE_CATEGORIES if t_type == "expense" else INCOME_CATEGORIES
        builder = InlineKeyboardBuilder()
        for cat in categories:
            builder.button(text=cat, callback_data=f"cat:{cat}")
        builder.button(text="❌ Отмена", callback_data="cancel_action")
        builder.adjust(2)
        await state.set_state(FinanceStates.choosing_category)
        
        sign_text = "🔴 расход" if t_type == "expense" else "🟢 доход"
        await message.answer(f"Вы ввели {sign_text} на сумму **{amount:.2f}**.\n📁 Выберите категорию:", reply_markup=builder.as_markup())
    except ValueError:
        await message.answer("⚠️ Введите корректное число. Пример: `-150` ")

@dp.callback_query(F.data.startswith("cat:"), FinanceStates.choosing_category)
async def process_category_selection(callback: types.CallbackQuery, state: FSMContext):
    category = callback.data.split("cat:")
    user_data = await state.get_data()
    amount = user_data['amount']
    t_type = user_data['type']
    user_id = callback.from_user.id

    with sqlite3.connect("finance.db") as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO transactions (user_id, type, amount, category) VALUES (?, ?, ?, ?)", (user_id, t_type, amount, category))
        conn.commit()

    await state.clear()
    emoji = "🔴" if t_type == "expense" else "🟢"
    await callback.message.edit_text(f"✅ **Записано!**\n\n{emoji} Сумма: **{amount:.2f}**\n📁 Категория: **{category}**")
    await callback.answer()

# Функция веб-сервера для Render
async def handle(request):
    return web.Response(text="Bot is alive!")

async def main():
    # Запускаем фоновый веб-сервер, чтобы Render был доволен
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10000)
    asyncio.create_task(site.start())
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
    
