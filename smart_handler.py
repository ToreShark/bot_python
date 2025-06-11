# smart_handler.py
from telebot import types

class SmartHandler:
    """Умный обработчик сообщений пользователей"""
    
    def __init__(self, bot):
        self.bot = bot
        
        # Словарь ключевых слов - что ищем в сообщениях пользователей
        self.keywords = {
            'банкротство': [
                'банкротство', 'банкрот', 'долги', 'долг', 'кредит', 'займ', 
                'просрочка', 'не могу платить', 'нет денег', 'процедура',
                'внесудебное', 'судебное'
            ],
            'отчет': [
                'кредитный отчет', 'отчет', 'проверить', 'анализ', 'ПКБ', 'ГКБ',
                'состояние', 'кредитная история'
            ],
            'консультация': [
                'консультация', 'вопрос', 'помощь', 'совет', 'юрист', 'адвокат',
                'как получить', 'что делать'
            ]
        }

    def analyze_message(self, text):
        """Анализируем сообщение пользователя - о чем он спрашивает?"""
        text_lower = text.lower()  # Переводим в нижний регистр
        
        # Проверяем каждую категорию
        for category, keywords in self.keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return category  # Возвращаем найденную категорию
        
        return 'общее'  # Если ничего не нашли

    def create_response(self, category):
        """Создаем ответ в зависимости от того, о чем спросил пользователь"""
        
        if category == 'банкротство':
            text = (
                "🤖 Вижу, что вас интересует **банкротство**!\n\n"
                "📋 **Я могу помочь следующим:**\n\n"
                "⚖️ **Профессиональная консультация** (платно)\n"
                "• Подробные ответы по законодательству РК\n"
                "• Анализ вашей конкретной ситуации\n\n"
                "📅 **Бесплатная консультация с адвокатом**\n"
                "• Прямое общение с Мухтаровым Торехан\n"
                "• Каждый понедельник, 14:00-17:00\n\n"
                "🧮 **Банкротный калькулятор** (бесплатно)\n"
                "• Определит подходящую процедуру\n"
                "• Загрузите свой кредитный отчет"
            )
            buttons = ['lawyer_consultation', 'free_consultation', 'bankruptcy_calculator']
            
        elif category == 'отчет':
            text = (
                "📊 **Анализ кредитного отчета**\n\n"
                "🎯 **Что я могу сделать:**\n\n"
                "📋 **Полный анализ отчета** (бесплатно)\n"
                "• Список всех кредиторов и сумм\n"
                "• Автогенерация писем кредиторам\n\n"
                "🧮 **Банкротный калькулятор** (бесплатно)\n"
                "• Определение процедуры банкротства\n\n"
                "📄 **Список кредиторов PDF** (бесплатно)\n"
                "• Готовый документ для суда"
            )
            buttons = ['check_credit_report', 'bankruptcy_calculator', 'creditors_list']
            
        elif category == 'консультация':
            text = (
                "💬 **Нужна консультация?**\n\n"
                "🎯 **Выберите подходящий вариант:**\n\n"
                "⚖️ **Переписка с юристом** (платно)\n"
                "• Профессиональные ответы 24/7\n"
                "• Тарифы: 5000₸ - 15000₸\n\n"
                "📅 **Бесплатная консультация**\n"
                "• Живое общение с адвокатом Мухтаровым Торехан\n"
                "• Каждый понедельник с 14:00 до 17:00"
            )
            buttons = ['lawyer_consultation', 'free_consultation']
            
        else:  # общее
            text = (
                "🤖 **Добро пожаловать!**\n\n"
                "Я помогаю с банкротством физических лиц в Казахстане.\n\n"
                "🎯 **Основные услуги:**\n\n"
                "⚖️ **Юридическая помощь** - профессиональные консультации\n"
                "📊 **Анализ кредитного отчета** - проверка долгов\n"
                "🧮 **Банкротный калькулятор** - определение процедуры\n"
                "📅 **Бесплатная консультация** - с адвокатом\n\n"
                "💡 Выберите нужную услугу:"
            )
            buttons = ['lawyer_consultation', 'check_credit_report', 'bankruptcy_calculator', 'free_consultation']
        
        return text, buttons

    def create_buttons(self, button_types):
        """Создаем кнопки для ответа"""
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        # Настройки кнопок
        button_configs = {
            'lawyer_consultation': ("⚖️ Переписка (платно) 💰", "lawyer_consultation"),
            'free_consultation': ("📅 Бесплатная консультация 🆓", "free_consultation"),  
            'bankruptcy_calculator': ("🧮 Банкротный калькулятор 🆓", "bankruptcy_calculator"),
            'check_credit_report': ("📊 Проверить кредитный отчет 🆓", "check_credit_report"),
            'creditors_list': ("📋 Список кредиторов PDF 🆓", "creditors_list")
        }
        
        # Добавляем нужные кнопки
        for button_type in button_types:
            if button_type in button_configs:
                text, callback = button_configs[button_type]
                markup.add(types.InlineKeyboardButton(text, callback_data=callback))
        
        return markup

    def handle_message(self, message):
        """Основная функция - обрабатываем сообщение пользователя"""
        # ✅ ДОБАВИТЬ ЭТУ ПРОВЕРКУ:
        ADMIN_IDS = [376068212, 827743984]
        if message.from_user.id in ADMIN_IDS:
            # print(f"[SMART] Пропускаю админа {message.from_user.id}")
            return  # НЕ ОБРАБАТЫВАЕМ СООБЩЕНИЯ ОТ АДМИНОВ
        # 1. Анализируем сообщение
        category = self.analyze_message(message.text)
        
        # 2. Создаем ответ
        response_text, button_types = self.create_response(category)
        
        # 3. Создаем кнопки
        markup = self.create_buttons(button_types)
        
        # 4. Отправляем ответ пользователю
        self.bot.send_message(
            chat_id=message.chat.id,
            text=response_text,
            reply_markup=markup,
            parse_mode='Markdown'
        )
        
        # 5. Выводим в консоль для отладки
        print(f"[SMART] Пользователь {message.from_user.id}: '{message.text[:30]}...' -> {category}")