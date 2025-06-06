# consultation_manager.py

import telebot
from pymongo import MongoClient
from datetime import datetime, timedelta
from telebot import types
from bson import ObjectId
import os
from dotenv import load_dotenv

load_dotenv()

# Подключение к MongoDB (такое же как в main.py)
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client['telegram_bot']

# Коллекции для консультаций
consultation_slots_collection = db['consultation_slots']
consultation_queue_collection = db['consultation_queue']

class ConsultationManager:
    """Класс для управления системой консультаций"""
    
    def __init__(self, bot):
        self.bot = bot
    
    # Здесь будут все наши функции