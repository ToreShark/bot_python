import re
import logging
import os
from typing import Dict, List, Optional

from collateral_parser import extract_collateral_info


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

def clean_number(value: str) -> float:
    """Преобразует строковое представление числа в float"""
    if not value:
        return 0.0
    # Убираем все нечисловые символы кроме точки и запятой
    cleaned = re.sub(r'[^\d.,]', '', str(value))
    # Заменяем запятую на точку для дробной части
    cleaned = cleaned.replace(',', '.')
    # Убираем лишние точки (оставляем только последнюю как разделитель дробной части)
    if '.' in cleaned:
        parts = cleaned.split('.')
        if len(parts) > 2:
            # Если точек больше одной, считаем последнюю разделителем дробной части
            cleaned = ''.join(parts[:-1]) + '.' + parts[-1]
    
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        logger.warning(f"Не удалось преобразовать '{value}' в число")
        return 0.0

class FinalPKBParser:
    """Исправленный парсер для отчетов ПКБ с точным расчетом задолженности"""
    
    def __init__(self):
        self.logger = logger
    
    def extract_personal_info(self, text: str) -> Dict:
        """Извлекает персональную информацию из отчета ПКБ"""
        personal_info = {}
        
        # Извлечение ФИО и даты рождения из заголовка
        header_match = re.search(
            r'(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2})\s*\n([А-ЯЁІӘӨҰҚҢҮҺ\s]+)\s*\((\d{2}\.\d{2}\.\d{4}) г\.р\.\)',
            text
        )
        
        if header_match:
            full_name_raw = header_match.group(2).strip()
            birth_date = header_match.group(3).strip()
            
            personal_info["full_name"] = full_name_raw
            personal_info["birth_date"] = birth_date
        
        # ИИН
        iin_match = re.search(r'ИИН:\s*(\d{12})', text)
        if iin_match:
            personal_info["iin"] = iin_match.group(1)
        
        # Адрес
        address_match = re.search(r'МЕСТО ЖИТЕЛЬСТВА:\s*([^\n]+)', text)
        if address_match:
            personal_info["address"] = address_match.group(1).strip()
        
        # Номер документа
        doc_match = re.search(r'НОМЕР ДОКУМЕНТА:\s*(\d+)', text)
        if doc_match:
            personal_info["document_number"] = doc_match.group(1)
        
        return personal_info
    
    def extract_contract_summary(self, text: str) -> Dict:
        """Извлекает сводную информацию о договорах"""
        summary = {
            "active_without_overdue": 0,
            "active_with_overdue": 0,
            "completed_without_overdue": 0,
            "completed_with_overdue": 0,
            "total_active": 0
        }
        
        # Паттерны для поиска чисел перед ключевыми фразами
        patterns = [
            (r"(\d+)\s+Действующие договоры без просрочки", "active_without_overdue"),
            (r"(\d+)\s+Действующие договоры с просрочкой", "active_with_overdue"),
            (r"(\d+)\s+Завершенные договоры без просрочки", "completed_without_overdue"),
            (r"(\d+)\s+Завершенные договоры с просрочкой", "completed_with_overdue")
        ]
        
        for pattern, key in patterns:
            match = re.search(pattern, text)
            if match:
                summary[key] = int(match.group(1))
                self.logger.info(f"Найдено {key}: {summary[key]}")
        
        # Вычисляем общее количество активных договоров
        summary["total_active"] = summary["active_without_overdue"] + summary["active_with_overdue"]
        
        return summary
    
    def extract_total_amounts(self, text: str) -> Dict:
        """ИСПРАВЛЕННЫЙ: Извлекает общие суммы ТОЛЬКО из итоговой строки таблицы АКТИВНЫХ договоров"""
        totals = {
            "total_contract_amount": 0.0,
            "total_periodic_payment": 0.0,
            "total_unpaid_amount": 0.0,
            "total_overdue_amount": 0.0,
            "total_penalties": 0.0
        }
        
        # Ищем таблицу активных договоров и строку "Итого:" в ней
        active_section = re.search(
            r'ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ КРЕДИТНЫМ ДОГОВОРАМ.*?Итого:\s*\n(.*?)(?=ИНФОРМАЦИЯ|$)',
            text, 
            re.DOTALL
        )
        
        if not active_section:
            # Альтернативный поиск
            active_section = re.search(r"Итого:\s*(.+?)(?:\n|\r\n|$)", text)
        
        if active_section:
            itogo_line = active_section.group(1)
            self.logger.info(f"Найдена строка Итого для АКТИВНЫХ договоров: {itogo_line}")
            
            # Извлекаем все суммы в KZT из строки
            amounts = re.findall(r"([\d\s.,]+)\s*KZT", itogo_line)
            self.logger.info(f"Найденные суммы в итоговой строке: {amounts}")
            
            if len(amounts) >= 6:  # В отчете 6 сумм в итоговой строке
                totals["total_contract_amount"] = clean_number(amounts[0])
                totals["total_periodic_payment"] = clean_number(amounts[1])
                totals["total_unpaid_amount"] = clean_number(amounts[2])
                totals["total_overdue_amount"] = clean_number(amounts[3])  # ЭТО ОСНОВНАЯ ЗАДОЛЖЕННОСТЬ
                # amounts[4] - это штрафы
                totals["total_penalties"] = clean_number(amounts[5])  # Пени
                
                self.logger.info(f"Извлеченные итоговые суммы для АКТИВНЫХ договоров: {totals}")
        
        return totals
    
    def extract_creditors_from_table(self, text: str) -> List[Dict]:
        """РАБОЧИЙ МЕТОД: Извлекает информацию о кредиторах из отчета, работает с многострочными данными"""
        
        def clean_number_local(value: str) -> float:
            if not value:
                return 0.0
            # Убираем даты из строки
            value = re.sub(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", "", str(value))
            cleaned = re.sub(r"[^\d.,]", "", value)
            cleaned = cleaned.replace(",", ".")
            if '.' in cleaned:
                parts = cleaned.split('.')
                if len(parts) > 2:
                    cleaned = ''.join(parts[:-1]) + '.' + parts[-1]
            try:
                return float(cleaned)
            except ValueError:
                return 0.0

        def split_by_creditor_markers(text: str) -> List[str]:
            # Разбиваем по началу договоров
            parts = re.split(r"(?=(?:Займ|Кредит)\s+[^\n]+)", text)
            return [p.strip() for p in parts if p.strip()]

        def parse_creditor_block(block: str) -> Optional[Dict]:
            try:
                # Убираем даты из блока
                block = re.sub(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", "", block)
                
                # ИСПРАВЛЕНО: Улучшенный поиск названия кредитора
                creditor_match = None
                
                # Паттерн 1: Кредитная карта/Займ + название + Заёмщик
                patterns = [
                    r'(?:Кредитная карта|Займ|Кредит)\s+(.*?)\s+Заёмщик',  # Основной паттерн включая "Кредитная карта"
                    r'\b(АО|ТОО)\s+["""«][^"""«»]+["""»]',                    # АО/ТОО с кавычками
                    r'\b(АО|ТОО)\s+"[^"]+?"',                                # АО/ТОО с обычными кавычками
                    r'\b(АО|ТОО)\s+[^\n\r\t]+?(?=\s+Заёмщик)',              # АО/ТОО до слова Заёмщик
                ]
                
                for pattern in patterns:
                    creditor_match = re.search(pattern, block, re.DOTALL)
                    if creditor_match:
                        if len(creditor_match.groups()) > 0:
                            creditor = creditor_match.group(1).strip()
                        else:
                            creditor = creditor_match.group(0).strip()
                        break
                        
                if not creditor_match:
                    creditor = "Неизвестный"
                # Убираем переносы строк и лишние пробелы
                creditor = re.sub(r'\s+', ' ', creditor).strip()
                
                # Извлекаем все суммы KZT
                kzt_values = re.findall(r"([\d\s.,]+)\s*KZT", block)
                amounts = [clean_number_local(val) for val in kzt_values]
                
                if len(amounts) < 4:
                    self.logger.warning(f"Недостаточно сумм для кредитора {creditor}: {amounts}")
                    return None
                
                contract_amount = amounts[0]
                periodic_payment = amounts[1]
                unpaid_amount = amounts[2]
                overdue_amount = amounts[3]
                balance = max(unpaid_amount, overdue_amount)
                
                # ИСПРАВЛЕНО: Правильный поиск дней просрочки с учетом пробелов
                overdue_days = 0
                
                # Метод 1: Ищем в детальной секции "Количество дней просрочки: XXX"
                detailed_days_match = re.search(r'Количество дней просрочки:\s*(\d+)', block)
                if detailed_days_match:
                    overdue_days = int(detailed_days_match.group(1))
                    self.logger.info(f"Найдены дни просрочки (детальная секция): {overdue_days}")
                else:
                    # Метод 2: Ищем паттерн "число пробел число" для дней типа "1 156"
                    # Структура: ... KZT [дни_часть1] [дни_часть2] [штрафы/статус]
                    spaced_days_match = re.search(r'KZT\s+(\d{1,2})\s+(\d{2,3})\s+(?:0\s*KZT|-)', block)
                    if spaced_days_match:
                        part1 = spaced_days_match.group(1)
                        part2 = spaced_days_match.group(2)
                        # Объединяем: "1" + "156" = "1156"
                        if len(part1) <= 2 and len(part2) == 3:
                            overdue_days = int(part1 + part2)
                            self.logger.info(f"Найдены дни просрочки (с пробелом): {part1} {part2} = {overdue_days}")
                    
                    # Метод 3: Ищем одно число после KZT (без пробелов)
                    if overdue_days == 0:
                        single_days_match = re.search(r'KZT\s+(\d{3,4})\s+(?:0\s*KZT|-)', block)
                        if single_days_match:
                            candidate_days = int(single_days_match.group(1))
                            if 30 <= candidate_days <= 3000:
                                overdue_days = candidate_days
                                self.logger.info(f"Найдены дни просрочки (одно число): {overdue_days}")
                    
                    # Метод 4: Поиск всех чисел в строке и фильтрация
                    if overdue_days == 0:
                        # Ищем все числа, исключая суммы KZT
                        text_without_kzt = re.sub(r'[\d\s.,]+\s*KZT', ' REMOVED_KZT ', block)
                        
                        # Ищем отдельные числа и пары чисел
                        single_numbers = re.findall(r'\b(\d{3,4})\b', text_without_kzt)
                        paired_numbers = re.findall(r'\b(\d{1,2})\s+(\d{2,3})\b', text_without_kzt)
                        
                        # Проверяем пары чисел (приоритет)
                        for pair in paired_numbers:
                            combined = int(pair[0] + pair[1])
                            if 100 <= combined <= 3000:  # Реалистичный диапазон для дней просрочки
                                overdue_days = combined
                                self.logger.info(f"Найдены дни просрочки (пара без KZT): {pair[0]} {pair[1]} = {overdue_days}")
                                break
                        
                        # Если не нашли в парах, проверяем одиночные числа
                        if overdue_days == 0:
                            for num_str in single_numbers:
                                num = int(num_str)
                                if 100 <= num <= 3000:
                                    overdue_days = num
                                    self.logger.info(f"Найдены дни просрочки (одиночное без KZT): {overdue_days}")
                                    break
                
                # Ищем информацию о последнем платеже
                last_payment_amount = 0.0
                last_payment_date = ""
                
                # Поиск суммы последнего платежа
                payment_amount_match = re.search(r'Сумма последнего платежа:\s*([\d.,]+)\s*KZT', block)
                if payment_amount_match:
                    last_payment_amount = clean_number_local(payment_amount_match.group(1))
                
                # Поиск даты последнего платежа  
                payment_date_match = re.search(r'Дата последнего платежа:\s*(\d{2}\.\d{2}\.\d{4})', block)
                if payment_date_match:
                    last_payment_date = payment_date_match.group(1)
                
                self.logger.info(f"Найден кредитор: '{creditor}', долг: {balance}, дни: {overdue_days}")
                self.logger.info(f"Последний платеж: {last_payment_amount} ₸ от {last_payment_date}")
                self.logger.info(f"Исходный блок (первые 200 символов): {block[:200]}...")
                
                return {
                    "creditor": creditor,
                    "periodic_payment": round(periodic_payment, 2),
                    "total_debt": round(balance, 2),
                    "overdue_amount": round(overdue_amount, 2),
                    "overdue_days": overdue_days,
                    "overdue_status": "просрочка" if overdue_days > 0 else "нет просрочки",
                    "last_payment_amount": round(last_payment_amount, 2),
                    "last_payment_date": last_payment_date
                }

            except Exception as e:
                self.logger.error(f"Ошибка парсинга блока кредитора: {e}")
                return None

        # Находим секцию активных договоров
        active_section_match = re.search(
            r'ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ КРЕДИТНЫМ ДОГОВОРАМ(.*?)(?=ИНФОРМАЦИЯ ИЗ ДОПОЛНИТЕЛЬНЫХ|ЗАВЕРШЕННЫЕ ДОГОВОРЫ|$)',
            text,
            re.DOTALL
        )
        
        if not active_section_match:
            self.logger.warning("Не найдена секция с активными договорами")
            return []
        
        active_text = active_section_match.group(1)
        self.logger.info("Работаем только с секцией активных договоров")
        
        # Разбиваем на блоки и парсим
        blocks = split_by_creditor_markers(active_text)
        obligations = []
        
        for block in blocks:
            parsed = parse_creditor_block(block)
            if parsed:
                obligations.append(parsed)

        self.logger.info(f"Найдено {len(obligations)} кредиторов")
        return obligations
        """ИСПРАВЛЕННЫЙ: Извлекает информацию ТОЛЬКО из таблицы действующих договоров"""
        
        # Находим секцию только с активными договорами
        active_section_match = re.search(
            r'ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ КРЕДИТНЫМ ДОГОВОРАМ(.*?)(?=ИНФОРМАЦИЯ ИЗ ДОПОЛНИТЕЛЬНЫХ|ЗАВЕРШЕННЫЕ ДОГОВОРЫ|$)',
            text,
            re.DOTALL
        )
        
        if not active_section_match:
            self.logger.warning("Не найдена секция с активными договорами")
            return []
        
        active_text = active_section_match.group(1)
        self.logger.info("Работаем только с секцией активных договоров")
        
        def parse_active_row(row: str) -> Optional[Dict]:
            """Парсит строку из таблицы активных договоров"""
            if not row.strip() or "Вид финансирования" in row or "Итого:" in row:
                return None
            
            # Извлекаем название кредитора
            creditor_patterns = [
                r'ТОО\s*["""«][^"""«»]+["""»]',
                r'АО\s*["""«][^"""«»]+["""»]',
                r'(ТОО|АО)\s+[^\n\t]+?(?=\s+Заёмщик|\s+\d)',
            ]
            
            creditor_name = "Неизвестный"
            for pattern in creditor_patterns:
                match = re.search(pattern, row)
                if match:
                    creditor_name = match.group(0).strip()
                    break
            
            # Извлекаем все суммы KZT из строки, исключая даты
            amounts = []
            kzt_matches = re.findall(r'([\d\s.,]+)\s*KZT', row)
            
            for amount_str in kzt_matches:
                # Проверяем, не является ли это датой (формат dd.mm)  
                if not re.match(r'^\d{1,2}\.\d{1,2}$', amount_str.strip()):
                    amount_val = clean_number(amount_str)
                    if amount_val >= 0:  # Принимаем все значения, включая 0
                        amounts.append(amount_val)
            
            # Извлекаем дни просрочки
            days_match = re.search(r'(\d{3,4})', row)
            overdue_days = int(days_match.group(1)) if days_match else 0
            
            if len(amounts) >= 4:
                return {
                    "creditor": creditor_name,
                    "contract_amount": amounts[0],           # Сумма по договору
                    "periodic_payment": amounts[1],          # Периодический платеж
                    "unpaid_amount": amounts[2],             # Непогашенная сумма
                    "overdue_amount": amounts[3],            # Сумма просрочки
                    "penalties": amounts[-1] if len(amounts) > 4 else 0.0,  # Пени
                    "overdue_days": overdue_days,
                    "total_debt": max(amounts[2], amounts[3])  # Максимум из непогашенной и просрочки
                }
            
            return None
        
        # Разбиваем текст на строки и парсим каждую
        lines = active_text.split('\n')
        creditors = []
        
        for line in lines:
            if 'Займ' in line or 'Кредит' in line:  # Строки с договорами
                parsed = parse_active_row(line)
                if parsed:
                    creditors.append(parsed)
                    self.logger.info(f"Найден активный договор: {parsed['creditor']} - {parsed['total_debt']} ₸")
        
        return creditors
    
    # def group_creditors(self, creditors: List[Dict]) -> Dict[str, List[Dict]]:
    #     """Группирует кредиторов по названию с улучшенной нормализацией"""
    #     groups = {}
    #     for creditor in creditors:
    #         name = creditor["creditor"]
            
    #         # УЛУЧШЕННАЯ НОРМАЛИЗАЦИЯ:
    #         # 1. Приводим к нижнему регистру для сравнения
    #         normalized_lower = name.lower()
            
    #         # 2. Заменяем разные типы кавычек на стандартные
    #         normalized_lower = re.sub(r'["""«»„"'']', '"', normalized_lower)
            
    #         # 3. Убираем лишние пробелы
    #         normalized_lower = re.sub(r'\s+', ' ', normalized_lower).strip()
            
    #         # 4. КЛЮЧЕВОЕ: Нормализуем ТОО/АО - убираем организационно-правовую форму для группировки
    #         # Убираем "тоо", "ао", "оао", "зао" в начале
    #         normalized_lower = re.sub(r'^\s*(тоо|ао|оао|зао|ооо)\s*', '', normalized_lower)
            
    #         # 5. Убираем кавычки для группировки (но сохраняем оригинальное имя для отображения)
    #         normalized_lower = normalized_lower.replace('"', '').strip()
            
    #         # Используем нормализованное имя как ключ для группировки
    #         group_key = normalized_lower
            
    #         if group_key not in groups:
    #             groups[group_key] = {
    #                 "display_name": name,  # Сохраняем ПЕРВОЕ найденное имя для отображения
    #                 "contracts": []
    #             }
    #         else:
    #             # Если уже есть группа, выбираем наиболее полное название для отображения
    #             existing_name = groups[group_key]["display_name"]
    #             if len(name) > len(existing_name):  # Более длинное имя обычно более полное
    #                 groups[group_key]["display_name"] = name
                    
    #         groups[group_key]["contracts"].append(creditor)
            
    #         self.logger.info(f"Группировка: '{name}' -> ключ: '{group_key}' -> отображение: '{groups[group_key]['display_name']}'")
        
    #     # Преобразуем в старый формат для совместимости
    #     result = {}
    #     for group_key, group_data in groups.items():
    #         result[group_data["display_name"]] = group_data["contracts"]
        
    #     return result
    
    def group_creditors(self, creditors: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Группирует кредиторов по названию с улучшенной нормализацией:
        - Удаляет лишние кавычки, формы типа "ТОО", "АО"
        - Приводит к нижнему регистру для ключа группировки
        - Сохраняет наиболее полное название для отображения
        """
        def improved_normalize_creditor_name(name: str) -> str:
            # Приведение всех кавычек к обычным
            name = re.sub(r'[«»„“”]', '"', name)
            while '""' in name:
                name = name.replace('""', '"')
            name = re.sub(r'\bс правом обратного выкупа\b', '', name, flags=re.IGNORECASE)
            name = re.sub(r'^\s*(тоо|ао|оао|зао|ооо)\s*', '', name, flags=re.IGNORECASE)
            name = name.strip('" ').strip()
            name = re.sub(r'[\)"]+$', '', name).strip()
            return name

        groups = {}
        
        for creditor in creditors:
            name = creditor["creditor"]
            
            # 🧠 Ключ: нормализуем имя (без регистра), чтобы сгруппировать похожие
            normalized_key = improved_normalize_creditor_name(name).lower()
            display_name = self._normalize_creditor_display(name)

            # print(f"\n📌 СЫРОЙ кредитор: {name}")
            # print(f"🔑 Ключ группировки: {normalized_key}")
            # print(f"🪪 Отображаемое имя: {display_name}")
            
            if normalized_key not in groups:
                groups[normalized_key] = {
                    "display_name": display_name,  # уже нормализован
                    "contracts": []
                }
            else:
                existing_display = groups[normalized_key]["display_name"]
                # сравниваем по длине нормализованных, но сохраняем нормализованное
                if len(display_name) > len(existing_display):
                    groups[normalized_key]["display_name"] = display_name

            
            groups[normalized_key]["contracts"].append(creditor)
        
        # 🎯 Возвращаем в нужной форме: {отображаемое имя: [контракты]}
        result = {}
        for group_data in groups.values():
            result[group_data["display_name"]] = group_data["contracts"]
        
        return result

    def _normalize_creditor_display(self, name: str) -> str:
        """Нормализует имя кредитора для вывода пользователю"""
        name = re.sub(r'[«»„“”]', '"', name)
        name = name.replace('""', '"')
        name = re.sub(r'\bс правом обратного выкупа\b', '', name, flags=re.IGNORECASE)
        name = name.strip(' "\')')
        return name.strip()

    def parse(self, text: str) -> Dict:
        """ИСПРАВЛЕННЫЙ: Основной метод парсинга отчета ПКБ"""
        try:
            # Извлекаем персональную информацию
            personal_info = self.extract_personal_info(text)
            
            # Извлекаем сводную информацию о договорах
            contract_summary = self.extract_contract_summary(text)
            
            # ИСПРАВЛЕНИЕ: Берем данные ТОЛЬКО из строки "Итого:" для активных договоров
            totals = self.extract_total_amounts(text)
            
            # ИСПРАВЛЕНИЕ: Используем рабочий метод извлечения кредиторов
            creditors = self.extract_creditors_from_table(text)
            
            # Группируем кредиторов
            creditor_groups = self.group_creditors(creditors)
            
            # ИСПРАВЛЕНИЕ: Используем ТОЛЬКО данные из строки "Итого:"
            total_debt = totals["total_overdue_amount"]  # Берем сумму просрочки из итогов
            total_monthly_payment = totals["total_periodic_payment"]  # Берем ежемесячный платеж из итогов
            
            # ИСПРАВЛЕНИЕ: НЕ СУММИРУЕМ по кредиторам, используем только официальные итоги
            self.logger.info(f"Используем официальные итоги: долг = {total_debt}, платеж = {total_monthly_payment}")
            
            # ИСПРАВЛЕНО: Берем количество просроченных из официальной сводки, а не парсим строки
            total_obligations = contract_summary["total_active"]
            overdue_obligations = contract_summary["active_with_overdue"]  # Используем готовые данные из отчета!
            
            # Дополнительная проверка: если в сводке нет данных, считаем по суммам
            if overdue_obligations == 0 and total_debt > 0:
                # Если есть сумма просрочки, значит есть просроченные обязательства
                overdue_obligations = len([c for c in creditors if c.get("overdue_amount", 0) > 0])
            
            self.logger.info(f"Статистика: всего активных = {total_obligations}, просроченных = {overdue_obligations}")
            
            # Конвертируем кредиторов в стандартный формат для системы
            obligations = []
            for group_name, group_creditors in creditor_groups.items():
                # Суммируем данные по группе
                total_group_debt = sum(c["total_debt"] for c in group_creditors)
                total_group_payment = sum(c["periodic_payment"] for c in group_creditors)
                total_group_overdue = sum(c["overdue_amount"] for c in group_creditors)
                max_overdue_days = max(c["overdue_days"] for c in group_creditors)
                
                # Находим информацию о последнем платеже в группе
                last_payment_amount = 0.0
                last_payment_date = ""
                
                # Ищем самую свежую дату платежа в группе
                latest_date = ""
                for c in group_creditors:
                    if c.get("last_payment_date", "") and c["last_payment_date"] > latest_date:
                        latest_date = c["last_payment_date"]
                        last_payment_amount = c.get("last_payment_amount", 0.0)
                        last_payment_date = c["last_payment_date"]
                # 🛠️ Очищаем имя кредитора даже для отображения
                # normalized_display_name = self._normalize_creditor_display(group_name)
                normalized_display_name = group_name
                obligations.append({
                    "creditor": normalized_display_name,
                    "balance": round(total_group_debt, 2),
                    "monthly_payment": round(total_group_payment, 2),
                    "overdue_amount": round(total_group_overdue, 2),
                    "overdue_days": max_overdue_days,
                    "overdue_status": "просрочка" if max_overdue_days > 0 else "нет просрочки",
                    "contracts_count": len(group_creditors),
                    "last_payment_amount": round(last_payment_amount, 2),
                    "last_payment_date": last_payment_date
                })
            
            result = {
                "personal_info": personal_info,
                "total_debt": round(total_debt, 2),  # ИСПРАВЛЕНО: только из официальных итогов
                "total_monthly_payment": round(total_monthly_payment, 2),  # ИСПРАВЛЕНО: только из официальных итогов
                "total_obligations": total_obligations,
                "overdue_obligations": overdue_obligations,
                "obligations": obligations,
                "contract_summary": contract_summary,
                "totals": totals,
                "creditor_groups": creditor_groups
            }
            
            self.logger.info(f"ИСПРАВЛЕННЫЙ парсинг: Общий долг = {total_debt} ₸, найдено {len(obligations)} групп кредиторов")
            # Извлекаем залоги
            collaterals = extract_collateral_info(text)
            result["collaterals"] = collaterals
            return result
            
        except Exception as e:
            self.logger.error(f"Ошибка при парсинге отчета ПКБ: {e}")
            return {
                "personal_info": {},
                "total_debt": 0.0,
                "total_monthly_payment": 0.0,
                "total_obligations": 0,
                "overdue_obligations": 0,
                "obligations": [],
                "parsing_error": True,
                "error_message": str(e)
            }

def format_pkb_summary(data: Dict) -> str:
    """Форматирует результат парсинга ПКБ для пользователя"""
    
    if data.get("parsing_error", False):
        return (
            "⚠️ Не удалось корректно распознать кредитный отчет ПКБ.\n"
            f"Ошибка: {data.get('error_message', 'Неизвестная ошибка')}"
        )
    
    # Формируем блок с личной информацией
    personal_info = data.get("personal_info", {})
    personal_text = ""
    
    if personal_info:
        personal_text = "👤 Личные данные:\n"
        if personal_info.get("full_name"):
            personal_text += f"— ФИО: {personal_info['full_name']}\n"
        if personal_info.get("iin"):
            personal_text += f"— ИИН: {personal_info['iin']}\n"
        if personal_info.get("birth_date"):
            personal_text += f"— Дата рождения: {personal_info['birth_date']}\n"
        if personal_info.get("address"):
            personal_text += f"— Адрес: {personal_info['address']}\n"
        personal_text += "\n"
    
    # ИСПРАВЛЕНО: Показываем данные из официальных итогов + пени отдельно
    totals = data.get("totals", {})
    total_with_penalties = data['total_debt'] + totals.get('total_penalties', 0)
    
    main_info = (
        f"📊 Итог по вашему кредитному отчёту:\n"
        f"— Всего активных договоров: {data['total_obligations']}\n"
        f"— Просроченных обязательств: {data['overdue_obligations']}\n"
        f"— Общая сумма просрочки: {data['total_debt']:,.2f} ₸\n"
        f"— Штрафы и пени: {totals.get('total_penalties', 0):,.2f} ₸\n"
        f"— ИТОГО К ДОПЛАТЕ: {total_with_penalties:,.2f} ₸\n"
        f"— Ежемесячный платёж: {data['total_monthly_payment']:,.2f} ₸\n"
    )
    
    # Детали по кредиторам
    obligations_text = ""
    obligations = data.get("obligations", [])
    
    if obligations:
        obligations_text = "\n📋 Детали по кредиторам:\n"
        for i, obligation in enumerate(obligations, 1):
            overdue_info = ""
            if obligation.get('overdue_days', 0) > 0:
                overdue_info = f" (просрочка {obligation['overdue_days']} дней)"
            
            contracts_info = ""
            if obligation.get('contracts_count', 0) > 1:
                contracts_info = f" [{obligation['contracts_count']} договоров]"
            
            # Информация о последнем платеже
            last_payment_info = ""
            if obligation.get('last_payment_date') and obligation.get('last_payment_amount', 0) > 0:
                last_payment_info = f"\n   └── Последний платеж: {obligation['last_payment_amount']:,.2f} ₸ от {obligation['last_payment_date']}"
            
            obligations_text += (
                f"{i}. {obligation['creditor']}{contracts_info}: {obligation['balance']:,.2f} ₸{overdue_info}{last_payment_info}\n"
            )
    # Информация о залогах
    collaterals = data.get("collaterals", [])
    if collaterals:
        collateral_text = "\n🏠 Информация по залогам:"
        for c in collaterals:
            creditor = c.get("creditor", "Неизвестно")
            kind = c.get("collateral_type", "Неизвестно")
            value = c.get("market_value", 0.0)
            collateral_text += f"\n— {creditor}: {kind} ({value:,.2f} ₸)"
        obligations_text += "\n" + collateral_text

    return personal_text + main_info + obligations_text

# Функция для интеграции в существующую систему
def create_improved_pkb_parser():
    """Создает исправленный парсер ПКБ для интеграции в систему"""
    return FinalPKBParser()