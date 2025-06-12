from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime
from telebot import types

load_dotenv()

# Подключение к базе (как в main.py)
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client['telegram_bot']

# Те же коллекции, что создавали
courses_collection = db['courses']
modules_collection = db['modules']
lessons_collection = db['lessons']
user_progress_collection = db['user_progress']
users_collection = db['users']  # Для проверки тарифа

class VideoCourseManager:
    def __init__(self, bot):
        self.bot = bot
    
    # Пока пустой класс - будем добавлять методы по одному
    def check_course_access(self, user_id):
        """Проверяет, есть ли у пользователя доступ к курсам (тариф 15000₸)"""
        try:
            user = users_collection.find_one({"user_id": user_id})
            
            # Если пользователь не найден - нет доступа
            if not user:
                return False
            
            # Проверяем, есть ли у него активный доступ И лимит сообщений
            has_access = user.get("access", False)
            message_limit = user.get("message_limit", 0)
            
            # Доступ к курсам только у пользователей с лимитом >= 30 сообщений
            # (это означает тариф 15000₸)
            return has_access and message_limit >= 30
            
        except Exception as e:
            print(f"[ERROR] Ошибка проверки доступа: {e}")
            return False
        
    def get_available_courses(self):
        """Получает список всех активных курсов"""
        try:
            courses = list(courses_collection.find(
                {"is_active": True}
            ).sort("created_at", 1))
            
            return courses
        except Exception as e:
            print(f"[ERROR] Ошибка получения курсов: {e}")
            return []
        
    def get_course_modules(self, course_id):
        """Получает модули конкретного курса"""
        try:
            modules = list(modules_collection.find(
                {"course_id": course_id}
            ).sort("order", 1))
            
            return modules
        except Exception as e:
            print(f"[ERROR] Ошибка получения модулей: {e}")
            return []

    def get_module_lessons(self, module_id):
        """Получает уроки конкретного модуля"""
        try:
            lessons = list(lessons_collection.find(
                {"module_id": module_id}
            ).sort("order", 1))
            
            return lessons
        except Exception as e:
            print(f"[ERROR] Ошибка получения уроков: {e}")
            return []

    def get_lesson_by_id(self, lesson_id):
        """Получает конкретный урок по ID"""
        try:
            lesson = lessons_collection.find_one({"lesson_id": lesson_id})
            return lesson
        except Exception as e:
            print(f"[ERROR] Ошибка получения урока: {e}")
        return None
    
    def get_user_progress(self, user_id, course_id):
        """Получает прогресс пользователя по курсу"""
        try:
            progress = user_progress_collection.find_one({
                "user_id": user_id,
                "course_id": course_id
            })
            
            # Если прогресса нет - создаем пустой
            if not progress:
                progress = {
                    "user_id": user_id,
                    "course_id": course_id,
                    "completed_lessons": [],
                    "current_lesson": None,
                    "progress_percent": 0,
                    "last_accessed": datetime.utcnow()
                }
                user_progress_collection.insert_one(progress)
            
            return progress
        except Exception as e:
            print(f"[ERROR] Ошибка получения прогресса: {e}")
            return None

    def mark_lesson_completed(self, user_id, lesson_id):
        """Отмечает урок как просмотренный (улучшенная версия)"""
        try:
            # Сначала находим курс этого урока
            lesson = self.get_lesson_by_id(lesson_id)
            if not lesson:
                return False
            
            module = modules_collection.find_one({"module_id": lesson["module_id"]})
            if not module:
                return False
            
            course_id = module["course_id"]
            
            # Получаем прогресс пользователя (создастся если нет)
            progress = self.get_user_progress(user_id, course_id)
            
            # Считаем процент прогресса (нужно знать сколько уроков добавится)
            current_completed = len(progress.get("completed_lessons", []))
            if lesson_id not in progress.get("completed_lessons", []):
                current_completed += 1  # Добавится новый урок
            
            course = courses_collection.find_one({"course_id": course_id})
            total_lessons = course.get("total_lessons", 1)
            progress_percent = round((current_completed / total_lessons) * 100)
            
            # ✅ УЛУЧШЕННОЕ ОБНОВЛЕНИЕ с $addToSet
            user_progress_collection.update_one(
                {"user_id": user_id, "course_id": course_id},
                {
                    "$addToSet": {"completed_lessons": lesson_id},  # Автоматически избегает дубликатов
                    "$set": {
                        "current_lesson": lesson_id,
                        "progress_percent": progress_percent,
                        "last_accessed": datetime.utcnow(),
                    },
                },
            )
            
            return True
        except Exception as e:
            print(f"[ERROR] Ошибка обновления прогресса: {e}")
            return False
        
    def create_courses_menu(self, user_id):
        """Создает главное меню курсов"""
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        courses = self.get_available_courses()
        
        for course in courses:
            course_id = course["course_id"]
            title = course["title"]
            
            # Получаем прогресс пользователя
            progress = self.get_user_progress(user_id, course_id)
            progress_percent = progress.get("progress_percent", 0)
            
            # Формируем текст кнопки с прогрессом
            if progress_percent > 0:
                button_text = f"📚 {title} ({progress_percent}%)"
            else:
                button_text = f"📚 {title}"
            
            markup.add(types.InlineKeyboardButton(
                button_text, 
                callback_data=f"course_{course_id}"
            ))
        
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu"))
        
        return markup

    def create_modules_menu(self, course_id, user_id):
        """Создает меню модулей курса"""
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        modules = self.get_course_modules(course_id)
        progress = self.get_user_progress(user_id, course_id)
        completed_lessons = progress.get("completed_lessons", [])
        
        for module in modules:
            module_id = module["module_id"]
            title = module["title"]
            
            # Считаем сколько уроков завершено в этом модуле
            module_lessons = self.get_module_lessons(module_id)
            completed_in_module = len([l for l in module_lessons if l["lesson_id"] in completed_lessons])
            total_in_module = len(module_lessons)
            
            # Формируем текст кнопки
            if completed_in_module > 0:
                button_text = f"📖 {title} ({completed_in_module}/{total_in_module})"
            else:
                button_text = f"📖 {title}"
            
            markup.add(types.InlineKeyboardButton(
                button_text,
                callback_data=f"module_{module_id}"
            ))
        
        markup.add(types.InlineKeyboardButton("🔙 К курсам", callback_data="video_courses"))
        
        return markup
    pass

# Расширенный тест
if __name__ == "__main__":
    manager = VideoCourseManager(None)
    
    print("=== РАСШИРЕННЫЙ ТЕСТ ===")
    
    # 1. Тестируем курсы
    courses = manager.get_available_courses()
    print(f"📚 Курсов: {len(courses)}")
    
    if courses:
        first_course = courses[0]
        course_id = first_course["course_id"]
        print(f"   Тестируем курс: {first_course['title']}")
        
        # 2. Тестируем модули
        modules = manager.get_course_modules(course_id)
        print(f"📖 Модулей в курсе: {len(modules)}")
        
        if modules:
            first_module = modules[0]
            module_id = first_module["module_id"]
            print(f"   Тестируем модуль: {first_module['title']}")
            
            # 3. Тестируем уроки
            lessons = manager.get_module_lessons(module_id)
            print(f"🎥 Уроков в модуле: {len(lessons)}")
            
            if lessons:
                first_lesson = lessons[0]
                lesson_id = first_lesson["lesson_id"]
                print(f"   Тестируем урок: {first_lesson['title']}")
                print(f"   Ссылка на видео: {first_lesson['video_url']}")
                
                # 4. Тестируем прогресс
                user_id = 376068212  # ЗАМЕНИТЕ НА СВОЙ ID
                progress = manager.get_user_progress(user_id, course_id)
                print(f"\n👤 Прогресс пользователя {user_id}:")
                print(f"   Завершено уроков: {len(progress.get('completed_lessons', []))}")
                print(f"   Процент: {progress.get('progress_percent', 0)}%")
                
                # 5. Тестируем отметку урока
                print(f"\n✅ Отмечаем урок как просмотренный...")
                success = manager.mark_lesson_completed(user_id, lesson_id)
                print(f"   Результат: {'Успешно' if success else 'Ошибка'}")
                
                # 6. Проверяем обновленный прогресс
                updated_progress = manager.get_user_progress(user_id, course_id)
                print(f"   Новый процент: {updated_progress.get('progress_percent', 0)}%")