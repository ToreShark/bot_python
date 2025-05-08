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
            "messages": []  # Пустой список для сообщений
        })
    bot.send_message(message.chat.id, "Привет!")

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