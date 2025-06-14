# admin_consultation.py

from telebot import types
from pymongo import MongoClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from db import consultation_slots_collection, consultation_queue_collection
import threading
import time
from datetime import datetime, timedelta


load_dotenv()

DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"
env = "dev" if DEBUG_MODE else "prod"
ADMIN_IDS = [376068212, 827743984]  # Добавьте нужные ID администраторов

class AdminConsultationManager:
    def __init__(self, bot, user_states_dict):
        self.bot = bot
        self.user_states = user_states_dict
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
    
    def manual_send_reminders(self, call):
        """Ручная отправка всех напоминаний (кнопка админа)"""
        if call.from_user.id not in self.ADMIN_IDS:
            self.bot.answer_callback_query(call.id, "⛔️ У вас нет доступа.")
            return
        
        try:
            # Показываем процесс
            status_msg = self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="📤 **Ручная отправка напоминаний**\n\n⏳ Проверяю базу данных...",
                parse_mode='Markdown'
            )
            
            # Создаем планировщик и запускаем проверку
            scheduler = ConsultationNotificationScheduler(self.bot)
            total_sent = scheduler.check_and_send_notifications()
            
            # Показываем результат
            if total_sent > 0:
                result_text = (
                    f"📤 **Ручная отправка завершена**\n\n"
                    f"✅ Отправлено уведомлений: **{total_sent}**\n"
                    f"📊 Проверка выполнена успешно."
                )
            else:
                result_text = (
                    f"📤 **Ручная отправка завершена**\n\n"
                    f"ℹ️ Нет уведомлений для отправки.\n"
                    f"📊 Все участники уже уведомлены или слоты неактуальны."
                )
            
            from telebot import types
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=status_msg.message_id,
                text=result_text,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 Назад в меню", callback_data="admin_consultations_menu")
                ),
                parse_mode='Markdown'
            )
            
            self.bot.answer_callback_query(call.id, f"✅ Отправлено: {total_sent}")
            
        except Exception as e:
            print(f"[ERROR] Ошибка ручной отправки: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка при отправке напоминаний")

    def find_empty_slot(self):
        """Находит первый доступный пустой слот для автоматической записи"""
        from datetime import datetime, timedelta
        import pytz
        
        # Получить текущее время с учетом часового пояса (Алматы)
        almaty_tz = pytz.timezone('Asia/Almaty')
        now = datetime.now(almaty_tz)
        today_str = now.strftime("%Y-%m-%d")
        
        # Запрос к БД для поиска открытых слотов
        slots = consultation_slots_collection.find({
            "status": "open",
            "date": {"$gte": today_str}
        }).sort([("date", 1), ("time_slot", 1)])
        
        for slot in slots:
            try:
                slot_date = slot["date"]
                time_slot = slot["time_slot"]
                slot_id = f"{slot_date}_{time_slot.split('-')[0]}"
                
                # Проверить, что время еще не прошло
                slot_datetime_str = f"{slot_date} {time_slot.split('-')[0]}"
                slot_datetime = datetime.strptime(slot_datetime_str, "%Y-%m-%d %H:%M")
                slot_datetime = almaty_tz.localize(slot_datetime)
                
                if slot_datetime <= now:
                    continue  # Слот уже прошел
                
                # Подсчитать количество активных записей
                active_bookings = consultation_queue_collection.count_documents({
                    "slot_id": slot_id,
                    "status": {"$nin": ["cancelled", "completed"]}
                })
                
                # Если записей 0 - вернуть информацию о слоте
                if active_bookings == 0:
                    slot_date_obj = datetime.strptime(slot_date, "%Y-%m-%d")
                    formatted_date = slot_date_obj.strftime("%d.%m.%Y")
                    
                    return {
                        "slot_id": slot_id,
                        "date": slot_date,
                        "time_slot": time_slot,
                        "formatted_date": formatted_date
                    }
                    
            except Exception as e:
                print(f"[ERROR] Ошибка при обработке слота {slot}: {e}")
                continue
        
        # Если пустых слотов нет - вернуть None
        return None

    def handle_rebooking_cancel(self, call, booking_id):
        """Обрабатывает отмену записи при перезаписи"""
        from bson import ObjectId
        from datetime import datetime
        
        try:
            # Находим запись пользователя
            booking = consultation_queue_collection.find_one({"_id": ObjectId(booking_id)})
            if not booking:
                self.bot.answer_callback_query(call.id, "❌ Запись не найдена")
                return
            
            user_id = booking["user_id"]
            slot_id = booking["slot_id"]
            position = booking["position"]
            
            # Отменяем запись
            consultation_queue_collection.update_one(
                {"_id": ObjectId(booking_id)},
                {"$set": {
                    "status": "cancelled",
                    "cancelled_at": datetime.utcnow(),
                    "cancelled_reason": "user_rebooking_cancel"
                }}
            )
            
            # Обновляем позиции других участников в очереди (сдвигаем на -1)
            consultation_queue_collection.update_many(
                {
                    "slot_id": slot_id,
                    "position": {"$gt": position},
                    "status": {"$nin": ["cancelled", "completed"]}
                },
                {"$inc": {"position": -1}}
            )
            
            # Убираем состояние ожидания
            if user_id in self.user_states:
                del self.user_states[user_id]
            
            # Получаем информацию о слоте для отображения
            date_str, time_str = slot_id.split("_")
            slot_date = datetime.strptime(date_str, "%Y-%m-%d")
            formatted_date = slot_date.strftime("%d.%m.%Y")
            end_hour = int(time_str.split(":")[0]) + 1
            time_display = f"{time_str}-{end_hour:02d}:00"
            
            # Отправляем подтверждение об отмене
            confirmation_text = (
                f"✅ **Запись отменена**\n\n"
                f"📅 Отмененная консультация:\n"
                f"🗓 Дата: {formatted_date}\n"
                f"🕐 Время: {time_display}\n\n"
                f"💡 **Что дальше?**\n"
                f"Вы можете записаться на другое время когда будет удобно"
            )
            
            # Создаем кнопки
            from telebot import types
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("📅 Записаться заново", callback_data="free_consultation"),
                types.InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")
            )
            
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=confirmation_text,
                reply_markup=markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            print(f"[ERROR] Ошибка в handle_rebooking_cancel: {e}")
            self.bot.answer_callback_query(call.id, "❌ Произошла ошибка при отмене")

    #новый метод handle_admin_callback
    #Этот метод должен проверять если call.data.startswith("admin_message_user_")
    #Извлекать user_id из callback_data
    #Устанавливать состояние админа для ввода сообщения
    def handle_admin_callback(self, call):
        if call.data.startswith("admin_message_user_"):
            user_id = int(call.data.split("_")[-1])
            admin_id = call.from_user.id

            if admin_id not in self.ADMIN_IDS:
                self.bot.answer_callback_query(call.id, "⛔️ У вас нет доступа.")
                return
            
            self.user_states[admin_id] = f"admin_messaging_{user_id}"
            # print(f"[DEBUG] Состояние установлено: {self.user_states.get(admin_id)}")
            # print(f"[DEBUG] id(user_states): {id(self.user_states)}")
            # ❌ УБРАТЬ ЭТУ СТРОКУ:
            # from main import user_states
            
            # ✅ ДОБАВИТЬ ПРЯМОЙ ДОСТУП К ГЛОБАЛЬНОЙ ПЕРЕМЕННОЙ:
            import main
            main.user_states[admin_id] = f"admin_messaging_{user_id}"
            
            # 🔧 ОТЛАДКА
            # print(f"[DEBUG] Установлено состояние админа {admin_id}: admin_messaging_{user_id}")
            # print(f"[DEBUG] Проверка состояния сразу: {main.user_states.get(admin_id)}")
            
            self.bot.send_message(
                chat_id=call.message.chat.id,
                text=f"✍️ Введите сообщение для пользователя с ID `{user_id}`:",
                reply_markup=types.ReplyKeyboardRemove(),
                parse_mode='Markdown'
            )      
    


class ConsultationNotificationScheduler:
    def __init__(self, bot):
        self.bot = bot
        self.running = False
        self.thread = None

    def start_scheduler(self):
        """Запускает планировщик уведомлений"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._scheduler_loop, daemon=True)
            self.thread.start()
            print("[INFO] 📅 Планировщик консультаций запущен")

    def stop_scheduler(self):
        """Останавливает планировщик"""
        self.running = False
        if self.thread:
            self.thread.join()
        print("[INFO] 📅 Планировщик консультаций остановлен")

    def _scheduler_loop(self):
        """Оптимизированный цикл планировщика"""
        while self.running:
            try:
                now = datetime.now()
                
                # 1️⃣ Проверяем уведомления за ДЕНЬ - только в 10:00 и 18:00
                if now.hour in [10, 18] and now.minute < 5:
                    print(f"[INFO] 📅 Проверка уведомлений за день: {now.strftime('%H:%M')}")
                    self.send_day_before_notifications(now)
                
                # 2️⃣ Проверяем уведомления за ЧАС - только в рабочее время (12:00-18:00)
                if 12 <= now.hour <= 18 and now.minute < 5:
                    print(f"[INFO] ⏰ Проверка уведомлений за час: {now.strftime('%H:%M')}")
                    self.send_hour_before_notifications(now)

                # 3️⃣ Обрабатываем завершенные консультации (16-18 каждый час)
                if now.hour in [16, 17, 18] and now.minute < 5:
                    print(f"[INFO] 🧹 Очистка завершенных слотов: {now.strftime('%H:%M')}")
                    self.cleanup_completed_consultations()
                
                # 🌙 НОЧНОЙ РЕЖИМ: проверяем реже
                if 22 <= now.hour or now.hour <= 6:
                    sleep_time = 3600  # 1 час ночью
                else:
                    sleep_time = 300   # 5 минут днем
                
                time.sleep(sleep_time)
                
            except Exception as e:
                print(f"[ERROR] Ошибка в планировщике: {e}")
                time.sleep(300)

    def check_and_send_notifications(self):
        """Принудительная проверка (для ручного режима)"""
        now = datetime.now()
        print(f"[INFO] 🔧 Ручная проверка уведомлений: {now.strftime('%d.%m.%Y %H:%M')}")
        
        day_count = self.send_day_before_notifications(now)
        hour_count = self.send_hour_before_notifications(now)
        
        total = day_count + hour_count
        print(f"[INFO] ✅ Отправлено уведомлений: {total}")
        return total

    def send_day_before_notifications(self, now):
        """Отправляет уведомления за день"""
        from db import consultation_slots_collection, consultation_queue_collection
        
        tomorrow_start = now + timedelta(hours=20)
        tomorrow_date = tomorrow_start.strftime("%Y-%m-%d")
        
        bookings_to_notify = list(consultation_queue_collection.find({
            "status": {"$nin": ["cancelled", "completed"]},
            "notifications_sent.day_before": False,
            "slot_id": {"$regex": f"^{tomorrow_date}"}
        }))

        sent_count = 0
        for booking in bookings_to_notify:
            try:
                self._send_day_before_notification(booking)
                consultation_queue_collection.update_one(
                    {"_id": booking["_id"]},
                    {"$set": {"notifications_sent.day_before": True}}
                )
                sent_count += 1
                
            except Exception as e:
                print(f"[ERROR] Ошибка дневного уведомления {booking['user_id']}: {e}")

        return sent_count

    def cleanup_completed_consultations(self):
        """Обрабатывает консультации, время которых прошло"""
        from db import consultation_slots_collection, consultation_queue_collection
        from bson import ObjectId
        now = datetime.now()
        threshold = now - timedelta(hours=1)

        slots = list(consultation_slots_collection.find({}))
        for slot in slots:
            slot_id = slot.get("slot_id")
            if not slot_id:
                continue
            date_str, time_str = slot_id.split("_")
            slot_start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            slot_end = slot_start + timedelta(hours=1)

            if slot_end > threshold:
                continue  # еще не завершился

            queue = list(consultation_queue_collection.find({
                "slot_id": slot_id,
                "status": {"$nin": ["cancelled", "completed", "missed"]}
            }).sort("position", 1))

            if not queue:
                continue

            for idx, booking in enumerate(queue):
                booking_id = booking["_id"]
                if idx == 0:
                    if booking["status"] == "confirmed_hour":
                        new_status = "completed"
                    elif booking["status"] == "waiting":
                        new_status = "missed"
                    else:
                        new_status = booking["status"]

                    consultation_queue_collection.update_one(
                        {"_id": ObjectId(booking_id)},
                        {"$set": {"status": new_status}}
                    )
                else:
                    consultation_queue_collection.update_one(
                        {"_id": ObjectId(booking_id)},
                        {"$set": {
                            "status": "cancelled",
                            "cancelled_at": datetime.utcnow(),
                            "cancelled_reason": "slot_completed"
                        }}
                    )
                    try:
                        self._send_reschedule_notification(booking)
                    except Exception as e:
                        print(f"[WARN] Не удалось отправить уведомление {booking.get('user_id')}: {e}")

    def _send_reschedule_notification(self, booking):
        """Уведомляет пользователя о переносе после завершения слота"""
        from telebot import types

        user_id = booking["user_id"]
        user_name = booking.get("user_name", "Пользователь")
        slot_id = booking["slot_id"]
        position = booking["position"]

        date_str, time_str = slot_id.split("_")
        slot_date = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = slot_date.strftime("%d.%m.%Y")
        end_hour = int(time_str.split(":")[0]) + 1
        time_display = f"{time_str}-{end_hour:02d}:00"

        text = (
            "🕐 Консультация завершена\n\n"
            f"Здравствуйте, {user_name}!\n\n"
            f"Консультация {formatted_date} {time_display} завершилась. "
            f"Вы были {position}-м в очереди.\n\n"
            "🎯 Что хотите сделать дальше?"
        )

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("✅ Записаться автоматически", callback_data=f"reschedule_auto_{booking['_id']}")
        )
        markup.add(
            types.InlineKeyboardButton("🗓️ Выбрать время самостоятельно", callback_data=f"reschedule_manual_{booking['_id']}")
        )
        markup.add(
            types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"reschedule_cancel_{booking['_id']}")
        )

        self.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=markup,
            parse_mode='Markdown'
        )

    def send_hour_before_notifications(self, now):
        """Отправляет уведомления за час"""
        from db import consultation_slots_collection, consultation_queue_collection
        
        current_date = now.strftime("%Y-%m-%d")
        current_hour = now.hour
        next_hours = [(current_hour + i) % 24 for i in range(3)]
        
        sent_count = 0
        
        for hour in next_hours:
            slot_pattern = f"{current_date}_{hour:02d}:00"
            
            bookings_to_notify = list(consultation_queue_collection.find({
                "status": {"$nin": ["cancelled", "completed"]},
                "notifications_sent.hour_before": False,
                "slot_id": slot_pattern
            }))

            for booking in bookings_to_notify:
                try:
                    slot_id = booking["slot_id"]
                    date_str, time_str = slot_id.split("_")
                    consultation_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                    
                    time_diff = consultation_time - now
                    
                    if timedelta(minutes=50) <= time_diff <= timedelta(minutes=70):
                        self._send_hour_before_notification(booking)
                        consultation_queue_collection.update_one(
                            {"_id": booking["_id"]},
                            {"$set": {"notifications_sent.hour_before": True}}
                        )
                        sent_count += 1
                        
                except Exception as e:
                    print(f"[ERROR] Ошибка часового уведомления {booking['user_id']}: {e}")

        return sent_count

    def _send_day_before_notification(self, booking):
        """Отправляет уведомление за день"""
        from telebot import types
        
        user_id = booking["user_id"]
        user_name = booking.get("user_name", "Пользователь")
        slot_id = booking["slot_id"]
        position = booking["position"]
        
        date_str, time_str = slot_id.split("_")
        slot_date = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = slot_date.strftime("%d.%m.%Y")
        end_hour = int(time_str.split(':')[0]) + 1
        time_display = f"{time_str}-{end_hour:02d}:00"
        
        text = (
            f"📅 **Напоминание о консультации**\n\n"
            f"Здравствуйте, {user_name}!\n\n"
            f"⏰ Завтра у вас консультация:\n"
            f"📅 Дата: {formatted_date} (понедельник)\n"
            f"🕐 Время: {time_display}\n"
            f"📍 Ваше место в очереди: {position}\n\n"
            f"🔔 **Пожалуйста, подтвердите участие!**"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Подтверждаю участие", 
                                     callback_data=f"confirm_day_{booking['_id']}"),
            types.InlineKeyboardButton("❌ Не смогу участвовать", 
                                     callback_data=f"cancel_day_{booking['_id']}")
        )
        
        self.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=markup,
            parse_mode='Markdown'
        )

    def _send_hour_before_notification(self, booking):
        """Отправляет уведомление за час"""
        from telebot import types
        
        user_id = booking["user_id"]
        user_name = booking.get("user_name", "Пользователь")
        slot_id = booking["slot_id"]
        position = booking["position"]
        
        date_str, time_str = slot_id.split("_")
        slot_date = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = slot_date.strftime("%d.%m.%Y")
        end_hour = int(time_str.split(':')[0]) + 1
        time_display = f"{time_str}-{end_hour:02d}:00"
        
        text = (
            f"🔔 **Консультация через час!**\n\n"
            f"Здравствуйте, {user_name}!\n\n"
            f"⏰ Ваша консультация начнется через час:\n"
            f"📅 Сегодня, {formatted_date}\n"
            f"🕐 Время: {time_display}\n"
            f"📍 Ваше место в очереди: {position}\n\n"
            f"🚀 **Подготовьтесь к консультации!**"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Готов к консультации", 
                                     callback_data=f"confirm_hour_{booking['_id']}"),
            types.InlineKeyboardButton("❌ Отменить участие", 
                                     callback_data=f"cancel_hour_{booking['_id']}")
        )
        
        self.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=markup,
            parse_mode='Markdown'
        )