#!/usr/bin/env python3
"""
Быстрая проверка состояния видеосистемы на продакшн
"""

import telebot
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

def quick_check():
    print("🔍 БЫСТРАЯ ПРОВЕРКА ПРОДАКШН")
    print("=" * 40)
    
    # 1. Проверка подключения к БД
    try:
        client = MongoClient(os.getenv("MONGO_URI"))
        db = client["telegram_bot"]
        lessons = db["lessons"]
        
        # Считаем ссылки
        new_links = lessons.count_documents({
            "video_url": {"$regex": "t.me/c/2684584475/"}
        })
        old_links = lessons.count_documents({
            "video_url": {"$regex": "t.me/c/2275474152/"}
        })
        
        print(f"📊 БД состояние:")
        print(f"  ✅ Новые ссылки: {new_links}")
        print(f"  ❌ Старые ссылки: {old_links}")
        
        if new_links >= 9 and old_links == 0:
            print("  ✅ БД обновлена корректно")
            db_ok = True
        else:
            print("  ⚠️  БД требует обновления")
            db_ok = False
            
    except Exception as e:
        print(f"❌ Ошибка БД: {e}")
        db_ok = False
    
    # 2. Проверка доступа бота к каналу
    try:
        bot = telebot.TeleBot(os.getenv("TELEGRAM_BOT_TOKEN"))
        chat = bot.get_chat(-1002684584475)
        print(f"🤖 Бот:")
        print(f"  ✅ Доступ к каналу: {chat.title}")
        bot_ok = True
    except Exception as e:
        print(f"🤖 Бот:")
        print(f"  ❌ Нет доступа к каналу: {e}")
        bot_ok = False
    
    # 3. Итоговый статус
    print(f"\n🎯 СТАТУС:")
    if db_ok and bot_ok:
        print("  ✅ ВСЕ ГОТОВО! Видеокурсы должны работать")
        return True
    else:
        print("  ❌ ТРЕБУЕТСЯ НАСТРОЙКА:")
        if not db_ok:
            print("    - Запустить: python seed_video_production.py")
        if not bot_ok:
            print("    - Добавить бота в канал 2684584475")
        return False

if __name__ == "__main__":
    success = quick_check()
    exit(0 if success else 1)