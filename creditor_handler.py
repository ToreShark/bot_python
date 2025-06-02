import os
from collateral_parser import extract_collateral_info
from credit_parser import create_parser_chain, extract_credit_data_with_total
from text_extractor import extract_text_from_pdf
from ocr import ocr_file
from credit_application_generator import generate_creditors_list_pdf

def process_all_creditors_request(filepath, user_id):
    """
    Обрабатывает PDF-файл, извлекает всех кредиторов и генерирует один PDF со списком

    Args:
        filepath (str): путь к загруженному PDF-файлу
        user_id (int or str): ID пользователя (можно использовать для логирования)

    Returns:
        dict: результат с PDF-файлом или сообщением об ошибке
    """
    try:
        # 1. Извлекаем текст из PDF (OCR, если нужно)
        text = extract_text_from_pdf(filepath)
        if not text.strip():
            text = ocr_file(filepath)

        # 2. Парсим кредиторов и сумму задолженности
        # parsed_data = extract_credit_data_with_total(text)
        parser = create_parser_chain()
        parsed_data = parser.parse(text)
        if parsed_data:
            parsed_data["collaterals"] = extract_collateral_info(text)

        # 3. Генерируем один PDF со списком всех кредиторов
        creditors_list_pdf = generate_creditors_list_pdf(parsed_data)

        if not creditors_list_pdf:
            return {"status": "fail", "message": "Не удалось сгенерировать PDF или кредиторы не найдены."}

        return {
            "status": "success", 
            "pdf_path": creditors_list_pdf,
            "creditors_count": len(parsed_data.get('creditors', []))
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}
