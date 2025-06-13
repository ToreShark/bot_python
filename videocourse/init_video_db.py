from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# ──────────────────── Подключение к MongoDB ────────────────────
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
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

# ──────────────────── Данные для сидирования ────────────────────
course_1 = {
    "course_id": "bankruptcy_basics",
    "title": "Основы банкротства физических лиц",
    "description": "Полный курс по банкротству в Казахстане",
    "modules": ["intro_module", "procedures_module", "documents_module"],
    "created_at": datetime.utcnow(),
    "is_active": True,
    "total_lessons": 9,
    "estimated_duration": "3 часа",
}

course_2 = {
    "course_id": "creditor_relations",
    "title": "Работа с кредиторами",
    "description": "Как правильно общаться с банками и МФО",
    "modules": ["negotiation_module", "legal_module"],
    "created_at": datetime.utcnow(),
    "is_active": True,
    "total_lessons": 6,
    "estimated_duration": "2 часа",
}

modules_data = [
    # Курс 1: Основы банкротства
    {
        "module_id": "intro_module",
        "course_id": "bankruptcy_basics",
        "title": "Модуль 1: Введение в банкротство",
        "description": "Основные понятия и термины",
        "lessons": ["lesson_1_1", "lesson_1_2", "lesson_1_3"],
        "order": 1,
        "estimated_duration": "45 минут",
    },
    {
        "module_id": "procedures_module",
        "course_id": "bankruptcy_basics",
        "title": "Модуль 2: Процедуры банкротства",
        "description": "Внесудебное и судебное банкротство",
        "lessons": ["lesson_2_1", "lesson_2_2", "lesson_2_3"],
        "order": 2,
        "estimated_duration": "60 минут",
    },
    {
        "module_id": "documents_module",
        "course_id": "bankruptcy_basics",
        "title": "Модуль 3: Документооборот",
        "description": "Какие документы нужны и как их оформить",
        "lessons": ["lesson_3_1", "lesson_3_2", "lesson_3_3"],
        "order": 3,
        "estimated_duration": "75 минут",
    },
]

lessons_data = [
    # ───────── Модуль 1 ─────────
    {
        "lesson_id": "lesson_1_1",
        "module_id": "intro_module",
        "title": "Урок 1.1: Что такое банкротство",
        "description": "Определение и основные принципы",
        "video_url": "https://t.me/c/2275474152/23",
        "duration": "",
        "order": 1,
    },
    {
        "lesson_id": "lesson_1_2",
        "module_id": "intro_module",
        "title": "Урок 1.2: Кто может стать банкротом",
        "description": "Условия и требования к должнику",
        "video_url": "https://t.me/c/2275474152/22",
        "duration": "",
        "order": 2,
    },
    {
        "lesson_id": "lesson_1_3",
        "module_id": "intro_module",
        "title": "Урок 1.3: Последствия банкротства",
        "description": "Что происходит после процедуры",
        "video_url": "https://t.me/c/2275474152/21",
        "duration": "",
        "order": 3,
    },
    # ───────── Модуль 2 ─────────
    {
        "lesson_id": "lesson_2_1",
        "module_id": "procedures_module",
        "title": "Урок 2.1: Внесудебная процедура",
        "description": "Ключевые шаги внесудебного банкротства",
        "video_url": "https://t.me/c/2275474152/20",
        "duration": "",
        "order": 1,
    },
    {
        "lesson_id": "lesson_2_2",
        "module_id": "procedures_module",
        "title": "Урок 2.2: Судебная процедура",
        "description": "Как проходит судебное банкротство",
        "video_url": "https://t.me/c/2275474152/19",
        "duration": "",
        "order": 2,
    },
    {
        "lesson_id": "lesson_2_3",
        "module_id": "procedures_module",
        "title": "Урок 2.3: Ограничения и риски",
        "description": "На что обратить внимание должнику",
        "video_url": "https://t.me/c/2275474152/18",
        "duration": "",
        "order": 3,
    },
    # ───────── Модуль 3 ─────────
    {
        "lesson_id": "lesson_3_1",
        "module_id": "documents_module",
        "title": "Урок 3.1: Базовые документы",
        "description": "Перечень обязательных бумаг",
        "video_url": "https://t.me/c/2275474152/17",
        "duration": "",
        "order": 1,
    },
    {
        "lesson_id": "lesson_3_2",
        "module_id": "documents_module",
        "title": "Урок 3.2: Образцы заявлений",
        "description": "Скачать и заполнить правильно",
        "video_url": "https://t.me/c/2275474152/16",
        "duration": "",
        "order": 2,
    },
    {
        "lesson_id": "lesson_3_3",
        "module_id": "documents_module",
        "title": "Урок 3.3: Подготовка к подаче",
        "description": "Финальная проверка комплекта",
        "video_url": "https://t.me/c/2275474152/15",
        "duration": "",
        "order": 3,
    },
]

# ──────────────────── Вставка данных ────────────────────
def insert_test_data():
    try:
        print("Очищаем старые данные...")
        courses_collection.delete_many({})
        modules_collection.delete_many({})
        lessons_collection.delete_many({})

        print("Добавляем курсы...")
        courses_collection.insert_many([course_1, course_2])

        print("Добавляем модули...")
        modules_collection.insert_many(modules_data)

        print("Добавляем уроки...")
        lessons_collection.insert_many(lessons_data)

        print("✅ Тестовые данные добавлены!")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

# ──────────────────── Проверка ────────────────────
def check_data():
    print("\n=== ПРОВЕРКА ДАННЫХ ===")
    print(f"Курсов: {courses_collection.count_documents({})}")
    print(f"Модулей: {modules_collection.count_documents({})}")
    print(f"Уроков: {lessons_collection.count_documents({})}")

    print("\nКурсы:")
    for course in courses_collection.find():
        print(f"  • {course['title']} ({course['course_id']})")

# ──────────────────── Точка входа ────────────────────
if __name__ == "__main__":
    create_indexes()
    insert_test_data()
    check_data()
