import logging
import sqlite3
import asyncio
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
from openpyxl import Workbook

# 🔑 ТОКЕН ИЗ BOTFATHER
TOKEN = "8838512329:AAGzohl24qnx5X2_qurny0obXcpGNC5PEQU"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Фиксированные категории по умолчанию
EXPENSE_CATEGORIES = ["🛒 Продукты", "🚗 Транспорт", "🏠 Жилье", "🍔 Кафе/Еда", "🎬 Развлечения", "📦 Другое"]
INCOME_CATEGORIES = ["💰 Зарплата", "💼 Фриланс", "🎁 Подарок", "📈 Инвестиции"]

class FinanceStates(StatesGroup):
    choosing_category = State()

def init_db():
    with sqlite3.connect("finance_v3.db") as conn:
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

def get_main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Посмотреть статистику", callback_data="menu_stats")
    builder.button(text="📉 Выгрузить отчет в Excel", callback_data="export_excel")
    builder.button(text="↩️ Удалить последнюю запись", callback_data="delete_last")
    builder.adjust(1)
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 **Привет! Это твой финансовый трекер.**\n\n"
        "🟢 Бот автоматически обнуляет баланс в начале каждого месяца и присылает вам готовый Excel-отчет за прошлый месяц!\n\n"
        "✏ " + "**Как записать операцию?**\n"
        "Просто отправь мне число со знаком:\n"
        "• `-500` — записать расход\n"
        "• `+2500` — записать доход",
        reply_markup=get_main_menu_keyboard()
    )
    
@dp.message(F.text & ~F.text.startswith('/'))
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
        if amount > 999999999.99:
            await message.answer("⚠️ Ошибка! Введена слишком большая сумма. Максимальный лимит: **999 999 999.99**")
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
    except (ValueError, OverflowError):
        await message.answer("⚠️ Введите корректное и реалистичное число. Пример: `-150` ")

@dp.callback_query(F.data.startswith("cat:"), FinanceStates.choosing_category)
async def process_category_selection(callback: types.CallbackQuery, state: FSMContext):
    category = callback.data.split("cat:")[1]
    user_data = await state.get_data()
    amount = user_data['amount']
    t_type = user_data['type']
    user_id = callback.from_user.id

    with sqlite3.connect("finance_v3.db") as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO transactions (user_id, type, amount, category) VALUES (?, ?, ?, ?)", (user_id, t_type, amount, category))
        conn.commit()

    await state.clear()
    emoji = "🔴" if t_type == "expense" else "🟢"
    await callback.message.edit_text(
        f"✅ **Записано!**\n\n{emoji} Сумма: **{amount:.2f}**\n📁 Категория: **{category}**", 
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "cancel_action", FinanceStates.choosing_category)
async def process_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Запись операции отменена.", reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "delete_last")
async def process_delete_last(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    with sqlite3.connect("finance_v3.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, type, amount, category FROM transactions WHERE user_id=? ORDER BY date DESC LIMIT 1", (user_id,))
        last_tx = cur.fetchone()
        
        if not last_tx:
            await callback.answer("У вас пока нет записей для удаления!", show_alert=True)
            return
            
        tx_id, t_type, amount, category = last_tx
        cur.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
        conn.commit()
        
    emoji = "🔴" if t_type == "expense" else "🟢"
    await callback.message.answer(f"🗑 **Успешно удалена последняя запись:**\n{emoji} {category}: {amount:.2f}", reply_markup=get_main_menu_keyboard())
    await callback.answer()
    
@dp.callback_query(F.data == "menu_stats")
async def process_stats_menu(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="🗓 За этот месяц", callback_data="stats:month")
    builder.button(text="📆 За сегодня", callback_data="stats:today")
    builder.button(text="🌍 За всё время", callback_data="stats:all")
    builder.button(text="🔙 В главное меню", callback_data="to_main")
    builder.adjust(1)
    await callback.message.edit_text("⏱ Выберите период для просмотра статистики:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("stats:"))
async def display_stats(callback: types.CallbackQuery):
    period = callback.data.split("stats:")[1]
    user_id = callback.from_user.id
    
    sql_time_clause = ""
    if period == "today":
        sql_time_clause = " AND date >= datetime('now', 'start of day')"
    elif period == "month":
        sql_time_clause = " AND date >= datetime('now', 'start of month')"

    with sqlite3.connect("finance_v3.db") as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT category, SUM(amount) FROM transactions WHERE user_id=? AND type='income' {sql_time_clause} GROUP BY category", (user_id,))
        incomes = cur.fetchall()
        cur.execute(f"SELECT category, SUM(amount) FROM transactions WHERE user_id=? AND type='expense' {sql_time_clause} GROUP BY category", (user_id,))
        expenses = cur.fetchall()

    total_income = sum(item[1] for item in incomes) if incomes else 0
    total_expense = sum(item[1] for item in expenses) if expenses else 0
    balance = total_income - total_expense

    period_titles = {"today": "за сегодня", "month": "за этот месяц (текущий)", "all": "за всё время"}
    text = f"📊 **СТАТИСТИКА ({period_titles[period].upper()})**\n─────────────────────\n\n🟢 **ДОХОДЫ:**\n"
    if incomes:
        for cat, amt in incomes: text += f"• {cat}: {amt:.2f}\n"
    else: text += "• Нет данных\n"
    text += f"👉 **Всего получено:** {total_income:.2f}\n\n🔴 **РАСХОДЫ:**\n"
    if expenses:
        for cat, amt in expenses: text += f"• {cat}: {amt:.2f}\n"
    else: text += "• Нет данных\n"
    text += f"👉 **Всего потрачено:** {total_expense:.2f}\n─────────────────────\n💰 **БАЛАНС: {balance:.2f}**"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад к периодам", callback_data="menu_stats")
    builder.button(text="🏠 В меню", callback_data="to_main")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

def generate_excel_report(user_id, sql_time_clause):
    with sqlite3.connect("finance_v3.db") as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT date, type, amount, category FROM transactions WHERE user_id=? {sql_time_clause} ORDER BY date ASC", (user_id,))
        rows = cur.fetchall()
    
    if not rows:
        return None
        
    wb = Workbook()
    ws = wb.active
    ws.title = "Транзакции"
    ws.append(["Дата и Время", "Тип операции", "Сумма", "Категория"])
    
    for row in rows:
        ru_type = "Расход" if row[1] == "expense" else "Доход"
        ws.append([row[0], ru_type, row[2], row[3]])
        
    filename = f"report_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    wb.save(filename)
    return filename

@dp.callback_query(F.data == "export_excel")
async def process_export_excel(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    filename = generate_excel_report(user_id, "")
    
    if not filename:
        await callback.answer("⚠️ В базе данных пока нет операций!", show_alert=True)
        return
        
    input_file = types.FSInputFile(filename)
    await callback.message.answer_document(document=input_file, caption="📊 Держи твой полный финансовый отчет!")
    if os.path.exists(filename):
        os.remove(filename)
    await callback.answer()

@dp.callback_query(F.data == "to_main")
async def process_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu_keyboard())
    await callback.answer()

async def monthly_report_scheduler():
    while True:
        now = datetime.now()
        if now.month == 12:
            next_month = datetime(now.year + 1, 1, 1, 0, 1)
        else:
            next_month = datetime(now.year, now.month + 1, 1, 0, 1)
            
        sleep_seconds = (next_month - now).total_seconds()
        logging.info(f"Планировщик отчетов спит {sleep_seconds} секунд до следующего месяца.")
        
        await asyncio.sleep(max(sleep_seconds, 1))
        
        logging.info("Наступил новый месяц! Формируем автоматические отчеты...")
        prev_month_date = datetime.now() - timedelta(days=5)
        last_month_str = prev_month_date.strftime('%Y-%m')
        sql_last_month = f" AND date LIKE '{last_month_str}%'"
        
        with sqlite3.connect("finance_v3.db") as conn:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT user_id FROM transactions")
            users = cur.fetchall()
            
            for user in users:
                user_id = user[0]
                cur.execute(f"SELECT SUM(amount) FROM transactions WHERE user_id=? AND type='income' {sql_last_month}", (user_id,))
                inc_res = cur.fetchone()
                inc = inc_res[0] if inc_res and inc_res[0] else 0
                
                cur.execute(f"SELECT SUM(amount) FROM transactions WHERE user_id=? AND type='expense' {sql_last_month}", (user_id,))
                exp_res = cur.fetchone()
                exp = exp_res[0] if exp_res and exp_res[0] else 0
                
                if inc == 0 and exp == 0:
                    continue
                    
                filename = generate_excel_report(user_id, sql_last_month)
                
                try:
                    month_name = prev_month_date.strftime('%B %Y')
                    text = (
                        f"🏁 **ИТОГОВЫЙ ОТЧЕТ ЗА ПРОШЛЫЙ МЕСЯЦ ({month_name.upper()})**\n"
                        f"─────────────────────────────\n"
                        f"🟢 Всего получено: **{inc:.2f}**\n"
                        f"🔴 Всего потрачено: **{exp:.2f}**\n"
                        f"💰 Чистый остаток: **{inc - exp:.2f}**\n\n"
                        f"📥 Ниже прикреплен файл Excel со всеми транзакциями за месяц.\n"
                        f"✨ Текущий баланс в меню /stats обнулен и начал новый отсчет!"
                    )
                    
                    if filename:
                        input_file = types.FSInputFile(filename)
                        await bot.send_document(chat_id=user_id, document=input_file, caption=text)
                        os.remove(filename)
                    else:
                        await bot.send_message(chat_id=user_id, text=text)
                except Exception as e:
                    logging.error(f"Не удалось отправить отчет пользователю {user_id}: {e}")
                    
        await asyncio.sleep(60)

async def handle(request):
    return web.Response(text="Monthly Scheduled Bot is active!")

async def main():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10000)
    asyncio.create_task(site.start())
    asyncio.create_task(monthly_report_scheduler())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
    
    

    
            
