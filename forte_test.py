import re, json, os
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv
load_dotenv()


MONGO_ID = "68285ab16520c18e1a4a7b28"  # ← ваш ID

# ── Нормализация текста для защиты от OCR ошибок ─────────────────────────────
def normalize(text: str) -> str:
    """Заменяет OCR-ошибки и унифицирует кавычки"""
    replacements = {
        "В": "B", "в": "b",  # кириллическая В → латинская B
        "О": "O", "о": "o",  # кириллическая О → латинская O
        "«": "\"", "»": "\"",  # кавычки
    }
    for cyrillic, latin in replacements.items():
        text = text.replace(cyrillic, latin)
    return text


# ── Подключение к MongoDB ────────────────────────────────────────────────────
cli = MongoClient(os.getenv("MONGO_URI"))
doc = cli["telegram_bot"].documents.find_one(
    {"_id": ObjectId(MONGO_ID)}, {"text": 1, "_id": 0})

if not doc or "text" not in doc:
    raise SystemExit("❌ Документ не найден или нет поля text")

txt = normalize(doc["text"])  # нормализуем текст

# ── Поиск блока по регулярке с гибкой проверкой ──────────────────────────────
m = re.search(
    r"(Займ|Кредитная карта|Кредитная линия)[^\n]*?\n\s*АО\s*[\"']?\s*F[oо]rte[BВ]ank\s*[\"']?",
    txt, re.I
)

if not m:
    print("⚠️  ForteBank не найден стандартной регуляркой, пробую вручную…")
    # Альтернативный поиск через разбиение на блоки
    for block in txt.split("Займ"):
        if "RBK" in block:
            print("✅ Найден блок ForteBank вручную!")
            txt = "Займ" + block  # восстанавливаем заголовок блока
            break
    else:
        raise SystemExit("❌ Блок ForteBank не найден — проверь оригинальный текст.")

else:
    # Получаем весь блок, начиная с совпадения
    start = m.start()
    following = txt[start:]
    next_match = re.search(r"\n(Займ|Кредитная карта|Кредитная линия)\b", following[10:])
    end = start + (next_match.start() + 10 if next_match else len(following))
    txt = txt[start:end]  # теперь txt — только блок ForteBank

# ── Парсинг чисел ────────────────────────────────────────────────────────────
def num(s: str) -> float:
    return float(re.sub(r"[^\d,\.]", "", s).replace(",", ".").replace(" ", "")) if s else 0.0

def find(pattern, text, default="0"):
    m = re.search(pattern, text, re.I)
    return m.group(1) if m else default

# ── Извлекаем данные из блока ────────────────────────────────────────────────
# 🔍 Показываем блок ForteBank полностью
print("===== Содержимое блока ForteBank =====")
print(txt)
print("===== Конец блока =====")

# ── Извлекаем данные из блока ────────────────────────────────────────────────
# Ищем все суммы с KZT
# Получаем все строки, где есть "KZT" — даже если на новой строке
lines = txt.splitlines()
amounts = [line.strip() for line in lines if "KZT" in line]


# Ищем отдельно все числа без букв (для дней просрочки)
all_numbers = re.findall(r"\b\d{1,3}\b", txt)  # числа до 3 цифр, чтобы не захватывать даты

# Извлекаем нужные значения
contract_amount = num(amounts[0]) if len(amounts) > 0 else 0.0
balance = num(amounts[1]) if len(amounts) > 1 else 0.0
overdue_amount = num(amounts[2]) if len(amounts) > 2 else 0.0
overdue_days = int(all_numbers[3]) if len(all_numbers) > 3 else 0  # после даты и сумм

# 👇 ДОБАВЬ ЭТО!
data = {
    "creditor": "АО «ForteBank»",
    "financing_type": find(r"(Займ|Кредитная карта|Кредитная линия)", txt),
    "contract_amount": contract_amount,
    "balance": balance,
    "overdue_amount": overdue_amount,
    "overdue_days": overdue_days
}


# ── Сохраняем и выводим результат ────────────────────────────────────────────
print(json.dumps(data, indent=2, ensure_ascii=False))

with open("forte_test.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("✅  Данные ForteBank сохранены в forte_test.json")
