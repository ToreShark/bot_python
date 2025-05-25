import telebot
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from legal_engine import query
from datetime import datetime, timezone, timedelta
from telebot import types
from document_processor import process_uploaded_file
import time
import requests
from pydub import AudioSegment
import openai
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
    
    # Главное меню с современным дизайном
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Кнопки услуг
    lawyer_btn = types.InlineKeyboardButton(
        "⚖️ Консультация юриста (платно) 💰", 
        callback_data="lawyer_consultation"
    )
    credit_btn = types.InlineKeyboardButton(
        "📊 Проверить кредитный отчет (бесплатно) 🆓", 
        callback_data="check_credit_report"
    )
    
    # Информационные кнопки
    info_btn = types.InlineKeyboardButton(
        "ℹ️ О боте", 
        callback_data="bot_info"
    )
    
    markup.add(lawyer_btn, credit_btn, info_btn)
    
    # Приветственное сообщение
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

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    
    if call.data == "lawyer_consultation":
        handle_lawyer_consultation(call)
    elif call.data == "check_credit_report":
        handle_credit_report_request(call)
    elif call.data == "bot_info":
        handle_bot_info(call)
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
    
    bot.answer_callback_query(call.id)

def create_main_menu():
    """Создает разметку главного меню"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    lawyer_btn = types.InlineKeyboardButton(
        "⚖️ Консультация юриста (платно) 💰", 
        callback_data="lawyer_consultation"
    )
    credit_btn = types.InlineKeyboardButton(
        "📊 Проверить кредитный отчет (бесплатно) 🆓", 
        callback_data="check_credit_report"
    )
    info_btn = types.InlineKeyboardButton(
        "ℹ️ О боте", 
        callback_data="bot_info"
    )
    
    markup.add(lawyer_btn, credit_btn, info_btn)
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
            "⚖️ **Консультация юриста**\n\n"
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
                text=f"⚖️ **Режим консультации активирован**\n\n"
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
        "📞 **Поддержка:** +77007000000"
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

# Используем существующую функцию из document_processor

@bot.message_handler(content_types=['document'])
def handle_document(message):
    """Обработка документов (PDF для кредитных отчетов и чеки об оплате)"""
    user_id = message.from_user.id
    current_state = user_states.get(user_id)
    
    if current_state == "waiting_credit_report":
        # Обработка кредитного отчета
        handle_credit_report_pdf(message)
    else:
        # Обработка чека об оплате (существующая логика)
        handle_payment_receipt(message)

def handle_credit_report_pdf(message):
    """Обработка PDF файла кредитного отчета"""
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
            "⏳ Обрабатываю ваш кредитный отчет...\n📄 Извлекаю текст из PDF..."
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
            text="⏳ Обрабатываю ваш кредитный отчет...\n🔍 Анализирую содержимое..."
        )
        
        # Используем существующую функцию обработки документов
        result = process_uploaded_file(file_path, user_id)
        
        # Создаем кнопки для навигации
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu"))
        markup.add(types.InlineKeyboardButton("📊 Проверить другой отчет", callback_data="check_credit_report"))
        
        # Отправляем результат
        if result and "message" in result:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=f"✅ **Анализ завершен**\n\n{result['message']}",
                reply_markup=markup,
                parse_mode='Markdown'
            )
        else:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text="❌ Не удалось обработать файл.\nПроверьте, что это корректный кредитный отчет.",
                reply_markup=markup
            )
        
        # Удаляем временный файл
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"[WARN] Не удалось удалить файл {file_path}: {e}")
        
        # Сбрасываем состояние пользователя
        user_states.pop(user_id, None)
        
        # Логируем успешную обработку
        print(f"[INFO] Успешно обработан кредитный отчет пользователя {user_id}")
        
    except Exception as e:
        print(f"[ERROR] Ошибка при обработке кредитного отчета: {e}")
        try:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text="❌ Произошла ошибка при обработке отчета.\nПопробуйте позже или обратитесь к администратору."
            )
        except:
            bot.send_message(
                message.chat.id,
                "❌ Произошла ошибка при обработке отчета.\nПопробуйте позже или обратитесь к администратору."
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
                "📞 Вопросы: +77007000000"
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

@bot.message_handler(commands=['grant_access'])
def grant_access(message):
    """Предоставление доступа администратором"""
    ADMIN_USER_IDS = [376068212, 827743984]
    if message.from_user.id not in ADMIN_USER_IDS:
        bot.reply_to(message, "⛔ У вас нет прав для выполнения этой команды.")
        return

    try:
        _, user_id_str, limit_str = message.text.split()
        user_id = int(user_id_str)
        message_limit = int(limit_str)

        result = users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"access": True, "message_limit": message_limit}}
        )

        if result.matched_count == 0:
            bot.reply_to(message, f"❌ Пользователь с ID {user_id} не найден.")
            return

        # Уведомляем пользователя
        bot.send_message(
            user_id, 
            f"✅ **Доступ активирован!**\n\n"
            f"📝 Лимит консультаций: {message_limit}\n"
            f"⚖️ Используйте /start для начала работы.",
            parse_mode='Markdown'
        )
        bot.reply_to(message, f"✅ Доступ предоставлен пользователю {user_id}.")
        
    except Exception as e:
        print(f"[ERROR grant_access] {e}")
        bot.reply_to(
            message, 
            "⚠️ Ошибка. Формат: /grant_access [user_id] [количество_вопросов]"
        )

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
            "📵 Лимит консультаций исчерпан.\n\nОбратитесь к администратору: +77007000000"
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

# Запуск бота
if __name__ == "__main__":
    print("[INFO] Бот запущен...")
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            print(f"[ERROR] Polling crashed: {e}")
            time.sleep(5)