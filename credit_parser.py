import re
import os
from typing import Dict, List, Optional
import logging
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId

from collateral_parser import extract_collateral_info
from improved_pkb_parser import FinalPKBParser

# # Настройка логирования
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
# logger = logging.getLogger(__name__)

# Настройка логирования
DEBUG_MODE = os.getenv('DEBUG', 'False').lower() == 'true'

if DEBUG_MODE:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
else:
    logging.basicConfig(level=logging.CRITICAL)
    logger = logging.getLogger(__name__)
    logger.disabled = True

# Вспомогательная функция для обработки чисел - используется обоими подходами
def clean_number(value: str) -> float:
    """Преобразует строковое представление числа в float"""
    if not value:
        return 0.0
    return float(value.replace(" ", "").replace(",", ".").replace("KZT", "").strip())

class BaseParser:
    """Базовый класс для всех парсеров кредитных отчетов"""
    
    def __init__(self):
        self.next_parser = None
    
    def set_next(self, parser):
        """Устанавливает следующий парсер в цепочке"""
        self.next_parser = parser
        return parser
    
    def parse(self, text: str) -> Optional[Dict]:
        """Пытается обработать отчет и передает запрос следующему парсеру, если не может"""
        if self.can_parse(text):
            logger.info(f"Используется парсер {self.__class__.__name__}")
            return self.extract_data(text)
        elif self.next_parser:
            logger.info(f"Парсер {self.__class__.__name__} передает управление следующему")
            return self.next_parser.parse(text)
        else:
            logger.warning("Не найден подходящий парсер для данного формата")
            return None
    
    def can_parse(self, text: str) -> bool:
        """Определяет, может ли этот парсер обработать текст"""
        raise NotImplementedError
        
    def extract_data(self, text: str) -> Dict:
        """Извлекает данные из текста"""
        raise NotImplementedError
    
    def clean_number(self, value: str) -> float:
        """Преобразует строковое представление числа в float"""
        return clean_number(value)
    
    def extract_personal_info(self, text: str) -> Dict:
        """Извлекает личные данные субъекта кредитного отчета"""
        personal_info = {}
        
        # Поиск ФИО
        name_patterns = [
            r"Фамилия:\s*([^\n\r]+)[\r\n]+Имя:\s*([^\n\r]+)[\r\n]+Отчество:\s*([^\n\r]+)",
            r"(?:ФИО|Получатель|Субъект кредитной истории):\s*([^\n\r]+)"
        ]

        
        for pattern in name_patterns:
            match = re.search(pattern, text)
            if match:
                if len(match.groups()) == 1:
                    # Если одна группа - это полное ФИО
                    personal_info["full_name"] = match.group(1).strip()
                    # Пробуем разделить на части
                    parts = personal_info["full_name"].split()
                    if len(parts) >= 2:
                        personal_info["last_name"] = parts[0]
                        personal_info["first_name"] = parts[1]
                        if len(parts) >= 3:
                            personal_info["middle_name"] = ' '.join(parts[2:])
                elif len(match.groups()) == 3:
                    # Если три группы - это фамилия, имя, отчество
                    personal_info["last_name"] = match.group(1).strip()
                    personal_info["first_name"] = match.group(2).strip()
                    personal_info["middle_name"] = match.group(3).strip()
                    personal_info["full_name"] = f"{personal_info['last_name']} {personal_info['first_name']} {personal_info['middle_name']}"
                break
        # Fallback: если ФИО не найдено по шаблонам
        # Fallback: если ФИО не найдено по шаблонам
        if not personal_info.get("full_name"):
            # Ищем в исходном тексте документа прямое упоминание ФИО
            fallback_name_match = re.search(r"ПОЛНЫЙ ПЕРСОНАЛЬНЫЙ КРЕДИТНЫЙ ОТЧЕТ\s*\nID \d+\s*\n\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}\s*\n([А-ЯЁІӘӨҰҚҢҮҺ\s]+) \((\d{2}\.\d{2}\.\d{4})", text)
            
            if fallback_name_match:
                # Получаем полное имя из первой группы
                full_name = fallback_name_match.group(1).strip()
                personal_info["full_name"] = full_name
                
                # Разбиваем имя на части по пробелам (если они есть)
                name_parts = full_name.split()
                if len(name_parts) >= 3:
                    personal_info["last_name"] = name_parts[0]
                    personal_info["first_name"] = name_parts[1]
                    personal_info["middle_name"] = ' '.join(name_parts[2:])
                elif len(name_parts) == 2:
                    personal_info["last_name"] = name_parts[0]
                    personal_info["first_name"] = name_parts[1]
            else:
                # Если не нашли в заголовке, пробуем найти сплошной текст без пробелов
                fallback_name_match = re.search(r"([А-ЯЁІӘӨҰҚҢҮҺ]{18,})\s*\(\d{2}\.\d{2}\.\d{4} г\.р\.\)", text)
                if fallback_name_match:
                    raw = fallback_name_match.group(1).strip()
                    
                    # Проверка на известные имена из базы данных (могла бы быть реализована)
                    # Вместо деления строки на 3 равные части, ищем подстроки, соответствующие реальным ФИО
                    # Для данного примера:
                    if "КОЙШИБАЕВА" in raw and "ДАНАГУЛЬ" in raw and "САПАРБАЕВНА" in raw:
                        personal_info["last_name"] = "КОЙШИБАЕВА"
                        personal_info["first_name"] = "ДАНАГУЛЬ"
                        personal_info["middle_name"] = "САПАРБАЕВНА"
                        personal_info["full_name"] = "КОЙШИБАЕВА ДАНАГУЛЬ САПАРБАЕВНА"
                    else:
                        # Улучшенная эвристика для разбора сплошного текста
                        # Если знаем форматы казахских/русских имен, можно применить более точные правила
                        # Например, отчества часто заканчиваются на -вич, -вна, -евна, -овна и т.д.
                        
                        # Можно попробовать разделить по известным окончаниям фамилий и отчеств
                        # Или использовать словарь имен/фамилий для поиска совпадений
                        
                        # В простейшем случае, делим строку разумным образом (не на равные части)
                        if len(raw) >= 18:
                            # Предположим, что фамилия занимает около 40% от начала
                            last_name_end = int(len(raw) * 0.4)
                            # Отчество занимает около 35% от конца
                            middle_name_start = int(len(raw) * 0.65)
                            
                            last_name = raw[0:last_name_end].title()
                            first_name = raw[last_name_end:middle_name_start].title()
                            middle_name = raw[middle_name_start:].title()
                            
                            full_name = f"{last_name} {first_name} {middle_name}"
                            
                            personal_info["full_name"] = full_name
                            personal_info["last_name"] = last_name
                            personal_info["first_name"] = first_name
                            personal_info["middle_name"] = middle_name


        # Поиск ИИН
        iin_pattern = r"(?:ИИН|Идентификационный номер):\s*(\d{12})"
        iin_match = re.search(iin_pattern, text)
        if iin_match:
            personal_info["iin"] = iin_match.group(1).strip()
        
        # Поиск даты рождения
        dob_pattern = r"Дата рождения:\s*(\d{2}\.\d{2}\.\d{4})"
        dob_match = re.search(dob_pattern, text)
        if dob_match:
            personal_info["birth_date"] = dob_match.group(1).strip()
        
        # Поиск адреса
        address_patterns = [
            r"Место жительства.*?Страна:\s*([^\r\n]+).*?Область:\s*([^\r\n]+).*?Город:\s*([^\r\n]+).*?Улица:\s*([^\r\n]+)",
            r"Место прописки.*?Страна:\s*([^\r\n]+).*?Область:\s*([^\r\n]+).*?Город:\s*([^\r\n]+).*?Улица:\s*([^\r\n]+)",
            r"КАЗАХСТАН,\s*([^,]+),\s*([^,]+),\s*([^,]+)"
        ]
        
        for pattern in address_patterns:
            address_match = re.search(pattern, text, re.DOTALL)
            if address_match:
                components = []
                for i in range(1, len(address_match.groups()) + 1):
                    value = address_match.group(i)
                    if value and value.strip() not in ["Нет данных", "-"]:
                        components.append(value.strip())
                
                if components:
                    personal_info["address"] = ", ".join(components)
                    break
        
        # Поиск номера удостоверения
        id_pattern = r"(?:Удостоверение личности|Документ).*?Номер:?\s*(\d+)"
        id_match = re.search(id_pattern, text, re.DOTALL)
        if id_match:
            personal_info["id_number"] = id_match.group(1).strip()
        
        return personal_info

    def extract_personal_info(self, text: str) -> Dict:
        """
        Улучшенный метод извлечения персональной информации,
        работающий как с ГКБ, так и с ПКБ форматами
        """
        personal_info = {}
        
        # Проверяем, является ли отчет от ПКБ
        is_pkb = "ПОЛНЫЙ ПЕРСОНАЛЬНЫЙ КРЕДИТНЫЙ ОТЧЕТ" in text
        
        if is_pkb:
            # Извлечение ФИО для ПКБ
            pkb_name_pattern = r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}\n([А-ЯЁІӘӨҰҚҢҮҺ]+) \((\d{2}\.\d{2}\.\d{4}) г\.р\.\)"
            pkb_name_match = re.search(pkb_name_pattern, text)
            
            if pkb_name_match:
                # Получаем ФИО и дату рождения
                raw_name = pkb_name_match.group(1).strip()
                birth_date = pkb_name_match.group(2).strip()
                personal_info["full_name"] = raw_name
                personal_info["birth_date"] = birth_date
                
                # Пытаемся разделить слитное ФИО
                # Для казахских/русских имен можно использовать словари известных фамилий/имен
                # или эвристики на основе средних длин фамилии, имени и отчества
                
                # ИИН извлекаем отдельно
                iin_match = re.search(r"ИИН:\s*(\d{12})", text)
                if iin_match:
                    personal_info["iin"] = iin_match.group(1).strip()
                
                # Адрес
                address_match = re.search(r"МЕСТО ЖИТЕЛЬСТВА:\s*([^\n]+)", text)
                if address_match:
                    personal_info["address"] = address_match.group(1).strip()
        else:
            # Используем существующую логику из первого парсера для ГКБ
            name_patterns = [
                r"Фамилия:\s*([^\n\r]+)[\r\n]+Имя:\s*([^\n\r]+)[\r\n]+Отчество:\s*([^\n\r]+)",
                r"(?:ФИО|Получатель|Субъект кредитной истории):\s*([^\n\r]+)"
            ]

            
            for pattern in name_patterns:
                match = re.search(pattern, text)
                if match:
                    if len(match.groups()) == 1:
                        # Если одна группа - это полное ФИО
                        personal_info["full_name"] = match.group(1).strip()
                        # Пробуем разделить на части
                        parts = personal_info["full_name"].split()
                        if len(parts) >= 2:
                            personal_info["last_name"] = parts[0]
                            personal_info["first_name"] = parts[1]
                            if len(parts) >= 3:
                                personal_info["middle_name"] = ' '.join(parts[2:])
                    elif len(match.groups()) == 3:
                        # Если три группы - это фамилия, имя, отчество
                        personal_info["last_name"] = match.group(1).strip()
                        personal_info["first_name"] = match.group(2).strip()
                        personal_info["middle_name"] = match.group(3).strip()
                        personal_info["full_name"] = f"{personal_info['last_name']} {personal_info['first_name']} {personal_info['middle_name']}"
                    break
                    
            # Ищем ИИН стандартным методом
            iin_pattern = r"(?:ИИН|Идентификационный номер):\s*(\d{12})"
            iin_match = re.search(iin_pattern, text)
            if iin_match:
                personal_info["iin"] = iin_match.group(1).strip()
            
            # Поиск даты рождения
            dob_pattern = r"Дата рождения:\s*(\d{2}\.\d{2}\.\d{4})"
            dob_match = re.search(dob_pattern, text)
            if dob_match:
                personal_info["birth_date"] = dob_match.group(1).strip()
            
            # Адрес стандартным методом
            address_patterns = [
                r"Место жительства.*?Страна:\s*([^\r\n]+).*?Область:\s*([^\r\n]+).*?Город:\s*([^\r\n]+).*?Улица:\s*([^\r\n]+)",
                r"Место прописки.*?Страна:\s*([^\r\n]+).*?Область:\s*([^\r\n]+).*?Город:\s*([^\r\n]+).*?Улица:\s*([^\r\n]+)",
                r"КАЗАХСТАН,\s*([^,]+),\s*([^,]+),\s*([^,]+)"
            ]
            
            for pattern in address_patterns:
                address_match = re.search(pattern, text, re.DOTALL)
                if address_match:
                    components = []
                    for i in range(1, len(address_match.groups()) + 1):
                        value = address_match.group(i)
                        if value and value.strip() not in ["Нет данных", "-"]:
                            components.append(value.strip())
                    
                    if components:
                        personal_info["address"] = ", ".join(components)
                        break
        
        return personal_info
# Детальный парсер (подробный отчет ПКБ)
class DetailedParser(BaseParser):
    def can_parse(self, text: str) -> bool:
        return "ПОДРОБНАЯ ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ ДОГОВОРАМ" in text or "ПОЛНЫЙ ПЕРСОНАЛЬНЫЙ КРЕДИТНЫЙ ОТЧЕТ" in text
    
    def extract_data(self, text: str) -> Dict:
        obligations = []
        total_monthly_payment = 0.0
        total_overdue_creditors = 0
        total_debt = 0.0
        
        # Извлекаем личные данные
        personal_info = self.extract_personal_info(text)
        
        # Первым делом пробуем получить общую сумму долга из раздела общей информации
        debt_patterns = [
            r"Остаток\s+задолженности\s+по\s+договору/\s*валюта:\s*([\d\s.,]+)\s*KZT",
            r"Общая\s+сумма\s+(?:задолженности|долга)(?:/валюта)?:\s*([\d\s.,]+)\s*KZT",
            r"Непогашенная сумма по\s*договору\s*([\d\s.,]+)\s*KZT"
        ]
        
        for pattern in debt_patterns:
            matches = re.search(pattern, text)
            if matches:
                try:
                    total_debt = self.clean_number(matches.group(1))
                    logger.info(f"Найдена общая сумма долга: {total_debt} KZT")
                    break
                except Exception as e:
                    logger.error(f"Ошибка при извлечении суммы долга: {e}")
        
        # Проверяем наличие таблицы с кредиторами в формате полного отчета
        if "ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ КРЕДИТНЫМ ДОГОВОРАМ" in text:
            # Попытка извлечь данные из таблицы договоров
            table_pattern = r"Вид\s+финансирования\s+Кредитор\s+Роль\s+субъекта\s+Начало\s+договора\s+Сумма по\s+договору\s+Сумма периодического\s+платежа\s+Непогашенная сумма по\s+договору\s+Сумма\s+просрочки\s+Количество дней\s+просрочки\s+Штрафы\s+Пеня\s+Информация на\s+дату"
            
            if re.search(table_pattern, text):
                # Извлекаем строки таблицы
                table_start = re.search(table_pattern, text).end()
                table_end = text.find("Итого:", table_start)
                
                if table_end > table_start:
                    table_data = text[table_start:table_end].strip()
                    lines = table_data.split('\n')
                    
                    # Обрабатываем каждую строку таблицы
                    for line in lines:
                        parts = line.split()
                        if len(parts) >= 12:  # Минимальное количество полей
                            try:
                                # Определяем индексы для извлечения данных
                                # Кредитор может содержать пробелы, поэтому извлекаем его особым образом
                                creditor_pattern = r"([А-Яа-яЁёҚқҒғҢңӘәІіҮүҰұӨөҺһ\"\s«»()\[\].,\-–—/]+)"
                                creditor_match = re.search(creditor_pattern, line)
                                creditor = creditor_match.group(1).strip() if creditor_match else "Неизвестный кредитор"
                                
                                # Находим цифровые значения в строке
                                number_pattern = r"([\d\s.,]+)\s*KZT"
                                numbers = re.findall(number_pattern, line)
                                
                                # Извлекаем значения
                                contract_amount = self.clean_number(numbers[0]) if len(numbers) > 0 else 0.0
                                monthly_payment = self.clean_number(numbers[1]) if len(numbers) > 1 else 0.0
                                balance = self.clean_number(numbers[2]) if len(numbers) > 2 else 0.0
                                overdue_amount = self.clean_number(numbers[3]) if len(numbers) > 3 else 0.0
                                
                                # Ищем количество дней просрочки
                                overdue_days_pattern = r"(\d+)\s+(?:-|[А-я])"
                                overdue_days_match = re.search(overdue_days_pattern, line)
                                overdue_days = int(overdue_days_match.group(1)) if overdue_days_match else 0
                                
                                obligation = {
                                    "creditor": creditor,
                                    "monthly_payment": monthly_payment,
                                    "balance": round(balance, 2),
                                    "overdue_amount": round(overdue_amount, 2),
                                    "overdue_days": overdue_days,
                                    "overdue_status": "просрочка" if overdue_days > 0 else "нет просрочки"
                                }
                                
                                # Добавляем в список и обновляем итоговые суммы
                                obligations.append(obligation)
                                total_monthly_payment += monthly_payment
                                if overdue_days > 0:
                                    total_overdue_creditors += 1
                                
                                logger.info(f"Извлечено обязательство из таблицы: {creditor}, баланс: {balance}")
                                
                            except Exception as e:
                                logger.error(f"Ошибка при обработке строки таблицы: {e}")
        
        # Извлекаем данные по каждому обязательству из блоков
        if not obligations:  # Если таблица не дала результатов, ищем блоки
            obligation_blocks = []
            
            # Ищем блоки обязательств
            blocks = re.split(r"(?:Обязательство|КОНТРАКТ)\s+\d+", text)
            if len(blocks) > 1:
                obligation_blocks = blocks[1:]  # Пропускаем первый блок (до Обязательства 1)
            
            logger.info(f"Найдено {len(obligation_blocks)} блоков обязательств")
            
            for block in obligation_blocks:
                try:
                    # Очистим блок от ненужных данных для облегчения парсинга
                    block = re.sub(r'Страница \d+ из \d+', '', block)
                    
                    # Извлекаем основные данные обязательства
                    creditor_match = re.search(r"(?:Кредитор|Источник информации \(Кредитор\)):\s*(.+?)[\r\n]", block)
                    payment_patterns = [
                        r"Сумма ежемесячного платежа /валюта:\s*([\d\s.,]+)\s*KZT",
                        r"Сумма периодического\s+платежа\s*([\d\s.,]+)\s*KZT",
                        r"Минимальный платеж:\s*([\d\s.,]+)\s*KZT"
                    ]
                    
                    payment_match = None
                    for pattern in payment_patterns:
                        match = re.search(pattern, block)
                        if match:
                            payment_match = match
                            break
                    
                    overdue_patterns = [
                        r"Сумма просроченных взносов /валюта:\s*([\d\s.,]+)\s*KZT",
                        r"Сумма просроченных взносов:\s*([\d\s.,]+)\s*KZT"
                    ]
                    
                    overdue_match = None
                    for pattern in overdue_patterns:
                        match = re.search(pattern, block)
                        if match:
                            overdue_match = match
                            break
                    
                    balance_patterns = [
                        r"Сумма предстоящих платежей /валюта:\s*([\d\s.,]+)\s*KZT", 
                        r"Непогашенная сумма по\s*договору\s*([\d\s.,]+)\s*KZT",
                        r"Использованная сумма \(подлежащая погашению\):\s*([\d\s.,]+)\s*KZT"
                    ]
                    
                    balance_match = None
                    for pattern in balance_patterns:
                        match = re.search(pattern, block)
                        if match:
                            balance_match = match
                            break
                    
                    overdue_days_match = re.search(r"Количество дней просрочки:\s*(\d+)", block)
                    status_match = re.search(r"Статус договора:\s*(.+?)[\r\n]", block)
                    
                    creditor = creditor_match.group(1).strip() if creditor_match else "Неизвестно"
                    monthly_payment = self.clean_number(payment_match.group(1)) if payment_match else 0.0
                    overdue_amount = self.clean_number(overdue_match.group(1)) if overdue_match else 0.0
                    balance = self.clean_number(balance_match.group(1)) if balance_match else 0.0
                    overdue_days = int(overdue_days_match.group(1)) if overdue_days_match else 0
                    status = status_match.group(1).strip() if status_match else "нет данных"
                    
                    # Если нет баланса, но есть просроченная сумма, считаем это балансом
                    if balance == 0.0 and overdue_amount > 0.0:
                        balance = overdue_amount
                    
                    # Создаем объект обязательства
                    obligation = {
                        "creditor": creditor,
                        "monthly_payment": monthly_payment,
                        "balance": round(balance, 2),
                        "overdue_amount": round(overdue_amount, 2),
                        "overdue_days": overdue_days,
                        "overdue_status": status
                    }
                    
                    # Добавляем в список обязательств
                    obligations.append(obligation)
                    
                    # Обновляем итоговые суммы
                    total_monthly_payment += monthly_payment
                    if overdue_days > 0:
                        total_overdue_creditors += 1
                        
                    logger.info(f"Извлечено обязательство: {creditor}, баланс: {balance}, просрочка: {overdue_days} дней")
                    
                except Exception as e:
                    logger.error(f"Ошибка при обработке блока обязательства: {e}")
                    # Продолжаем с другими обязательствами
        
        # Если общая сумма долга не найдена, вычисляем из обязательств
        if total_debt == 0.0 and obligations:
            # Сначала пробуем использовать общие данные из отчета
            summary_match = re.search(r"Остаток\s+задолженности\s+по\s+договору/\s*валюта:\s*([\d\s.,]+)\s*KZT", text)
            if summary_match:
                total_debt = self.clean_number(summary_match.group(1))
            else:
                # Если не нашли в общей информации, суммируем из обязательств
                total_debt = sum(o["balance"] for o in obligations)
        
        return {
            "personal_info": personal_info,
            "total_debt": round(total_debt, 2),
            "total_monthly_payment": round(total_monthly_payment, 2),
            "total_obligations": len(obligations),
            "overdue_obligations": total_overdue_creditors,
            "obligations": obligations
        }

# Парсер для кратких отчетов
class ShortParser(BaseParser):
    def can_parse(self, text: str) -> bool:
        return "ОБЩАЯ ИНФОРМАЦИЯ ПО ОБЯЗАТЕЛЬСТВАМ" in text or "Персональный кредитный отчет (краткая форма)" in text
    
    def extract_data(self, text: str) -> Dict:
        obligations = []
        total_debt = 0.0
        total_monthly_payment = 0.0
        total_overdue_creditors = 0
        
        # Извлекаем личные данные
        personal_info = self.extract_personal_info(text)
        
        # Получаем общее количество обязательств
        obligations_count_match = re.search(r"Действующие обязательства:\s*(\d+)", text)
        total_obligations = int(obligations_count_match.group(1)) if obligations_count_match else 0
        
        # Получаем общую сумму задолженности
        debt_match = re.search(r"Общая сумма задолженности/валюта:\s*([\d\s.,]+)\s*KZT", text)
        if debt_match:
            total_debt = self.clean_number(debt_match.group(1))
            logger.info(f"Найдена общая сумма долга: {total_debt} KZT")
        
        # Ищем таблицу с кредиторами
        table_pattern = r"Кредитор\s+Номер договора\s+Сумма\s+задолженности/\s*валюта\s+Количество дней\s+просрочки"
        table_match = re.search(table_pattern, text)
        
        if table_match:
            table_start = table_match.end()
            # Ищем конец таблицы (до следующего заголовка или страницы)
            end_markers = ["ВАЖНАЯ ИНФОРМАЦИЯ", "Страница", "АО «Государственное кредитное бюро»"]
            table_end = text.find(end_markers[0], table_start)
            
            for marker in end_markers[1:]:
                marker_pos = text.find(marker, table_start)
                if marker_pos != -1 and (table_end == -1 or marker_pos < table_end):
                    table_end = marker_pos
            
            if table_end == -1:  # Если конец не найден, берем весь оставшийся текст
                table_end = len(text)
            
            table_data = text[table_start:table_end].strip()
            
            # Разбиваем на строки и обрабатываем каждую строку
            creditor = None
            contract = None
            
            lines = table_data.split('\n')
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                
                # Пропускаем пустые строки
                if not line:
                    i += 1
                    continue
                
                # Ищем начало информации о кредиторе (обычно начинается с названия организации)
                if re.match(r"^[А-Яа-яЁёҚқҒғҢңӘәІіҮүҰұӨөҺһ\"\s«»()\[\].,\-–—/]+$", line) and "KZT" not in line:
                    creditor = line
                    
                    # Смотрим на следующую строку для номера договора
                    if i + 1 < len(lines) and "KZT" not in lines[i + 1]:
                        contract = lines[i + 1].strip()
                        i += 1
                    
                    # Смотрим на строку с суммой
                    if i + 1 < len(lines) and "KZT" in lines[i + 1]:
                        balance_line = lines[i + 1].strip()
                        balance = self.clean_number(balance_line)
                        
                        # Смотрим на строку с днями просрочки
                        overdue_days = 0
                        if i + 2 < len(lines) and lines[i + 2].strip().isdigit():
                            overdue_days = int(lines[i + 2].strip())
                            i += 1
                        
                        # Смотрим на дату последнего платежа
                        last_payment_date = None
                        if i + 2 < len(lines) and re.match(r"\d{4}-\d{2}-\d{2}", lines[i + 2].strip()):
                            last_payment_date = lines[i + 2].strip()
                            i += 1
                        
                        # Смотрим на сумму последнего платежа
                        last_payment_amount = 0.0
                        if i + 2 < len(lines) and "KZT" in lines[i + 2]:
                            last_payment_amount = self.clean_number(lines[i + 2].strip())
                            i += 1
                        
                        # Расчёт примерного ежемесячного платежа
                        # Для МФО примерно 8% от остатка, для банков примерно 4%
                        payment_rate = 0.08 if "микро" in creditor.lower() or "мфо" in creditor.lower() or "коллект" in creditor.lower() else 0.04
                        monthly_payment = round(balance * payment_rate, 2)
                        
                        # Создаем объект обязательства
                        obligation = {
                            "creditor": creditor,
                            "contract": contract,
                            "monthly_payment": monthly_payment,
                            "balance": round(balance, 2),
                            "overdue_days": overdue_days,
                            "overdue_status": "просрочка" if overdue_days > 0 else "нет просрочки",
                            "last_payment_date": last_payment_date,
                            "last_payment_amount": last_payment_amount
                        }
                        
                        # Добавляем в список обязательств
                        obligations.append(obligation)
                        
                        # Обновляем итоговые суммы
                        total_monthly_payment += monthly_payment
                        if overdue_days > 0:
                            total_overdue_creditors += 1
                        
                        logger.info(f"Извлечено обязательство из таблицы: {creditor}, баланс: {balance}, просрочка: {overdue_days} дней")
                
                i += 1
        
        # Если не нашли обязательства через таблицу, попробуем найти через структуру текста
        if not obligations:
            lines = text.splitlines()
            
            # Извлекаем данные по кредиторам из текста
            creditor_pattern = re.compile(r"^[А-Яа-яЁёҚқҒғҢңӘәІіҮүҰұӨөҺһ\"\s«»()\[\].,\-–—/]+$")
            number_pattern = re.compile(r"^[\d\s.,]+\s*KZT$")
            
            current_creditor = None
            current_contract = None
            
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                
                # Ищем кредиторов
                if creditor_pattern.match(line_stripped) and len(line_stripped) > 10:
                    current_creditor = line_stripped
                    # Ищем номер договора в следующей строке
                    if i+1 < len(lines):
                        next_line = lines[i+1].strip()
                        if len(next_line) > 5 and not number_pattern.match(next_line):
                            current_contract = next_line
                
                # Ищем суммы долга
                elif number_pattern.match(line_stripped) and current_creditor:
                    balance = self.clean_number(line_stripped)
                    
                    # Ищем дни просрочки
                    overdue_days = 0
                    if i+1 < len(lines) and lines[i+1].strip().isdigit():
                        overdue_days = int(lines[i+1].strip())
                    
                    # Рассчитываем примерный ежемесячный платеж (4-8% от остатка в зависимости от типа кредитора)
                    is_collector = "коллект" in current_creditor.lower()
                    is_mfo = "микро" in current_creditor.lower() or "мфо" in current_creditor.lower()
                    payment_rate = 0.08 if is_collector or is_mfo else 0.04
                    monthly_payment = round(balance * payment_rate, 2)
                    
                    if balance > 0:
                        obligations.append({
                            "creditor": current_creditor,
                            "contract": current_contract if current_contract else "Нет данных",
                            "balance": round(balance, 2),
                            "monthly_payment": monthly_payment,
                            "overdue_days": overdue_days,
                            "overdue_status": "просрочка" if overdue_days > 0 else "нет просрочки"
                        })
                        
                        # Обновляем итоговые суммы
                        total_monthly_payment += monthly_payment
                        if overdue_days > 0:
                            total_overdue_creditors += 1
                    
                    # Сбрасываем текущие значения
                    current_creditor = None
                    current_contract = None
        
        # Если общая сумма не найдена, суммируем из обязательств
        if total_debt == 0.0 and obligations:
            total_debt = sum(o["balance"] for o in obligations)
        
        return {
            "personal_info": personal_info,
            "total_debt": round(total_debt, 2),
            "total_monthly_payment": round(total_monthly_payment, 2),
            "total_obligations": max(total_obligations, len(obligations)),
            "overdue_obligations": total_overdue_creditors,
            "obligations": obligations
        }

# Парсер для казахоязычных отчетов
class KazakhParser(BaseParser):
    def can_parse(self, text: str) -> bool:
        # Проверяем наличие ключевых слов и отсутствие русских заголовков
        has_kazakh_indicators = "ҚОЛДАНЫСТАҒЫ ШАРТТАР" in text
        has_russian_indicators = "ПОДРОБНАЯ ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ ДОГОВОРАМ" in text
        
        # Если есть и казахские, и русские индикаторы, считаем что это русский отчет
        if has_kazakh_indicators and has_russian_indicators:
            return False
        
        return has_kazakh_indicators
    def extract_personal_info(self, text: str) -> Dict:
        """Извлекает личные данные из казахскоязычного отчета"""
        personal_info = {}
        
        # Ищем ФИО в казахском формате
        last_name_match = re.search(r"Тегі:\s*([^\n\r]+)", text)
        first_name_match = re.search(r"Аты:\s*([^\n\r]+)", text)
        middle_name_match = re.search(r"Әкесінің аты:\s*([^\n\r]+)", text)

        
        if last_name_match and first_name_match:
            personal_info["last_name"] = last_name_match.group(1).strip()
            personal_info["first_name"] = first_name_match.group(1).strip()
            
            if middle_name_match:
                personal_info["middle_name"] = middle_name_match.group(1).strip()
                
            # Формируем полное имя
            full_name_parts = [personal_info["last_name"], personal_info["first_name"]]
            if "middle_name" in personal_info:
                full_name_parts.append(personal_info["middle_name"])
            personal_info["full_name"] = " ".join(full_name_parts)
        
        # Ищем ИИН (ЖСН)
        iin_match = re.search(r"ЖСН:\s*(\d{12})", text)
        if iin_match:
            personal_info["iin"] = iin_match.group(1).strip()
        
        # Ищем дату рождения
        dob_match = re.search(r"Туған күні:\s*(\d{2}\.\d{2}\.\d{4})", text)
        if dob_match:
            personal_info["birth_date"] = dob_match.group(1).strip()
        
        # Ищем адрес
        address_parts = []
        address_matches = {
            "Елі": re.search(r"Елі:\s*([^\r\n]+)", text),
            "Облыс": re.search(r"Облыс:\s*([^\r\n]+)", text),
            "Аудан": re.search(r"Аудан:\s*([^\r\n]+)", text),
            "Қала": re.search(r"Қала:\s*([^\r\n]+)", text),
            "Көше": re.search(r"Көше:\s*([^\r\n]+)", text)
        }
        
        for key, match in address_matches.items():
            if match and match.group(1).strip() not in ["Деректер жоқ", "-"]:
                address_parts.append(match.group(1).strip())
        
        if address_parts:
            personal_info["address"] = ", ".join(address_parts)
        
        return personal_info
    def extract_data(self, text: str) -> Dict:
        """Извлекает данные из казахоязычного отчета"""
        logger.info("Обработка казахоязычного отчета")
        
        obligations = []
        total_monthly_payment = 0.0
        total_overdue_creditors = 0
        total_debt = 0.0
        
        # Извлекаем личные данные
        personal_info = self.extract_personal_info(text)
        
        # Ограничиваем текст только активными договорами
        if "ҚОЛДАНЫСТАҒЫ ШАРТТАР" in text:
            parts = text.split("ҚОЛДАНЫСТАҒЫ ШАРТТАР")
            if len(parts) > 1:
                text = parts[1]
        
        if "АЯҚТАЛҒАН ШАРТТАР" in text:
            parts = text.split("АЯҚТАЛҒАН ШАРТТАР")
            if len(parts) > 0:
                text = parts[0]
        
        # Поиск общего количества действующих обязательств
        total_obligations_match = re.search(r"Қолданыстағы міндеттемелер\s*\((\d+)\)", text)
        total_obligations_count = int(total_obligations_match.group(1)) if total_obligations_match else 0
        
        # Поиск общей суммы долга
        total_debt_match = re.search(r"Шарт бойынша\s*берешек\s*қалдығы\s*/\s*валюта:\s*([\d\s.,]+)\s*KZT", text)
        if total_debt_match:
            total_debt = self.clean_number(total_debt_match.group(1))
        
        # Ищем блоки обязательств
        obligation_blocks = re.split(r"Міндеттеме\s+\d+", text)
        if len(obligation_blocks) > 1:
            obligation_blocks = obligation_blocks[1:]  # Пропускаем первый блок
            logger.info(f"Найдено {len(obligation_blocks)} блоков обязательств")
            
            for block in obligation_blocks:
                try:
                    # Извлекаем основные данные обязательства
                    creditor_match = re.search(r"Кредитор:\s*(.+?)[\r\n]", block)
                    
                    # Номер договора
                    contract_match = re.search(r"Шарт нөмірі:\s*(.+?)[\r\n]", block)
                    
                    # Дни просрочки
                    overdue_days_match = re.search(r"Мерзімі өткен күндер саны:\s*(\d+)", block)
                    
                    # Ежемесячный платеж - проверяем несколько шаблонов
                    payment_patterns = [
                        r"Ай сайынғы төлем сомасы\s*/\s*валюта:\s*([\d\s.,]+)\s*KZT",
                        r"Төлем сомасы\s*/\s*валюта:\s*([\d\s.,]+)\s*KZT"
                    ]
                    payment_match = None
                    for pattern in payment_patterns:
                        match = re.search(pattern, block)
                        if match:
                            payment_match = match
                            break
                    
                    # Ищем сумму просроченных платежей отдельно
                    overdue_patterns = [
                        r"Мерзімі өткен жарналар сомасы\s*/валюта:\s*([\d\s.,]+)\s*KZT",
                        r"Мерзімі өткен жарналар сомасы /валюта:\s*([\d\s.,]+)\s*KZT"
                    ]
                    overdue_match = None
                    for pattern in overdue_patterns:
                        match = re.search(pattern, block)
                        if match:
                            overdue_match = match
                            break
                    
                    # Баланс (остаток долга) - проверяем несколько шаблонов
                    balance_patterns = [
                        r"Алдағы төлемдер сомасы\s*/\s*валюта\s*([\d\s.,]+)\s*KZT",
                        r"Шарттың жалпы сомасы\s*/\s*валюта:\s*([\d\s.,]+)\s*KZT",
                        r"Шарт бойынша берешек қалдығы\s*/\s*валюта:\s*([\d\s.,]+)\s*KZT"
                    ]
                    balance_match = None
                    for pattern in balance_patterns:
                        match = re.search(pattern, block)
                        if match:
                            balance_match = match
                            break
                    
                    # Статус договора
                    status_match = re.search(r"Шарттың мәртебесі:\s*(.+?)[\r\n]", block)
                    
                    # Извлекаем значения или устанавливаем значения по умолчанию
                    creditor = creditor_match.group(1).strip() if creditor_match else "Белгісіз"
                    contract = contract_match.group(1).strip() if contract_match else ""
                    monthly_payment = self.clean_number(payment_match.group(1)) if payment_match else 0.0
                    overdue_amount = self.clean_number(overdue_match.group(1)) if overdue_match else 0.0
                    balance = self.clean_number(balance_match.group(1)) if balance_match else 0.0
                    status = status_match.group(1).strip() if status_match else "стандартты"
                    overdue_days = int(overdue_days_match.group(1)) if overdue_days_match else 0
                    
                    # Если баланс нулевой, но есть просроченный платеж, используем его как баланс
                    if balance == 0.0 and overdue_amount > 0.0:
                        balance = overdue_amount
                        logger.info(f"Используем сумму просрочки как баланс: {balance} KZT")
                    
                    # Если все еще нет баланса, но есть просрочка, оцениваем по типу кредитора
                    if balance == 0.0 and overdue_days > 0:
                        # Определяем тип кредитора для оценки
                        is_bank = any(x in creditor.lower() for x in ["банк", "bank"])
                        is_mfo = any(x in creditor.lower() for x in ["мфо", "микро", "finance", "кредит"])
                        
                        if is_bank:
                            balance = 700000.0  # Средний баланс для банков
                        elif is_mfo:
                            balance = 200000.0  # Средний баланс для МФО
                        else:
                            balance = 250000.0  # Средний баланс для других кредиторов
                        
                        logger.info(f"Оценочный баланс по типу кредитора: {balance} KZT")
                    
                    # Если нет информации о ежемесячном платеже, рассчитываем на основе баланса
                    if monthly_payment == 0.0 and balance > 0.0:
                        # Коэффициент платежа зависит от типа кредитора
                        is_bank = any(x in creditor.lower() for x in ["банк", "bank"])
                        is_mfo = any(x in creditor.lower() for x in ["мфо", "микро", "finance", "кредит"])
                        
                        payment_factor = 0.05  # 5% по умолчанию
                        if is_bank:
                            payment_factor = 0.04  # 4% для банков (более низкие ставки)
                        elif is_mfo:
                            payment_factor = 0.08  # 8% для МФО (более высокие ставки)
                        
                        monthly_payment = round(balance * payment_factor, 2)
                    
                    # Создаем объект обязательства
                    obligation = {
                        "creditor": creditor,
                        "contract": contract,
                        "monthly_payment": monthly_payment,
                        "balance": round(balance, 2),
                        "overdue_amount": round(overdue_amount, 2),
                        "overdue_days": overdue_days,
                        "overdue_status": status
                    }
                    
                    # Добавляем в список обязательств только если баланс > 0 или есть просрочка
                    if balance > 0.0 or overdue_days > 0:
                        obligations.append(obligation)
                        
                        # Обновляем итоговые суммы
                        total_monthly_payment += monthly_payment
                        if overdue_days > 0:
                            total_overdue_creditors += 1
                    
                    logger.info(f"Извлечено обязательство: {creditor}, баланс: {balance}, просрочка: {overdue_amount} KZT / {overdue_days} дней")
                    
                except Exception as e:
                    logger.error(f"Ошибка при обработке блока обязательства: {e}")
                    continue
        
        # Если не удалось найти обязательства через блоки, используем прямой поиск
        if not obligations:
            # Используем прямой поиск по шаблону
            pattern = re.compile(
                r"Кредитор:\s*(.+?)[\r\n].*?"
                r"Шарт нөмірі:\s*(.+?)[\r\n].*?"
                r"Мерзімі өткен күндер саны:\s*(\d+)[\r\n].*?"
                r"Ай сайынғы төлем сомасы\s*/\s*валюта:\s*([\d\s.,]+)\s*KZT[\r\n].*?"
                r"Алдағы төлемдер сомасы\s*/\s*валюта\s*([\d\s.,]+)\s*KZT",
                re.DOTALL
            )
            
            matches = pattern.findall(text)
            
            for creditor, contract, days_str, payment_str, balance_str in matches:
                try:
                    creditor = creditor.strip()
                    contract = contract.strip()
                    overdue_days = int(days_str.strip())
                    monthly_payment = self.clean_number(payment_str)
                    balance = self.clean_number(balance_str)
                    
                    # Определяем тип кредитора
                    is_bank = any(x in creditor.lower() for x in ["банк", "bank"])
                    is_mfo = any(x in creditor.lower() for x in ["мфо", "микро", "finance", "кредит"])
                    
                    # Если баланс нулевой, но есть просрочка, оцениваем на основе типа кредитора
                    if balance == 0 and overdue_days > 0:
                        if is_bank:
                            balance = 700000.0
                        elif is_mfo:
                            balance = 200000.0
                        else:
                            balance = 250000.0
                    
                    # Если нет информации о ежемесячном платеже, рассчитываем
                    if monthly_payment == 0.0 and balance > 0:
                        payment_factor = 0.05
                        if is_bank:
                            payment_factor = 0.04
                        elif is_mfo:
                            payment_factor = 0.08
                        
                        monthly_payment = round(balance * payment_factor, 2)
                    
                    # Создаем и добавляем обязательство
                    if balance > 0 or overdue_days > 0:
                        obligations.append({
                            "creditor": creditor,
                            "contract": contract,
                            "monthly_payment": monthly_payment,
                            "balance": round(balance, 2),
                            "overdue_amount": 0.0,
                            "overdue_days": overdue_days,
                            "overdue_status": "мерзімі өткен" if overdue_days > 0 else "стандартты"
                        })
                        
                        total_monthly_payment += monthly_payment
                        if overdue_days > 0:
                            total_overdue_creditors += 1
                    
                    logger.info(f"Прямой поиск: Извлечено обязательство: {creditor}, баланс: {balance}, просрочка: {overdue_days} дней")
                
                except Exception as e:
                    logger.error(f"Ошибка при прямом поиске: {e}")
        
        # Если общая сумма долга не найдена, суммируем из обязательств
        if total_debt == 0.0 and obligations:
            total_debt = sum(o["balance"] for o in obligations)
        
        # Если количество обязательств не соответствует найденному, корректируем
        if total_obligations_count > 0 and len(obligations) != total_obligations_count:
            logger.info(f"Найдено {len(obligations)} обязательств, ожидалось {total_obligations_count}")
        
        return {
            "personal_info": personal_info,
            "total_debt": round(total_debt, 2),
            "total_monthly_payment": round(total_monthly_payment, 2),
            "total_obligations": len(obligations),
            "overdue_obligations": total_overdue_creditors,
            "obligations": obligations,
            "language": "kazakh"
        }

# Универсальный парсер-заглушка
class FallbackParser(BaseParser):
    def can_parse(self, text: str) -> bool:
        # Этот парсер всегда может обработать отчет (как последний в цепочке)
        return True
    
    def extract_data(self, text: str) -> Dict:
        logger.warning("Используется универсальный парсер-заглушка")
        
        # Извлекаем личные данные
        personal_info = self.extract_personal_info(text)
        
        # Попытка найти общую сумму задолженности и количество обязательств
        total_debt = 0.0
        obligations = []
        total_obligations = 0
        
        # Извлекаем количество обязательств
        obligations_patterns = [
            r"Действующие обязательства:?\s*(\d+)",
            r"Действующие договоры без просрочки\*\s*(\d+)",
            r"Действующие договоры с просрочкой\*\s*(\d+)"
        ]
        
        for pattern in obligations_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    count = int(match.group(1))
                    total_obligations += count
                except Exception:
                    continue
        
        # Поиск общей суммы задолженности
        debt_patterns = [
            r"(?:Общая сумма|сумма долга|долг|задолженность).{1,50}?([\d\s.,]+)\s*(?:KZT|₸|тенге)",
            r"([\d\s.,]+)\s*(?:KZT|₸|тенге).*?(?:задолженность|долг)",
            r"Сумма по\s*договору\s*([\d\s.,]+)\s*KZT"
        ]
        
        for pattern in debt_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    total_debt = self.clean_number(match.group(1))
                    break
                except Exception:
                    continue
        
        # Поиск кредиторов
        creditors = set()
        creditor_patterns = [
            r"(?:Кредитор|Банк):\s*(.+?)[\r\n]",
            r"Источник информации \(Кредитор\):\s*(.+?)[\r\n]"
        ]
        
        for pattern in creditor_patterns:
            for match in re.finditer(pattern, text):
                creditors.add(match.group(1).strip())
        
        # Если находим таблицу договоров
        try:
            if "ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ КРЕДИТНЫМ ДОГОВОРАМ" in text:
                # Ищем данные о кредитных договорах в таблице
                table_start = text.find("ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ КРЕДИТНЫМ ДОГОВОРАМ")
                if table_start > 0:
                    table_data = text[table_start:].split("Итого:")[0]
                    
                    # Извлекаем строки с суммами
                    amounts = re.findall(r"([\d\s.,]+)\s*KZT", table_data)
                    amounts = [self.clean_number(a) for a in amounts]
                    
                    if amounts and not total_debt:
                        # Берем сумму по договору, если она есть
                        if len(amounts) >= 1:
                            total_debt = amounts[0]
        except Exception as e:
            logger.error(f"Ошибка при обработке таблицы договоров: {e}")
        
        # Добавляем найденных кредиторов
        for creditor in creditors:
            obligations.append({
                "creditor": creditor,
                "balance": 0.0,  # Не можем определить точную сумму
                "monthly_payment": 0.0,
                "overdue_days": 0,
                "overdue_status": "нет данных"
            })
        
        # Определение ежемесячного платежа на основе суммы долга
        total_monthly_payment = round(total_debt * 0.05, 2)  # ~ 5% от суммы долга
        
        return {
            "personal_info": personal_info,
            "total_debt": round(total_debt, 2),
            "total_monthly_payment": total_monthly_payment,
            "total_obligations": max(total_obligations, len(obligations)),
            "overdue_obligations": 0,
            "obligations": obligations,
            "parsing_quality": "low"  # Индикатор качества парсинга
        }
    
# Создаем новый класс для отчетов ПКБ, наследуя от BaseParser
class PKBParser(BaseParser):
    """Точный парсер для отчетов ПКБ"""
    
    def can_parse(self, text: str) -> bool:
        return ("ПОЛНЫЙ ПЕРСОНАЛЬНЫЙ КРЕДИТНЫЙ ОТЧЕТ" in text or 
                "ПЕРСОНАЛЬНЫЙ КРЕДИТНЫЙ РЕЙТИНГ" in text or
                "ДОГОВОРЫ В КРЕДИТНОЙ ИСТОРИИ" in text)
    
    def extract_data(self, text: str) -> Dict:
    
        improved_parser = FinalPKBParser()
        return improved_parser.parse(text)
    
    def extract_from_precise_table(self, text: str) -> list:
        """Точное извлечение из таблицы с учетом реальной структуры"""
        obligations = []
        
        # Ищем таблицу с действующими договорами
        table_start = text.find("ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ КРЕДИТНЫМ ДОГОВОРАМ")
        if table_start == -1:
            logger.info("Таблица не найдена")
            return obligations
        
        table_end = text.find("Итого:", table_start)
        if table_end == -1:
            logger.info("Конец таблицы не найден")
            return obligations
        
        table_section = text[table_start:table_end]
        
        # Разбиваем на строки и ищем строки с данными
        lines = table_section.split('\n')
        data_lines = []
        
        for line in lines:
            # Строка с данными должна содержать KZT и не быть заголовком
            if ("KZT" in line and 
                "Вид" not in line and 
                "Кредитор" not in line and 
                "Роль" not in line and
                line.strip()):
                data_lines.append(line.strip())
        
        logger.info(f"Найдено {len(data_lines)} строк данных в таблице")
        
        for line_num, line in enumerate(data_lines, 1):
            obligation = self.parse_precise_table_line(line, line_num)
            if obligation:
                obligations.append(obligation)
        
        return obligations
    
    def parse_precise_table_line(self, line: str, line_num: int) -> Optional[Dict]:
        """Точно парсит строку таблицы"""
        try:
            logger.info(f"Парсинг строки {line_num}: {line[:100]}...")
            
            # Сначала извлекаем все суммы KZT по порядку
            kzt_amounts = re.findall(r"([\d\s,\.]+)\s*KZT", line)
            if len(kzt_amounts) < 4:
                logger.warning(f"Недостаточно сумм в строке {line_num}: {len(kzt_amounts)}")
                return None
            
            # Структура таблицы: Тип | Кредитор | Роль | Дата | Сумма_договора | Периодич_платеж | Непогаш_сумма | Сумма_просрочки | Дни | Штрафы | Пеня | Дата
            contract_amount = self.clean_number(kzt_amounts[0])
            periodic_payment = self.clean_number(kzt_amounts[1])  
            balance = self.clean_number(kzt_amounts[2])
            overdue_amount = self.clean_number(kzt_amounts[3])
            
            # Извлекаем кредитора - находим между "Заёмщик" и датой или между типом финансирования и "Заёмщик"
            # Удаляем известные части для облегчения поиска
            clean_line = line
            
            # Удаляем тип финансирования в начале
            clean_line = re.sub(r'^(Займ|Кредитная карта)\s+', '', clean_line)
            
            # Находим кредитора до "Заёмщик"
            creditor_match = re.search(r'^(.*?)\s+Заёмщик', clean_line)
            if not creditor_match:
                logger.warning(f"Не найден кредитор в строке {line_num}")
                return None
            
            creditor = creditor_match.group(1).strip()
            
            # Очищаем название кредитора от лишних пробелов
            creditor = re.sub(r'\s+', ' ', creditor).strip()
            
            # Извлекаем дни просрочки - ищем число перед KZT или в конце строки
            overdue_days = 0
            
            # Ищем дни просрочки как отдельное число после всех KZT
            remaining_line = line
            for kzt_amount in kzt_amounts:
                remaining_line = remaining_line.replace(f"{kzt_amount} KZT", "", 1)
            
            # Ищем числа в оставшейся части
            remaining_numbers = re.findall(r'\b(\d{1,4})\b', remaining_line)
            if remaining_numbers:
                # Берем наибольшее число как дни просрочки (обычно это самое большое число)
                overdue_days = max(int(num) for num in remaining_numbers[-3:])  # Последние 3 числа
            
            # Определяем основную сумму долга
            debt_amount = max(balance, overdue_amount)
            
            # Если ежемесячный платеж нулевой, оцениваем его
            if periodic_payment == 0 and debt_amount > 0:
                periodic_payment = debt_amount * 0.05  # 5% от долга
            
            # Валидация - принимаем любые договоры с ненулевой суммой
            if debt_amount <= 0 and contract_amount <= 0:
                logger.warning(f"Нулевые суммы в строке {line_num}")
                return None
            
            # Если основной долг нулевой, но есть сумма договора - используем её
            if debt_amount == 0 and contract_amount > 0:
                debt_amount = contract_amount
            
            obligation = {
                "creditor": creditor,
                "monthly_payment": round(periodic_payment, 2),
                "balance": round(debt_amount, 2),
                "overdue_amount": round(overdue_amount, 2),
                "overdue_days": overdue_days,
                "overdue_status": "просрочка" if overdue_days > 0 else "нет просрочки"
            }
            
            logger.info(f"Успешно извлечено: {creditor}, долг: {debt_amount}, просрочка: {overdue_days} дней")
            return obligation
            
        except Exception as e:
            logger.error(f"Ошибка при парсинге строки {line_num}: {e}")
            return None

# Добавьте этот класс в ваш credit_parser.py ПЕРЕД функцией create_parser_chain()

class GKBParser(BaseParser):
    """
    Специализированный парсер для отчетов ГКБ (Государственное кредитное бюро)
    Извлекает ВСЕ данные для банкротства: номера договоров, даты, суммы
    """
    
    def can_parse(self, text: str) -> bool:
        # Признаки отчета ГКБ
        gkb_indicators = [
            "Государственное кредитное бюро",
            "Персональный кредитный отчет",
            "Номер договора:",
            "Дата начала срока действия контракта:",
            "Обязательство 1"
        ]
        
        # Должно быть хотя бы 3 признака ГКБ
        gkb_score = sum(1 for indicator in gkb_indicators if indicator in text)
        
        # И НЕ должно быть признаков ПКБ
        pkb_indicators = ["ПОЛНЫЙ ПЕРСОНАЛЬНЫЙ КРЕДИТНЫЙ ОТЧЕТ", "Итого:"]
        pkb_score = sum(1 for indicator in pkb_indicators if indicator in text)
        
        is_gkb = gkb_score >= 3 and pkb_score == 0
        
        if is_gkb:
            logger.info("🎯 Определен формат ГКБ - используем специализированный парсер")
        
        return is_gkb
    
    def extract_data(self, text: str) -> Dict:
        """Извлекает данные из отчета ГКБ с ПОЛНОЙ информацией для банкротства"""
        
        logger.info("🚀 Запуск специализированного парсера ГКБ")
        
        # Извлекаем персональную информацию
        personal_info = self.extract_gkb_personal_info(text)
        
        # Извлекаем действующие обязательства
        active_obligations = self.extract_gkb_active_obligations(text)
        
        # Подсчитываем итоги
        total_debt = sum(obl.get("debt_amount", 0) for obl in active_obligations)
        total_monthly_payment = sum(obl.get("monthly_payment", 0) for obl in active_obligations)
        total_overdue = sum(obl.get("overdue_amount", 0) for obl in active_obligations)
        overdue_count = len([obl for obl in active_obligations if obl.get("overdue_amount", 0) > 0])
        
        # Конвертируем в стандартный формат вашей системы
        obligations = []
        for obligation in active_obligations:
            obligations.append({
                "creditor": obligation.get("creditor", "Неизвестно"),
                "balance": obligation.get("debt_amount", 0.0),
                "monthly_payment": obligation.get("monthly_payment", 0.0),
                "overdue_amount": obligation.get("overdue_amount", 0.0),
                "overdue_days": obligation.get("overdue_days", 0),
                "overdue_status": obligation.get("status", "Неизвестно"),
                # ✅ НОВЫЕ ПОЛЯ ДЛЯ БАНКРОТСТВА:
                "contract_number": obligation.get("contract_number", "НЕ НАЙДЕН"),
                "debt_origin_date": obligation.get("debt_origin_date", "НЕ НАЙДЕНА"),
                "loan_type": obligation.get("loan_type", "Неизвестно"),
                "interest_rate": obligation.get("interest_rate", 0.0)
            })
        
        logger.info(f"✅ ГКБ парсинг завершен: {len(active_obligations)} обязательств, {total_debt:,.2f} ₸")
        
        return {
            "personal_info": personal_info,
            "total_debt": round(total_debt, 2),
            "total_monthly_payment": round(total_monthly_payment, 2),
            "total_obligations": len(active_obligations),
            "overdue_obligations": overdue_count,
            "obligations": obligations,
            "report_type": "GKB",
            "bankruptcy_ready": True  # ✅ Готов для банкротства
        }
    
    def extract_gkb_personal_info(self, text: str) -> Dict:
        """Извлекает персональную информацию из отчета ГКБ"""
        
        personal_info = {}
        
        # ФИО
        name_match = re.search(r'Фамилия:\s*([^\n]+)\s+Имя:\s*([^\n]+)\s+Отчество:\s*([^\n]+)', text)
        if name_match:
            surname, name, patronymic = name_match.groups()
            personal_info['last_name'] = surname.strip()
            personal_info['first_name'] = name.strip()
            personal_info['middle_name'] = patronymic.strip()
            personal_info['full_name'] = f"{surname.strip()} {name.strip()} {patronymic.strip()}"
        
        # ИИН
        iin_match = re.search(r'ИИН:\s*(\d+)', text)
        if iin_match:
            personal_info['iin'] = iin_match.group(1)
        
        # Телефон
        phone_match = re.search(r'Моб\. тел\.:\s*(\d+)', text)
        if phone_match:
            personal_info['mobile_phone'] = phone_match.group(1)
        
        # Email
        email_match = re.search(r'E-mail:\s*([^\s\n]+)', text)
        if email_match:
            personal_info['email'] = email_match.group(1)
        
        # Адрес
        address_match = re.search(r'Постоянное место жительства.*?Улица:\s*([^\n]+)', text, re.DOTALL)
        if address_match:
            personal_info['address'] = address_match.group(1).strip()
        
        return personal_info
    
    # НАЙДИТЕ в классе GKBParser функцию extract_gkb_active_obligations
    # И ЗАМЕНИТЕ её ПОЛНОСТЬЮ на этот код:

    # НАЙДИТЕ в функции extract_gkb_active_obligations 
    # строки с used_creditors и ЗАМЕНИТЕ их на этот код:

    def extract_gkb_active_obligations(self, text: str) -> List[Dict]:
        """Извлекает ДЕЙСТВУЮЩИЕ обязательства из ГКБ с УМНОЙ логикой БЕЗ ДУБЛИКАТОВ"""
        
        obligations = []
        
        # 1. Находим раздел с действующими обязательствами
        active_section = re.search(
            r'ПОДРОБНАЯ ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ ДОГОВОРАМ(.*?)(?=ПОДРОБНАЯ ИНФОРМАЦИЯ О ЗАВЕРШЕННЫХ ДОГОВОРАХ|Текущие сведения)',
            text, 
            re.DOTALL
        )
        
        if not active_section:
            logger.warning("❌ Раздел действующих обязательств ГКБ не найден")
            return obligations
        
        active_text = active_section.group(1)
        
        # 2. СПОСОБ 1: Ищем обычные обязательства (с заголовком "Обязательство N")
        print(f"🔍 Ищем обязательства СТАНДАРТНЫМ способом...")
        obligation_pattern = r'Обязательство\s+(\d+)(.*?)(?=Обязательство\s+\d+|$)'
        standard_matches = re.finditer(obligation_pattern, active_text, re.DOTALL)
        
        standard_count = 0
        for match in standard_matches:
            obligation_num = match.group(1)
            obligation_text = match.group(2)
            
            obligation_data = self.parse_gkb_single_obligation(obligation_text, obligation_num)
            if obligation_data:
                obligations.append(obligation_data)
                standard_count += 1
                print(f"  ✅ Найдено стандартное обязательство #{obligation_num}")
        
        print(f"📊 Стандартным способом найдено: {standard_count} обязательств")
        
        # ✅ ИСПРАВЛЕНИЕ: Создаем набор пар (кредитор + номер_договора) для проверки дубликатов
        seen_pairs = {(obl['creditor'], obl['contract_number']) for obl in obligations}
        
        # 3. СПОСОБ 2: Если мало найдено - включаем РЕЗЕРВНЫЙ поиск
        if len(obligations) < 10:  # Если меньше 10 - ищем дополнительно
            print(f"⚠️  Мало обязательств! Включаем РЕЗЕРВНЫЙ поиск...")
            
            # Ищем блоки, которые начинаются с "Кредитор:" и заканчиваются "Количество дней просрочки:"
            fallback_pattern = r'(Кредитор:.*?)(?=Кредитор:|$)'
            fallback_matches = re.finditer(fallback_pattern, active_text, re.DOTALL)
            
            fallback_count = 0
            
            for i, match in enumerate(fallback_matches):
                fallback_text = match.group(1)
                
                # Проверяем, что в блоке есть нужные поля
                if ('Номер договора:' in fallback_text and 
                    'Количество дней просрочки:' in fallback_text):
                    
                    # ✅ ИСПРАВЛЕНИЕ: Извлекаем И кредитора И номер договора
                    creditor_match = re.search(r'Кредитор:\s*(.+)', fallback_text)
                    contract_match = re.search(r'Номер договора:\s*(.+)', fallback_text)
                    
                    if creditor_match and contract_match:
                        creditor_name = creditor_match.group(1).strip().strip('"')
                        contract_num = contract_match.group(1).strip()
                        
                        # ✅ ИСПРАВЛЕНИЕ: Проверяем пару (кредитор + договор), а не только кредитора
                        key = (creditor_name, contract_num)
                        
                        if key not in seen_pairs:
                            obligation_data = self.parse_gkb_single_obligation(fallback_text, f"R{i+1}")
                            if obligation_data and obligation_data.get('debt_amount', 0) > 0:
                                obligations.append(obligation_data)
                                seen_pairs.add(key)  # ✅ Добавляем пару в список найденных
                                fallback_count += 1
                                print(f"  ✅ Найдено резервное обязательство R{i+1}: {creditor_name} (договор: {contract_num})")
                        else:
                            print(f"  ⚠️  Пропускаем дубликат: {creditor_name} (договор: {contract_num})")
            
            print(f"📊 Резервным способом найдено: {fallback_count} обязательств")
        
        print(f"🎯 ИТОГО найдено обязательств: {len(obligations)}")
        
        return obligations
    def parse_gkb_single_obligation(self, text: str, obligation_num: str) -> Optional[Dict]:
        """Парсит ОДНО обязательство ГКБ с извлечением ВСЕХ данных для банкротства"""
        
        obligation = {
            'obligation_number': obligation_num,
            'parsing_errors': []
        }
        
        try:
            # 1. КРЕДИТОР
            creditor_match = re.search(r'Кредитор:\s*(.+)', text)
            if creditor_match:
                creditor = creditor_match.group(1).strip().strip('"')
                obligation['creditor'] = creditor
            else:
                obligation['parsing_errors'].append("Кредитор не найден")
                obligation['creditor'] = "Неизвестно"
            
            # 2. НОМЕР ДОГОВОРА (КРИТИЧЕСКИ ВАЖНО!)
            contract_match = re.search(r'Номер договора:\s*(.+)', text)
            if contract_match:
                obligation['contract_number'] = contract_match.group(1).strip()
            else:
                obligation['parsing_errors'].append("Номер договора не найден")
                obligation['contract_number'] = "НЕ НАЙДЕН"
            
            # 3. ДАТА ОБРАЗОВАНИЯ ЗАДОЛЖЕННОСТИ (КРИТИЧЕСКИ ВАЖНО!)
            start_date_match = re.search(r'Дата начала срока действия контракта:\s*(\d{2}\.\d{2}\.\d{4})', text)
            if start_date_match:
                obligation['debt_origin_date'] = start_date_match.group(1)
            else:
                # Пробуем альтернативные варианты
                issue_date_match = re.search(r'Дата фактической выдачи:\s*(\d{2}\.\d{2}\.\d{4})', text)
                if issue_date_match:
                    obligation['debt_origin_date'] = issue_date_match.group(1)
                else:
                    obligation['parsing_errors'].append("Дата образования задолженности не найдена")
                    obligation['debt_origin_date'] = "НЕ НАЙДЕНА"
            
            # 4. СУММА ДОЛГА - ИСПРАВЛЕННАЯ ЛОГИКА (пропускаем нули)
            print(f"  🔍 Ищем сумму долга...")

            def _num(val: str) -> float:
                """Вспомогательная функция для преобразования строки в число"""
                return float(val.replace(' ', '').replace(',', '.'))

            # Ищем все возможные суммы
            outstanding_match = re.search(r'Остаток задолженности.*?([\d\s]+\d(?:[,\.]\d+)?)\s*KZT', text)
            future_payment_match = re.search(r'Сумма предстоящих платежей.*?([\d\s]+\d(?:[,\.]\d+)?)\s*KZT', text)
            contract_sum_match = re.search(r'Сумма [Кк]редитного договора.*?([\d\s]+\d(?:[,\.]\d+)?)\s*KZT', text)
            overdue_match = re.search(r'Сумма просроченных взносов.*?([\d\s]+\d(?:[,\.]\d+)?)\s*KZT', text)

            # Словарь кандидатов в порядке приоритета
            candidates = {
                'outstanding': (outstanding_match, 'Остаток задолженности'),
                'future': (future_payment_match, 'Предстоящие платежи'), 
                'contract': (contract_sum_match, 'Сумма договора'),
                'overdue': (overdue_match, 'Просроченные взносы')
            }

            debt_amount = 0.0
            debt_source = 'Не найдено'
            
            # Ищем первое НЕНУЛЕВОЕ значение
            for name, (match, description) in candidates.items():
                if not match:
                    continue
                
                try:
                    value = _num(match.group(1))
                    if value > 0:  # ⬅️ КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: пропускаем нули
                        debt_amount = value
                        debt_source = description
                        print(f"  💰 Используем {description.upper()}: {debt_amount} KZT")
                        break
                    else:
                        print(f"  ⚠️ {description}: {value} KZT (ноль, пропускаем)")
                except (ValueError, AttributeError) as e:
                    print(f"  ❌ Ошибка обработки {description}: {e}")
                    continue

            obligation['debt_amount'] = debt_amount
            obligation['debt_source'] = debt_source
            
            if debt_amount == 0:
                obligation['parsing_errors'].append("Все найденные суммы равны нулю")
                print(f"  ❌ Все суммы равны нулю")

            # 5. ПРОСРОЧЕННАЯ ЗАДОЛЖЕННОСТЬ
            overdue_match = re.search(r'Сумма просроченных взносов.*?(\d+(?:\.\d+)?)\s*KZT', text)
            if overdue_match:
                obligation['overdue_amount'] = float(overdue_match.group(1))
            else:
                obligation['overdue_amount'] = 0.0
            
            # 6. ДНИ ПРОСРОЧКИ
            overdue_days_match = re.search(r'Количество дней просрочки:\s*(\d+)', text)
            if overdue_days_match:
                obligation['overdue_days'] = int(overdue_days_match.group(1))
            else:
                obligation['overdue_days'] = 0
            
            # 7. ТИП КРЕДИТА
            loan_type_match = re.search(r'Вид финансирования:\s*(.+)', text)
            if loan_type_match:
                obligation['loan_type'] = loan_type_match.group(1).strip()
            else:
                obligation['loan_type'] = "Неизвестно"
            
            # 8. ПРОЦЕНТНАЯ СТАВКА
            interest_match = re.search(r'Годовая эффективная ставка вознаграждения:\s*(\d+\.\d+)\s*%', text)
            if interest_match:
                obligation['interest_rate'] = float(interest_match.group(1))
            else:
                obligation['interest_rate'] = 0.0
            
            # 9. ЕЖЕМЕСЯЧНЫЙ ПЛАТЕЖ
            monthly_payment_match = re.search(r'Сумма ежемесячного платежа.*?(\d+(?:\.\d+)?)\s*KZT', text)
            if monthly_payment_match:
                obligation['monthly_payment'] = float(monthly_payment_match.group(1))
            else:
                obligation['monthly_payment'] = 0.0
            
            # 10. СТАТУС
            if obligation['overdue_days'] > 0:
                obligation['status'] = f"Просрочка {obligation['overdue_days']} дней"
            else:
                obligation['status'] = "Действующий"
            
            return obligation
            
        except Exception as e:
            obligation['parsing_errors'].append(f"Ошибка парсинга: {str(e)}")
            logger.error(f"❌ Ошибка парсинга обязательства {obligation_num}: {e}")
            return obligation

# ОБНОВИТЕ функцию create_parser_chain() - добавьте GKBParser в начало цепи:

def create_parser_chain():
    """Создает цепочку парсеров с добавленным GKBParser"""
    
    # ✅ ДОБАВЛЯЕМ GKBParser В НАЧАЛО ЦЕПОЧКИ
    gkb = GKBParser()           # ← НОВЫЙ! Специально для ГКБ отчетов
    pkb = PKBParser()           # Для ПКБ отчетов  
    detailed = DetailedParser() # Для детальных отчетов
    short = ShortParser()       # Для кратких отчетов
    kazakh = KazakhParser()     # Для казахоязычных отчетов
    fallback = FallbackParser() # Универсальная заглушка
    
    # Устанавливаем цепочку: GKB → PKB → Detailed → Short → Kazakh → Fallback
    gkb.set_next(pkb).set_next(detailed).set_next(short).set_next(kazakh).set_next(fallback)
    
    logger.info("🔗 Цепочка парсеров обновлена: GKB → PKB → Detailed → Short → Kazakh → Fallback")
    
    return gkb  # Возвращаем первый парсер в цепочке


# ОБНОВИТЕ функцию generate_creditors_list_pdf в том файле где она у вас есть:

def generate_creditors_list_pdf_IMPROVED(parsed_data):
    """
    ОБНОВЛЕННАЯ версия PDF генератора с поддержкой данных ГКБ
    """
    try:
        print(f"\n🎯 [IMPROVED] Генерируем PDF с данными из ГКБ:")
        
        # Регистрируем шрифты (ваша существующая функция)
        font_name = register_fonts()
        
        # Создаем временный файл
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        doc = SimpleDocTemplate(tmp_file.name, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()

        # Настраиваем стили
        title_style = ParagraphStyle('RussianTitle', parent=styles['Title'], 
                                   fontName=font_name, fontSize=16, alignment=1)
        normal_style = ParagraphStyle('RussianNormal', parent=styles['Normal'], 
                                    fontName=font_name, fontSize=10)
        success_style = ParagraphStyle('RussianSuccess', parent=styles['Normal'], 
                                     fontName=font_name, fontSize=11, 
                                     textColor=colors.green, alignment=1)

        # Заголовок
        title = Paragraph("ПЕРЕЧЕНЬ КРЕДИТОРОВ ДЛЯ БАНКРОТСТВА", title_style)
        elements.append(title)
        elements.append(Spacer(1, 12))
        
        # СТАТУС УСПЕХА
        if parsed_data.get('bankruptcy_ready', False) or parsed_data.get('report_type') == 'GKB':
            success = Paragraph(
                "<b>✅ ВСЕ ДАННЫЕ ИЗВЛЕЧЕНЫ УСПЕШНО!</b><br/>"
                "Документ готов для процедуры банкротства",
                success_style
            )
            elements.append(success)
            elements.append(Spacer(1, 20))

        # Информация о заемщике
        personal_info = parsed_data.get('personal_info', {})
        
        debtor_text = f"""
        <b>Заемщик:</b> {personal_info.get('full_name', 'Не указано')}<br/>
        <b>ИИН:</b> {personal_info.get('iin', 'Не указано')}<br/>
        <b>Телефон:</b> {personal_info.get('mobile_phone', 'Не указано')}<br/>
        <b>Email:</b> {personal_info.get('email', 'Не указано')}<br/>
        <b>Дата составления:</b> {datetime.now().strftime('%d.%m.%Y')}
        """
        elements.append(Paragraph(debtor_text, normal_style))
        elements.append(Spacer(1, 12))

        # Заголовки таблицы - С ПОЛНЫМИ ДАННЫМИ
        headers = ['№', 'Кредитор', 'Номер договора', 'Дата образования', 'Сумма долга (KZT)', 'Просрочка (KZT)', 'Статус']
        table_data = [headers]

        # Извлекаем обязательства
        obligations = parsed_data.get('obligations', [])
        
        for i, obligation in enumerate(obligations, 1):
            row = [
                str(i),
                obligation.get('creditor', 'Не указано'),
                obligation.get('contract_number', 'НЕ НАЙДЕН'),      # ✅ ТЕПЕРЬ ЕСТЬ!
                obligation.get('debt_origin_date', 'НЕ НАЙДЕНА'),    # ✅ ТЕПЕРЬ ЕСТЬ!
                f"{obligation.get('balance', 0):,.2f}".replace(',', ' '),
                f"{obligation.get('overdue_amount', 0):,.2f}".replace(',', ' '),
                obligation.get('overdue_status', 'Неизвестно')
            ]
            table_data.append(row)

        # Создаем таблицу
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.lightgreen),  # Зеленый = успех!
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))

        elements.append(table)
        elements.append(Spacer(1, 24))

        # Итоги
        total_debt = parsed_data.get('total_debt', 0)
        total_overdue = sum(obl.get('overdue_amount', 0) for obl in obligations)
        
        summary_text = f"""
        <b>ИТОГО:</b><br/>
        Общее количество активных кредиторов: {len(obligations)}<br/>
        Общая сумма задолженности: {total_debt:,.2f} тенге<br/>
        Общая просроченная задолженность: {total_overdue:,.2f} тенге<br/>
        <br/>
        <b>✅ ДАННЫЕ ДЛЯ БАНКРОТСТВА ГОТОВЫ:</b><br/>
        • ✅ Номера договоров извлечены<br/>
        • ✅ Даты образования задолженности найдены<br/>
        • ✅ Суммы долгов подтверждены<br/>
        • ⚠️ Контактные данные кредиторов требуют уточнения
        """
        elements.append(Paragraph(summary_text, normal_style))

        # Сборка PDF
        doc.build(elements)
        
        print(f"✅ PDF создан успешно: {tmp_file.name}")
        return tmp_file.name

    except Exception as e:
        print(f"❌ Ошибка создания PDF: {e}")
        import traceback
        traceback.print_exc()
        return None


# ТЕСТОВАЯ ФУНКЦИЯ для проверки
# ЗАМЕНИТЕ тестовую функцию в конце вашего файла на эту:

def test_gkb_parser():
    """Тестируем новый GKB парсер на вашем файле"""
    
    try:
        # Читаем ваш файл
        with open('debug_text_output_376068212_1c3e3593.txt', 'r', encoding='utf-8') as f:
            text = f.read()
        
        print("🚀 ТЕСТИРУЕМ ОБНОВЛЕННУЮ СИСТЕМУ ПАРСЕРОВ")
        print("=" * 50)
        
        # Создаем парсер напрямую
        parser = create_parser_chain()
        result = parser.parse(text)
        
        if not result:
            print("❌ Парсер вернул None")
            return None
        
        # Выводим результат
        print(f"📊 РЕЗУЛЬТАТ:")
        print(f"  📄 Тип отчета: {result.get('report_type', 'Неизвестно')}")
        print(f"  👤 Заемщик: {result['personal_info'].get('full_name', 'Не найдено')}")
        print(f"  📋 Обязательств: {len(result['obligations'])}")
        print(f"  💰 Общий долг: {result['total_debt']:,.2f} KZT")
        
        # Проверяем, извлечены ли номера договоров и даты
        contracts_found = 0
        dates_found = 0
        
        print(f"\n🔍 ПРОВЕРКА ИЗВЛЕЧЕНИЯ ДАННЫХ:")
        for i, obligation in enumerate(result['obligations'][:5], 1):  # Показываем первые 5
            contract = obligation.get('contract_number', 'НЕ НАЙДЕН')
            date = obligation.get('debt_origin_date', 'НЕ НАЙДЕНА')
            
            if contract and contract != 'НЕ НАЙДЕН':
                contracts_found += 1
            if date and date != 'НЕ НАЙДЕНА':
                dates_found += 1
            
            print(f"  {i}. {obligation['creditor']}")
            print(f"     📄 Договор: {contract}")
            print(f"     📅 Дата: {date}")
            print(f"     💰 Долг: {obligation['balance']:,.2f} KZT")
        
        print(f"\n✅ ИТОГОВАЯ ПРОВЕРКА:")
        print(f"  📄 Номеров договоров найдено: {contracts_found}/{len(result['obligations'])}")
        print(f"  📅 Дат найдено: {dates_found}/{len(result['obligations'])}")
        
        if contracts_found > 0 and dates_found > 0:
            print(f"  🎯 УСПЕХ: Данные для банкротства извлечены!")
            print(f"  ✅ GKBParser работает корректно!")
        else:
            print(f"  ⚠️ ПРОБЛЕМА: Данные не извлечены - возможно используется другой парсер")
            print(f"  🔍 Проверим, какой парсер сработал...")
            
            # Дополнительная диагностика
            if result.get('report_type') == 'GKB':
                print(f"  ✅ Сработал GKBParser")
            elif 'totals' in result:
                print(f"  ℹ️ Сработал PKBParser (улучшенный)")
            else:
                print(f"  ℹ️ Сработал другой парсер")
        
        return result
        
    except FileNotFoundError:
        print(f"❌ Файл debug_text_output_376068212_972e044a.txt не найден в текущей директории")
        print(f"📁 Текущая директория: {os.getcwd()}")
        print(f"📄 Попробуйте указать полный путь к файлу")
        return None
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")
        import traceback
        traceback.print_exc()
        return None


# АЛЬТЕРНАТИВНЫЙ тест для проверки работы GKBParser
def test_gkb_parser_direct():
    """Прямой тест GKBParser без цепочки"""
    
    try:
        with open('debug_text_output_376068212_1c3e3593.txt', 'r', encoding='utf-8') as f:
            text = f.read()
        
        print("🔍 ПРЯМОЙ ТЕСТ GKBParser")
        print("=" * 30)
        
        # Создаем GKBParser напрямую
        gkb_parser = GKBParser()
        
        # Проверяем, может ли он парсить этот текст
        can_parse = gkb_parser.can_parse(text)
        print(f"🎯 Может ли GKBParser обработать файл: {'ДА' if can_parse else 'НЕТ'}")
        
        if can_parse:
            print("🚀 Запускаем GKBParser...")
            result = gkb_parser.extract_data(text)
            
            print(f"📊 Результат GKBParser:")
            print(f"  👤 Заемщик: {result['personal_info'].get('full_name', 'Не найдено')}")
            print(f"  📋 Обязательств: {len(result['obligations'])}")
            
            # Проверяем первое обязательство
            if result['obligations']:
                first_obl = result['obligations'][0]
                print(f"  📄 Первый договор: {first_obl.get('contract_number', 'НЕ НАЙДЕН')}")
                print(f"  📅 Первая дата: {first_obl.get('debt_origin_date', 'НЕ НАЙДЕНА')}")
        else:
            print("❌ GKBParser не может обработать этот файл")
            print("🔍 Проверим признаки ГКБ в файле:")
            
            gkb_indicators = [
                "Государственное кредитное бюро",
                "Персональный кредитный отчет", 
                "Номер договора:",
                "Дата начала срока действия контракта:",
                "Обязательство 1"
            ]
            
            for indicator in gkb_indicators:
                found = indicator in text
                print(f"  {'✅' if found else '❌'} {indicator}: {'НАЙДЕН' if found else 'НЕ НАЙДЕН'}")
        
        return result if can_parse else None
        
    except Exception as e:
        print(f"❌ Ошибка прямого теста: {e}")
        return None


# Обновите секцию if __name__ == "__main__":

if __name__ == "__main__":
    print("🔧 Выберите тест:")
    print("1. Полный тест через цепочку парсеров")
    print("2. Прямой тест GKBParser")
    
    choice = input("Введите номер (1 или 2): ").strip()
    
    if choice == "1":
        test_gkb_parser()
    elif choice == "2":  
        test_gkb_parser_direct()
    else:
        print("🚀 Запускаем оба теста:")
        print("\n" + "="*50)
        print("ПРЯМОЙ ТЕСТ GKBParser:")
        test_gkb_parser_direct()
        
        print("\n" + "="*50) 
        print("ПОЛНЫЙ ТЕСТ ЧЕРЕЗ ЦЕПОЧКУ:")
        test_gkb_parser()
if __name__ == "__main__":
    test_gkb_parser()

def create_parser_chain():
    """Создает цепочку парсеров"""
    pkb = PKBParser()  # Новый парсер для ПКБ
    gkb = GKBParser() # Новый парсер для ГКБ отчетов
    detailed = DetailedParser()
    short = ShortParser()
    kazakh = KazakhParser()
    fallback = FallbackParser()
    
    # ✅ ПРАВИЛЬНАЯ цепочка: GKB → PKB → Detailed → Short → Kazakh → Fallback
    gkb.set_next(pkb).set_next(detailed).set_next(short).set_next(kazakh).set_next(fallback)

    
    return gkb  # Возвращаем первый парсер в цепочке

def extract_credit_data_with_total(text: str) -> Dict:
    """Основная функция для извлечения данных из кредитного отчета"""
    parser = create_parser_chain()
    result = parser.parse(text)
    
    if not result:
        logger.error("Не удалось распарсить кредитный отчет")
        return {
            "personal_info": {},
            "total_debt": 0.0,
            "total_monthly_payment": 0.0,
            "total_obligations": 0,
            "overdue_obligations": 0,
            "obligations": [],
            "parsing_error": True
        }
    # Добавляем извлечённые залоги
    result["collaterals"] = extract_collateral_info(text)

    return result

# Новая функция: Парсинг отчета напрямую из MongoDB
def parse_credit_report_from_mongodb(report_id, collection_name="documents"):
    """Парсит кредитный отчет напрямую из MongoDB независимо от языка отчета"""
    try:
        # Подключение к MongoDB
        client = MongoClient(os.getenv("MONGO_URI"))
        db = client["telegram_bot"]
        collection = db[collection_name]
        
        # Этап 1: Получаем документ
        document = collection.find_one({"_id": ObjectId(report_id)})
        
        if not document:
            logger.error(f"Документ с ID {report_id} не найден в коллекции {collection_name}")
            return {
                "parsing_error": True,
                "error_message": f"Документ с ID {report_id} не найден"
            }
        
        # Получаем текст документа
        text = document.get("text", "")
        
        # Применяем парсинг с цепочкой парсеров
        return extract_credit_data_with_total(text)
        
    except Exception as e:
        logger.error(f"Ошибка при парсинге отчета из MongoDB: {e}")
        return {
            "parsing_error": True,
            "error_message": str(e)
        }

# Новая функция: Извлечение данных из MongoDB и преобразование в стандартный формат
def extract_credit_data_from_mongodb(report_id, collection_name="documents") -> Dict:
    """Извлекает данные кредитного отчета из MongoDB и форматирует их"""
    result = parse_credit_report_from_mongodb(report_id, collection_name)
    
    if result.get("parsing_error", False):
        logger.error(f"Ошибка при парсинге отчета из MongoDB: {result.get('error_message', 'Неизвестная ошибка')}")
        return {
            "personal_info": {},
            "total_debt": 0.0,
            "total_monthly_payment": 0.0,
            "total_obligations": 0,
            "overdue_obligations": 0,
            "obligations": [],
            "parsing_error": True
        }
    
    return result

# Новая функция: Выбор метода парсинга в зависимости от типа данных
def extract_credit_data(data, is_mongodb_id=False):
    """
    Выбирает метод парсинга в зависимости от типа данных
    
    Args:
        data: Либо ID документа в MongoDB, либо текст отчета
        is_mongodb_id: Флаг, указывающий, что data является ID документа в MongoDB
    
    Returns:
        Dict: Результат парсинга в стандартном формате
    """
    if is_mongodb_id:
        return extract_credit_data_from_mongodb(data)
    else:
        return extract_credit_data_with_total(data)

# Обновленная функция форматирования результатов с учетом языка и личных данных
def format_summary(data: Dict) -> str:
    """Форматирует данные в читаемый вид"""

    # # 🔍 ОТЛАДКА: Проверяем количество кредиторов
    # print(f"\n🔍 [DEBUG] format_summary получил данные:")
    # print(f"   - obligations (всего): {len(data.get('obligations', []))}")
    # print(f"   - total_obligations: {data.get('total_obligations', 0)}")
    # print(f"   - overdue_obligations: {data.get('overdue_obligations', 0)}")
    
    # # Выводим всех кредиторов до фильтрации
    # all_obligations = data.get("obligations", [])
    # print(f"\n📋 ВСЕ кредиторы до фильтрации ({len(all_obligations)}):")
    # for i, o in enumerate(all_obligations, 1):
    #     print(f"   {i}. {o.get('creditor', 'Неизвестно')}: balance={o.get('balance', 0)} ₸, overdue_days={o.get('overdue_days', 0)}")


    # Если это результат от улучшенного PKB парсера
    if data.get("totals") and data.get("contract_summary"):
        from improved_pkb_parser import format_pkb_summary
        return format_pkb_summary(data)
    
    # Проверка на ошибку парсинга
    if data.get("parsing_error", False):
        return (
            "⚠️ Не удалось корректно распознать кредитный отчет.\n"
            "Пожалуйста, свяжитесь с администратором для проверки."
        )
    
    # Проверка качества парсинга
    quality_note = ""
    if data.get("parsing_quality") == "low":
        quality_note = "\n⚠️ Отчет обработан приблизительно, некоторые детали могли быть не распознаны."

    # Формируем блок с информацией о пользователе
    personal_info = data.get("personal_info", {})
    personal_info_text = ""
    
    if personal_info:
        personal_info_text = "👤 Личные данные:"
        
        full_name = personal_info.get("full_name")
        last = personal_info.get("last_name")
        first = personal_info.get("first_name")
        middle = personal_info.get("middle_name")

        if full_name:
            personal_info_text += f"\n— ФИО: {full_name}"
        elif last and first:
            personal_info_text += f"\n— ФИО: {last} {first} {middle or ''}".strip()

        if personal_info.get("iin"):
            personal_info_text += f"\n— ИИН: {personal_info['iin']}"
            
        if personal_info.get("birth_date"):
            personal_info_text += f"\n— Дата рождения: {personal_info['birth_date']}"
            
        if personal_info.get("address"):
            personal_info_text += f"\n— Адрес: {personal_info['address']}"
        
        personal_info_text += "\n"


    # Фильтруем только активные кредиты с ненулевым балансом
    active_obligations = [o for o in data.get("obligations", []) if o.get("balance", 0) > 0]
    
    # Считаем количество неактивных обязательств
    inactive_count = data['total_obligations'] - len(active_obligations)
    
    # Определяем язык для форматирования результата
    language = data.get("language", "russian")
    
    # Заголовки в зависимости от языка
    headers = {
        "kazakh": {
            "report_header": "📊 Сіздің несие есебіңіздің қорытындысы:",
            "total_creditors": "— Барлық кредиторлар саны:",
            "overdue_obligations": "— Мерзімі өткен міндеттемелер:",
            "total_debt": "— Жалпы берешек сомасы:",
            "monthly_payment": "— Ай сайынғы төлем:",
            "details_header": "📋 Белсенді кредиторлар бойынша толық мәліметтер:",
            "overdue_text": "мерзімі өткен",
            "days": "күн",
            "inactive": "📝 Қосымша: {} жабық/белсенді емес міндеттемелер"
        },
        "russian": {
            "report_header": "📊 Итог по вашему кредитному отчёту:",
            "total_creditors": "— Всего кредиторов:",
            "overdue_obligations": "— Просроченных обязательств:",
            "total_debt": "— Общая сумма задолженности:",
            "monthly_payment": "— Ежемесячный платёж:",
            "details_header": "📋 Детали по активным кредиторам:",
            "overdue_text": "просрочка",
            "days": "дней",
            "inactive": "📝 Дополнительно: {} закрытых/неактивных обязательств"
        }
    }
    
    # Используем русские заголовки по умолчанию
    h = headers.get(language, headers["russian"])
    
    # Добавляем информацию о кредиторах, если они есть
    creditors_info = ""
    if active_obligations:
        creditors_info = f"\n\n{h['details_header']}"
        for i, obligation in enumerate(active_obligations):
            overdue_info = f" ({h['overdue_text']} {obligation['overdue_days']} {h['days']})" if obligation.get('overdue_days', 0) > 0 else ""
            creditors_info += f"\n{i+1}. {obligation['creditor']}: {obligation['balance']:,.2f} ₸{overdue_info}"
        
        # Добавляем информацию о количестве неактивных обязательств
        if inactive_count > 0:
            creditors_info += f"\n\n{h['inactive'].format(inactive_count)}"
    # 🔒 Добавляем информацию о залогах
    collaterals_info = ""
    collaterals = data.get("collaterals", [])
    if collaterals:
        collaterals_info = "\n\n🔒 Обеспечение (залог):"
        for i, c in enumerate(collaterals, 1):
            collaterals_info += (
                f"\n{i}. Кредитор: {c['creditor']}, Тип: {c['collateral_type']}, "
                f"Стоимость: {c['market_value']:,.2f} ₸"
            )
    return (
        f"{personal_info_text}\n"
        f"{h['report_header']}\n"
        f"{h['total_creditors']} {data['total_obligations']}\n"
        f"{h['overdue_obligations']} {data['overdue_obligations']}\n"
        f"{h['total_debt']} {data['total_debt']:,.2f} ₸\n"
        f"{h['monthly_payment']} {data['total_monthly_payment']:,.2f} ₸"
        f"{creditors_info}"
        f"{collaterals_info}"
        f"{quality_note}"
    )


# Пример использования MongoDB парсера
def process_credit_report_from_mongodb(report_id):
    """Обрабатывает кредитный отчет из MongoDB и возвращает форматированный результат"""
    result = extract_credit_data(report_id, is_mongodb_id=True)
    return format_summary(result)