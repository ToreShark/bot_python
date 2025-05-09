import telebot
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from legal_engine import query
from datetime import datetime, timezone, timedelta
import time

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN)

# Подключение к MongoDB Atlas
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)

# Выбор базы данных и коллекции
db = client['telegram_bot']  # Название базы данных
users_collection = db['users']  # Коллекция для пользователей и их сообщений

# Простая антивандальная структура: последний доступ
user_last_access = {}

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
            "messages": []  # Пустой список для сообщений
        })
    # Сообщение пользователю
    bot.send_message(message.chat.id, "👋 Привет! Ваша заявка отправлена администратору.")

    # Уведомление админу
    # ADMIN_USER_ID = 376068212
    ADMIN_USER_IDS = [376068212, 827743984]
    if user_id not in ADMIN_USER_IDS:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        admin_text = (
            "🆕 Пользователь хочет начать общение с ботом:\n"
            f"👤 Имя: {first_name} {last_name}\n"
            f"🆔 ID: {user_id}\n"
            f"🕒 Время: {timestamp}"
        )
        for admin_id in ADMIN_USER_IDS:
            bot.send_message(admin_id, admin_text)

@bot.message_handler(commands=['grant_access'])
def grant_access(message):
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
        bot.send_message(user_id, f"✅ Вам предоставлен доступ. Лимит: {message_limit} сообщений.")
        bot.reply_to(message, f"✅ Доступ предоставлен пользователю {user_id}.")
    except Exception as e:
        print(f"[ERROR grant_access] {e}")
        bot.reply_to(message, "⚠️ Ошибка. Используйте команду так: /grant_access [user_id] [кол-во_сообщений]")


@bot.message_handler(func=lambda message: message.text.startswith('/law '))
def handle_legal_query(message):
    user_question = message.text[len('/law '):].strip()
    response = query(user_question)  # вызываем LangChain пайплайн
    bot.send_message(message.chat.id, response)

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    text = message.text
    now = datetime.now(timezone.utc)

    user = users_collection.find_one({"user_id": user_id})

    if not user:
        bot.send_message(message.chat.id, "❌ Сначала отправьте /start, чтобы зарегистрироваться.")
        return

    if not user.get("access", False):
        bot.send_message(message.chat.id, "⛔ Доступ не активирован. Ожидайте подтверждения от администратора.")
        return

    if user.get("message_limit", 0) <= 0:
        bot.send_message(message.chat.id, "📵 Ваш лимит сообщений исчерпан. Обратитесь к администратору.")
        return

    # 1. Ограничение по количеству сообщений в сутки
    # ADMIN_USER_ID = 376068212  # ID без ограничения
    ADMIN_USER_IDS = [376068212, 827743984]
    if user_id not in ADMIN_USER_IDS:
        today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        message_count = users_collection.count_documents({
            "user_id": user_id,
            "messages.timestamp": {"$gte": today_start.isoformat()}
        })

        if message_count >= 3:
            bot.send_message(message.chat.id, "📵 Лимит: не более 3 запросов в сутки.")
            return


    # Ограничение по частоте (30 секунд)
    if user_id in user_last_access:
        last_time = user_last_access[user_id]
        if now - last_time < timedelta(minutes=5):
            bot.send_message(message.chat.id, "⏳ Подождите 5 минут перед следующим запросом.")
            return
    user_last_access[user_id] = now

   # Сохраняем сообщение с timestamp
    users_collection.update_one(
        {"user_id": user_id},
        {"$push": {
            "messages": {
                "text": text,
                "timestamp": datetime.utcnow().isoformat()
            }
        }}
    )

    # Отвечаем через LangChain-пайплайн
    try:
        # Отправляем "ожидание" и получаем ID сообщения
        status_msg = bot.send_message(message.chat.id, "⌛ Обрабатываю ваш вопрос...")

       # Функция для обновления текста в этом сообщении
        def progress_callback(stage_text):
            try:
                bot.edit_message_text(chat_id=message.chat.id,
                                      message_id=status_msg.message_id,
                                      text=stage_text)
            except Exception as e:
                print(f"[WARN] Не удалось обновить статус: {e}")

        # Запускаем обработку с обновлением статуса
        answer = query(text, progress_callback=progress_callback)

        # Сохраняем ответ с timestamp
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
        # Финальный ответ
        bot.edit_message_text(chat_id=message.chat.id,
                              message_id=status_msg.message_id,
                              text=answer)
    except Exception as e:
        print(f"[ERROR] {e}")
        bot.send_message(message.chat.id, "❌ Произошла ошибка при обработке. Попробуйте позже.")


while True:
    try:
        bot.polling(none_stop=True, timeout=60)
    except Exception as e:
        print(f"[ERROR] polling crashed: {e}")
        time.sleep(5)  # ждём и перезапускаем