# text_extractor.py
import io
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
import logging
import os

# Настройка логирования
DEBUG_MODE = os.getenv('DEBUG', 'False').lower() == 'true'

if DEBUG_MODE:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
else:
    logging.basicConfig(level=logging.CRITICAL)
    logger = logging.getLogger(__name__)
    logger.disabled = True

def extract_text_from_pdf(filepath):
    """
    Извлекает текст из PDF используя pdfminer.six с настроенными LAParams
    для стабильного порядка строк
    """
    try:
        # Настройки LAParams для кредитных отчетов
        laparams = LAParams(
            char_margin=2.0,        # Расстояние между символами для группировки в слова
            line_margin=0.3,        # Расстояние между строками для группировки в абзацы
            word_margin=0.1,        # Расстояние между словами
            boxes_flow=0.5,         # Порядок обхода блоков (0.5 = сбалансированный)
            detect_vertical=False,  # Не обнаруживать вертикальный текст
            all_texts=False         # Не включать ненужные элементы
        )
        
        output_string = io.StringIO()
        rsrcmgr = PDFResourceManager()
        device = TextConverter(rsrcmgr, output_string, laparams=laparams)
        interpreter = PDFPageInterpreter(rsrcmgr, device)
        
        with open(filepath, 'rb') as file:
            page_count = 0
            for page in PDFPage.get_pages(file, check_extractable=True):
                interpreter.process_page(page)
                page_count += 1
                
                if DEBUG_MODE and page_count <= 3:
                    logger.info(f"Обработана страница {page_count}")
        
        text = output_string.getvalue()
        device.close()
        output_string.close()
        
        if DEBUG_MODE:
            logger.info(f"Извлечено {len(text)} символов из {page_count} страниц")
            logger.info(f"Первые 200 символов: {text[:200]}...")
        
        return text
        
    except Exception as e:
        logger.error(f"Ошибка извлечения текста с pdfminer.six: {e}")
        
        # Fallback на PyMuPDF
        logger.info("Используем fallback на PyMuPDF...")
        return extract_text_fallback_pymupdf(filepath)

def extract_text_fallback_pymupdf(filepath):
    """
    Fallback метод используя PyMuPDF если pdfminer.six не работает
    """
    try:
        import fitz  # PyMuPDF
        
        doc = fitz.open(filepath)
        text = ""
        
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text += page.get_text()
            
            if DEBUG_MODE and page_num < 3:
                logger.info(f"Fallback: обработана страница {page_num + 1}")
        
        doc.close()
        
        if DEBUG_MODE:
            logger.info(f"Fallback: извлечено {len(text)} символов")
        
        return text
        
    except Exception as e:
        logger.error(f"Ошибка и в fallback методе: {e}")
        return ""

def extract_text_robust(filepath):
    """
    Робустный метод с несколькими попытками и разными параметрами
    """
    
    # Набор различных конфигураций LAParams
    configs = [
        # Конфигурация для кредитных отчетов (основная)
        LAParams(char_margin=2.0, line_margin=0.3, word_margin=0.1, boxes_flow=0.5),
        
        # Конфигурация для плотных документов
        LAParams(char_margin=1.5, line_margin=0.2, word_margin=0.05, boxes_flow=0.3),
        
        # Конфигурация для документов с таблицами
        LAParams(char_margin=3.0, line_margin=0.5, word_margin=0.2, boxes_flow=0.7),
        
        # Минимальная конфигурация
        LAParams(char_margin=1.0, line_margin=0.1, word_margin=0.0, boxes_flow=0.1)
    ]
    
    for i, laparams in enumerate(configs):
        try:
            if DEBUG_MODE:
                logger.info(f"Пробуем конфигурацию {i+1}/{len(configs)}")
            
            output_string = io.StringIO()
            rsrcmgr = PDFResourceManager()
            device = TextConverter(rsrcmgr, output_string, laparams=laparams)
            interpreter = PDFPageInterpreter(rsrcmgr, device)
            
            with open(filepath, 'rb') as file:
                for page in PDFPage.get_pages(file, check_extractable=True):
                    interpreter.process_page(page)
            
            text = output_string.getvalue()
            device.close()
            output_string.close()
            
            # Проверяем качество извлечения
            if len(text) > 1000 and "кредит" in text.lower():
                if DEBUG_MODE:
                    logger.info(f"Успешно с конфигурацией {i+1}")
                return text
                
        except Exception as e:
            if DEBUG_MODE:
                logger.warning(f"Конфигурация {i+1} не сработала: {e}")
            continue
    
    # Если все конфигурации не сработали
    logger.warning("Все конфигурации pdfminer.six не сработали, используем fallback")
    return extract_text_fallback_pymupdf(filepath)

# Основная функция для совместимости
def extract_text_from_pdf_enhanced(filepath):
    """
    Расширенная функция извлечения с автоматическим выбором метода
    """
    
    # Сначала пробуем основной метод
    text = extract_text_from_pdf(filepath)
    
    # Если результат неудовлетворительный, пробуем робустный метод
    if len(text) < 500 or not any(keyword in text.lower() for keyword in ["кредит", "обязательство", "долг", "банк"]):
        if DEBUG_MODE:
            logger.info("Основной метод дал плохой результат, пробуем робустный...")
        text = extract_text_robust(filepath)
    
    return text

# Функция для тестирования разных методов
def test_extraction_methods(filepath):
    """
    Тестирует разные методы извлечения и выбирает лучший
    """
    
    results = {}
    
    # Тест pdfminer.six
    try:
        text_pdfminer = extract_text_from_pdf(filepath)
        results['pdfminer'] = {
            'length': len(text_pdfminer),
            'has_keywords': any(kw in text_pdfminer.lower() for kw in ["кредит", "обязательство", "долг"]),
            'sample': text_pdfminer[:200]
        }
    except Exception as e:
        results['pdfminer'] = {'error': str(e)}
    
    # Тест PyMuPDF
    try:
        text_pymupdf = extract_text_fallback_pymupdf(filepath)
        results['pymupdf'] = {
            'length': len(text_pymupdf),
            'has_keywords': any(kw in text_pymupdf.lower() for kw in ["кредит", "обязательство", "долг"]),
            'sample': text_pymupdf[:200]
        }
    except Exception as e:
        results['pymupdf'] = {'error': str(e)}
    
    # Тест робустного метода
    try:
        text_robust = extract_text_robust(filepath)
        results['robust'] = {
            'length': len(text_robust),
            'has_keywords': any(kw in text_robust.lower() for kw in ["кредит", "обязательство", "долг"]),
            'sample': text_robust[:200]
        }
    except Exception as e:
        results['robust'] = {'error': str(e)}
    
    return results

if __name__ == "__main__":
    # Тест на примере файла
    test_file = "temp/test.pdf"  # Замените на реальный файл
    
    if os.path.exists(test_file):
        print("🧪 Тестируем методы извлечения текста...")
        results = test_extraction_methods(test_file)
        
        for method, result in results.items():
            print(f"\n📊 {method.upper()}:")
            if 'error' in result:
                print(f"   ❌ Ошибка: {result['error']}")
            else:
                print(f"   📏 Длина: {result['length']}")
                print(f"   🔍 Ключевые слова: {'✅' if result['has_keywords'] else '❌'}")
                print(f"   📄 Образец: {result['sample']}...")
    else:
        print(f"❌ Тестовый файл {test_file} не найден")