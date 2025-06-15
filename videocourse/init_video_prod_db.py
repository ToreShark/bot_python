from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# ──────────────────── Проверки безопасности ────────────────────
print("🔐 PRODUCTION VIDEO COURSES INITIALIZATION")
print("=" * 60)

# Проверка окружения
if os.getenv("DEBUG_MODE", "False").lower() == "true":
    print("⚠️  ВНИМАНИЕ: Обнаружен DEBUG_MODE=True!")
    print("❌ Для production используйте DEBUG_MODE=False")
    confirm = input("Продолжить все равно? (yes/no): ")
    if confirm.lower() != 'yes':
        print("❌ Операция отменена")
        exit(1)

# ──────────────────── Подключение к MongoDB ────────────────────
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    print("❌ MONGO_URI не найден в .env файле!")
    exit(1)

client = MongoClient(MONGO_URI)

# Проверка подключения
try:
    client.admin.command('ping')
    print("✅ Соединение с MongoDB установлено")
    db_name = client.get_database().name if hasattr(client, 'get_database') else 'telegram_bot'
    print(f"📊 База данных: {db_name}")
except Exception as e:
    print(f"❌ Ошибка подключения к БД: {e}")
    exit(1)

db = client["telegram_bot"]

# Коллекции
courses_collection = db["courses"]
modules_collection = db["modules"]
lessons_collection = db["lessons"]
user_progress_collection = db["user_progress"]

# ──────────────────── Индексы ────────────────────
def create_indexes():
    print("Создаем индексы...")
    courses_collection.create_index("course_id", unique=True)
    courses_collection.create_index("is_active")

    modules_collection.create_index("module_id", unique=True)
    modules_collection.create_index("course_id")
    modules_collection.create_index([("course_id", 1), ("order", 1)])

    lessons_collection.create_index("lesson_id", unique=True)
    lessons_collection.create_index("module_id")
    lessons_collection.create_index([("module_id", 1), ("order", 1)])

    user_progress_collection.create_index([("user_id", 1), ("course_id", 1)], unique=True)
    user_progress_collection.create_index("user_id")
    print("✅ Индексы созданы")

# ──────────────────── PRODUCTION DATA ────────────────────
# Основной курс
main_course = {
    "course_id": "bankruptcy_kz",
    "title": "Банкротство физических лиц в Казахстане",
    "description": "Полный курс по всем процедурам банкротства: внесудебное, восстановление платежеспособности и судебное банкротство",
    "modules": ["extrajudicial_module", "recovery_module", "judicial_module"],
    "created_at": datetime.utcnow(),
    "is_active": True,
    "total_lessons": 8,
    "estimated_duration": "4 часа",
}

# Модули
modules_data = [
    # Модуль 1: Внесудебное банкротство
    {
        "module_id": "extrajudicial_module",
        "course_id": "bankruptcy_kz",
        "title": "Модуль 1: Внесудебное банкротство",
        "description": "От основ банкротства до подачи заявления на внесудебную процедуру",
        "lessons": ["lesson_1_1", "lesson_1_2", "lesson_1_3"],
        "order": 1,
        "estimated_duration": "90 минут",
    },
    # Модуль 2: Восстановление платежеспособности
    {
        "module_id": "recovery_module",
        "course_id": "bankruptcy_kz",
        "title": "Модуль 2: Восстановление платежеспособности",
        "description": "Как восстановить платежеспособность и составить план погашения долгов",
        "lessons": ["lesson_2_1", "lesson_2_2", "lesson_2_3"],
        "order": 2,
        "estimated_duration": "90 минут",
    },
    # Модуль 3: Судебное банкротство
    {
        "module_id": "judicial_module",
        "course_id": "bankruptcy_kz",
        "title": "Модуль 3: Судебное банкротство",
        "description": "Процедура судебного банкротства от А до Я",
        "lessons": ["lesson_3_1", "lesson_3_2"],
        "order": 3,
        "estimated_duration": "60 минут",
    },
]

# Уроки
lessons_data = [
    # ───────── Модуль 1: Внесудебное банкротство ─────────
    {
        "lesson_id": "lesson_1_1",
        "module_id": "extrajudicial_module",
        "title": "Урок 1.1: Введение в банкротство",
        "description": "Что такое банкротство физических лиц в Казахстане",
        "video_url": "https://t.me/c/2275474152/20",
        "duration": "30 минут",
        "order": 1,
    },
    {
        "lesson_id": "lesson_1_2",
        "module_id": "extrajudicial_module",
        "title": "Урок 1.2: Внесудебное банкротство",
        "description": "Самый простой способ банкротства - внесудебная процедура",
        "video_url": "https://t.me/c/2275474152/22",
        "duration": "30 минут",
        "order": 2,
    },
    {
        "lesson_id": "lesson_1_3",
        "module_id": "extrajudicial_module",
        "title": "Урок 1.3: Как подать на внесудебное банкротство",
        "description": "Пошаговая инструкция подачи заявления",
        "video_url": "https://t.me/c/2275474152/13",
        "duration": "30 минут",
        "order": 3,
    },
    # ───────── Модуль 2: Восстановление платежеспособности ─────────
    {
        "lesson_id": "lesson_2_1",
        "module_id": "recovery_module",
        "title": "Урок 2.1: Основы восстановления платежеспособности",
        "description": "Что такое восстановление платежеспособности и кому подходит",
        "video_url": "https://t.me/c/2275474152/16",
        "duration": "30 минут",
        "order": 1,
    },
    {
        "lesson_id": "lesson_2_2",
        "module_id": "recovery_module",
        "title": "Урок 2.2: Процедура восстановления",
        "description": "Как проходит процедура восстановления платежеспособности",
        "video_url": "https://t.me/c/2275474152/14",
        "duration": "30 минут",
        "order": 2,
    },
    {
        "lesson_id": "lesson_2_3",
        "module_id": "recovery_module",
        "title": "Урок 2.3: План восстановления",
        "description": "Как составить план восстановления платежеспособности",
        "video_url": "https://t.me/c/2275474152/15",
        "duration": "30 минут",
        "order": 3,
    },
    # ───────── Модуль 3: Судебное банкротство ─────────
    {
        "lesson_id": "lesson_3_1",
        "module_id": "judicial_module",
        "title": "Урок 3.1: Что такое судебное банкротство",
        "description": "Основы судебной процедуры банкротства",
        "video_url": "https://t.me/c/2275474152/21",
        "duration": "30 минут",
        "order": 1,
    },
    {
        "lesson_id": "lesson_3_2",
        "module_id": "judicial_module",
        "title": "Урок 3.2: Процедура судебного банкротства",
        "description": "Пошаговое прохождение судебной процедуры",
        "video_url": "https://t.me/c/2275474152/18",
        "duration": "30 минут",
        "order": 2,
    },
]

# ──────────────────── Вставка данных ────────────────────
def insert_production_data():
    try:
        print("\n🚀 PRODUCTION SEED - Начинаем...")
        
        # Показываем текущее состояние
        current_courses = courses_collection.count_documents({})
        current_modules = modules_collection.count_documents({})
        current_lessons = lessons_collection.count_documents({})
        
        if current_courses > 0 or current_modules > 0 or current_lessons > 0:
            print(f"\n⚠️  ВНИМАНИЕ! В базе уже есть данные:")
            print(f"   - Курсов: {current_courses}")
            print(f"   - Модулей: {current_modules}")
            print(f"   - Уроков: {current_lessons}")
            
            # Подтверждение удаления
            print("\n❗ Эта операция УДАЛИТ ВСЕ существующие видеокурсы!")
            confirm = input("Вы уверены? Введите 'DELETE ALL' для подтверждения: ")
            
            if confirm != 'DELETE ALL':
                print("❌ Операция отменена")
                return False
        
        # Очистка старых данных
        print("\n🧹 Очищаем старые данные...")
        result_courses = courses_collection.delete_many({})
        result_modules = modules_collection.delete_many({})
        result_lessons = lessons_collection.delete_many({})
        
        print(f"   Удалено курсов: {result_courses.deleted_count}")
        print(f"   Удалено модулей: {result_modules.deleted_count}")
        print(f"   Удалено уроков: {result_lessons.deleted_count}")
        
        # Вставка новых данных
        print("📚 Добавляем курс...")
        courses_collection.insert_one(main_course)
        
        print("📦 Добавляем модули...")
        modules_collection.insert_many(modules_data)
        
        print("🎬 Добавляем уроки...")
        lessons_collection.insert_many(lessons_data)
        
        print("✅ Production данные успешно добавлены!")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при добавлении данных: {e}")
        return False

# ──────────────────── Проверка данных ────────────────────
def check_production_data():
    print("\n📊 === ПРОВЕРКА PRODUCTION ДАННЫХ ===")
    print(f"Курсов: {courses_collection.count_documents({})}")
    print(f"Модулей: {modules_collection.count_documents({})}")
    print(f"Уроков: {lessons_collection.count_documents({})}")
    
    print("\n📚 Структура курса:")
    for course in courses_collection.find():
        print(f"\n🎓 {course['title']} ({course['course_id']})")
        
        # Показываем модули
        for module in modules_collection.find({"course_id": course['course_id']}).sort("order", 1):
            print(f"  📦 {module['title']}")
            
            # Показываем уроки
            for lesson in lessons_collection.find({"module_id": module['module_id']}).sort("order", 1):
                print(f"    🎬 {lesson['title']}")
                print(f"       URL: {lesson['video_url']}")

# ──────────────────── Дополнительные функции для миграций ────────────────────
def add_new_lesson(module_id, lesson_data):
    """Добавить новый урок в существующий модуль"""
    try:
        # Находим максимальный order в модуле
        last_lesson = lessons_collection.find_one(
            {"module_id": module_id},
            sort=[("order", -1)]
        )
        
        # Устанавливаем order для нового урока
        lesson_data["order"] = (last_lesson["order"] + 1) if last_lesson else 1
        lesson_data["module_id"] = module_id
        
        # Вставляем урок
        lessons_collection.insert_one(lesson_data)
        print(f"✅ Урок '{lesson_data['title']}' добавлен!")
        
    except Exception as e:
        print(f"❌ Ошибка при добавлении урока: {e}")

def add_new_module(course_id, module_data):
    """Добавить новый модуль в курс"""
    try:
        # Находим максимальный order
        last_module = modules_collection.find_one(
            {"course_id": course_id},
            sort=[("order", -1)]
        )
        
        # Устанавливаем order для нового модуля
        module_data["order"] = (last_module["order"] + 1) if last_module else 1
        module_data["course_id"] = course_id
        
        # Вставляем модуль
        modules_collection.insert_one(module_data)
        
        # Обновляем список модулей в курсе
        courses_collection.update_one(
            {"course_id": course_id},
            {"$push": {"modules": module_data["module_id"]}}
        )
        
        print(f"✅ Модуль '{module_data['title']}' добавлен!")
        
    except Exception as e:
        print(f"❌ Ошибка при добавлении модуля: {e}")

# ──────────────────── Точка входа ────────────────────
if __name__ == "__main__":
    try:
        # Финальное подтверждение
        print("\n⚡ ФИНАЛЬНАЯ ПРОВЕРКА")
        print("Вы собираетесь инициализировать видеокурсы в PRODUCTION базе!")
        print(f"MongoDB URI: {MONGO_URI[:20]}...{MONGO_URI[-10:] if len(MONGO_URI) > 30 else ''}")
        
        final_confirm = input("\nНачать инициализацию? (yes/no): ")
        if final_confirm.lower() != 'yes':
            print("❌ Инициализация отменена")
            exit(0)
        
        # Создаем индексы
        create_indexes()
        
        # Вставляем production данные
        success = insert_production_data()
        
        if success:
            # Проверяем результат
            check_production_data()
            
            print("\n✅ PRODUCTION инициализация завершена успешно!")
            print("\n💡 Совет: Используй функции add_new_lesson() и add_new_module() для добавления контента!")
            
            # Сохраняем лог операции
            log_entry = {
                "operation": "video_courses_init",
                "timestamp": datetime.utcnow(),
                "courses_added": 1,
                "modules_added": len(modules_data),
                "lessons_added": len(lessons_data),
                "environment": "production"
            }
            print(f"\n📝 Лог операции: {log_entry}")
        else:
            print("\n❌ Инициализация не выполнена")
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Операция прервана пользователем")
        exit(1)
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        exit(1)