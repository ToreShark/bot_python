# consultation_scheduler.py
"""
Система автоматических напоминаний о консультациях
Запускается каждый час через cron
"""

import telebot
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson import ObjectId
import os
from dotenv import load_dotenv
import logging

load_dotenv()

# Настройка логирования для отслеживания работы
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('consultation_scheduler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Подключение к MongoDB и боту
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['telegram_bot']

consultation_slots_collection = db['consultation_slots']
consultation_queue_collection = db['consultation_queue']

class ConsultationScheduler:
    """Планировщик уведомлений для консультаций"""
    
    def __init__(self):
        self.bot = bot
        logger.info("🤖 ConsultationScheduler инициализирован")
    
    def send_day_before_reminders(self):
        """Отправляет напоминания за 24 часа до консультации"""
        now = datetime.now()
        target_time = now + timedelta(hours=24)
        target_date = target_time.strftime("%Y-%m-%d")
        target_hour = f"{target_time.hour:02d}:00"

        logger.info(f"🔔 Поиск слотов на {target_date} в {target_hour} (напоминания за день)")

        # Ищем слоты на нужную дату и час
        slots = consultation_slots_collection.find({
            "date": target_date,
            "time_slot": {"$regex": f"^{target_hour}"},  # начинается с нужного часа
            "status": "open"
        })

        for slot in slots:
            slot_id = slot["slot_id"]

            # Находим первого в очереди со статусом waiting
            first_user = consultation_queue_collection.find_one({
                "slot_id": slot_id,
                "position": 1,
                "status": "waiting",
                "notifications_sent.day_before": False
            })

            if not first_user:
                continue  # никого нет или уже отправлено

            user_id = first_user["user_id"]
            date_str = slot["date"]
            time_str = slot["time_slot"]

            message = (
                f"⏰ *Напоминание!*\n\n"
                f"📅 Завтра у вас консультация:\n"
                f"🕐 {date_str} в {time_str}\n\n"
                f"✅ Пожалуйста, подтвердите участие, чтобы сохранить место."
            )

            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✅ Подтверждаю", callback_data=f"confirm_day_{slot_id}"),
                types.InlineKeyboardButton("❌ Отменяю", callback_data=f"cancel_booking_{first_user['_id']}")
            )

            try:
                self.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )

                consultation_queue_collection.update_one(
                    {"_id": first_user["_id"]},
                    {"$set": {"notifications_sent.day_before": True}}
                )

                logger.info(f"📩 Напоминание за день отправлено пользователю {user_id} для {slot_id}")

            except Exception as e:
                logger.error(f"❌ Ошибка при отправке напоминания за день: {e}")

    def send_hour_before_reminders(self):
        """Отправляет напоминания за 1 час или продвигает очередь"""
        now = datetime.now()
        target_time = now + timedelta(hours=1)
        target_date = target_time.strftime("%Y-%m-%d")
        target_hour = f"{target_time.hour:02d}:00"

        logger.info(f"⏰ Проверка слотов на {target_date} в {target_hour} (напоминания за час)")

        slots = consultation_slots_collection.find({
            "date": target_date,
            "time_slot": {"$regex": f"^{target_hour}"},
            "status": "open"
        })

        for slot in slots:
            slot_id = slot["slot_id"]

            while True:
                first_user = consultation_queue_collection.find_one({
                    "slot_id": slot_id,
                    "position": 1,
                    "status": "waiting"
                })

                if not first_user:
                    logger.info(f"📭 Нет активных участников в {slot_id}")
                    break

                user_id = first_user["user_id"]

                # Уже отправляли?
                if first_user.get("notifications_sent", {}).get("hour_before", False):
                    logger.info(f"⏳ Уже отправлено за час пользователю {user_id} — пропускаем")
                    break

                # Подтвержден ли за день?
                if first_user.get("confirmed_day_at"):
                    # Отправить финальное напоминание
                    try:
                        date_str = slot["date"]
                        time_str = slot["time_slot"]
                        message = (
                            f"📣 *Напоминание!*\n\n"
                            f"📅 Сегодня в {time_str} у вас консультация.\n"
                            f"⏱️ Остался 1 час — подтвердите, что вы на связи."
                        )
                        markup = types.InlineKeyboardMarkup()
                        markup.add(
                            types.InlineKeyboardButton("✅ Я готов(а)", callback_data=f"confirm_hour_{slot_id}"),
                            types.InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_booking_{first_user['_id']}")
                        )

                        self.bot.send_message(
                            chat_id=user_id,
                            text=message,
                            reply_markup=markup,
                            parse_mode='Markdown'
                        )

                        consultation_queue_collection.update_one(
                            {"_id": first_user["_id"]},
                            {"$set": {"notifications_sent.hour_before": True}}
                        )

                        logger.info(f"📩 Напоминание за час отправлено пользователю {user_id} в {slot_id}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки за час: {e}")
                    break  # остановиться — подтвердивший не удаляется
                else:
                    # Удаляем и двигаем очередь
                    logger.info(f"⚠️ Пользователь {user_id} не подтвердил за день — удаляется из очереди")

                    consultation_queue_collection.update_one(
                        {"_id": first_user["_id"]},
                        {"$set": {
                            "status": "cancelled",
                            "cancelled_at": datetime.utcnow()
                        }}
                    )

                    # Сдвигаем остальных
                    consultation_queue_collection.update_many(
                        {
                            "slot_id": slot_id,
                            "position": {"$gt": first_user["position"]},
                            "status": {"$nin": ["cancelled", "completed"]}
                        },
                        {"$inc": {"position": -1}}
                    )

                    logger.info(f"↩️ Очередь обновлена для {slot_id}. Ищем нового первого...")
                    # Повторим цикл с новым первым

    def promote_queue(self, slot_id: str, reason: str):
        """Продвигает очередь после отказа/неподтверждения"""
        first_user = consultation_queue_collection.find_one({
            "slot_id": slot_id,
            "position": 1,
            "status": "waiting"
        })

        if not first_user:
            logger.info(f"👤 Нет первого участника для продвижения в слоте {slot_id}")
            return

        # Отменяем первого
        consultation_queue_collection.update_one(
            {"_id": first_user["_id"]},
            {"$set": {
                "status": "cancelled",
                "cancelled_at": datetime.utcnow(),
                "cancelled_reason": reason
            }}
        )

        logger.info(f"🚫 Пользователь {first_user['user_id']} удалён из очереди ({reason})")

        # Сдвигаем остальных
        consultation_queue_collection.update_many(
            {
                "slot_id": slot_id,
                "position": {"$gt": first_user["position"]},
                "status": {"$nin": ["cancelled", "completed"]}
            },
            {"$inc": {"position": -1}}
        )

        # Новый первый
        new_first = consultation_queue_collection.find_one({
            "slot_id": slot_id,
            "position": 1,
            "status": "waiting"
        })

        date_str, time_str = slot_id.split("_")
        slot_date = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = slot_date.strftime("%d.%m.%Y")
        end_hour = int(time_str.split(":")[0]) + 1
        time_display = f"{time_str}-{end_hour:02d}:00"

        if new_first:
            user_id = new_first["user_id"]

            if reason == "no_day_confirmation":
                text = (
                    f"📢 *Освободилось место!*\n\n"
                    f"📅 Консультация: {formatted_date} в {time_display}\n"
                    f"Вы стали первым в очереди. Подтвердите участие!"
                )
                callback = f"confirm_day_{slot_id}"
                consultation_queue_collection.update_one(
                    {"_id": new_first["_id"]},
                    {"$set": {"notifications_sent.day_before": False}}
                )
            elif reason == "no_hour_confirmation":
                text = (
                    f"🚨 *СРОЧНО!*\n\n"
                    f"📅 Консультация уже через час: {formatted_date} в {time_display}\n"
                    f"Вы продвинулись в очередь и теперь первый!\n"
                    f"Подтвердите участие немедленно."
                )
                callback = f"confirm_hour_{slot_id}"
                consultation_queue_collection.update_one(
                    {"_id": new_first["_id"]},
                    {"$set": {"notifications_sent.hour_before": False}}
                )
            else:
                text = f"📅 Вы стали первым в очереди на {formatted_date} в {time_display}!"
                callback = None

            markup = types.InlineKeyboardMarkup()
            if callback:
                markup.add(
                    types.InlineKeyboardButton("✅ Подтвердить участие", callback_data=callback),
                    types.InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_booking_{new_first['_id']}")
                )

            try:
                self.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=markup if callback else None,
                    parse_mode='Markdown'
                )
                logger.info(f"📨 Новый первый уведомлён: {user_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка уведомления нового первого: {e}")

        # Уведомляем остальных о продвижении
        promoted = consultation_queue_collection.find({
            "slot_id": slot_id,
            "position": {"$gt": 1},
            "status": {"$nin": ["cancelled", "completed"]}
        })

        for user in promoted:
            try:
                self.bot.send_message(
                    chat_id=user["user_id"],
                    text=(
                        f"📈 Вы продвинулись в очереди!\n"
                        f"📅 Консультация: {formatted_date} в {time_display}\n"
                        f"📍 Новое место: {user['position'] - 1}"
                    ),
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.warning(f"⚠️ Не удалось уведомить {user['user_id']}: {e}")

    def check_expired_confirmations(self):
        """Обрабатывает просроченные подтверждения и продвигает очередь"""
        now = datetime.now()

        # 🔍 1. Проверка просроченных подтверждений за день (больше 3 часов назад)
        three_hours_ago = now - timedelta(hours=3)
        expired_day = consultation_queue_collection.find({
            "status": "waiting",
            "confirmed_day_at": None,
            "notifications_sent.day_before": True,
            "registered_at": {"$lte": three_hours_ago}
        })

        for user in expired_day:
            slot_id = user["slot_id"]
            logger.info(f"⏱ Просрочено подтверждение за день: {user['user_id']} → {slot_id}")
            self.promote_queue(slot_id, reason="no_day_confirmation")

        # 🔍 2. Проверка просроченных подтверждений за час (больше 30 минут назад)
        thirty_minutes_ago = now - timedelta(minutes=30)
        hour_limit = now + timedelta(minutes=30)  # если до консультации <30 мин

        slots = consultation_slots_collection.find({
            "status": "open"
        })

        for slot in slots:
            slot_id = slot["slot_id"]
            date_str, time_str = slot_id.split("_")
            slot_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")

            # Пропускаем, если до слота больше 30 минут
            if slot_dt > hour_limit:
                continue

            user = consultation_queue_collection.find_one({
                "slot_id": slot_id,
                "position": 1,
                "status": "waiting",
                "confirmed_hour_at": None,
                "notifications_sent.hour_before": True,
                "registered_at": {"$lte": thirty_minutes_ago}
            })

            if user:
                logger.info(f"🚨 Просрочено подтверждение за час: {user['user_id']} → {slot_id}")
                self.promote_queue(slot_id, reason="no_hour_confirmation")

    def run_scheduled_tasks(self):
        """Главный запуск всех проверок и уведомлений"""
        logger.info(f"🕒 Запуск плановых задач: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            self.check_expired_confirmations()
            logger.info("✅ Завершено: check_expired_confirmations")
        except Exception as e:
            logger.error(f"❌ Ошибка в check_expired_confirmations: {e}")

        try:
            self.send_day_before_reminders()
            logger.info("✅ Завершено: send_day_before_reminders")
        except Exception as e:
            logger.error(f"❌ Ошибка в send_day_before_reminders: {e}")

        try:
            self.send_hour_before_reminders()
            logger.info("✅ Завершено: send_hour_before_reminders")
        except Exception as e:
            logger.error(f"❌ Ошибка в send_hour_before_reminders: {e}")

        logger.info("🏁 Плановые задачи завершены.\n")
