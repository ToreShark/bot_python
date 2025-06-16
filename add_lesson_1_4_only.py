# add_lesson_1_4_only.py
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
db = client["telegram_bot"]

# Проверяем, есть ли уже урок
if db.lessons.find_one({"lesson_id": "lesson_1_4"}):
    print("✅ Урок 1.4 уже существует!")
else:
    # Добавляем только новый урок
    db.lessons.insert_one({
        "lesson_id": "lesson_1_4",
        "module_id": "extrajudicial_module",
        "title": "Урок 1.4: Что делать при отказе во внесудебном банкротстве",
        "description": "Пошаговые действия при получении отказа",
        "video_url": "https://t.me/c/2275474152/34",
        "duration": "30 минут",
        "order": 4,
    })
    
    # Обновляем модуль
    db.modules.update_one(
        {"module_id": "extrajudicial_module"},
        {
            "$push": {"lessons": "lesson_1_4"},
            "$set": {"estimated_duration": "120 минут"}
        }
    )
    
    # Обновляем курс
    db.courses.update_one(
        {"course_id": "bankruptcy_kz"},
        {"$set": {"total_lessons": 9}}
    )
    
    print("✅ Урок 1.4 добавлен!")