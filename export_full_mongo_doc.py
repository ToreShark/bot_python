import json
import os
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

def fetch_document():
    client = MongoClient(os.getenv("MONGO_URI"))
    db = client["telegram_bot"]
    doc = db.documents.find_one({"_id": ObjectId("6826f90c5877e257b5e6f660")})
    return doc

def preview_document(doc):
    result = {}
    for key, value in doc.items():
        if isinstance(value, str) and len(value) > 1000:
            result[key] = value[:1000] + "... [truncated]"
        else:
            result[key] = value
    return result

if __name__ == "__main__":
    document = fetch_document()
    if document:
        document["_id"] = str(document["_id"])
        preview = preview_document(document)
        with open("mongo_document_preview.json", "w", encoding="utf-8") as f:
            json.dump(preview, f, ensure_ascii=False, indent=2)
        print("✅ Ключи и часть данных сохранены в mongo_document_preview.json")
    else:
        print("❌ Документ не найден.")