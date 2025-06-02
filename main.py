import telebot
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bankruptcy_calculator import analyze_credit_report_for_bankruptcy
from legal_engine import query
from datetime import datetime, timezone, timedelta
from telebot import types
from document_processor import process_uploaded_file
from credit_parser import format_summary
import time
import requests
from pydub import AudioSegment
import openai
from creditor_handler import process_all_creditors_request

# Парсер кредитных отчетов уже интегрирован в document_processor

load_dotenv()

print(f"[INFO] Текущий режим: {os.getenv('ENV', 'prod')}")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

# Подключение к MongoDB Atlas
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)

# Выбор базы данных и коллекции
db = client['telegram_bot']
users_collection = db['users']

# Простая антивандальная структура: последний доступ
user_last_access = {}
user_states = {}  # Для отслеживания состояний пользователей
def send_long_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
    """Отправляет длинные сообщения по частям"""
    
    MAX_LENGTH = 4000  # Максимум символов в одном сообщении
    
    # Если сообщение короткое - отправляем как обычно
    if len(text) <= MAX_LENGTH:
        bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return
    
    # Если длинное - разбиваем на части
    parts = []
    lines = text.split('\n')  # Разбиваем по строкам
    current_part = ""
    
    for line in lines:
        # Проверяем, поместится ли строка
        if len(current_part + line) <= MAX_LENGTH:
            if current_part:
                current_part += '\n'
            current_part += line
        else:
            # Сохраняем текущую часть и начинаем новую
            if current_part:
                parts.append(current_part)
            current_part = line
    
    # Добавляем последнюю часть
    if current_part:
        parts.append(current_part)
    
    # Отправляем все части по очереди
    for i, part in enumerate(parts):
        # Кнопки добавляем только к последнему сообщению
        markup = reply_markup if i == len(parts) - 1 else None
        
        bot.send_message(
            chat_id=chat_id,
            text=part,
            reply_markup=markup,
            parse_mode=parse_mode
        )
        
        # Небольшая пауза между сообщениями
        import time
        time.sleep(0.3)

@bot.message_handler(commands=['start'])
def main(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    # Проверка: есть ли пользователь в базе
    existing_user = users_collection.find_one({"user_id": user_id})
    if not existing_user:
        # Добавляем нового пользователя
        users_collection.insert_one({
            "user_id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "access": False,
            "message_limit": 0,
            "messages": []
        })
    # 🛠 Заменили ручную разметку на универсальную
    markup = create_main_menu()
    
    welcome_text = (
        f"👋 Добро пожаловать, {first_name}!\n\n"
        "🤖 Я ваш персональный юридический ассистент.\n"
        "Выберите нужную услугу:"
    )
    
    bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=markup
    )
    
    # Уведомление админу
    ADMIN_USER_IDS = [376068212, 827743984]
    if user_id not in ADMIN_USER_IDS:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        admin_text = (
            "🆕 Новый пользователь:\n"
            f"👤 Имя: {first_name} {last_name}\n"
            f"🆔 ID: {user_id}\n"
            f"🕒 Время: {timestamp}"
        )
        for admin_id in ADMIN_USER_IDS:
            try:
                bot.send_message(admin_id, admin_text)
            except Exception as e:
                print(f"[WARN] Не удалось отправить сообщение админу {admin_id}: {e}")

# @bot.callback_query_handler(func=lambda call: True)
# def handle_callback_query(call):
#     user_id = call.from_user.id
    
#     if call.data == "lawyer_consultation":
#         handle_lawyer_consultation(call)
#     elif call.data == "check_credit_report":
#         handle_credit_report_request(call)
#     elif call.data == "bankruptcy_calculator":
#         handle_bankruptcy_calculator(call)
#     elif call.data == "bot_info":
#         handle_bot_info(call)
#     elif call.data.startswith("pay_"):
#         handle_payment_callback(call)
#     elif call.data == "back_to_menu":
#         # Возврат в главное меню
#         main_menu_markup = create_main_menu()
#         bot.edit_message_text(
#             chat_id=call.message.chat.id,
#             message_id=call.message.message_id,
#             text="🏠 Главное меню\nВыберите нужную услугу:",
#             reply_markup=main_menu_markup
#         )
    
#     bot.answer_callback_query(call.id)

def create_main_menu():
    """Создает разметку главного меню"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    lawyer_btn = types.InlineKeyboardButton(
        "⚖️ Переписка (платно) 💰",
        callback_data="lawyer_consultation"
    )
    credit_btn = types.InlineKeyboardButton(
        "📊 Проверить кредитный отчет (бесплатно) 🆓", 
        callback_data="check_credit_report"
    )
    bankruptcy_btn = types.InlineKeyboardButton(
        "🧮 Банкротный калькулятор (бесплатно) 🆓", 
        callback_data="bankruptcy_calculator"
    )
    creditors_list_btn = types.InlineKeyboardButton(
        "📋 Список кредиторов PDF (бесплатно) 🆓",
        callback_data="creditors_list"
    )
    info_btn = types.InlineKeyboardButton(
        "ℹ️ О боте", 
        callback_data="bot_info"
    )
    
    markup.add(lawyer_btn, credit_btn, bankruptcy_btn, creditors_list_btn, info_btn)
    return markup

def handle_lawyer_consultation(call):
    """Обработка запроса на консультацию юриста"""
    user_id = call.from_user.id
    user = users_collection.find_one({"user_id": user_id})
    
    if not user or not user.get("access", False):
        # Показываем варианты оплаты
        markup = types.InlineKeyboardMarkup()
        
        markup.add(types.InlineKeyboardButton("💰 5 000 ₸ - 10 вопросов", callback_data="pay_5000"))
        markup.add(types.InlineKeyboardButton("💰 10 000 ₸ - 25 вопросов", callback_data="pay_10000"))
        markup.add(types.InlineKeyboardButton("💰 15 000 ₸ - 50 вопросов", callback_data="pay_15000"))
        markup.add(types.InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu"))
        
        payment_text = (
            "⚖️ **Переписка**\n\n" 
            "💡 Получите профессиональную юридическую помощь:\n"
            "• Анализ договоров\n"
            "• Консультации по трудовому праву\n"
            "• Семейные споры\n"
            "• Защита прав потребителей\n\n"
            "💳 Выберите подходящий тариф:"
        )
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=payment_text,
            reply_markup=markup,
            parse_mode='Markdown'
        )
    else:
        # Проверяем лимит сообщений
        if user.get("message_limit", 0) <= 0:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="📵 Ваш лимит консультаций исчерпан.\n\nОбратитесь к администратору для пополнения.",
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")
                )
            )
        else:
            # Активируем режим консультации
            user_states[user_id] = "lawyer_consultation"
            
            remaining = user.get("message_limit", 0)
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"⚖️ **Режим переписки активирован**\n\n"
                     f"📝 Осталось вопросов: {remaining}\n\n"
                     f"✍️ Опишите вашу ситуацию подробно, и я дам юридическую консультацию.",
                parse_mode='Markdown',
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")
                )
            )

def handle_credit_report_request(call):
    """Обработка запроса на проверку кредитного отчета"""
    user_id = call.from_user.id
    user_states[user_id] = "waiting_credit_report"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❓ Как получить отчет?", callback_data="how_to_get_report"))
    markup.add(types.InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu"))
    
    instruction_text = (
        "📊 **Проверка кредитного отчета**\n\n"
        "📄 Отправьте PDF файл вашего кредитного отчета из:\n"
        "• Государственного кредитного бюро (ГКБ)\n"
        "• Первого кредитного бюро (ПКБ)\n\n"
        "🎯 Я проанализирую отчет и предоставлю:\n"
        "• Общую сумму задолженности\n"
        "• Список всех кредиторов\n"
        "• Информацию о просрочках\n"
        "• Ежемесячную нагрузку\n\n"
        "📎 **Отправьте PDF файл прямо сейчас**"
    )
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=instruction_text,
        reply_markup=markup,
        parse_mode='Markdown'
    )

def handle_bot_info(call):
    """Показать информацию о боте"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu"))
    
    info_text = (
        "ℹ️ **О боте**\n\n"
        "🤖 Я - ваш персональный юридический ассистент с функцией анализа кредитных отчетов.\n\n"
        "**Мои возможности:**\n"
        "⚖️ Юридические консультации (платно)\n"
        "📊 Анализ кредитных отчетов (бесплатно)\n"
        "🎤 Работа с голосовыми сообщениями\n\n"
        "**Поддерживаемые форматы отчетов:**\n"
        "• ГКБ (Государственное кредитное бюро)\n"
        "• ПКБ (Первое кредитное бюро)\n"
        "• Казахский и русский языки\n\n"
        "📞 **Поддержка:** +77027568921"
    )
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=info_text,
        reply_markup=markup,
        parse_mode='Markdown'
    )

def handle_payment_callback(call):
    """Обработка выбора суммы оплаты"""
    amount_map = {
        "pay_5000": ("5 000", "10 вопросов"),
        "pay_10000": ("10 000", "25 вопросов"),
        "pay_15000": ("15 000", "50 вопросов")
    }
    
    amount, questions = amount_map.get(call.data, ("неизвестная сумма", "0 вопросов"))
    
    if amount == "неизвестная сумма":
        bot.answer_callback_query(call.id, "⚠️ Ошибка: сумма не распознана.")
        return
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад к тарифам", callback_data="lawyer_consultation"))
    
    payment_text = (
        f"💳 **Оплата {amount} ₸**\n"
        f"📝 Количество вопросов: {questions}\n\n"
        f"🏦 **Для оплаты используйте:**\n"
        f"💳 Kaspi: https://pay.kaspi.kz/pay/izbl0ktq\n\n"
        f"📸 После оплаты пришлите скриншот чека."
    )
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=payment_text,
        reply_markup=markup,
        parse_mode='Markdown'
    )

    # Добавить эту функцию после handle_payment_callback

def handle_bankruptcy_calculator(call):
    """Обработка запроса на банкротный калькулятор"""
    user_id = call.from_user.id
    user_states[user_id] = "waiting_bankruptcy_report"  # Специальное состояние

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❓ Как получить отчет?", callback_data="how_to_get_report"))
    markup.add(types.InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu"))

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            "🧮 **Банкротный калькулятор**\n\n"
            "📄 Загрузите PDF файл вашего кредитного отчета из ПКБ или ГКБ.\n\n"
            "🔍 **Система определит:**\n"
            "• Подходит ли внесудебное банкротство\n"
            "• Требуется ли судебное банкротство  \n"
            "• Возможно ли восстановление платежеспособности\n\n"
            "📊 **Анализируемые критерии:**\n"
            "• Общая сумма долга (порог 6,291,200 ₸)\n"
            "• Количество дней просрочки (минимум 365)\n"
            "• Наличие залогового имущества\n\n"
            "📎 **Отправьте PDF файл прямо сейчас**"
        ),
        reply_markup=markup,
        parse_mode='Markdown'
    )

def handle_creditors_list_request(call):
    """Обработка запроса на создание списка кредиторов"""
    user_id = call.from_user.id
    user_states[user_id] = "waiting_creditors_list"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❓ Как получить отчет?", callback_data="how_to_get_report"))
    markup.add(types.InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu"))
    
    instruction_text = (
        "📋 **Список кредиторов PDF**\n\n"
        "📄 Отправьте PDF файл вашего кредитного отчета из ГКБ или ПКБ.\n\n"
        "🎯 **Что получите:**\n"
        "• Один PDF-документ со сводной таблицей всех кредиторов\n"
        "• Номера договоров и суммы задолженности\n"
        "• Даты образования долгов\n"
        "• Статусы просрочек\n"
        "• Готовый документ для банкротства\n\n"
        "💡 **Отличие от обычной проверки:**\n"
        "• Не генерирует отдельные заявления кредиторам\n"
        "• Создает только сводный список в одном PDF\n"
        "• Идеально для приложения к заявлению о банкротстве\n\n"
        "📎 **Отправьте PDF файл прямо сейчас**"
    )
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=instruction_text,
        reply_markup=markup,
        parse_mode='Markdown'
    )
# Используем существующую функцию из document_processor

# Также нужно обновить функцию handle_document для поддержки банкротного режима:
@bot.message_handler(content_types=['document'])
def handle_document(message):
    """Обработка документов (PDF для кредитных отчетов и чеки об оплате)"""
    user_id = message.from_user.id
    current_state = user_states.get(user_id)
    
    if current_state in ["waiting_credit_report", "waiting_bankruptcy_report"]:
        # Обработка кредитного отчета (включая банкротный анализ)
        handle_credit_report_pdf(message)
    elif current_state == "waiting_creditors_list":  # ⭐ НОВОЕ УСЛОВИЕ
        # Обработка создания списка кредиторов
        handle_creditors_list_pdf(message)
    else:
        # Обработка чека об оплате (существующая логика)
        handle_payment_receipt(message)

# Добавить в main.py

# Модифицировать функцию handle_credit_report_pdf:
def handle_credit_report_pdf(message):
    """Обработка PDF файла кредитного отчета с генерацией заявлений И банкротным анализом"""
    user_id = message.from_user.id
    current_state = user_states.get(user_id)
    
    # Определяем тип обработки по состоянию пользователя
    is_bankruptcy_mode = current_state == "waiting_bankruptcy_report"
    
    try:
        # Проверяем, что это PDF файл
        file_name = message.document.file_name
        if not file_name or not file_name.lower().endswith('.pdf'):
            bot.reply_to(
                message, 
                "⚠️ Пожалуйста, отправьте PDF файл кредитного отчета."
            )
            return
        
        # Отправляем сообщение о начале обработки
        if is_bankruptcy_mode:
            status_msg = bot.send_message(
                message.chat.id, 
                "⏳ Анализирую ваш кредитный отчет для определения процедуры банкротства...\n📄 Извлекаю текст из PDF..."
            )
        else:
            status_msg = bot.send_message(
                message.chat.id, 
                "⏳ Обрабатываю ваш кредитный отчет...\n📄 Извлекаю текст из PDF..."
            )
        
        # Сохраняем файл во временную папку
        file_info = bot.get_file(message.document.file_id)
        file_path = f"temp/{file_name}"
        os.makedirs("temp", exist_ok=True)
        
        with open(file_path, "wb") as f:
            f.write(bot.download_file(file_info.file_path))
        
        # Обновляем статус
        if is_bankruptcy_mode:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text="⏳ Анализирую ваш кредитный отчет для определения процедуры банкротства...\n🧮 Рассчитываю банкротные критерии..."
            )
        else:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text="⏳ Обрабатываю ваш кредитный отчет...\n🔍 Анализирую содержимое..."
            )
        
        # Импортируем необходимые модули
        from text_extractor import extract_text_from_pdf
        from ocr import ocr_file
        from credit_parser import extract_credit_data_with_total
        
        # Извлекаем текст из PDF
        text = extract_text_from_pdf(file_path)
        if not text.strip():
            text = ocr_file(file_path)
        
        # Парсим кредитный отчет
        parsed_data = extract_credit_data_with_total(text)
        
        # 🆕 ДОБАВИТЬ ЭТИ СТРОКИ - СОХРАНЕНИЕ В БД:
        # Сохраняем в БД (однократно)  
        try:
            process_uploaded_file(file_path, user_id)
            print(f"[INFO] Кредитный отчет пользователя {user_id} сохранен в БД")
        except Exception as save_error:
            print(f"[ERROR] Ошибка сохранения в БД: {save_error}")

        if is_bankruptcy_mode:
            # РЕЖИМ БАНКРОТНОГО КАЛЬКУЛЯТОРА
            
            # Проводим анализ банкротства
            bankruptcy_analysis = analyze_credit_report_for_bankruptcy(parsed_data)
            
            # Создаем кнопки для навигации
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu"))
            markup.add(types.InlineKeyboardButton("📊 Проверить другой отчет", callback_data="bankruptcy_calculator"))
            
            # Отправляем результат банкротного анализа
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text="✅ **Банкротный анализ завершен**",
                parse_mode='Markdown'
            )
            
            # Отправляем детальный анализ
            send_long_message(
                bot=bot,   
                chat_id=message.chat.id,
                text=bankruptcy_analysis,
                reply_markup=markup,
                parse_mode='Markdown'
            )
            
        else:
            # ОБЫЧНЫЙ РЕЖИМ ПРОВЕРКИ КРЕДИТНОГО ОТЧЕТА
            
            # Обновляем статус для генерации заявлений
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text="⏳ Анализ завершен! Генерирую заявления к кредиторам..."
            )
            
            # ЗАМЕНИТЕ старый блок try/except на этот новый:
            try:
                from credit_application_generator import generate_applications_from_parsed_data
                result = generate_applications_from_parsed_data(parsed_data, user_id)
                print(f"[INFO] Результат генерации: статус={result.get('status')}, заявлений={result.get('applications_count', 0)}")
            except Exception as generation_error:
                print(f"[ERROR] Ошибка генерации заявлений: {generation_error}")
                import traceback
                traceback.print_exc()
                # Fallback - используем стандартную обработку
                result = {
                    "status": "error",
                    "message": format_summary(parsed_data),
                    "type": "credit_report",
                    "applications": [],
                    "applications_count": 0
                }
            
            # Создаем кнопки для навигации
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu"))
            markup.add(types.InlineKeyboardButton("📊 Проверить другой отчет", callback_data="check_credit_report"))
            markup.add(types.InlineKeyboardButton("🧮 Банкротный калькулятор", callback_data="bankruptcy_calculator"))
            
            # Отправляем анализ кредитного отчета
            if result and "message" in result:
                
                # ДОБАВЬТЕ эту проверку статуса в самом начале:
                if result.get('status') == 'error':
                    # Если ошибка генерации, все равно показываем анализ отчета
                    send_long_message(
                        bot=bot,
                        chat_id=message.chat.id,
                        text=f"✅ **Анализ завершен**\n\n{result['message']}\n\n⚠️ Заявления не сгенерированы из-за ошибки.",
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                    # Показываем банкротный анализ
                    bankruptcy_analysis = analyze_credit_report_for_bankruptcy(parsed_data)
                    bot.send_message(
                        chat_id=message.chat.id,
                        text=f"🧮 **ДОПОЛНИТЕЛЬНО: Банкротный анализ**\n\n{bankruptcy_analysis}",
                        parse_mode='Markdown'
                    )
                    
                else:
                    # ОРИГИНАЛЬНЫЙ КОД остается БЕЗ ИЗМЕНЕНИЙ:
                    send_long_message(
                        bot=bot,
                        chat_id=message.chat.id,
                        text=f"✅ **Анализ завершен**\n\n{result['message']}",
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                
                # Отправляем сгенерированные заявления (если есть)
                if result.get('applications'):
                    applications = result['applications']
                    bot.send_message(
                        chat_id=message.chat.id,
                        text=f"📄 Генерирую {len(applications)} заявлений к кредиторам..."
                    )
                    
                    # Отправляем каждое заявление как отдельный PDF
                    for i, app in enumerate(applications, 1):
                        try:
                            temp_pdf_path = f"temp/application_{i}_{user_id}.pdf"
                            with open(temp_pdf_path, 'wb') as f:
                                f.write(app['content'])
                            
                            with open(temp_pdf_path, 'rb') as pdf_file:
                                bot.send_document(
                                    chat_id=message.chat.id,
                                    document=pdf_file,
                                    caption=f"📋 Заявление #{i}: {app['creditor']}\n💰 Сумма долга: {app['debt_amount']:,.2f} ₸",
                                    visible_file_name=app['filename']
                                )
                            
                            # Удаляем временный файл
                            try:
                                os.remove(temp_pdf_path)
                            except:
                                pass
                                
                        except Exception as e:
                            print(f"[ERROR] Ошибка отправки заявления {i}: {e}")
                    
                    # # ДОБАВЛЯЕМ БАНКРОТНЫЙ АНАЛИЗ после основного анализа
                    # bankruptcy_analysis = analyze_credit_report_for_bankruptcy(parsed_data)
                    
                    # bot.send_message(
                    #     chat_id=message.chat.id,
                    #     text=f"🧮 **ДОПОЛНИТЕЛЬНО: Банкротный анализ**\n\n{bankruptcy_analysis}",
                    #     parse_mode='Markdown'
                    # )
                    
                    # Итоговое сообщение
                    bot.send_message(
                        chat_id=message.chat.id,
                        text=f"✅ **Готово!**\n\n"
                             f"📊 Отчет проанализирован\n"
                             f"📄 Отправлено {len(applications)} заявлений\n"
                             f"🧮 Проведен банкротный анализ\n\n"
                             f"💡 **Что делать дальше:**\n"
                             f"1. Распечатайте заявления\n"  
                             f"2. Подпишите и поставьте дату\n"
                             f"3. Отправьте кредиторам по почте\n"
                             f"4. Рассмотрите рекомендации по банкротству",
                        parse_mode='Markdown'
                    )
                else:
                    # Если заявления не сгенерированы, все равно показываем банкротный анализ
                    bankruptcy_analysis = analyze_credit_report_for_bankruptcy(parsed_data)
                    
                    bot.send_message(
                        chat_id=message.chat.id,
                        text=f"🧮 **ДОПОЛНИТЕЛЬНО: Банкротный анализ**\n\n{bankruptcy_analysis}",
                        parse_mode='Markdown'
                    )
            else:
                bot.send_message(
                    chat_id=message.chat.id,
                    text="❌ Не удалось обработать файл.\nПроверьте, что это корректный кредитный отчет.",
                    reply_markup=markup
                )
        
        # Удаляем исходный временный файл
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"[WARN] Не удалось удалить файл {file_path}: {e}")
        
        # Удаляем сообщение о статусе
        try:
            bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        except:
            pass
        
        # Сбрасываем состояние пользователя
        user_states.pop(user_id, None)
        
        # Логируем успешную обработку
        mode = "банкротного анализа" if is_bankruptcy_mode else "кредитного отчета"
        print(f"[INFO] Успешно обработан {mode} пользователя {user_id}")
        
    except Exception as e:
        print(f"[ERROR] Ошибка при обработке: {e}")
        import traceback
        traceback.print_exc()
        try:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=f"❌ Произошла ошибка: {str(e)}\nПопробуйте позже или обратитесь к администратору."
            )
        except:
            bot.send_message(
                message.chat.id,
                f"❌ Произошла ошибка: {str(e)}\nПопробуйте позже или обратитесь к администратору."
            )

def handle_creditors_list_pdf(message):
    """Обработка PDF файла для создания списка кредиторов"""
    user_id = message.from_user.id
    
    try:
        # Проверяем, что это PDF файл
        file_name = message.document.file_name
        if not file_name or not file_name.lower().endswith('.pdf'):
            bot.reply_to(
                message, 
                "⚠️ Пожалуйста, отправьте PDF файл кредитного отчета."
            )
            return
        
        # Отправляем сообщение о начале обработки
        status_msg = bot.send_message(
            message.chat.id, 
            "⏳ Создаю список кредиторов...\n📄 Извлекаю данные из PDF..."
        )
        
        # Сохраняем файл во временную папку
        file_info = bot.get_file(message.document.file_id)
        file_path = f"temp/{file_name}"
        os.makedirs("temp", exist_ok=True)
        
        with open(file_path, "wb") as f:
            f.write(bot.download_file(file_info.file_path))
        
        # Обновляем статус
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text="⏳ Создаю список кредиторов...\n🔍 Анализирую кредиторов..."
        )
        
        # Обрабатываем файл через нашу функцию
        result = process_all_creditors_request(file_path, user_id)
        
        # Обновляем статус
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text="⏳ Создаю список кредиторов...\n📄 Генерирую PDF документ..."
        )
        
        if result["status"] == "success":
            # Отправляем сгенерированный PDF
            pdf_path = result["pdf_path"]
            creditors_count = result["creditors_count"]
            
            with open(pdf_path, 'rb') as pdf_file:
                bot.send_document(
                    chat_id=message.chat.id,
                    document=pdf_file,
                    caption=f"📋 **Список кредиторов**\n\n"
                           f"👥 Найдено кредиторов: {creditors_count}\n"
                           f"📄 Готово для приложения к заявлению о банкротстве\n\n"
                           f"💡 **Как использовать:**\n"
                           f"1. Распечатайте документ\n"
                           f"2. Приложите к заявлению о банкротстве\n"
                           f"3. Подайте в суд или используйте для процедуры",
                    visible_file_name="Список_кредиторов.pdf",
                    parse_mode='Markdown'
                )
            
            # Создаем кнопки для навигации
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu"))
            markup.add(types.InlineKeyboardButton("📋 Создать еще один список", callback_data="creditors_list"))
            markup.add(types.InlineKeyboardButton("🧮 Банкротный калькулятор", callback_data="bankruptcy_calculator"))
            
            # Финальное сообщение
            bot.send_message(
                chat_id=message.chat.id,
                text="✅ **Список кредиторов готов!**\n\n"
                     "📋 PDF документ содержит полную информацию о всех ваших кредиторах.\n"
                     "🎯 Этот документ можно использовать в процедуре банкротства.",
                reply_markup=markup,
                parse_mode='Markdown'
            )
            
            # Удаляем временный PDF
            try:
                os.remove(pdf_path)
            except:
                pass
                
        else:
            # Обработка ошибок
            error_message = result.get("message", "Неизвестная ошибка")
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu"))
            markup.add(types.InlineKeyboardButton("🔄 Попробовать снова", callback_data="creditors_list"))
            
            bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ **Ошибка создания списка**\n\n"
                     f"📝 {error_message}\n\n"
                     f"💡 **Возможные причины:**\n"
                     f"• Неподдерживаемый формат отчета\n"
                     f"• Отчет поврежден или пустой\n"
                     f"• Отсутствуют данные о кредиторах",
                reply_markup=markup,
                parse_mode='Markdown'
            )
        
        # Удаляем исходный файл
        try:
            os.remove(file_path)
        except:
            pass
        
        # Удаляем сообщение о статусе
        try:
            bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        except:
            pass
        
        # Сбрасываем состояние пользователя
        user_states.pop(user_id, None)
        
        # Логируем успешную обработку
        print(f"[INFO] Создан список кредиторов для пользователя {user_id}")
        
    except Exception as e:
        print(f"[ERROR] Ошибка создания списка кредиторов: {e}")
        import traceback
        traceback.print_exc()
        
        try:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=f"❌ Произошла ошибка: {str(e)}\nПопробуйте позже или обратитесь к администратору."
            )
        except:
            bot.send_message(
                message.chat.id,
                f"❌ Произошла ошибка: {str(e)}\nПопробуйте позже или обратитесь к администратору."
            )

def handle_payment_receipt(message):
    """Обработка чека об оплате (существующая логика)"""
    user_id = message.from_user.id
    file_info = bot.get_file(message.document.file_id)
    file_name = message.document.file_name
    file_path = f"temp/{file_name}"
    os.makedirs("temp", exist_ok=True)
    
    with open(file_path, "wb") as f:
        f.write(bot.download_file(file_info.file_path))

    try:
        result = process_uploaded_file(file_path, user_id)
        
        if "message" in result:
            bot.send_message(message.chat.id, result["message"])

        if result["type"] == "payment_receipt":
            bot.send_message(
                message.chat.id,
                "✅ Спасибо! Чек получен и передан на проверку.\n\n"
                "⏰ Доступ будет активирован в течение 1 часа.\n"
                "📞 Вопросы: +77027568921"
            )

    except Exception as e:
        print(f"[ERROR] Ошибка обработки файла: {e}")
        bot.send_message(message.chat.id, "⚠️ Ошибка при обработке файла. Попробуйте позже.")
    finally:
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"[WARN] Не удалось удалить файл {file_path}: {e}")

    # Уведомление админов
    ADMIN_USER_IDS = [376068212, 827743984]
    caption = (
        f"📩 Получен чек об оплате:\n"
        f"👤 Пользователь: {user_id}\n"
        f"📎 Файл: {file_name}"
    )

    for admin_id in ADMIN_USER_IDS:
        try:
            bot.forward_message(
                chat_id=admin_id, 
                from_chat_id=message.chat.id, 
                message_id=message.message_id
            )
            bot.send_message(admin_id, caption)
        except Exception as e:
            print(f"[WARN] Не удалось переслать файл админу {admin_id}: {e}")

# Добавить эти функции в main.py

@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    """Массовая рассылка сообщений всем пользователям (только для администраторов)"""
    ADMIN_USER_IDS = [376068212, 827743984]
    if message.from_user.id not in ADMIN_USER_IDS:
        bot.reply_to(message, "⛔ У вас нет прав для выполнения этой команды.")
        return

    try:
        # Извлекаем текст сообщения после команды
        command_parts = message.text.split(' ', 1)
        if len(command_parts) < 2:
            bot.reply_to(
                message, 
                "⚠️ Формат: /broadcast [текст сообщения]\n\n"
                "Пример: /broadcast 🎉 Новые функции доступны!"
            )
            return
            
        broadcast_text = command_parts[1]
        
        # Получаем всех пользователей из базы данных
        all_users = list(users_collection.find({}, {"user_id": 1, "first_name": 1}))
        
        if not all_users:
            bot.reply_to(message, "❌ В базе данных нет пользователей.")
            return
        
        # Отправляем подтверждение админу
        confirmation_text = (
            f"📢 **Подтверждение рассылки**\n\n"
            f"👥 Количество получателей: {len(all_users)}\n"
            f"📝 Текст сообщения:\n{broadcast_text}\n\n"
            f"⚠️ Отправить всем?"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Отправить", callback_data=f"confirm_broadcast"),
            types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_broadcast")
        )
        
        # Сохраняем текст рассылки для использования в callback
        user_states[message.from_user.id] = {
            "type": "broadcast_confirmation",
            "text": broadcast_text,
            "users": all_users
        }
        
        bot.send_message(
            message.chat.id,
            confirmation_text,
            reply_markup=markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"[ERROR broadcast] {e}")
        bot.reply_to(message, f"❌ Ошибка при подготовке рассылки: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data in ["confirm_broadcast", "cancel_broadcast"])
def handle_broadcast_callback(call):
    """Обработка подтверждения/отмены рассылки"""
    ADMIN_USER_IDS = [376068212, 827743984]
    if call.from_user.id not in ADMIN_USER_IDS:
        bot.answer_callback_query(call.id, "⛔ Доступ запрещен")
        return
        
    user_state = user_states.get(call.from_user.id)
    if not user_state or user_state.get("type") != "broadcast_confirmation":
        bot.answer_callback_query(call.id, "⚠️ Сессия истекла")
        return
    
    if call.data == "cancel_broadcast":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ Рассылка отменена."
        )
        user_states.pop(call.from_user.id, None)
        bot.answer_callback_query(call.id, "Рассылка отменена")
        return
    
    # Подтверждение рассылки
    broadcast_text = user_state["text"]
    all_users = user_state["users"]
    
    # Обновляем сообщение на статус отправки
    status_msg = bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"📤 Отправляю рассылку...\n👥 Пользователей: {len(all_users)}\n📊 Отправлено: 0"
    )
    
    # Отправляем сообщения
    sent_count = 0
    failed_count = 0
    
    for i, user in enumerate(all_users):
        try:
            user_id = user["user_id"]
            
            # Создаем кнопку "В главное меню" для каждого сообщения рассылки
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu"))
            
            bot.send_message(
                chat_id=user_id,
                text=broadcast_text,
                reply_markup=markup,
                parse_mode='Markdown'
            )
            
            sent_count += 1
            
            # Обновляем прогресс каждые 5 отправленных сообщений
            if (i + 1) % 5 == 0:
                try:
                    bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=status_msg.message_id,
                        text=f"📤 Отправляю рассылку...\n👥 Пользователей: {len(all_users)}\n📊 Отправлено: {sent_count}"
                    )
                except:
                    pass
            
            # Небольшая пауза чтобы не превысить лимиты Telegram API
            time.sleep(0.1)
            
        except Exception as e:
            failed_count += 1
            print(f"[WARN] Не удалось отправить сообщение пользователю {user.get('user_id', 'unknown')}: {e}")
    
    # Итоговый отчет
    final_report = (
        f"✅ **Рассылка завершена**\n\n"
        f"📊 **Статистика:**\n"
        f"👥 Всего пользователей: {len(all_users)}\n"
        f"✅ Успешно отправлено: {sent_count}\n"
        f"❌ Ошибок: {failed_count}\n\n"
        f"📝 **Отправленный текст:**\n{broadcast_text}"
    )
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=status_msg.message_id,
        text=final_report,
        parse_mode='Markdown'
    )
    
    # Очищаем состояние
    user_states.pop(call.from_user.id, None)
    bot.answer_callback_query(call.id, f"Рассылка завершена! Отправлено: {sent_count}")

# Также нужно обновить обработчик callback_query_handler, добавив новые условия:

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    
    if call.data == "lawyer_consultation":
        handle_lawyer_consultation(call)
    elif call.data == "check_credit_report":
        handle_credit_report_request(call)
    elif call.data == "bankruptcy_calculator":
        handle_bankruptcy_calculator(call)
    elif call.data == "creditors_list":  # ⭐ НОВАЯ СТРОКА
        handle_creditors_list_request(call)
    elif call.data == "bot_info":
        handle_bot_info(call)
    elif call.data == "how_to_get_report":
        handle_how_to_get_report(call)
    elif call.data.startswith("pay_"):
        handle_payment_callback(call)
    elif call.data == "back_to_menu":
        # Возврат в главное меню
        main_menu_markup = create_main_menu()
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="🏠 Главное меню\nВыберите нужную услугу:",
            reply_markup=main_menu_markup
        )
    # ДОБАВИТЬ ЭТИ СТРОКИ:
    elif call.data in ["confirm_broadcast", "cancel_broadcast"]:
        handle_broadcast_callback(call)
    
    bot.answer_callback_query(call.id)

# Пример текста для первой рассылки о новых функциях:
ANNOUNCEMENT_TEXT = """🎉 **НОВЫЕ ФУНКЦИИ В БОТЕ!**

🆕 **Что добавилось:**

📄 **Автогенерация досудебных писем**
• При анализе кредитного отчета бот теперь автоматически создает персональные письма ко всем вашим кредиторам
• Готовые PDF документы для отправки по почте
• Полностью бесплатно!

🧮 **Банкротный калькулятор** 
• Определяет подходящую процедуру банкротства
• Анализирует критерии для внесудебного/судебного банкротства
• Рекомендации по восстановлению платежеспособности

✨ **Как использовать:**
Нажмите /start и выберите нужную услугу из обновленного меню!

💡 Все функции анализа кредитных отчетов остаются бесплатными."""

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Обработка всех остальных сообщений"""
    user_id = message.from_user.id
    current_state = user_states.get(user_id)
    
    if current_state == "lawyer_consultation":
        # Обработка вопроса к юристу
        handle_lawyer_question(message)
    elif current_state == "waiting_credit_report":
        # Пользователь в режиме ожидания кредитного отчета
        bot.reply_to(
            message,
            "📊 Пожалуйста, отправьте PDF файл кредитного отчета.\n"
            "Текстовые сообщения не обрабатываются в этом режиме."
        )
    else:
        # Предлагаем воспользоваться главным меню
        markup = create_main_menu()
        bot.send_message(
            message.chat.id,
            "🤖 Используйте команду /start или выберите услугу:",
            reply_markup=markup
        )

def handle_lawyer_question(message):
    """Обработка вопроса к юристу"""
    user_id = message.from_user.id
    text = message.text
    now = datetime.now(timezone.utc)

    user = users_collection.find_one({"user_id": user_id})

    if not user or not user.get("access", False):
        bot.send_message(
            message.chat.id, 
            "⛔ Доступ не активирован. Воспользуйтесь /start для оплаты."
        )
        user_states.pop(user_id, None)
        return

    if user.get("message_limit", 0) <= 0:
        bot.send_message(
            message.chat.id, 
            "📵 Лимит консультаций исчерпан.\n\nОбратитесь к администратору: +77027568921"
        )
        user_states.pop(user_id, None)
        return

    # Проверки ограничений (как в оригинальном коде)
    ADMIN_USER_IDS = [376068212, 827743984]
    if user_id not in ADMIN_USER_IDS:
        today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        message_count = users_collection.count_documents({
            "user_id": user_id,
            "messages.timestamp": {"$gte": today_start.isoformat()}
        })

        if message_count >= 3:
            bot.send_message(message.chat.id, "📵 Лимит: не более 3 вопросов в сутки.")
            return

    # Ограничение по частоте (5 минут)
    if user_id in user_last_access:
        last_time = user_last_access[user_id]
        if now - last_time < timedelta(minutes=5):
            bot.send_message(message.chat.id, "⏳ Подождите 5 минут перед следующим вопросом.")
            return
    user_last_access[user_id] = now

    # Сохраняем сообщение
    users_collection.update_one(
        {"user_id": user_id},
        {"$push": {
            "messages": {
                "text": text,
                "timestamp": datetime.utcnow().isoformat()
            }
        }}
    )

    # Обрабатываем вопрос
    try:
        status_msg = bot.send_message(message.chat.id, "⌛ Анализирую ваш вопрос...")

        def progress_callback(stage_text):
            try:
                bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=status_msg.message_id,
                    text=stage_text
                )
            except Exception as e:
                print(f"[WARN] Не удалось обновить статус: {e}")

        # Получаем ответ от юридического движка
        answer = query(text, progress_callback=progress_callback)

        # Сохраняем ответ
        users_collection.update_one(
            {"user_id": user_id},
            {"$push": {
                "answers": {
                    "text": answer,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            }}
        )
        
        # Уменьшаем лимит
        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"message_limit": -1}}
        )
        
        # Отправляем ответ
        remaining = user.get("message_limit", 1) - 1
        final_answer = f"{answer}\n\n📝 Осталось вопросов: {remaining}"
        
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text=final_answer
        )
        
    except Exception as e:
        print(f"[ERROR] {e}")
        bot.send_message(
            message.chat.id, 
            "❌ Произошла ошибка при обработке. Попробуйте позже."
        )

@bot.message_handler(content_types=['voice'])
def handle_voice_message(message):
    """Обработка голосовых сообщений (только для юридических консультаций)"""
    user_id = message.from_user.id
    current_state = user_states.get(user_id)
    
    if current_state != "lawyer_consultation":
        bot.reply_to(
            message,
            "🎤 Голосовые сообщения принимаются только в режиме юридических консультаций.\n"
            "Используйте /start для выбора услуги."
        )
        return
    
    # Существующий код обработки голосовых сообщений...
    # (можно скопировать из оригинального кода)
def handle_how_to_get_report(call):
    """Инструкция по получению кредитного отчета"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
    
    instruction_text = (
        "📋 **Как получить кредитный отчет**\n\n"
        
        "🌐 **Официальный сайт:** https://id.mkb.kz/#/auth\n\n"
        
        "⚠️ **ВАЖНО:** Используйте только **персональный кредитный отчет** с этого сайта!\n\n"
        
        "📋 **Пошаговая инструкция:**\n"
        "1. Перейдите на сайт ГКБ: https://id.mkb.kz/#/auth\n"
        "2. Зарегистрируйтесь или войдите в личный кабинет\n"
        "3. Найдите раздел 'Персональный кредитный отчет'\n"
        "4. Выберите язык: **русский** (рекомендуется)\n"
        "5. Скачайте отчет в формате PDF\n\n"
        
        "✅ **Почему именно этот отчет:**\n"
        "• Содержит актуальную информацию\n"
        "• Правильный формат для анализа ботом\n"
        "• Показывает все активные кредиты и долги\n\n"
        
        "❌ **Не подходят:**\n"
        "• Отчеты с других сайтов\n"
        "• Устаревшие версии отчетов\n"
        "• Скриншоты или фото экрана\n\n"
        
        "🛡️ **Гарантия качества:** Бот корректно анализирует только официальные персональные отчеты с ГКБ."
    )
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=instruction_text,
        reply_markup=markup,
        parse_mode='Markdown'
    )
# Запуск бота
if __name__ == "__main__":
    print("[INFO] Бот запущен...")
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            print(f"[ERROR] Polling crashed: {e}")
            time.sleep(5)