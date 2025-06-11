import telebot
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from admin_consultation import AdminConsultationManager, ConsultationNotificationScheduler
from bankruptcy_calculator import analyze_credit_report_for_bankruptcy
from collateral_parser import extract_collateral_info
from legal_engine import query
from datetime import datetime, timezone, timedelta
from telebot import types
from document_processor import process_uploaded_file
from credit_parser import FallbackParser, GKBParser, PKBParser, format_summary
import time
import requests
from pydub import AudioSegment
import openai
from creditor_handler import process_all_creditors_request
from smart_handler import SmartHandler

# Парсер кредитных отчетов уже интегрирован в document_processor

load_dotenv()

print(f"[INFO] Текущий режим: {os.getenv('ENV', 'prod')}")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
CHANNEL_ID = -1002275474152  # ID канала для проверки связи
smart_handler = SmartHandler(bot)

notification_scheduler = ConsultationNotificationScheduler(bot)

# Подключение к MongoDB Atlas
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)

# Выбор базы данных и коллекции
db = client['telegram_bot']
users_collection = db['users']

# Коллекции для курсов (добавить эти строки)
courses_collection = db['courses']
lessons_collection = db['lessons'] 
course_access_collection = db['course_access']
user_progress_collection = db['user_progress']
# Коллекции для системы консультаций
consultation_slots_collection = db['consultation_slots']
consultation_queue_collection = db['consultation_queue']
temp_videos_collection = db['temp_videos']

# Простая антивандальная структура: последний доступ
user_last_access = {}
user_states = {}  # Для отслеживания состояний пользователей
def get_available_consultation_slots():
    """Получает доступные слоты консультаций на ближайшие 3 понедельника"""
    from datetime import datetime, timedelta

    available_slots = []
    
    # Находим ближайшие 3 понедельника
    today = datetime.now()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0 and today.hour >= 17:  # Если уже поздно в понедельник
        days_until_monday = 7

    for week in range(3):  # Ближайшие 3 недели
        monday_date = today + timedelta(days=days_until_monday + (week * 7))
        date_str = monday_date.strftime("%Y-%m-%d")
        date_formatted = monday_date.strftime("%d.%m.%Y")
        
        for hour in [14, 15, 16]:  # слоты на 14:00, 15:00, 16:00
            slot_id = f"{date_str}_{hour:02d}:00"
            time_display = f"{hour:02d}:00-{hour+1:02d}:00"

            # Проверка существующего слота
            existing_slot = consultation_slots_collection.find_one({"slot_id": slot_id})
            
            if not existing_slot:
                consultation_slots_collection.insert_one({
                    "date": date_str,
                    "time_slot": time_display,
                    "slot_id": slot_id,
                    "status": "open",
                    "max_capacity": 1,
                    "created_at": datetime.utcnow(),
                    "admin_notes": ""
                })
            
            # Проверяем статус и очередь
            slot = consultation_slots_collection.find_one({"slot_id": slot_id})
            if slot and slot["status"] == "open":
                queue_count = consultation_queue_collection.count_documents({
                    "slot_id": slot_id,
                    "status": {"$nin": ["cancelled", "completed"]}
                })

                available_slots.append({
                    "slot_id": slot_id,
                    "date": date_str,
                    "date_formatted": date_formatted,
                    "time_display": time_display,
                    "queue_length": queue_count
                })

    return available_slots

def handle_slot_booking(call):
    """Обработка записи пользователя на конкретный слот"""
    user_id = call.from_user.id
    first_name = call.from_user.first_name or "Пользователь"
    last_name = call.from_user.last_name or ""
    user_name = f"{first_name} {last_name}".strip()
    
    slot_id = call.data.replace("book_slot_", "")

    # ✅ НОВАЯ ПРОВЕРКА: записан ли пользователь на ЛЮБУЮ консультацию
    any_active_booking = consultation_queue_collection.find_one({
        "user_id": user_id,                              # ← ЛЮБОЙ слот этого пользователя
        "status": {"$nin": ["cancelled", "completed"]}   # ← активные записи
    })
    
    if any_active_booking:
        # Получаем информацию о существующей записи
        existing_slot_id = any_active_booking["slot_id"]
        date_str, time_str = existing_slot_id.split("_")
        slot_date = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = slot_date.strftime("%d.%m.%Y")
        end_hour = int(time_str.split(':')[0]) + 1
        time_display = f"{time_str}-{end_hour:02d}:00"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📋 Мои записи", callback_data="my_consultations"))
        markup.add(types.InlineKeyboardButton("🔙 Назад к слотам", callback_data="free_consultation"))
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="⚠️ **Вы уже записаны на консультацию**\n\n"
                 f"📅 Дата: {formatted_date}\n"
                 f"🕐 Время: {time_display}\n"
                 f"📍 Место в очереди: {any_active_booking['position']}\n"
                 f"📊 Статус: {get_status_text(any_active_booking['status'])}\n\n"
                 f"💡 Можно записаться только на одну консультацию.\n"
                 f"Отмените текущую запись, чтобы выбрать другое время.",
            reply_markup=markup,
            parse_mode='Markdown'
        )
        return
    
    # Проверка: не записан ли уже пользователь
    existing_booking = consultation_queue_collection.find_one({
        "slot_id": slot_id,
        "user_id": user_id,
        "status": {"$nin": ["cancelled", "completed"]}
    })
    
    if existing_booking:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад к слотам", callback_data="free_consultation"))
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="⚠️ **Вы уже записаны на эту консультацию**\n\n"
                 f"📍 Ваше место в очереди: {existing_booking['position']}\n"
                 f"📊 Статус: {get_status_text(existing_booking['status'])}",
            reply_markup=markup,
            parse_mode='Markdown'
        )
        return
    
    # Проверяем доступность слота
    slot = consultation_slots_collection.find_one({"slot_id": slot_id})
    if not slot or slot["status"] != "open":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад к слотам", callback_data="free_consultation"))
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ **Слот недоступен**\n\n"
                 "Этот временной слот закрыт или отменен.",
            reply_markup=markup,
            parse_mode='Markdown'
        )
        return
    
    # Запись в очередь
    queue_size = consultation_queue_collection.count_documents({
        "slot_id": slot_id,
        "status": {"$nin": ["cancelled", "completed"]}
    })
    new_position = queue_size + 1

    consultation_queue_collection.insert_one({
        "slot_id": slot_id,
        "user_id": user_id,
        "user_name": user_name,
        "position": new_position,
        "status": "waiting",
        "registered_at": datetime.utcnow(),
        "confirmed_day_at": None,
        "confirmed_hour_at": None,
        "notifications_sent": {
            "day_before": False,
            "hour_before": False
        }
    })

    # Отображаем пользователю запись
    date_str, time_str = slot_id.split("_")
    slot_date = datetime.strptime(date_str, "%Y-%m-%d")
    formatted_date = slot_date.strftime("%d.%m.%Y")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📋 Мои записи", callback_data="my_consultations"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu"))
    
    pos_text = "первые" if new_position == 1 else f"{new_position}-е место"
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="✅ **Запись успешна!**\n\n"
             f"📅 Дата: {formatted_date} (понедельник)\n"
             f"🕐 Время: {time_str}-{int(time_str.split(':')[0]) + 1:02d}:00\n"
             f"📍 Ваше место: {pos_text}\n\n"
             "📲 Мы отправим вам напоминания:\n"
             "• За день до консультации\n"
             "• За час до консультации\n\n"
             "💡 Обязательно подтверждайте участие!",
        reply_markup=markup,
        parse_mode='Markdown'
    )

def get_status_text(status):
    """Преобразует статус в читаемый текст"""
    status_map = {
        "waiting": "Ожидание",
        "confirmed_day": "Подтвержден (за день)",
        "confirmed_hour": "Подтвержден (за час)",
        "cancelled": "Отменен",
        "completed": "Завершен"
    }
    return status_map.get(status, "Неизвестно")

def handle_my_consultations(call):
    """Показывает записи пользователя на консультации"""
    user_id = call.from_user.id

    # Получаем активные записи
    user_bookings = list(consultation_queue_collection.find({
        "user_id": user_id,
        "status": {"$nin": ["cancelled", "completed"]}
    }).sort("registered_at", 1))

    if not user_bookings:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📅 Записаться", callback_data="free_consultation"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="📋 **Мои записи**\n\n"
                 "У вас нет активных записей на консультации.\n"
                 "Хотите записаться?",
            reply_markup=markup,
            parse_mode='Markdown'
        )
        return

    # Формируем текст
    bookings_text = "📋 **Мои записи на консультации:**\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)

    for booking in user_bookings:
        slot_id = booking["slot_id"]
        date_str, time_str = slot_id.split("_")
        slot_date = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = slot_date.strftime("%d.%m.%Y")
        end_hour = int(time_str.split(':')[0]) + 1
        time_display = f"{time_str}-{end_hour:02d}:00"
        status_text = get_status_text(booking["status"])
        position = booking["position"]

        bookings_text += f"📅 **{formatted_date}** в **{time_display}**\n"
        bookings_text += f"📍 Место в очереди: {position}\n"
        bookings_text += f"📊 Статус: {status_text}\n"

        now = datetime.now()
        consultation_dt = datetime.combine(slot_date.date(), datetime.strptime(time_str, "%H:%M").time())
        if consultation_dt > now:
            delta = consultation_dt - now
            days = delta.days
            hours = delta.seconds // 3600
            if days > 0:
                bookings_text += f"⏰ Через {days} дн. {hours} ч.\n"
            elif hours > 0:
                bookings_text += f"⏰ Через {hours} ч.\n"
            else:
                bookings_text += f"⏰ Скоро!\n"
        
        bookings_text += "\n"

        markup.add(types.InlineKeyboardButton(
            f"❌ Отменить {formatted_date} {time_str}",
            callback_data=f"cancel_booking_{booking['_id']}"
        ))

    markup.add(types.InlineKeyboardButton("📅 Записаться еще", callback_data="free_consultation"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu"))

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=bookings_text,
        reply_markup=markup,
        parse_mode='Markdown'
    )

def handle_cancel_booking(call):
    """Отменяет запись пользователя и продвигает очередь"""
    from bson import ObjectId
    user_id = call.from_user.id
    booking_id = call.data.replace("cancel_booking_", "")

    try:
        booking = consultation_queue_collection.find_one({
            "_id": ObjectId(booking_id),
            "user_id": user_id
        })

        if not booking:
            bot.answer_callback_query(call.id, "❌ Запись не найдена")
            return

        slot_id = booking["slot_id"]
        cancelled_position = booking["position"]

        consultation_queue_collection.update_one(
            {"_id": ObjectId(booking_id)},
            {
                "$set": {
                    "status": "cancelled",
                    "cancelled_at": datetime.utcnow()
                }
            }
        )

        consultation_queue_collection.update_many(
            {
                "slot_id": slot_id,
                "position": {"$gt": cancelled_position},
                "status": {"$nin": ["cancelled", "completed"]}
            },
            {"$inc": {"position": -1}}
        )

        promoted_users = list(consultation_queue_collection.find({
            "slot_id": slot_id,
            "position": {"$lte": cancelled_position},
            "status": {"$nin": ["cancelled", "completed"]},
            "user_id": {"$ne": user_id}
        }))

        for promoted_user in promoted_users:
            try:
                date_str, time_str = slot_id.split("_")
                slot_date = datetime.strptime(date_str, "%Y-%m-%d")
                formatted_date = slot_date.strftime("%d.%m.%Y")
                end_hour = int(time_str.split(':')[0]) + 1
                time_display = f"{time_str}-{end_hour:02d}:00"
                new_position = promoted_user["position"]

                if new_position == 1:
                    msg = (
                        f"🎉 **Отличная новость!**\n\n"
                        f"Вы стали первым в очереди на консультацию!\n\n"
                        f"📅 Дата: {formatted_date}\n"
                        f"🕐 Время: {time_display}\n\n"
                        f"📲 Мы пришлем вам напоминания перед консультацией."
                    )
                else:
                    msg = (
                        f"📈 **Вы продвинулись в очереди!**\n\n"
                        f"📅 Дата: {formatted_date}\n"
                        f"🕐 Время: {time_display}\n"
                        f"📍 Новое место: {new_position}\n\n"
                        f"🎯 Вы стали ближе к консультации!"
                    )

                bot.send_message(promoted_user["user_id"], msg, parse_mode='Markdown')

            except Exception as e:
                print(f"[ERROR] Не удалось уведомить пользователя {promoted_user['user_id']}: {e}")

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📋 Мои записи", callback_data="my_consultations"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu"))

        date_str, time_str = slot_id.split("_")
        slot_date = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = slot_date.strftime("%d.%m.%Y")
        end_hour = int(time_str.split(':')[0]) + 1
        time_display = f"{time_str}-{end_hour:02d}:00"

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ **Запись отменена**\n\n"
                 f"📅 Отменена консультация: {formatted_date} в {time_display}\n\n"
                 "👥 Очередь автоматически продвинута.\n"
                 "📲 Участники уведомлены о изменениях.",
            reply_markup=markup,
            parse_mode='Markdown'
        )

        print(f"[INFO] Пользователь {user_id} отменил запись на {slot_id}, позиция {cancelled_position}")

    except Exception as e:
        print(f"[ERROR] Ошибка отмены записи: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка при отмене записи")

def confirm_consultation_participation(call, booking_id, stage):
    """Обрабатывает подтверждение участия пользователем"""
    from bson import ObjectId
    booking = consultation_queue_collection.find_one({"_id": ObjectId(booking_id)})

    if not booking or booking["status"] != "waiting":
        bot.answer_callback_query(call.id, "❌ Запись не найдена или уже неактуальна")
        return

    update = {"status": f"confirmed_{stage}"}
    if stage == "day":
        update["confirmed_day_at"] = datetime.utcnow()
    elif stage == "hour":
        update["confirmed_hour_at"] = datetime.utcnow()

    consultation_queue_collection.update_one(
        {"_id": ObjectId(booking_id)},
        {"$set": update}
    )

    bot.answer_callback_query(call.id, "✅ Участие подтверждено!")
    bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)

def cancel_consultation_booking(call, booking_id, reason):
    """Обрабатывает отмену записи пользователем и запускает продвижение очереди"""
    from bson import ObjectId
    booking = consultation_queue_collection.find_one({"_id": ObjectId(booking_id)})

    if not booking:
        bot.answer_callback_query(call.id, "❌ Запись не найдена")
        return

    slot_id = booking["slot_id"]

    consultation_queue_collection.update_one(
        {"_id": ObjectId(booking_id)},
        {"$set": {
            "status": "cancelled",
            "cancelled_at": datetime.utcnow(),
            "cancelled_reason": reason
        }}
    )

    # Продвигаем очередь
    try:
        from consultation_scheduler import ConsultationScheduler
        scheduler = ConsultationScheduler()
        scheduler.promote_queue(slot_id, reason=reason)
    except Exception as e:
        print(f"[ERROR] Не удалось продвинуть очередь: {e}")

    bot.answer_callback_query(call.id, "✅ Запись отменена")
    bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)

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

@bot.message_handler(commands=['slots_today'])
def view_today_slots(message):
    ADMIN_USER_IDS = [376068212, 827743984]
    if message.from_user.id not in ADMIN_USER_IDS:
        bot.send_message(message.chat.id, "⛔️ У вас нет доступа.")
        return

    from admin_consultation import AdminConsultationManager
    manager = AdminConsultationManager(bot, user_states)
    manager.show_today_slots(message)

@bot.message_handler(commands=["admin_consultations"])
def handle_admin_consultations(message):
    from admin_consultation import AdminConsultationManager
    manager = AdminConsultationManager(bot, user_states)
    manager.show_admin_menu(message)

@bot.message_handler(commands=['admin'])
def handle_admin_command(message):
    from admin_consultation import AdminConsultationManager
    manager = AdminConsultationManager(bot, user_states)
    manager.show_admin_menu(message)

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
    consultation_btn = types.InlineKeyboardButton(
        "📅 Бесплатная консультация 🆓",
        callback_data="free_consultation"
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
    courses_btn = types.InlineKeyboardButton(
        "🎥 Видео-курсы", 
        callback_data="video_courses"
    )
    info_btn = types.InlineKeyboardButton(
        "ℹ️ О боте", 
        callback_data="bot_info"
    )
    
    markup.add(lawyer_btn, credit_btn, bankruptcy_btn, creditors_list_btn, consultation_btn, info_btn, courses_btn)
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
            "• Банкротство физичесикх лиц в Казахстане\n"
            "• Восстановление платежеспособности\n"
            "• Внесудебное банкротство\n"
            "• Судебное банкротство\n\n"
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

def handle_free_consultation_request(call):
    """Обработка запроса на бесплатную консультацию"""
    user_id = call.from_user.id
    user_states[user_id] = "selecting_consultation_slot"
    
    # Получаем доступные слоты на ближайшие понедельники
    available_slots = get_available_consultation_slots()
    
    if not available_slots:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu"))
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="📅 **Бесплатная консультация**\n\n"
                 "❌ К сожалению, на ближайшие недели все слоты заняты.\n"
                 "Попробуйте позже или воспользуйтесь платной консультацией.",
            reply_markup=markup,
            parse_mode='Markdown'
        )
        return
    
    # Создаем кнопки с доступными слотами
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for slot in available_slots:
        slot_text = f"📅 {slot['date_formatted']} в {slot['time_display']}"
        if slot['queue_length'] > 0:
            slot_text += f" (очередь: {slot['queue_length']})"
        
        markup.add(types.InlineKeyboardButton(
            slot_text,
            callback_data=f"book_slot_{slot['slot_id']}"
        ))
    
    markup.add(types.InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu"))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="📅 **Бесплатная консультация**\n\n"
             "🕐 **Расписание:** Каждый понедельник с 14:00 до 17:00\n"
             "⏱️ **Длительность:** 1 час\n"
             "📋 **Формат:** Telegram чат с юристом\n\n"
             "Выберите удобное время:",
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
        
        # # Извлекаем текст из PDF
        # text = extract_text_from_pdf(file_path)
        # if not text.strip():
        #     text = ocr_file(file_path)
        
        # # Парсим кредитный отчет
        # parsed_data = extract_credit_data_with_total(text)
        if is_bankruptcy_mode:
            # 🧮 БАНКРОТНЫЙ КАЛЬКУЛЯТОР: используем GKBParser для точности
            # print(f"[INFO] Банкротный режим: используем цепочку парсеров для файла {file_path}")
            
            # Импортируем цепочку парсеров (как в document_processor.py)
            from text_extractor import extract_text_from_pdf
            from ocr import ocr_file
            
            
            # Извлекаем текст из PDF
            text = extract_text_from_pdf(file_path)
            if not text.strip():
                text = ocr_file(file_path)
            
            # Создаем цепочку парсеров (как в document_processor.py)
            gkb_parser = GKBParser()
            pkb_parser = PKBParser()
            fallback_parser = FallbackParser()
            
            # Устанавливаем цепочку: GKB -> PKB -> Emergency
            gkb_parser.set_next(pkb_parser).set_next(fallback_parser)
            
            # Запускаем парсинг через цепочку
            # print(f"[INFO] Запускаем цепочку парсеров для банкротного анализа...")
            parsed_data = gkb_parser.parse(text)
            
            parsed_data["collaterals"] = extract_collateral_info(text)
            # print(f"[INFO] Результат парсинга: {len(parsed_data.get('obligations', []))} обязательств найдено")
            
        else:
            # 📊 ОБЫЧНЫЙ РЕЖИМ: используем старый парсинг (не трогаем)
            print(f"[INFO] Обычный режим: используем старую логику парсинга")
            
            # Импортируем старые модули
            from text_extractor import extract_text_from_pdf
            from ocr import ocr_file
            from credit_parser import extract_credit_data_with_total
            
            # Извлекаем текст из PDF (старая логика)
            text = extract_text_from_pdf(file_path)
            if not text.strip():
                text = ocr_file(file_path)
            
            # Парсим кредитный отчет (старая логика)
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
                # print(f"[INFO] Результат генерации: статус={result.get('status')}, заявлений={result.get('applications_count', 0)}")
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

@bot.message_handler(commands=['grant_access'])
def grant_access(message):
    """Даёт доступ пользователю"""
    ADMIN_USER_IDS = [376068212, 827743984]
    if message.from_user.id not in ADMIN_USER_IDS:
        return

    try:
        # Разбираем команду: /grant_access 1175419316 10
        parts = message.text.split()
        user_id = int(parts[1])
        limit = int(parts[2])
        
        # Обновляем в базе данных
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"access": True, "message_limit": limit}}
        )
        
        bot.reply_to(message, f"✅ Пользователю {user_id} дано {limit} сообщений")
        
    except:
        bot.reply_to(message, "❌ Формат: /grant_access user_id количество")

@bot.message_handler(commands=['debug_user'])
def debug_user(message):
    """Проверяем что в базе данных у пользователя"""
    ADMIN_USER_IDS = [376068212, 827743984]
    if message.from_user.id not in ADMIN_USER_IDS:
        return

    try:
        parts = message.text.split()
        user_id = int(parts[1])
        
        # Ищем пользователя в базе
        user = users_collection.find_one({"user_id": user_id})
        
        if user:
            access = user.get("access", "НЕТ ПОЛЯ")
            limit = user.get("message_limit", "НЕТ ПОЛЯ")
            
            bot.reply_to(message, 
                f"🔍 Пользователь {user_id}:\n"
                f"access: {access}\n"
                f"message_limit: {limit}\n"
                f"Состояние: {user_states.get(user_id, 'НЕТ')}"
            )
        else:
            bot.reply_to(message, f"❌ Пользователь {user_id} НЕ НАЙДЕН в базе!")
            
    except:
        bot.reply_to(message, "Формат: /debug_user user_id")

@bot.message_handler(commands=['test_channel'])
def test_channel(message):
    ADMIN_IDS = [376068212, 827743984]
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ Доступ запрещен.")
        return

    try:
        bot.send_message(CHANNEL_ID, "📡 Тест связи с каналом: всё работает!")
        bot.reply_to(message, "✅ Связь с каналом работает. Бот может отправлять сообщения.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка отправки: {e}")

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

# СЛОТЫ АДМИНИСТРАТОРА
admin_manager = AdminConsultationManager(bot,user_states)

@bot.callback_query_handler(func=lambda call: call.data == "admin_slots_today")
def handle_admin_slots_today(call):
    ADMIN_USER_IDS = [376068212, 827743984]
    if call.from_user.id not in ADMIN_USER_IDS:
        bot.send_message(call.message.chat.id, "⛔️ У вас нет доступа.")
        return
    admin_manager.show_today_slots(call.message)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_slot_details_"))
def handle_admin_slot_details(call):
    slot_id = call.data.replace("admin_slot_details_", "")
    admin_manager.show_slot_details(call, slot_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_slots_week")
def handle_admin_slots_week(call):
    manager = AdminConsultationManager(bot, user_states)
    manager.show_week_slots(call)
# Также нужно обновить обработчик callback_query_handler, добавив новые условия:

@bot.callback_query_handler(func=lambda call: call.data == "admin_all_slots")
def handle_admin_all_slots(call):
    manager = AdminConsultationManager(bot, user_states)
    manager.show_all_slots(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_cancel_slot_"))
def handle_admin_cancel_slot(call):
    slot_id = call.data.replace("admin_cancel_slot_", "")
    admin_manager.cancel_slot(call, slot_id)


@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    # ✅ ДОБАВИТЬ ЭТУ ПРОВЕРКУ В НАЧАЛО:
    ADMIN_IDS = [376068212, 827743984]
    if user_id in ADMIN_IDS and call.data.startswith("admin_"):
        # print(f"[DEBUG] Админский callback: {call.data}")
        # Передаем админские callback в AdminConsultationManager
        from admin_consultation import AdminConsultationManager
        manager = AdminConsultationManager(bot, user_states)
        manager.handle_admin_callback(call)
        bot.answer_callback_query(call.id)
        return  # ← ВЫХОДИМ, НЕ ОЧИЩАЕМ СОСТОЯНИЕ!
    if call.data == "lawyer_consultation":
        handle_lawyer_consultation(call)
    elif call.data == "check_credit_report":
        handle_credit_report_request(call)
    elif call.data == "bankruptcy_calculator":
        handle_bankruptcy_calculator(call)
    elif call.data == "creditors_list":  # ⭐ НОВАЯ СТРОКА
        handle_creditors_list_request(call)
    elif call.data == "free_consultation":
        handle_free_consultation_request(call)
    elif call.data.startswith("book_slot_"):
        handle_slot_booking(call)
    elif call.data == "my_consultations":
        handle_my_consultations(call)
    elif call.data.startswith("cancel_booking_"):
        handle_cancel_booking(call)
    elif call.data == "bot_info":
        handle_bot_info(call)
    elif call.data == "how_to_get_report":
        handle_how_to_get_report(call)
    elif call.data.startswith("admin_"):
        from admin_consultation import AdminConsultationManager
        manager = AdminConsultationManager(bot, user_states)

        # Обработка ручной отправки напоминаний
        if call.data == "admin_send_reminders":
            manager.manual_send_reminders(call)
        else:
            manager.handle_admin_callback(call)
            
    elif call.data.startswith("confirm_day_"):
        booking_id = call.data.replace("confirm_day_", "")
        confirm_consultation_participation(call, booking_id, "day")
    elif call.data.startswith("cancel_day_"):
        booking_id = call.data.replace("cancel_day_", "")
        cancel_consultation_booking(call, booking_id, "not_available_day_before")
    elif call.data.startswith("confirm_hour_"):
        booking_id = call.data.replace("confirm_hour_", "")
        confirm_consultation_participation(call, booking_id, "hour")
    elif call.data.startswith("cancel_hour_"):
        booking_id = call.data.replace("cancel_hour_", "")
        cancel_consultation_booking(call, booking_id, "not_available_hour_before")
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

# И добавьте эту команду:
@bot.message_handler(commands=['get_channel_id'])
def get_channel_id(message):
    ADMIN_IDS = [376068212, 827743984]  # ваши ID
    if message.from_user.id not in ADMIN_IDS:
        return
    
    bot.reply_to(message, "Перешлите любое сообщение из канала")

# Новый обработчик только для пересылки
@bot.message_handler(content_types=['text'], func=lambda message: message.forward_from_chat is not None)
def handle_forwarded(message):
    ADMIN_IDS = [376068212, 827743984]
    if message.from_user.id not in ADMIN_IDS:
        return
        
    channel_id = message.forward_from_chat.id
    bot.reply_to(message, f"ID канала: {channel_id}")

# @bot.message_handler(func=lambda message: True)
# def handle_all_messages(message):
#     """Обработка всех остальных сообщений"""
#     user_id = message.from_user.id
#     current_state = user_states.get(user_id)
    
#     if current_state == "lawyer_consultation":
#         # Обработка вопроса к юристу
#         handle_lawyer_question(message)
#     elif current_state == "waiting_credit_report":
#         # Пользователь в режиме ожидания кредитного отчета
#         bot.reply_to(
#             message,
#             "📊 Пожалуйста, отправьте PDF файл кредитного отчета.\n"
#             "Текстовые сообщения не обрабатываются в этом режиме."
#         )
#     else:
#         # Предлагаем воспользоваться главным меню
#         markup = create_main_menu()
#         bot.send_message(
#             message.chat.id,
#             "🤖 Используйте команду /start или выберите услугу:",
#             reply_markup=markup
#         )

# ЗАМЕНИТЬ ФУНКЦИЮ handle_all_messages на эту:

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Улучшенная обработка всех сообщений с умным анализом"""
    user_id = message.from_user.id
    # print(f"[TRACE] handle_all_messages вызван для {user_id}")
    # print(f"[TRACE] id(user_states): {id(user_states)}") 
    current_state = user_states.get(user_id)
    # print(f"[DEBUG] Состояние: {current_state}")

    # 🔧 ОТЛАДКА: проверяем состояние админа
    # print(f"[DEBUG] Пользователь {user_id}: состояние = '{current_state}'")
    # print(f"[DEBUG] Сообщение: '{message.text}'")
    
    if current_state == "lawyer_consultation":
        # Обработка вопроса к юристу (существующая логика)
        handle_lawyer_question(message)
    elif current_state in ["waiting_credit_report", "waiting_bankruptcy_report", "waiting_creditors_list"]:
        # Пользователь в режиме ожидания файла
        file_type_map = {
            "waiting_credit_report": "кредитного отчета",
            "waiting_bankruptcy_report": "отчета для банкротного анализа", 
            "waiting_creditors_list": "отчета для списка кредиторов"
        }
        
        file_type = file_type_map.get(current_state, "файла")
        
        bot.reply_to(
            message,
            f"📄 Пожалуйста, отправьте PDF файл {file_type}.\n"
            "Текстовые сообщения не обрабатываются в этом режиме.\n\n"
            "💡 Если хотите задать вопрос, используйте /start и выберите подходящую услугу."
        )
    elif current_state and current_state.startswith("admin_messaging_"):
        # 🆕 ДОБАВИТЬ ЭТОТ БЛОК
        # Админ отправляет сообщение пользователю
        target_user_id = int(current_state.replace("admin_messaging_", ""))
        admin_message = message.text
        
        try:
            # Отправляем сообщение пользователю
            bot.send_message(
                chat_id=target_user_id,
                text=f"📩 **Сообщение от администратора:**\n\n{admin_message}",
                parse_mode='Markdown'
            )
            
            # Подтверждение админу
            bot.reply_to(message, f"✅ Сообщение отправлено пользователю {target_user_id}")
            
        except Exception as e:
            # Ошибка отправки
            bot.reply_to(message, f"❌ Не удалось отправить сообщение: {str(e)}")
        
        # Сбрасываем состояние админа
        user_states.pop(user_id, None)
        return
    else:
        # 🆕 НОВАЯ УМНАЯ ОБРАБОТКА
        smart_handler.handle_message(message)
        print(f"[SMART] Обработано умным способом: {message.text[:30]}...")

@bot.message_handler(commands=['channel_info'])
def channel_info(message):
    ADMIN_IDS = [376068212, 827743984]
    if message.from_user.id not in ADMIN_IDS:
        return
    
    bot.reply_to(message, 
        "📋 **Способы получения ID канала:**\n\n"
        "**Вариант 1:** Сделайте канал публичным:\n"
        "• Настройки канала → Тип канала → Публичный\n"
        "• Установите username (например @mychannel)\n"
        "• ID будет: @mychannel\n\n"
        "**Вариант 2:** Временно публичный:\n"
        "1. Сделайте канал публичным\n"
        "2. Перешлите сообщение из канала мне\n"
        "3. Верните канал обратно в приватный\n\n"
        "**Вариант 3:** Отправьте сообщение прямо в канал с ботом",
        parse_mode='Markdown'
    )
@bot.message_handler(func=lambda message: message.chat.type in ['channel', 'supergroup'])
def handle_channel_message(message):
    """Обработка сообщений в канале/группе"""
    ADMIN_IDS = [376068212, 827743984]
    
    # Проверяем, есть ли админ в канале
    try:
        for admin_id in ADMIN_IDS:
            chat_member = bot.get_chat_member(message.chat.id, admin_id)
            if chat_member.status in ['creator', 'administrator', 'member']:
                # Отправляем ID канала админу в личку
                bot.send_message(
                    admin_id, 
                    f"📢 ID канала/группы: `{message.chat.id}`\n"
                    f"📝 Название: {message.chat.title}\n"
                    f"💬 Сообщение: {message.text[:50]}...",
                    parse_mode='Markdown'
                )
                break
    except Exception as e:
        print(f"[ERROR] Ошибка в канале: {e}")

# Запуск бота
if __name__ == "__main__":
    print("[INFO] Бот запущен...")
     # 🚀 ЗАПУСКАЕМ ПЛАНИРОВЩИК УВЕДОМЛЕНИЙ
    notification_scheduler.start_scheduler()
    print("[INFO] 📅 Автоматические уведомления включены")

    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            print(f"[ERROR] Polling crashed: {e}")
            time.sleep(5)

# Удалите старый @bot.message_handler(func=lambda message: True)

