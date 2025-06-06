# admin_consultation.py

from telebot import types
from pymongo import MongoClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["telegram_bot"]

consultation_slots_collection = db["consultation_slots"]
consultation_queue_collection = db["consultation_queue"]

class AdminConsultationManager:
    def __init__(self, bot):
        self.bot = bot
        self.ADMIN_IDS = [376068212, 827743984]  # Добавьте нужные ID

    def show_admin_menu(self, message):
        if message.from_user.id not in self.ADMIN_IDS:
            self.bot.send_message(message.chat.id, "⛔️ У вас нет доступа.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📅 Слоты на сегодня", callback_data="admin_slots_today"),
            types.InlineKeyboardButton("🗓 Слоты на неделю", callback_data="admin_slots_week"),
            types.InlineKeyboardButton("➕ Добавить слот", callback_data="admin_add_slot"),
            types.InlineKeyboardButton("📋 Очередь по слоту", callback_data="admin_view_queue"),
            types.InlineKeyboardButton("📤 Ручная отправка напоминаний", callback_data="admin_send_reminders")
        )

        self.bot.send_message(
            message.chat.id,
            "👨‍💼 *Админ-панель консультаций*\nВыберите действие:",
            reply_markup=markup,
            parse_mode='Markdown'
        )

    def show_slots_today(self, message):
        """Показывает все консультационные слоты на сегодня"""
        if message.from_user.id not in self.ADMIN_IDS:
            self.bot.send_message(message.chat.id, "⛔️ У вас нет доступа.")
            return

        today = datetime.now().strftime("%Y-%m-%d")
        slots = consultation_slots_collection.find({
            "date": today
        }).sort("time_slot", 1)

        if slots.count() == 0:
            self.bot.send_message(message.chat.id, "📅 На сегодня слоты отсутствуют.")
            return

        text = f"📅 *Слоты на сегодня* ({today}):\n\n"
        for slot in slots:
            slot_id = slot["slot_id"]
            time_slot = slot["time_slot"]
            status = slot["status"]
            queue_count = consultation_queue_collection.count_documents({
                "slot_id": slot_id,
                "status": {"$nin": ["cancelled", "completed"]}
            })
            text += f"🕐 `{time_slot}` | Статус: *{status}* | В очереди: *{queue_count}*\n"

        self.bot.send_message(
            chat_id=message.chat.id,
            text=text,
            parse_mode='Markdown'
        )

    def show_today_slots(self, message):
        """Показывает администратору все слоты на сегодня"""
        if message.from_user.id not in self.ADMIN_IDS:
            self.bot.send_message(message.chat.id, "⛔️ У вас нет доступа.")
            return

        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        readable_date = today.strftime("%d.%m.%Y")

        slots = list(consultation_slots_collection.find({"date": today_str}).sort("time_slot", 1))

        if not slots:
            self.bot.send_message(message.chat.id, f"📅 На сегодня ({readable_date}) слоты не найдены.")
            return

        for slot in slots:
            slot_id = slot["slot_id"]
            time_slot = slot["time_slot"]
            status = slot["status"]

            # Очередь
            queue = list(consultation_queue_collection.find({
                "slot_id": slot_id,
                "status": {"$nin": ["cancelled", "completed"]}
            }).sort("position", 1))
            queue_count = len(queue)

            # Первый в очереди
            if queue:
                first_user = queue[0]
                name = first_user.get("user_name", "Неизвестно")
                stat = first_user.get("status", "waiting")
                if stat == "waiting":
                    status_text = "ожидает"
                elif stat == "confirmed_day":
                    status_text = "подтвердил за день"
                elif stat == "confirmed_hour":
                    status_text = "подтвердил за час"
                else:
                    status_text = stat
                first_line = f"🥇 Первый: {name} ({status_text})"
            else:
                first_line = "🥇 Первый: —"

            # Текст слота
            text = (
                f"🕐 *{time_slot}*\n"
                f"👥 Очередь: {queue_count} человек(а)\n"
                f"{first_line}\n"
                f"📊 Статус: *{status}*"
            )

            # Кнопки управления
            markup = types.InlineKeyboardMarkup(row_width=3)
            markup.add(
                types.InlineKeyboardButton("📋 Детали", callback_data=f"admin_slot_details_{slot_id}"),
                types.InlineKeyboardButton("⚙️ Изменить", callback_data=f"admin_edit_slot_{slot_id}"),
                types.InlineKeyboardButton("❌ Отменить", callback_data=f"admin_cancel_slot_{slot_id}")
            )

            self.bot.send_message(
                chat_id=message.chat.id,
                text=text,
                reply_markup=markup,
                parse_mode='Markdown'
            )

    def edit_slot_time(self, slot_id, new_time):
        """Изменяет время слота и уведомляет всех участников"""
        try:
            # Получение текущего слота
            slot = consultation_slots_collection.find_one({"slot_id": slot_id})
            if not slot:
                logger.warning(f"Слот {slot_id} не найден.")
                return

            # Проверка нового времени — оно должно быть в будущем
            date_str = slot["date"]
            new_slot_id = f"{date_str}_{new_time}"
            new_time_slot = f"{new_time}-{int(new_time.split(':')[0]) + 1:02d}:00"

            slot_datetime = datetime.strptime(f"{date_str} {new_time}", "%Y-%m-%d %H:%M")
            if slot_datetime <= datetime.now():
                logger.warning(f"Новое время {new_time} должно быть в будущем.")
                return

            # Обновляем слот
            consultation_slots_collection.update_one(
                {"slot_id": slot_id},
                {
                    "$set": {
                        "slot_id": new_slot_id,
                        "time_slot": new_time_slot
                    }
                }
            )

            # Обновляем все записи в очереди
            affected_users = list(consultation_queue_collection.find({"slot_id": slot_id}))
            for user in affected_users:
                consultation_queue_collection.update_one(
                    {"_id": user["_id"]},
                    {"$set": {"slot_id": new_slot_id}}
                )

            # Оповещение всех участников
            for user in affected_users:
                user_id = user["user_id"]
                position = user["position"]
                user_name = user.get("user_name", "Пользователь")
                old_time = slot["time_slot"]
                formatted_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")

                text = (
                    f"⚠️ *ИЗМЕНЕНИЕ ВРЕМЕНИ КОНСУЛЬТАЦИИ*\n\n"
                    f"Здравствуйте, {user_name}!\n\n"
                    f"📅 Дата: {formatted_date}\n"
                    f"🕐 Было: {old_time}\n"
                    f"🕐 Стало: {new_time_slot}\n\n"
                    f"📍 Ваше место в очереди не изменилось: *{position}*\n\n"
                    f"Пожалуйста, подтвердите, что новое время вам подходит."
                )

                markup = types.InlineKeyboardMarkup()
                markup.add(
                    types.InlineKeyboardButton(
                        "✅ Подтверждаю новое время",
                        callback_data=f"confirm_time_change_{user['_id']}"
                    ),
                    types.InlineKeyboardButton(
                        "❌ Отменяю запись",
                        callback_data=f"cancel_due_time_change_{user['_id']}"
                    )
                )

                try:
                    self.bot.send_message(
                        chat_id=user_id,
                        text=text,
                        reply_markup=markup,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление {user_id}: {e}")

            logger.info(f"✅ Слот {slot_id} успешно перенесён на {new_time}, уведомлено {len(affected_users)} человек.")

        except Exception as e:
            logger.error(f"❌ Ошибка при изменении времени слота: {e}")
