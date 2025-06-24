#!/usr/bin/env python3
"""
Production seed script для обновления видео ссылок
Использовать ТОЛЬКО на продакшн сервере!
"""

import os
from pymongo import MongoClient
from datetime import datetime

# ВАЖНО: Эти настройки для ПРОДАКШН
MONGO_URI = os.getenv("MONGO_URI_PROD") or input("Введите MONGO_URI для продакшн: ")
NEW_CHANNEL_ID = "2684584475"
OLD_CHANNEL_ID = "2275474152"

# Таблица соответствий (та же что и локально)
VIDEO_MAPPING = {
    "lesson_1_1": {"old": 20, "new": 5},
    "lesson_1_2": {"old": 22, "new": 3},
    "lesson_1_3": {"old": 13, "new": 12},
    "lesson_1_4": {"old": 34, "new": 14},
    "lesson_2_1": {"old": 16, "new": 9},
    "lesson_2_2": {"old": 14, "new": 11},
    "lesson_2_3": {"old": 15, "new": 10},
    "lesson_3_1": {"old": 21, "new": 6},
    "lesson_3_2": {"old": 18, "new": 7},
}

def update_production_videos():
    """Обновляет видео ссылки в продакшн БД"""
    print("🚀 PRODUCTION SEED: Обновление видео ссылок")
    print(f"🎯 Канал: {OLD_CHANNEL_ID} → {NEW_CHANNEL_ID}")
    print("=" * 50)
    
    # Подключение к продакшн БД
    try:
        client = MongoClient(MONGO_URI)
        db = client["telegram_bot"]
        lessons = db["lessons"]
        print("✅ Подключение к продакшн БД успешно")
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        return False
    
    # Проверяем текущее состояние
    total_lessons = lessons.count_documents({})
    old_links = lessons.count_documents({
        "video_url": {"$regex": f"t.me/c/{OLD_CHANNEL_ID}/"}
    })
    new_links = lessons.count_documents({
        "video_url": {"$regex": f"t.me/c/{NEW_CHANNEL_ID}/"}
    })
    
    print(f"📊 Текущее состояние:")
    print(f"  Всего уроков: {total_lessons}")
    print(f"  Старые ссылки: {old_links}")
    print(f"  Новые ссылки: {new_links}")
    
    if old_links == 0:
        print("✅ Все ссылки уже обновлены!")
        return True
    
    # Подтверждение
    confirm = input(f"\n⚠️  Обновить {old_links} ссылок? (yes/no): ")
    if confirm.lower() != "yes":
        print("❌ Отменено пользователем")
        return False
    
    # Обновляем
    updated = 0
    for lesson_id, mapping in VIDEO_MAPPING.items():
        old_url = f"https://t.me/c/{OLD_CHANNEL_ID}/{mapping['old']}"
        new_url = f"https://t.me/c/{NEW_CHANNEL_ID}/{mapping['new']}"
        
        result = lessons.update_one(
            {"lesson_id": lesson_id, "video_url": old_url},
            {
                "$set": {
                    "video_url": new_url,
                    "updated_at": datetime.utcnow(),
                    "migration_info": {
                        "migrated_from": old_url,
                        "migrated_at": datetime.utcnow(),
                        "script_version": "production_seed_v1"
                    }
                }
            }
        )
        
        if result.modified_count > 0:
            print(f"✅ {lesson_id}: {old_url} → {new_url}")
            updated += 1
        else:
            lesson = lessons.find_one({"lesson_id": lesson_id})
            if lesson:
                current_url = lesson.get("video_url", "")
                if current_url == new_url:
                    print(f"ℹ️  {lesson_id}: Уже обновлено")
                else:
                    print(f"⚠️  {lesson_id}: Неожиданная ссылка - {current_url}")
    
    print(f"\n✅ Обновлено: {updated} уроков")
    
    # Финальная проверка
    final_old = lessons.count_documents({
        "video_url": {"$regex": f"t.me/c/{OLD_CHANNEL_ID}/"}
    })
    final_new = lessons.count_documents({
        "video_url": {"$regex": f"t.me/c/{NEW_CHANNEL_ID}/"}
    })
    
    print(f"\n📊 Финальное состояние:")
    print(f"  Старые ссылки: {final_old}")
    print(f"  Новые ссылки: {final_new}")
    
    if final_old == 0:
        print("🎉 ВСЕ ССЫЛКИ УСПЕШНО ОБНОВЛЕНЫ!")
        return True
    else:
        print(f"⚠️  Остались необновленные ссылки: {final_old}")
        return False

if __name__ == "__main__":
    print("🔥 PRODUCTION SEED SCRIPT")
    print("Убедитесь, что запускаете на правильном сервере!")
    print("Этот скрипт изменит продакшн базу данных!")
    
    server_confirm = input("\n⚠️  Это продакшн сервер? (YES для продолжения): ")
    if server_confirm != "YES":
        print("❌ Скрипт остановлен для безопасности")
        exit(1)
    
    success = update_production_videos()
    
    if success:
        print("\n✨ MIGRATION COMPLETED SUCCESSFULLY!")
        print("🔄 Перезапустите бота для применения изменений")
    else:
        print("\n❌ MIGRATION FAILED!")
        print("🔍 Проверьте логи и попробуйте снова")