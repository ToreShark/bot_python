# db.py

from pymongo import MongoClient
from dotenv import load_dotenv
import os

# Загрузка переменных окружения из .env
load_dotenv()

# Получаем режим работы
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"
env = "dev" if DEBUG_MODE else "prod"

# Подключение к MongoDB
if DEBUG_MODE:
    client = MongoClient("mongodb://localhost:27017")
    print(f"[DEBUG] Подключение к локальной MongoDB (режим: {env})")
else:
    MONGO_URI = os.getenv("MONGO_URI")
    client = MongoClient(MONGO_URI)
    print(f"[DEBUG] Подключение к MongoDB Atlas (режим: {env})")

# Имя базы данных
db_name = "tg_bot_dev" if DEBUG_MODE else "telegram_bot"
db = client[db_name]

# Коллекции, которые будут использоваться
consultation_slots_collection = db["consultation_slots"]
consultation_queue_collection = db["consultation_queue"]