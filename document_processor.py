# document_processor.py

from pymongo import MongoClient
import os
from datetime import datetime
from text_extractor import extract_text_from_pdf
from ocr import ocr_file, detect_document_type
from credit_parser import extract_credit_data_with_total, format_summary
from dotenv import load_dotenv

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


def process_uploaded_file(filepath, user_id):
    # 1. Пытаемся извлечь текст напрямую
    text = extract_text_from_pdf(filepath)
    # print(f"[DEBUG] Direct PDF text length: {len(text)}")

     # 🔍 Сохраняем извлечённый текст для отладки
    with open("debug_text_output.txt", "w", encoding="utf-8") as f:
        f.write(text)

    # 2. Если текста нет — OCR
    if not text.strip():
        # print("[INFO] PDF не содержит текста. Запускаем OCR...")
        text = ocr_file(filepath)
        # print(f"[DEBUG] OCR text length: {len(text)}")

         # 🔍 Сохраняем текст после OCR тоже
        with open("debug_text_output_ocr.txt", "w", encoding="utf-8") as f:
            f.write(text)

    # 3. Определяем тип документа
    doc_type = detect_document_type(text)

    # 4. Сохраняем в Mongo
    doc_record = {
        "user_id": user_id,
        "doc_type": doc_type,
        "text": text,
        "uploaded_at": datetime.utcnow().isoformat()
    }
    docs_collection.insert_one(doc_record)

     # Распознаём кредитный отчёт
    if doc_type == "credit_report":
        # print(f"[DEBUG] Начинаем парсинг, длина текста: {len(text)}")
        parsed = extract_credit_data_with_total(text)
        # print(f"[DEBUG] Результат парсинга: {parsed}")

        # Сохраняем в отдельную коллекцию
        db['credit_reports'].insert_one({
            "user_id": user_id,
            "parsed": parsed,
            "uploaded_at": datetime.utcnow().isoformat()
        })

        summary = format_summary(parsed)
        return {"type": doc_type, "message": f"📄 Отчёт обработан.\n\n{summary}"}

    # 5. Ответ (оставляем только для других типов)
    elif doc_type == "payment_receipt":
        return {"type": doc_type, "message": "📸 Квитанция получена. Ожидайте подтверждения."}
    else:
        return {"type": "unknown", "message": "❓ Документ получен, но тип не распознан."}

    
    
