# admin_consultation.py

from telebot import types
from pymongo import MongoClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from db import consultation_slots_collection, consultation_queue_collection


load_dotenv()

DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"
env = "dev" if DEBUG_MODE else "prod"

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
            # сводка по всем слотам /all_consultations
            types.InlineKeyboardButton("📅 Сводка по всем слотам", callback_data="admin_all_slots"),
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

    def show_today_slots(self, message, user_id=None):
        if user_id is not None and user_id not in self.ADMIN_IDS:
            self.bot.send_message(message.chat.id, "⛔️ У вас нет доступа.")
            return

        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        readable_date = today.strftime("%d.%m.%Y")

        slots = list(consultation_queue_collection.find({"date": today_str}).sort("time_slot", 1))

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

            print(f"Current slot status: {slot['status']}")
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

    def show_slot_details(self, call, slot_id):
        slot = consultation_slots_collection.find_one({"slot_id": slot_id})
        if not slot:
            self.bot.answer_callback_query(call.id, "❌ Слот не найден")
            return

        queue = list(consultation_queue_collection.find(
            {"slot_id": slot_id, "status": {"$nin": ["cancelled", "completed"]}}
        ).sort("position", 1))

        date_str = slot.get("date", "—")
        time_slot = slot.get("time_slot", "—")
        formatted_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")

        header = f"📋 *ДЕТАЛИ СЛОТА:* {formatted_date} {time_slot}\n\n"
        header += f"👥 *ОЧЕРЕДЬ* ({len(queue)} человек):\n\n"

        medal_icons = ["🥇", "🥈", "🥉"]
        text_lines = []
        markup = types.InlineKeyboardMarkup(row_width=2)

        for idx, user in enumerate(queue):
            user_name = user.get("user_name", "Неизвестно")
            user_id = user.get("user_id", "—")
            status = user.get("status", "waiting")
            booking_id = user.get("_id")
            registered_at = user.get("registered_at")

            status_map = {
                "waiting": "ожидает",
                "confirmed_day": "подтвердил за день",
                "confirmed_hour": "подтвердил за час"
            }
            status_text = status_map.get(status, status)

            reg_dt = registered_at.strftime("%d.%m.%Y %H:%M") if registered_at else "—"
            icon = medal_icons[idx] if idx < 3 else f"{idx + 1}."

            text_lines.append(
                f"{icon} *{idx + 1}. {user_name}*\n"
                f"   📱 ID: `{user_id}`\n"
                f"   📊 Статус: {status_text}\n"
                f"   📅 Записался: {reg_dt}"
            )

            markup.add(
                types.InlineKeyboardButton("❌ Убрать", callback_data=f"admin_remove_user_{booking_id}"),
                types.InlineKeyboardButton("📞 Написать", callback_data=f"admin_message_user_{user_id}")
            )

        markup.add(types.InlineKeyboardButton("🔙 Назад к слотам", callback_data="admin_consultations"))

        full_text = header + "\n\n".join(text_lines)
        self.bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=full_text,
            reply_markup=markup,
            parse_mode="Markdown"
        )

    def show_week_slots(self, call):
        """Показывает администратору слоты на 7 дней вперед с кнопками управления."""
        if call.from_user.id not in self.ADMIN_IDS:
            self.bot.answer_callback_query(call.id, "⛔️ У вас нет доступа.")
            return

        # 1. Определяем диапазон дат
        today = datetime.now()
        end_date = today + timedelta(days=6)
        
        today_str = today.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        # 2. Ищем все слоты в этом диапазоне
        # ДОЛЖНО БЫТЬ:
        slots = list(consultation_slots_collection.find({
            "date": {"$gte": today_str, "$lte": end_date_str},
            "status": {"$ne": "cancelled"}
        }).sort([("date", 1), ("time_slot", 1)]))

        if not slots:
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="📅 На предстоящие 7 дней нет запланированных слотов."
            )
            return

        # 3. Показываем каждый слот отдельной карточкой
        for slot in slots:
            slot_id = slot["slot_id"]
            time_slot = slot["time_slot"]
            status = slot["status"]
            date_str = slot["date"]
            
            # Маркер даты
            formatted_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
            date_marker = f"🔹 СЕГОДНЯ ({formatted_date})" if date_str == today_str else f"🔸 {formatted_date}"
            
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
                f"{date_marker}\n"
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
                chat_id=call.message.chat.id,
                text=text,
                reply_markup=markup,
                parse_mode='Markdown'
            )

    def show_all_slots(self, call):
        """Показывает администратору сводку по всем слотам."""
        # print("show_all_slots called")
        if call.from_user.id not in self.ADMIN_IDS:
            self.bot.answer_callback_query(call.id, "⛔️ У вас нет доступа.")
            return
        
        # ДОЛЖНО БЫТЬ:
        # slots = list(consultation_slots_collection.find({
        #     # "status": {"$ne": "cancelled"}  # ← ТОЛЬКО фильтр статуса
        # }).sort([("date", 1), ("time_slot", 1)]))
        # ИСПРАВЛЕННЫЙ запрос - показывает ВСЕ слоты (включая отмененные):
        slots = list(consultation_slots_collection.find({}).sort([("date", 1), ("time_slot", 1)]))
        if not slots:
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="📅 На данный момент нет доступных слотов."
            )
            return

        text_lines = ["📅 *ВСЕ КОНСУЛЬТАЦИИ*"]
        total_registrations = 0

        for slot in slots:
            slot_id = slot["slot_id"]
            date_str = slot["date"]
            time_slot = slot["time_slot"]

            # Получаем всех активных участников очереди
            queue = list(consultation_queue_collection.find({
                "slot_id": slot_id,
                "status": {"$nin": ["cancelled", "completed"]}
            }))
            
            queue_count = len(queue)
            total_registrations += queue_count
            
            # Считаем подтвердивших
            confirmed_count = 0
            for user in queue:
                if user.get("status") in ["confirmed_day", "confirmed_hour"]:
                    confirmed_count += 1
            
            formatted_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
            text_lines.append(f"🗓️ *{formatted_date}* 🕐 `{time_slot}` → {queue_count} чел. ({confirmed_count} подтв.)")

        text_lines.append(f"\nВсего записей: *{total_registrations}* человек.")

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад в меню", callback_data="admin_consultations_menu"))

        self.bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="\n".join(text_lines),
            reply_markup=markup,
            parse_mode='Markdown'
        )
        
   # я открываю детали слота и вижу три кнопки: "Детали", "Изменить", "Отменить". 
   # теперь надо реализовать логику для кнопки "Отменить", чтобы админ мог отменить и пользователю пришло уведомление.
    def cancel_slot(self, call, slot_id):
        """Отменяет слот и уведомляет всех участников."""
        if call.from_user.id not in self.ADMIN_IDS:
            self.bot.answer_callback_query(call.id, "⛔️ У вас нет доступа.")
            return

        slot = consultation_slots_collection.find_one({"slot_id": slot_id})
        if not slot:
            self.bot.answer_callback_query(call.id, "❌ Слот не найден")
            return

        # Получаем всех участников очереди ПЕРЕД удалением
        queue = list(consultation_queue_collection.find({"slot_id": slot_id}))
        
        # УДАЛЯЕМ слот из базы данных (вместо изменения статуса)
        result = consultation_slots_collection.delete_one({"slot_id": slot_id})
        
        # УДАЛЯЕМ все записи в очереди для этого слота
        queue_result = consultation_queue_collection.delete_many({"slot_id": slot_id})

        # Уведомляем всех участников
        for user in queue:
            user_id = user["user_id"]
            user_name = user.get("user_name", "Пользователь")
            text = (
                f"❌ *Слот отменён*\n\n"
                f"Здравствуйте, {user_name}!\n\n"
                f"К сожалению, слот на {slot['date']} в {slot['time_slot']} был отменён.\n"
                f"Вы можете записаться на другой доступный слот."
            )
            try:
                self.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
            except Exception as e:
                print(f"Не удалось отправить уведомление {user_id}: {e}")

        self.bot.answer_callback_query(call.id, "✅ Слот удален и участники уведомлены.")
        self.bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ Слот удален и участники уведомлены.\n💡 Теперь пользователи смогут записаться на это время заново.",
            reply_markup=None
        )
