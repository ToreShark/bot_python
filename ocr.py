# ocr.py

import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import os

def ocr_file(filepath):
    print(f"[DEBUG] OCR started for file: {filepath}")
    """
    Выполняет OCR документа (PDF или изображение).
    Возвращает распознанный текст.
    """
    text = ""
    if filepath.lower().endswith(".pdf"):
        try:
            images = convert_from_path(filepath, poppler_path="/opt/homebrew/bin")  # путь для macOS
            for i, img in enumerate(images):
                print(f"[DEBUG] OCR page {i+1}/{len(images)}")
                text += pytesseract.image_to_string(img, lang="kaz+rus")
        except Exception as e:
            print(f"[ERROR] Ошибка при обработке PDF: {e}")
            raise
    else:
        try:
            image = Image.open(filepath)
            text = pytesseract.image_to_string(image, lang="kaz+rus")
        except Exception as e:
            print(f"[ERROR] Ошибка при обработке изображения: {e}")
            raise
    return text

def detect_document_type(text):
    """
    Определяет тип документа по ключевым признакам на казахском и русском.
    """
    lowered = text.lower()

    credit_keywords = [
        # казахские ключи
        "кредиттік есеп", "жеке кредиттік есеп", "жсн",
        "ай сайынғы төлем сомасы", "шарт бойынша берешек қалдығы", "міндеттеме",
        # русские ключи
        "персональный кредитный отчет", "пкб", "иин",
        "сумма ежемесячного платежа", "обязательство", "просрочка"
    ]

    receipt_keywords = [
        "оплата", "квитанция", "kaspi", "каспи", "перевод", "платеж"
    ]

    if any(kw in lowered for kw in credit_keywords):
        return "credit_report"
    elif any(kw in lowered for kw in receipt_keywords):
        return "payment_receipt"
    else:
        return "unknown"
