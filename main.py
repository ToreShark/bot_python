import telebot
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from legal_engine import query

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN)

# Подключение к MongoDB Atlas
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)

# Выбор базы данных и коллекции
db = client['telegram_bot']  # Название базы данных
users_collection = db['users']  # Коллекция для пользователей и их сообщений

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

    # Сохраняем сообщение пользователя в MongoDB
    users_collection.update_one(
        {"user_id": user_id},
        {"$push": {"messages": text}}
    )

    # Отвечаем через LangChain-пайплайн
    try:
        bot.send_message(message.chat.id, "⌛ Обрабатываю ваш вопрос...")
        answer = query(text)
        bot.send_message(message.chat.id, answer)
    except Exception as e:
        print(f"[ERROR] {e}")
        bot.send_message(message.chat.id, "❌ Произошла ошибка при обработке. Попробуйте позже.")


bot.polling(none_stop=True)