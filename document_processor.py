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


# В файле document_processor.py замените функцию process_uploaded_file:

def process_uploaded_file(filepath, user_id):
    # 1. Извлекаем текст из PDF
    text = extract_text_from_pdf(filepath)
    
    # 2. Если текста нет — используем OCR
    if not text.strip():
        text = ocr_file(filepath)

    # 3. Определяем тип документа
    doc_type = detect_document_type(text)

    # 4. Обрабатываем кредитный отчёт
    if doc_type == "credit_report":
        # Парсим отчет
        parsed = extract_credit_data_with_total(text)
        
        # 🔍 ПРОВЕРЯЕМ ДУБЛИКАТЫ ПО ИИН
        iin = parsed.get("personal_info", {}).get("iin")
        
        if iin:
            # Ищем в базе отчет с таким же ИИН
            existing = db['credit_reports'].find_one({"parsed.personal_info.iin": iin})
            
            if existing:
                # Если найден дубликат - НЕ сохраняем
                print(f"[INFO] Найден дубликат отчета для ИИН {iin} - пропускаем")
                summary = format_summary(existing["parsed"])
                return {
                    "type": doc_type, 
                    "message": f"📄 Отчёт уже существует в базе данных.\n\n{summary}"
                }
        
        # Если дубликата нет - сохраняем как обычно
        print(f"[INFO] Сохраняем новый отчет для ИИН {iin or 'без ИИН'}")
        
        # Сохраняем документ
        docs_collection.insert_one({
            "user_id": user_id,
            "doc_type": doc_type,
            "text": text,
            "uploaded_at": datetime.utcnow().isoformat()
        })

        # Сохраняем парсинг
        db['credit_reports'].insert_one({
            "user_id": user_id,
            "parsed": parsed,
            "uploaded_at": datetime.utcnow().isoformat()
        })

        summary = format_summary(parsed)
        return {
            "type": doc_type, 
            "message": f"📄 Отчёт обработан.\n\n{summary}"
        }

    # 5. Обрабатываем чеки об оплате (без проверки дубликатов)
    elif doc_type == "payment_receipt":
        docs_collection.insert_one({
            "user_id": user_id,
            "doc_type": doc_type,
            "text": text,
            "uploaded_at": datetime.utcnow().isoformat()
        })
        return {"type": doc_type, "message": "📸 Квитанция получена. Ожидайте подтверждения."}
    
    # 6. Неизвестные документы
    else:
        docs_collection.insert_one({
            "user_id": user_id,
            "doc_type": doc_type,
            "text": text,
            "uploaded_at": datetime.utcnow().isoformat()
        })
        return {"type": "unknown", "message": "❓ Документ получен, но тип не распознан."}  
    
