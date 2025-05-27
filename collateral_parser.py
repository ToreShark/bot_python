import re
from typing import List, Dict

def clean_number(value: str) -> float:
    """Преобразует строковое представление числа в float"""
    if not value:
        return 0.0
    cleaned = re.sub(r'[^\d.,]', '', str(value))
    cleaned = cleaned.replace(',', '.')
    if '.' in cleaned:
        parts = cleaned.split('.')
        if len(parts) > 2:
            cleaned = ''.join(parts[:-1]) + '.' + parts[-1]
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0
    
def extract_collateral_info(text: str) -> List[Dict]:
    """
    Извлекает информацию по залогам из текста отчета.

    Returns:
        Список словарей с информацией по каждому залогу.
    """
    collateral_info = []
    obligation_blocks = re.split(r"(?:Обязательство|КОНТРАКТ)\s+\d+", text)

    for block in obligation_blocks:
        collateral_match = re.search(r"Вид обеспечения:\s*([^\n\r]+).*?Стоимость обеспечения /валюта:\s*([\d\s.,]+)\s*KZT", block, re.DOTALL)
        creditor_match = re.search(r"Кредитор:\s*(.+?)[\r\n]", block)
        
        if collateral_match and creditor_match:
            kind = collateral_match.group(1).strip()
            value = clean_number(collateral_match.group(2))
            creditor = creditor_match.group(1).strip()
            
            if value > 0:
                collateral_info.append({
                    "creditor": creditor,
                    "collateral_type": kind,
                    "market_value": round(value, 2)
                })

    return collateral_info
