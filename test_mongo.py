import re
import json
from pymongo import MongoClient
from bson import ObjectId
import os
from dotenv import load_dotenv

load_dotenv()

def clean_number(s: str) -> float:
    if not s or s in {"Деректер жоқ", "Нет данных", "-"}:
        return 0.0
    return float(re.sub(r"[^\d,\.]", "", s).replace(",", ".").replace(" ", ""))

def extract_active_credits(text: str) -> list:
    active_credits = []

    is_kazakh = "МІНДЕТТЕМЕЛЕР БОЙЫНША ЖАЛПЫ АҚПАРАТ" in text or "ҚОЛДАНЫСТАҒЫ ШАРТТАР" in text
    is_russian = "ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ КРЕДИТНЫМ ДОГОВОРАМ" in text or "ДЕЙСТВУЮЩИЕ ДОГОВОРА" in text

    if is_kazakh:
        blocks = list(re.finditer(r"Міндеттеме\s+\d+", text))
        for i, match in enumerate(blocks):
            start = match.start()
            end = blocks[i + 1].start() if i + 1 < len(blocks) else len(text)
            block = text[start:end]

            creditor_match = re.search(r"Кредитор:\s*(.*?)[\r\n]", block)
            if not creditor_match:
                continue
            creditor = creditor_match.group(1).strip()
            if re.search(r"ломбард", creditor, re.IGNORECASE):
                continue

            overdue_match = re.search(r"Мерзімі өткен жарналар сомасы\s*\/валюта:\s*([\d\s.,]+)\s*KZT", block)
            overdue = clean_number(overdue_match.group(1)) if overdue_match else 0

            balance_match = re.search(r"(?:Шарт бойынша берешек қалдығы|Алдағы төлемдер сомасы)(?:\/валюта)?[:]\s*([\d\s.,]+)\s*KZT", block)
            balance = clean_number(balance_match.group(1)) if balance_match else overdue

            days_match = re.search(r"Мерзімі өткен күндер саны:\s*(\d+)", block)
            overdue_days = int(days_match.group(1)) if days_match else 0

            monthly_match = re.search(r"Ай сайынғы төлем сомасы\s*\/\s*валюта:\s*([\d\s.,]+)\s*KZT", block)
            monthly = clean_number(monthly_match.group(1)) if monthly_match else 0

            status_match = re.search(r"Шарттың мәртебесі:\s*(.*?)[\r\n]", block)
            status = status_match.group(1).strip() if status_match else ""

            number_match = re.search(r"(?:Шарт нөмірі|Келісімшарт коды):\s*(.*?)[\r\n]", block)
            contract_number = number_match.group(1).strip() if number_match else ""

            dates = re.findall(r"\d{2}\.\d{2}\.\d{4}", block)[:3]

            financing_match = re.search(r"Қаржыландыру түрі:\s*(.*?)[\r\n]", block)
            financing_type = financing_match.group(1).strip() if financing_match else ""

            collateral_match = re.search(r"(Кепіл(?:дік)?(?: мүлкі)?(?: түрі)?:\s*)([^\n\r]+)", block, re.IGNORECASE)
            collateral_description = collateral_match.group(2).strip() if collateral_match else None
            if collateral_description:
                if re.search(r"(пәтер|үй|жылжымайтын мүлік)", collateral_description, re.IGNORECASE):
                    collateral_type = "недвижимое"
                elif re.search(r"(көлік|техника|мотоцикл)", collateral_description, re.IGNORECASE):
                    collateral_type = "движимое"
                else:
                    collateral_type = "неизвестно"
            else:
                collateral_type = None

            if any([balance, overdue, overdue_days, monthly]):
                active_credits.append({
                    "creditor": creditor,
                    "total_debt": balance if balance else overdue,
                    "overdue_amount": overdue,
                    "overdue_days": overdue_days,
                    "periodic_payment": monthly if monthly else (balance * 0.05),
                    "contract_number": contract_number,
                    "status": status,
                    "dates": dates,
                    "financing_type": financing_type,
                    "collateral_type": collateral_type,
                    "collateral_description": collateral_description,
                    "is_active": True
                })

    if is_russian:
        match = re.search(r"ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ КРЕДИТНЫМ ДОГОВОРАМ[\s\S]+?Итого:", text)
        if match:
            table_text = match.group()
            lines = table_text.split("\n")[1:-1]
            for line in lines:
                if not line.strip() or "Вид" in line:
                    continue
                parts = re.split(r"\s{2,}", line.strip())
                if len(parts) >= 8:
                    try:
                        financing_type, creditor = parts[0], parts[1]
                        if re.search(r"ломбард", creditor, re.IGNORECASE):
                            continue
                        amounts = [clean_number(a) for a in re.findall(r"(\d[\d\s.,]+)\s*KZT", line)]
                        overdue_days = int(re.findall(r"(\d+)(?:\s*-)?$", line)[0]) if re.findall(r"(\d+)(?:\s*-)?$", line) else 0
                        if len(amounts) >= 4:
                            contract_amount, periodic_payment, balance, overdue_amount = amounts[:4]
                            if any([balance, overdue_amount, overdue_days, periodic_payment]):
                                active_credits.append({
                                    "creditor": creditor,
                                    "financing_type": financing_type,
                                    "total_debt": balance if balance else overdue_amount,
                                    "contract_amount": contract_amount,
                                    "periodic_payment": periodic_payment,
                                    "overdue_amount": overdue_amount,
                                    "overdue_days": overdue_days,
                                    "status": "Просрочка" if overdue_days > 0 else "Стандартный кредит",
                                    "collateral_type": None,
                                    "collateral_description": None,
                                    "is_active": True
                                })
                    except:
                        continue

        contract_block_match = re.search(r"ДЕЙСТВУЮЩИЕ ДОГОВОРА[\s\S]+?(?=ЗАВЕРШЕННЫЕ ДОГОВОРЫ|$)", text, re.IGNORECASE)
        if contract_block_match:
            for contract in re.finditer(r"КОНТРАКТ\s+\d+[\s\S]+?(?=КОНТРАКТ\s+\d+|ЗАВЕРШЕННЫЕ ДОГОВОРЫ|$)", contract_block_match.group(), re.IGNORECASE):
                block = contract.group()
                creditor_match = re.search(r"Источник информации \(Кредитор\):\s*([^\n]+)", block)
                if not creditor_match:
                    continue
                creditor = creditor_match.group(1).strip()
                if re.search(r"ломбард", creditor, re.IGNORECASE):
                    continue

                debt = clean_number(re.search(r"(?:Непогашенная сумма по кредиту|Использованная сумма \(подлежащая погашению\)):\s*([\d\s.,]+)\s*KZT", block).group(1)) if re.search(r"(?:Непогашенная сумма по кредиту|Использованная сумма \(подлежащая погашению\)):\s*([\d\s.,]+)\s*KZT", block) else 0
                overdue = clean_number(re.search(r"Сумма просроченных взносов:\s*([\d\s.,]+)\s*KZT", block).group(1)) if re.search(r"Сумма просроченных взносов:\s*([\d\s.,]+)\s*KZT", block) else 0
                overdue_days = int(re.search(r"Количество дней просрочки:\s*(\d+)", block).group(1)) if re.search(r"Количество дней просрочки:\s*(\d+)", block) else 0
                payment = clean_number(re.search(r"(?:Сумма периодического платежа|Минимальный платеж):\s*([\d\s.,]+)\s*KZT", block).group(1)) if re.search(r"(?:Сумма периодического платежа|Минимальный платеж):\s*([\d\s.,]+)\s*KZT", block) else 0
                status = re.search(r"Статус договора:\s*([^\n]+)", block)
                contract_number = re.search(r"Номер договора:\s*([^\n]+)", block)
                financing_type = re.search(r"Вид финансирования:\s*([^\n]+)", block)

                collateral_match = re.search(r"(?:Залог|Обеспечение|Предмет залога|Тип залога):\s*([^\n\r]+)", block, re.IGNORECASE)
                collateral_description = collateral_match.group(1).strip() if collateral_match else None
                if collateral_description:
                    if re.search(r"(квартира|дом|недвижимость)", collateral_description, re.IGNORECASE):
                        collateral_type = "недвижимое"
                    elif re.search(r"(автомобиль|транспорт|техника|мотоцикл|ТС)", collateral_description, re.IGNORECASE):
                        collateral_type = "движимое"
                    else:
                        collateral_type = "неизвестно"
                else:
                    collateral_type = None

                if any([debt, overdue, overdue_days, payment]):
                    active_credits.append({
                        "creditor": creditor,
                        "total_debt": debt if debt else overdue,
                        "overdue_amount": overdue,
                        "overdue_days": overdue_days,
                        "periodic_payment": payment if payment else ((debt if debt else overdue) * 0.05),
                        "contract_number": contract_number.group(1).strip() if contract_number else "",
                        "status": status.group(1).strip() if status else "",
                        "financing_type": financing_type.group(1).strip() if financing_type else "",
                        "collateral_type": collateral_type,
                        "collateral_description": collateral_description,
                        "is_active": True
                    })

    seen = set()
    unique = []
    for item in active_credits:
        key = f"{item['creditor']}|{item.get('contract_number', '')}"
        if key not in seen:
            seen.add(key)
            unique.append(item)

    final_credits = [c for c in unique if not re.search(r"ломбард", c["creditor"], re.IGNORECASE)]
    final_credits.sort(key=lambda x: -x["total_debt"])
    return final_credits

# Fetch and run
client = MongoClient(os.getenv("MONGO_URI"))
db = client["telegram_bot"]
doc = db.documents.find_one({"_id": ObjectId("682615d5c5422db27300409d")})

if doc and "text" in doc:
    result = extract_active_credits(doc["text"])
    with open("result_combined.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    output_message = f"\u2705 Извлечено {len(result)} активных договоров (казахский + русский). Сохранено в result_combined.json"
else:
    output_message = "\u274c Документ не найден или отсутствует поле 'text'."

print(output_message)