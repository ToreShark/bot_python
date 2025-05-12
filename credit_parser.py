# credit_parser.py
import re
import os
from typing import Dict, List, Optional
import logging
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

# Детальный парсер (подробный отчет ПКБ)
class DetailedParser(BaseParser):
    def can_parse(self, text: str) -> bool:
        return "ПОДРОБНАЯ ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ ДОГОВОРАМ" in text
    
    def extract_data(self, text: str) -> Dict:
        obligations = []
        total_monthly_payment = 0.0
        total_overdue_creditors = 0
        total_debt = 0.0
        
        # Первым делом пробуем получить общую сумму долга из раздела общей информации
        debt_patterns = [
            r"Остаток\s+задолженности\s+по\s+договору/\s*валюта:\s*([\d\s.,]+)\s*KZT",
            r"Общая\s+сумма\s+(?:задолженности|долга)(?:/валюта)?:\s*([\d\s.,]+)\s*KZT"
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
        
        # Извлекаем данные по каждому обязательству
        obligation_blocks = []
        
        # Ищем блоки обязательств
        blocks = re.split(r"(?:Обязательство)\s+\d+", text)
        if len(blocks) > 1:
            obligation_blocks = blocks[1:]  # Пропускаем первый блок (до Обязательства 1)
        
        logger.info(f"Найдено {len(obligation_blocks)} блоков обязательств")
        
        for block in obligation_blocks:
            try:
                # Очистим блок от ненужных данных для облегчения парсинга
                block = re.sub(r'Страница \d+ из \d+', '', block)
                
                # Извлекаем основные данные обязательства
                creditor_match = re.search(r"Кредитор:\s*(.+?)[\r\n]", block)
                payment_match = re.search(
                    r"Сумма ежемесячного платежа /валюта:\s*([\d\s.,]+)\s*KZT", block
                )
                overdue_match = re.search(r"Сумма просроченных взносов /валюта:\s*([\d\s.,]+)\s*KZT", block)
                balance_match = re.search(
                    r"Сумма предстоящих платежей /валюта:\s*([\d\s.,]+)\s*KZT", block
                )
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
            "total_debt": round(total_debt, 2),
            "total_monthly_payment": round(total_monthly_payment, 2),
            "total_obligations": len(obligations),
            "overdue_obligations": total_overdue_creditors,
            "obligations": obligations
        }

# Парсер для кратких отчетов
class ShortParser(BaseParser):
    def can_parse(self, text: str) -> bool:
        return "ОБЩАЯ ИНФОРМАЦИЯ ПО ОБЯЗАТЕЛЬСТВАМ" in text and "Общая сумма задолженности/валюта" in text
    
    def extract_data(self, text: str) -> Dict:
        obligations = []
        total_debt = 0.0
        total_overdue_creditors = 0
        lines = text.splitlines()
        
        # Получаем общую сумму задолженности
        for i, line in enumerate(lines):
            if "Общая сумма задолженности/валюта" in line:
                try:
                    # Ищем сумму на следующей строке
                    for j in range(i+1, i+5):  # Смотрим в нескольких следующих строках
                        if j < len(lines) and re.match(r"^[\d\s.,]+\s*KZT$", lines[j].strip()):
                            total_debt = self.clean_number(lines[j])
                            break
                except Exception as e:
                    logger.error(f"Ошибка при определении общей суммы: {e}")
        
        # Извлекаем данные по кредиторам из таблицы
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
                
                if balance > 0:
                    obligations.append({
                        "creditor": current_creditor,
                        "contract": current_contract if current_contract else "Нет данных",
                        "balance": round(balance, 2),
                        "monthly_payment": 0.0,  # В кратком отчете нет этих данных
                        "overdue_days": overdue_days,
                        "overdue_status": "просрочка" if overdue_days > 0 else "нет просрочки"
                    })
                    
                    if overdue_days > 0:
                        total_overdue_creditors += 1
                
                # Сбрасываем текущие значения
                current_creditor = None
                current_contract = None
        
        # Если общая сумма не найдена, суммируем из обязательств
        if total_debt == 0.0 and obligations:
            total_debt = sum(o["balance"] for o in obligations)
        
        return {
            "total_debt": round(total_debt, 2),
            "total_monthly_payment": 0.0,  # В кратком отчете нет этих данных
            "total_obligations": len(obligations),
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
    
    def extract_data(self, text: str) -> Dict:
        """Извлекает данные из казахоязычного отчета"""
        logger.info("Обработка казахоязычного отчета")
        
        obligations = []
        total_monthly_payment = 0.0
        total_overdue_creditors = 0
        total_debt = 0.0
        
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
                    
                    # Баланс (остаток долга) - проверяем несколько шаблонов
                    balance_patterns = [
                        r"Алдағы төлемдер сомасы\s*/\s*валюта\s*([\d\s.,]+)\s*KZT",
                        r"Шарттың жалпы сомасы\s*/\s*валюта:\s*([\d\s.,]+)\s*KZT",
                        r"Мерзімі өткен жарналар сомасы\s*/валюта:\s*([\d\s.,]+)\s*KZT"
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
                    balance = self.clean_number(balance_match.group(1)) if balance_match else 0.0
                    status = status_match.group(1).strip() if status_match else "стандартты"
                    overdue_days = int(overdue_days_match.group(1)) if overdue_days_match else 0
                    
                    # Определяем тип кредитора для оценки
                    is_bank = any(x in creditor.lower() for x in ["банк", "bank"])
                    is_mfo = any(x in creditor.lower() for x in ["мфо", "микро", "finance", "кредит"])
                    
                    # Если нет информации о балансе, но есть просрочка, оцениваем по типу кредитора
                    if balance == 0 and overdue_days > 0:
                        # Отправляем запрос в БД для получения средних значений
                        # (псевдокод, замените на реальный запрос к вашей БД)
                        # average_balance = db.get_average_balance_for_creditor_type(is_bank, is_mfo)
                        
                        # Упрощенная оценка (можно заменить на результаты из БД)
                        if is_bank:
                            balance = 700000.0  # Средний баланс для банков
                        elif is_mfo:
                            balance = 200000.0  # Средний баланс для МФО
                        else:
                            balance = 250000.0  # Средний баланс для других кредиторов
                    
                    # Если нет информации о ежемесячном платеже, рассчитываем на основе баланса
                    if monthly_payment == 0.0 and balance > 0:
                        # Коэффициент платежа зависит от типа кредитора
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
                        "overdue_amount": 0.0,
                        "overdue_days": overdue_days,
                        "overdue_status": status
                    }
                    
                    # Добавляем в список обязательств только если баланс > 0 или есть просрочка
                    if balance > 0 or overdue_days > 0:
                        obligations.append(obligation)
                        
                        # Обновляем итоговые суммы
                        total_monthly_payment += monthly_payment
                        if overdue_days > 0:
                            total_overdue_creditors += 1
                    
                    logger.info(f"Извлечено обязательство: {creditor}, баланс: {balance}, просрочка: {overdue_days} дней")
                    
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
        
        # Попытка найти общую сумму задолженности и количество обязательств
        total_debt = 0.0
        obligations = []
        
        debt_patterns = [
            r"(?:Общая сумма|сумма долга|долг|задолженность).{1,50}?([\d\s.,]+)\s*(?:KZT|₸|тенге)",
            r"([\d\s.,]+)\s*(?:KZT|₸|тенге).*?(?:задолженность|долг)"
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
        creditor_pattern = r"(?:Кредитор|Банк):\s*(.+?)[\r\n]"
        for match in re.finditer(creditor_pattern, text):
            creditors.add(match.group(1).strip())
        
        for creditor in creditors:
            obligations.append({
                "creditor": creditor,
                "balance": 0.0,  # Не можем определить точную сумму
                "monthly_payment": 0.0,
                "overdue_days": 0,
                "overdue_status": "нет данных"
            })
        
        return {
            "total_debt": round(total_debt, 2),
            "total_monthly_payment": 0.0,
            "total_obligations": len(obligations),
            "overdue_obligations": 0,
            "obligations": obligations,
            "parsing_quality": "low"  # Индикатор качества парсинга
        }

def create_parser_chain():
    """Создает цепочку парсеров"""
    detailed = DetailedParser()
    short = ShortParser()
    kazakh = KazakhParser()
    fallback = FallbackParser()
    
    # Установка цепочки
    detailed.set_next(short).set_next(kazakh).set_next(fallback)
    
    return detailed  # Возвращаем первый парсер в цепочке

def extract_credit_data_with_total(text: str) -> Dict:
    """Основная функция для извлечения данных из кредитного отчета"""
    parser = create_parser_chain()
    result = parser.parse(text)
    
    if not result:
        logger.error("Не удалось распарсить кредитный отчет")
        return {
            "total_debt": 0.0,
            "total_monthly_payment": 0.0,
            "total_obligations": 0,
            "overdue_obligations": 0,
            "obligations": [],
            "parsing_error": True
        }
    
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
        
        text = document.get("text", "")
        
        # Определяем язык отчета
        language = "unknown"
        if "ҚОЛДАНЫСТАҒЫ ШАРТТАР" in text:
            language = "kazakh"
        elif "ПОДРОБНАЯ ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ ДОГОВОРАМ" in text:
            language = "russian"
        
        logger.info(f"Определен язык отчета: {language}")
        
        # Этап 2: Извлекаем общую информацию
        obligations = []
        total_monthly_payment = 0.0
        total_overdue_creditors = 0
        total_debt = 0.0
        
        # Общая сумма долга - разные шаблоны для разных языков
        total_debt_patterns = {
            "kazakh": [
                r"Шарт бойынша\s*берешек\s*қалдығы\s*/\s*валюта:\s*([\d\s.,]+)\s*KZT",
                r"Мерзімі өткен\s*жарналар\s*сомасы\s*/\s*валюта:\s*([\d\s.,]+)\s*KZT"
            ],
            "russian": [
                r"Остаток\s+задолженности\s+по\s+договору/\s*валюта:\s*([\d\s.,]+)\s*KZT",
                r"Общая\s+сумма\s+(?:задолженности|долга)(?:/валюта)?:\s*([\d\s.,]+)\s*KZT",
                r"Сумма\s+просроченных\s+взносов\s*/валюта:\s*([\d\s.,]+)\s*KZT"
            ]
        }
        
        # Извлекаем общую сумму долга
        patterns = total_debt_patterns.get(language, [])
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                debt_str = match.group(1).replace(" ", "").replace(",", ".").replace("KZT", "").strip()
                try:
                    total_debt = float(debt_str)
                    logger.info(f"Найдена общая сумма долга: {total_debt} KZT")
                    break
                except (ValueError, TypeError) as e:
                    logger.error(f"Ошибка при извлечении суммы долга: {e}")
        
        # Ищем блоки обязательств - разные шаблоны для разных языков
        block_pattern = "Міндеттеме\\s+\\d+" if language == "kazakh" else "Обязательство\\s+\\d+"
        obligation_blocks = re.split(block_pattern, text)
        
        if len(obligation_blocks) > 1:
            obligation_blocks = obligation_blocks[1:]  # Пропускаем первый блок
            logger.info(f"Найдено {len(obligation_blocks)} блоков обязательств")
            
            # Шаблоны для извлечения данных из обязательств
            patterns = {
                "creditor": r"Кредитор:\s*(.+?)[\r\n]",
                "kazakh": {
                    "payment": [
                        r"Ай сайынғы төлем сомасы\s*/\s*валюта:\s*([\d\s.,]+)\s*KZT",
                        r"Төлем сомасы\s*/\s*валюта:\s*([\d\s.,]+)\s*KZT"
                    ],
                    "balance": [
                        r"Алдағы төлемдер сомасы\s*/\s*валюта\s*([\d\s.,]+)\s*KZT",
                        r"Мерзімі өткен жарналар сомасы\s*/валюта:\s*([\d\s.,]+)\s*KZT"
                    ],
                    "overdue_days": r"Мерзімі өткен күндер саны:\s*(\d+)",
                    "status": r"Шарттың мәртебесі:\s*(.+?)[\r\n]"
                },
                "russian": {
                    "payment": [
                        r"Сумма ежемесячного платежа /валюта:\s*([\d\s.,]+)\s*KZT"
                    ],
                    "balance": [
                        r"Сумма предстоящих платежей /валюта:\s*([\d\s.,]+)\s*KZT",
                        r"Сумма просроченных взносов /валюта:\s*([\d\s.,]+)\s*KZT"
                    ],
                    "overdue_days": r"Количество дней просрочки:\s*(\d+)",
                    "status": r"Статус договора:\s*(.+?)[\r\n]"
                }
            }
            
            # Обрабатываем каждый блок
            for block in obligation_blocks:
                try:
                    # Извлекаем кредитора
                    creditor_match = re.search(patterns["creditor"], block)
                    creditor = creditor_match.group(1).strip() if creditor_match else "Неизвестно"
                    
                    # Извлекаем данные в зависимости от языка
                    lang_patterns = patterns.get(language, {})
                    
                    # Извлекаем ежемесячный платеж
                    payment_match = None
                    for pattern in lang_patterns.get("payment", []):
                        match = re.search(pattern, block)
                        if match:
                            payment_match = match
                            break
                    
                    # Извлекаем баланс/задолженность
                    balance_match = None
                    for pattern in lang_patterns.get("balance", []):
                        match = re.search(pattern, block)
                        if match:
                            balance_match = match
                            break
                    
                    # Извлекаем дни просрочки
                    overdue_days_match = re.search(lang_patterns.get("overdue_days", ""), block)
                    
                    # Извлекаем статус
                    status_match = re.search(lang_patterns.get("status", ""), block)
                    
                    # Обрабатываем извлеченные данные
                    monthly_payment = clean_number(payment_match.group(1)) if payment_match else 0.0
                    balance = clean_number(balance_match.group(1)) if balance_match else 0.0
                    overdue_days = int(overdue_days_match.group(1)) if overdue_days_match else 0
                    status = status_match.group(1).strip() if status_match else "Неизвестно"
                    
                    # Используем просроченную сумму как баланс, если основной баланс нулевой
                    if balance == 0.0:
                        # Ищем просроченную сумму
                        overdue_amount_pattern = r"Мерзімі өткен жарналар сомасы\s*/валюта:\s*([\d\s.,]+)\s*KZT" if language == "kazakh" else r"Сумма просроченных взносов /валюта:\s*([\d\s.,]+)\s*KZT"
                        overdue_match = re.search(overdue_amount_pattern, block)
                        if overdue_match:
                            balance = clean_number(overdue_match.group(1))
                    
                    # Оцениваем ежемесячный платеж, если он не указан
                    if monthly_payment == 0.0 and balance > 0:
                        monthly_payment = round(balance * 0.05, 2)  # 5% от баланса
                    
                    # Создаем объект обязательства
                    if balance > 0 or overdue_days > 0:
                        obligation = {
                            "creditor": creditor,
                            "monthly_payment": monthly_payment,
                            "balance": round(balance, 2),
                            "overdue_days": overdue_days,
                            "overdue_status": status
                        }
                        
                        obligations.append(obligation)
                        
                        # Обновляем итоговые данные
                        total_monthly_payment += monthly_payment
                        if overdue_days > 0:
                            total_overdue_creditors += 1
                        
                        logger.info(f"Извлечено обязательство: {creditor}, баланс: {balance}, просрочка: {overdue_days} дней")
                
                except Exception as e:
                    logger.error(f"Ошибка при обработке блока: {e}")
        
        # Если не нашли обязательства или общую сумму долга, используем альтернативный метод
        if not obligations and total_debt == 0.0:
            # Пробуем найти просроченные платежи
            overdue_pattern = r"Мерзімі өткен жарналар сомасы\s*/валюта:\s*([\d\s.,]+)\s*KZT|Сумма просроченных взносов /валюта:\s*([\d\s.,]+)\s*KZT"
            matches = re.finditer(overdue_pattern, text)
            
            for match in matches:
                overdue_str = match.group(1) or match.group(2)
                if overdue_str:
                    try:
                        overdue_amount = clean_number(overdue_str)
                        if overdue_amount > 0:
                            total_debt += overdue_amount
                            logger.info(f"Найдена просроченная сумма: {overdue_amount} KZT")
                    except (ValueError, TypeError):
                        continue
        
        # Если общая сумма долга не найдена, суммируем из обязательств
        if total_debt == 0.0 and obligations:
            total_debt = sum(o["balance"] for o in obligations)
        
        # Возвращаем результат
        return {
            "total_debt": round(total_debt, 2),
            "total_monthly_payment": round(total_monthly_payment, 2),
            "total_obligations": len(obligations),
            "overdue_obligations": total_overdue_creditors,
            "obligations": obligations,
            "language": language
        }
    
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

# Обновленная функция форматирования результатов с учетом языка
def format_summary(data: Dict) -> str:
    """Форматирует данные в читаемый вид"""
    
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
    
    return (
        f"{h['report_header']}\n"
        f"{h['total_creditors']} {data['total_obligations']}\n"
        f"{h['overdue_obligations']} {data['overdue_obligations']}\n"
        f"{h['total_debt']} {data['total_debt']:,.2f} ₸\n"
        f"{h['monthly_payment']} {data['total_monthly_payment']:,.2f} ₸"
        f"{creditors_info}"
        f"{quality_note}"
    )

# Пример использования MongoDB парсера
def process_credit_report_from_mongodb(report_id):
    """Обрабатывает кредитный отчет из MongoDB и возвращает форматированный результат"""
    result = extract_credit_data(report_id, is_mongodb_id=True)
    return format_summary(result)