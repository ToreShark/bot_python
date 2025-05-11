import re
from typing import Dict, List

def detect_report_format(text: str) -> str:
    if "Обязательство" in text or "ҚОЛДАНЫСТАҒЫ ШАРТТАР" in text:
        return "detailed"
    elif "Общая сумма задолженности/валюта" in text:
        return "short"
    return "unknown"

def extract_credit_data_with_total(text: str) -> Dict:
    obligations = []
    total_monthly_payment = 0.0
    total_overdue_creditors = 0
    total_debt = 0.0
    lines = text.splitlines()

    format_type = detect_report_format(text)

    # --- Подробный отчёт (ПКБ) ---
    if format_type == "detailed":
        if "ҚОЛДАНЫСТАҒЫ ШАРТТАР" in text:
            text = text.split("ҚОЛДАНЫСТАҒЫ ШАРТТАР")[1]
        if "АЯҚТАЛҒАН ШАРТТАР" in text:
            text = text.split("АЯҚТАЛҒАН ШАРТТАР")[0]

        blocks = re.split(r"(?:Міндеттеме|Обязательство)\s+\d+", text)
        for block in blocks[1:]:
            creditor_match = re.search(r"Кредитор:\s*(.+)", block)
            payment_match = re.search(
                r"(?:Ай сайынғы төлем сомасы|Сумма ежемесячного платежа).+?([\d\s.,]+)\s*KZT", block
            )
            balance_match = re.search(
                r"(?:Алдағы төлемдер сомасы|Сумма предстоящих платежей).+?([\d\s.,]+)\s*KZT", block
            )
            overdue_match = re.search(r"(?:Шарттың мәртебесі|Статус договора):\s*(.+)", block)
            overdue_days_match = re.search(r"(\d+)\s*(?:күн|дн(?:ей|я))", block)

            creditor = creditor_match.group(1).strip() if creditor_match else "Неизвестно"
            monthly_payment = (
                float(payment_match.group(1).replace(" ", "").replace(",", "."))
                if payment_match else 0.0
            )
            balance = (
                float(balance_match.group(1).replace(" ", "").replace(",", "."))
                if balance_match else 0.0
            )
            overdue_text = overdue_match.group(1).strip() if overdue_match else "нет просрочки"
            overdue_days = int(overdue_days_match.group(1)) if overdue_days_match else 0

            if balance == 0.0:
                continue

            obligations.append({
                "creditor": creditor,
                "monthly_payment": monthly_payment,
                "balance": round(balance, 2),
                "overdue_days": overdue_days,
                "overdue_status": overdue_text
            })

            total_monthly_payment += monthly_payment
            if overdue_days > 0:
                total_overdue_creditors += 1

    # --- Краткий отчёт (ПКБ/ГКБ) ---
    elif format_type == "short":
        for i, line in enumerate(lines):
            if "Общая сумма задолженности/валюта" in line:
                try:
                    total_debt_line = lines[i + 1]
                    total_debt = float(total_debt_line.replace(" ", "").replace(",", ".").replace("KZT", ""))
                except:
                    total_debt = 0.0

            if re.match(r"^[\d\s.,]+ KZT$", line.strip()):
                try:
                    balance = float(line.replace(" ", "").replace(",", ".").replace("KZT", ""))
                    overdue_line = lines[i + 1].strip()
                    if re.match(r"^\d+$", overdue_line):
                        overdue_days = int(overdue_line)
                        creditor = lines[i - 2].strip()
                        contract = lines[i - 1].strip()

                        if len(creditor) < 4 or balance == 0:
                            continue

                        obligations.append({
                            "creditor": creditor,
                            "contract": contract,
                            "balance": round(balance, 2),
                            "monthly_payment": 0.0,
                            "overdue_days": overdue_days,
                            "overdue_status": "нет данных"
                        })

                        if overdue_days > 0:
                            total_overdue_creditors += 1
                except:
                    continue

    # Если detailed-форма, то total_debt считается из суммы балансов
    if format_type == "detailed":
        total_debt = sum(o["balance"] for o in obligations)

    return {
        "total_debt": round(total_debt, 2),
        "total_monthly_payment": round(total_monthly_payment, 2),
        "total_obligations": len(obligations),
        "overdue_obligations": total_overdue_creditors,
        "obligations": obligations
    }

def format_summary(data: Dict) -> str:
    return (
        f"📊 Итог по вашему кредитному отчёту:\n"
        f"— Всего кредиторов: {data['total_obligations']}\n"
        f"— Просроченных обязательств: {data['overdue_obligations']}\n"
        f"— Общая сумма задолженности: {data['total_debt']:,} ₸\n"
        f"— Ежемесячный платёж: {data['total_monthly_payment']:,} ₸"
    )
