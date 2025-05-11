import re
from typing import Dict, List

def extract_credit_data_with_total(text: str) -> Dict:
    obligations = []
    total_monthly_payment = 0.0
    total_overdue_creditors = 0

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
        overdue_match = re.search(
            r"(?:Шарттың мәртебесі|Статус договора):\s*(.+)", block
        )
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
            continue  # исключаем обязательства с нулевым балансом

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
