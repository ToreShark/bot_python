# document_processor.py

from pymongo import MongoClient
import os
from datetime import datetime
from text_extractor import extract_text_from_pdf_enhanced as extract_text_from_pdf
from ocr import ocr_file, detect_document_type
from dotenv import load_dotenv
import hashlib

load_dotenv()  # Подгружаем .env переменные

# Определяем режим
env = os.getenv("ENV", "prod").lower()
DEBUG_MODE = env == "dev"

# Подключение к MongoDB
# Подключение к MongoDB
if DEBUG_MODE:
    client = MongoClient("mongodb://localhost:27017")
    print(f"[DEBUG] Подключение к локальной MongoDB (режим {env})")
else:
    client = MongoClient(os.getenv("MONGO_URI"))
    print(f"[DEBUG] Подключение к MongoDB Atlas (режим {env})")
# db_name = "tg_bot_dev" if DEBUG_MODE else "telegram_bot"
db_name = "telegram_bot"
db = client[db_name]
docs_collection = db['documents']


# В файле document_processor.py замените функцию process_uploaded_file:

def process_uploaded_file(filepath, user_id):
    # 1. Извлекаем текст из PDF с улучшенными параметрами
    text = extract_text_from_pdf(filepath)  # Теперь использует pdfminer.six
    
    # 2. Если текста нет — используем OCR
    if not text.strip():
        print(f"[INFO] Основное извлечение не дало результата, используем OCR...")
        text = ocr_file(filepath)
    
    # Остальной код остается без изменений...
    if DEBUG_MODE:
        # Создаем уникальное имя по user_id и имени файла
        base_name = os.path.basename(filepath)
        hash_id = hashlib.md5((str(user_id) + base_name).encode()).hexdigest()[:8]
        debug_filename = f"debug_text_output_{user_id}_{hash_id}.txt"
        try:
            with open(debug_filename, 'w', encoding='utf-8') as debug_file:
                debug_file.write(f"=== DEBUG OUTPUT для пользователя {user_id} ===\n")
                debug_file.write(f"Файл: {filepath}\n")
                debug_file.write(f"Время: {datetime.utcnow().isoformat()}\n")
                debug_file.write(f"Длина текста: {len(text)} символов\n")
                debug_file.write(f"Режим извлечения: pdfminer.six + LAParams\n")  # ← ОБНОВЛЕНО
                debug_file.write(f"Режим: {env}\n")
                debug_file.write("="*60 + "\n\n")
                debug_file.write(text)
            print(f"[DEBUG] Текст сохранен в {debug_filename}")
        except Exception as debug_error:
            print(f"[ERROR] Не удалось сохранить debug файл: {debug_error}")
