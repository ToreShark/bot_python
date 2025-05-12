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
    # Кнопки с вариантами оплаты
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💰 Оплатить 5 000 ₸", callback_data="pay_5000"))
    markup.add(types.InlineKeyboardButton("💰 Оплатить 10 000 ₸", callback_data="pay_10000"))
    markup.add(types.InlineKeyboardButton("💰 Оплатить 15 000 ₸", callback_data="pay_15000"))

    # Сообщение пользователю
    bot.send_message(
        message.chat.id,
        "💳 Выберите сумму оплаты, чтобы получить доступ:",
        reply_markup=markup
        )

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
            try:
                bot.send_message(admin_id, admin_text)
            except Exception as e:
                print(f"[WARN] Не удалось отправить сообщение админу {admin_id}: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def handle_payment_callback(call):
    amount_map = {
        "pay_5000": "5 000",
        "pay_10000": "10 000",
        "pay_15000": "15 000"
    }
    amount = amount_map.get(call.data, "неизвестная сумма")

    if amount == "неизвестная сумма":
        bot.send_message(call.message.chat.id, "⚠️ Ошибка: сумма не распознана.")
        bot.answer_callback_query(call.id)
        return

    payment_text = (
        f"💳 Для оплаты {amount} ₸ используйте ссылку:\n"
        "https://pay.kaspi.kz/pay/izbl0ktq\n\n"
        "📸 После оплаты пришлите сюда скриншот подтверждения."
    )

    bot.send_message(call.message.chat.id, payment_text)
    bot.answer_callback_query(call.id)


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

@bot.message_handler(content_types=['voice'])
def handle_voice_message(message):
    user_id = message.from_user.id
    now = datetime.now(timezone.utc)
    
    # Проверки доступа (аналогично функции handle_all_messages)
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
    
    # Здесь также добавьте проверки ограничений по количеству сообщений в сутки и частоте
    # как в функции handle_all_messages
    
    # Получаем информацию о голосовом сообщении
    file_info = bot.get_file(message.voice.file_id)
    file_path = file_info.file_path
    
    # Создаем временную директорию, если её нет
    os.makedirs("temp", exist_ok=True)
    
    # Путь для сохранения аудиофайла
    audio_path = f"temp/voice_{message.voice.file_id}.ogg"
    audio_path_mp3 = f"temp/voice_{message.voice.file_id}.mp3"
    
    # Скачиваем аудиофайл
    downloaded_file = bot.download_file(file_path)
    with open(audio_path, 'wb') as f:
        f.write(downloaded_file)
    
    # Отправляем сообщение о начале обработки
    status_msg = bot.send_message(message.chat.id, "🎤 Распознаю голосовое сообщение...")
    
    try:
        # Конвертируем ogg в mp3 (Whisper API лучше работает с mp3)
        audio = AudioSegment.from_ogg(audio_path)
        audio.export(audio_path_mp3, format="mp3")
        
        # Используем OpenAI Whisper API для распознавания речи
        openai.api_key = os.getenv("OPENAI_API_KEY")
        
        with open(audio_path_mp3, "rb") as audio_file:
            transcript = openai.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru"
            )
        
        recognized_text = transcript.text
        
        # Обновляем статус с распознанным текстом
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text=f"🎤 Распознанный текст:\n\n{recognized_text}\n\n⌛ Обрабатываю ваш вопрос..."
        )
        
        # Сохраняем сообщение в базу данных
        users_collection.update_one(
            {"user_id": user_id},
            {"$push": {
                "messages": {
                    "text": recognized_text,
                    "type": "voice",
                    "timestamp": datetime.utcnow().isoformat()
                }
            }}
        )
        
        # Функция для обновления текста в сообщении статуса
        def progress_callback(stage_text):
            try:
                bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=status_msg.message_id,
                    text=stage_text
                )
            except Exception as e:
                print(f"[WARN] Не удалось обновить статус: {e}")
        
        # Обрабатываем распознанный текст через LangChain-пайплайн
        answer = query(recognized_text, progress_callback=progress_callback)
        
        # Сохраняем ответ в базу данных
        users_collection.update_one(
            {"user_id": user_id},
            {"$push": {
                "answers": {
                    "text": answer,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            }}
        )
        
        # Уменьшаем лимит сообщений пользователя
        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"message_limit": -1}}
        )
        
        # Отправляем финальный ответ
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text=answer
        )
    
    except Exception as e:
        print(f"[ERROR] Ошибка при обработке голосового сообщения: {e}")
        bot.send_message(
            message.chat.id,
            "❌ Произошла ошибка при обработке голосового сообщения. Пожалуйста, попробуйте позже или отправьте ваш вопрос текстом."
        )
    
    finally:
        # Удаляем временные файлы
        try:
            os.remove(audio_path)
            os.remove(audio_path_mp3)
        except Exception as e:
            print(f"[WARN] Не удалось удалить временные файлы: {e}")

@bot.message_handler(content_types=['photo', 'document'])
def handle_payment_file(message):
    user_id = message.from_user.id
    file_info = bot.get_file(message.document.file_id)
    file_name = message.document.file_name
    file_path = f"temp/{file_name}"
    os.makedirs("temp", exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(bot.download_file(file_info.file_path))

    try:
        result = process_uploaded_file(file_path, user_id)
        # print(f"[DEBUG] Result from processor: {result}")

        # Показываем результат пользователю
        if "message" in result:
            bot.send_message(message.chat.id, result["message"])

        # Только для квитанции отправляем благодарность
        if result["type"] == "payment_receipt":
            bot.send_message(
                message.chat.id,
                "✅ Спасибо, файл получен. Мы проверим оплату в ближайшее время.\n\n"
                "📞 Если у вас есть вопросы, свяжитесь с администратором: +77007000000"
            )

    except Exception as e:
        print(f"[ERROR] Ошибка обработки файла: {e}")
        bot.send_message(message.chat.id, "⚠️ Ошибка при обработке файла. Попробуйте позже.")
    finally:
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"[WARN] Не удалось удалить файл {file_path}: {e}")

    # Сообщение админам
    ADMIN_USER_IDS = [376068212, 827743984]
    caption = (
        f"📩 Пользователь отправил файл, возможно, это квитанция:\n"
        f"👤 Telegram ID: {user_id}\n"
        f"📎 Тип: {'фото' if message.content_type == 'photo' else 'документ'}\n"
        f"📸 Переслано автоматически для проверки."
    )

    for admin_id in ADMIN_USER_IDS:
        try:
            bot.forward_message(chat_id=admin_id, from_chat_id=message.chat.id, message_id=message.message_id)
            bot.send_message(admin_id, caption)
        except Exception as e:
            print(f"[WARN] Не удалось переслать файл админу {admin_id}: {e}")



while True:
    try:
        bot.polling(none_stop=True, timeout=60)
    except Exception as e:
        print(f"[ERROR] polling crashed: {e}")
        time.sleep(5)  # ждём и перезапускаем