import re
from typing import Dict, List

def parse_credit_report(text: str) -> Dict:
    """Пытается разобрать кредитный отчет без OpenAI — с помощью регулярных выражений"""

    def extract_personal_info(text: str) -> Dict:
        """Извлекает ИИН, ФИО и др. данные клиента"""
        full_name = ""
        iin = ""
        birth_date = ""

        # Ищем казахские и русские поля
        last_name_match = re.search(r"(Тегі|Фамилия):\s*(\S+)", text)
        first_name_match = re.search(r"(Аты|Имя):\s*(\S+)", text)
        middle_name_match = re.search(r"(Әкесінің аты|Отчество):\s*(\S+)", text)
        iin_match = re.search(r"(ЖСН|ИИН):\s*(\d{12})", text)
        birth_date_match = re.search(r"(Туған күні|Дата рождения):\s*([\d.]+)", text)

        # Формируем полное имя
        if last_name_match and first_name_match:
            full_name = f"{last_name_match.group(2)} {first_name_match.group(2)}"
            if middle_name_match:
                full_name += f" {middle_name_match.group(2)}"

        if iin_match:
            iin = iin_match.group(2)

        if birth_date_match:
            birth_date = birth_date_match.group(2)

        return {
            "full_name": full_name.strip(),
            "iin": iin.strip(),
            "birth_date": birth_date.strip()
        }

    def split_obligations(text: str) -> List[str]:
        """Разделяет текст на блоки по каждому обязательству"""
        return re.split(r"(?:Міндеттеме|Обязательство)\s+\d+", text, flags=re.IGNORECASE)[1:]  # убираем первый заголовок

    def parse_obligation_block(block: str) -> Dict:
        """Парсит один блок с обязательством"""
        creditor_match = re.search(r"Кредитор:\s*\"?(.+?)\"?\n", block)
        balance_match = re.search(r"(Шарт бойынша берешек|Остаток задолженности)[^\d]*(\d[\d.,]*)", block)
        monthly_payment_match = re.search(r"(Ай сайынғы төлем|Сумма ежемесячного платежа)[^\d]*(\d[\d.,]*)", block)
        overdue_days_match = re.search(r"(Мерзімі өткен күндер саны|Количество дней просрочки)[^\d]*(\d+)", block)

        return {
            "creditor": creditor_match.group(1).strip() if creditor_match else "Неизвестно",
            "balance": float(balance_match.group(2).replace(',', '').replace(' ', '')) if balance_match else 0.0,
            "monthly_payment": float(monthly_payment_match.group(2).replace(',', '').replace(' ', '')) if monthly_payment_match else 0.0,
            "overdue_days": int(overdue_days_match.group(2)) if overdue_days_match else 0
        }

    # Определяем язык отчета
    is_kazakh = "Жеке кредиттік есеп" in text or "ҚОЛДАНЫСТАҒЫ ШАРТТАР" in text
    language = "kazakh" if is_kazakh else "russian"

    # 1. Личные данные
    personal_info = extract_personal_info(text)

    # 2. Все блоки обязательств
    obligation_blocks = split_obligations(text)

    obligations = []
    total_debt = 0.0
    total_monthly_payment = 0.0
    overdue_obligations = 0

    for block in obligation_blocks:
        parsed = parse_obligation_block(block)
        obligations.append(parsed)
        total_debt += parsed["balance"]
        total_monthly_payment += parsed["monthly_payment"]
        if parsed["overdue_days"] > 0:
            overdue_obligations += 1

    return {
        "personal_info": personal_info,
        "total_debt": round(total_debt, 2),
        "total_monthly_payment": round(total_monthly_payment, 2),
        "total_obligations": len(obligations),
        "overdue_obligations": overdue_obligations,
        "obligations": obligations,
        "language": language
    }
