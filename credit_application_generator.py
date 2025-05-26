import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from datetime import datetime
import tempfile
import os

# Регистрируем шрифт для русского текста
def register_fonts():
    """Регистрирует шрифты для корректного отображения кириллицы"""
    try:
        # Попробуем разные варианты шрифтов
        font_paths = [
            # Windows
            'C:/Windows/Fonts/arial.ttf',
            'C:/Windows/Fonts/calibri.ttf',
            # macOS
            '/System/Library/Fonts/Arial.ttf',
            '/System/Library/Fonts/Helvetica.ttc',
            # Linux
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/TTF/arial.ttf',
        ]
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont('RussianFont', font_path))
                print(f"[INFO] Зарегистрирован шрифт: {font_path}")
                return 'RussianFont'
        
        # Если не нашли файл шрифта, пробуем встроенные шрифты ReportLab
        from reportlab.lib.fonts import addMapping
        addMapping('RussianFont', 0, 0, 'Times-Roman')
        print("[INFO] Используем встроенный шрифт Times-Roman")
        return 'Times-Roman'
        
    except Exception as e:
        print(f"[WARN] Ошибка регистрации шрифта: {e}")
        return 'Times-Roman'  # Fallback

def generate_credit_application_pdf(personal_info, creditor_data, total_debt):
    """
    Генерирует PDF заявления для конкретного кредитора
    
    Args:
        personal_info: словарь с личными данными из отчета
        creditor_data: данные о конкретном кредиторе  
        total_debt: общая сумма задолженности из отчета
    
    Returns:
        bytes: содержимое PDF файла
    """
    
    # Создаем временный файл
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
    
    try:
        # Регистрируем шрифт для кириллицы
        font_name = register_fonts()
        
        # Создаем PDF
        c = canvas.Canvas(temp_file.name, pagesize=A4)
        width, height = A4
        
        # Настройки текста - ИСПОЛЬЗУЕМ РУССКИЙ ШРИФТ
        c.setFont(font_name, 12)
        
        # Заголовок
        y_position = height - 50
        
        # Получатель (название кредитора)
        c.drawString(50, y_position, f"в {creditor_data['creditor']}")
        y_position -= 40
        
        # Данные заявителя
        full_name = personal_info.get('full_name', 'Не указано')
        iin = personal_info.get('iin', 'Не указано')
        address = personal_info.get('address', 'Не указано')
        
        c.drawString(50, y_position, f"от {full_name}")
        y_position -= 20
        c.drawString(50, y_position, f"ИИН {iin}")
        y_position -= 40
        
        # Заголовок заявления
        c.setFont(font_name, 14)  # Используем тот же шрифт для заголовка
        c.drawString(200, y_position, "Заявление")
        y_position -= 20
        c.setFont(font_name, 12)  # Возвращаем обычный размер
        c.drawString(50, y_position, "об изменении условий займа и прощении просроченного долга")
        y_position -= 40
        
        # Основной текст
        c.setFont(font_name, 11)  # Используем русский шрифт

        # ФУНКЦИЯ ДЛЯ РАЗБИВКИ ДЛИННЫХ СТРОК
        def split_long_text(text, max_length=85):
            """Разбивает длинный текст на строки подходящей длины"""
            if len(text) <= max_length:
                return [text]
            
            lines = []
            words = text.split()
            current_line = ""
            
            for word in words:
                if len(current_line + " " + word) <= max_length:
                    current_line += (" " + word) if current_line else word
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            
            if current_line:
                lines.append(current_line)
            
            return lines
        
        # Разбиваем текст на строки
        text_lines = [
            "Выплата ежемесячной суммы кредита ставит меня в крайне тяжелое,",
            "фактически безвыходное положение и оставляет без средств к",
            f"существованию, иной материальной поддержки не имею. Кроме того, имеются",
            f"другие кредитные обязательства на общую сумму {total_debt:,.2f} тг.",
            "",
            'В соответствии с требованиями законов Республики Казахстан "О банках и',
            'банковской деятельности в Республике Казахстан" и "О микрофинансовой',
            'деятельности", а также в целях выполнения условий, предусмотренных',
            'подпунктом 3) пункта 1 статьи 5 и подпунктом 2) пункта 1 статьи 6',
            'Закона РК "О восстановлении платежеспособности и банкротстве граждан',
            'Республики Казахстан", прошу Вас рассмотреть возможность:',
            "",
            "- простить просроченный основной долг и вознаграждение;",
            "- отменить неустойку, штраф и пеню;",
            "- реструктурировать задолженность путем увеличения срока",
            "  погашения на дополнительных 10 (десять) лет с возможностью",
            "  ежемесячных выплат в посильном размере;",
            "- предоставить отсрочку платежа на определенный период;",
            "- изменить условия договора займа/микрокредита.",
            "",
            "Данное обращение направляется в рамках процедуры урегулирования",
            "неисполненных обязательств, предусмотренной статьями 5 и 6 Закона РК",
            '"О восстановлении платежеспособности и банкротстве граждан',
            'Республики Казахстан".',
            "",
            "В случае отсутствия ответа или отказа в урегулировании задолженности",
            "буду вынужден обратиться в суд с заявлением о применении процедуры",
            "банкротства в соответствии с указанным Законом.",
            "",
            "Прошу Вас рассмотреть данное заявление в срок, предусмотренный",
            "статьей 6 Закона РК \"О восстановлении платежеспособности и банкротстве",
            'граждан Республики Казахстан".',
        ]

        # ОБРАБАТЫВАЕМ ДЛИННЫЙ АДРЕС И ДОБАВЛЯЕМ К СПИСКУ
        address_text = f"Оригинал просим отправить по почтовому адресу: {address}."
        address_lines = split_long_text(address_text)

        # Добавляем строки адреса к основному списку
        text_lines.extend(address_lines)

        # Добавляем оставшиеся строки
        text_lines.extend([
            "",
            "Приложения:",
            "",
            "1. Отчет ПКБ."
        ])
        
        # Выводим текст построчно
        for line in text_lines:
            c.drawString(50, y_position, line)
            y_position -= 20
            
            # Проверяем, не вышли ли за границы страницы
            if y_position < 100:
                c.showPage()
                y_position = height - 50
                c.setFont(font_name, 11)  # Восстанавливаем шрифт на новой странице
        
        # Подпись и дата
        y_position -= 40
        current_date = datetime.now().strftime("%d.%m.%Y")
        c.drawString(50, y_position, f"Дата: {current_date}")
        c.drawString(300, y_position, "Подпись: ________________")
        
        # Сохраняем PDF
        c.save()
        
        # Читаем содержимое файла
        with open(temp_file.name, 'rb') as f:
            pdf_content = f.read()
        
        print(f"[DEBUG] PDF создан успешно для {creditor_data['creditor']}")
        return pdf_content
        
    except Exception as e:
        print(f"[ERROR] Ошибка создания PDF: {e}")
        return None
        
    finally:
        # Удаляем временный файл
        try:
            os.unlink(temp_file.name)
        except:
            pass

def generate_applications_for_all_creditors(parsed_data):
    """
    Генерирует заявления для всех кредиторов из отчета
    
    Args:
        parsed_data: результат парсинга кредитного отчета
    
    Returns:
        list: список словарей с данными о сгенерированных PDF
    """
    
    personal_info = parsed_data.get('personal_info', {})
    obligations = parsed_data.get('obligations', [])
    total_debt = parsed_data.get('total_debt', 0)
    
    generated_files = []
    
    print(f"[DEBUG] Генерируем заявления для {len(obligations)} кредиторов")
    
    for i, obligation in enumerate(obligations, 1):
        try:
            print(f"[DEBUG] Обрабатываем кредитора {i}: {obligation['creditor']}")
            
            # Генерируем PDF для каждого кредитора
            pdf_content = generate_credit_application_pdf(
                personal_info=personal_info,
                creditor_data=obligation,
                total_debt=total_debt
            )
            
            if pdf_content is None:
                print(f"[ERROR] Не удалось создать PDF для {obligation['creditor']}")
                continue
            
            # Создаем безопасное имя файла
            creditor_name = obligation['creditor']
            safe_name = "".join(c for c in creditor_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            filename = f"Заявление_{safe_name}.pdf"
            
            generated_files.append({
                'filename': filename,
                'content': pdf_content,
                'creditor': creditor_name,
                'debt_amount': obligation.get('balance', 0)
            })
            
            print(f"[DEBUG] ✅ Заявление для {creditor_name} создано успешно")
            
        except Exception as e:
            print(f"[ERROR] Ошибка при создании заявления для {obligation.get('creditor', 'неизвестно')}: {e}")
            continue
    
    print(f"[DEBUG] Итого создано {len(generated_files)} заявлений")
    return generated_files

# Функция для интеграции в document_processor.py
def process_credit_report_with_applications(filepath, user_id):
    """
    Обрабатывает кредитный отчет и генерирует заявления
    Эту функцию нужно добавить в document_processor.py
    """
    from document_processor import process_uploaded_file
    
    # Сначала обрабатываем как обычно
    result = process_uploaded_file(filepath, user_id)
    
    if result.get("type") == "credit_report":
        # Извлекаем данные из базы (если они там сохранены)
        # Или парсим заново
        from credit_parser import extract_credit_data_with_total
        from text_extractor import extract_text_from_pdf
        from ocr import ocr_file
        
        # Извлекаем текст
        text = extract_text_from_pdf(filepath)
        if not text.strip():
            text = ocr_file(filepath)
        
        # Парсим данные
        parsed_data = extract_credit_data_with_total(text)
        
        # Генерируем заявления
        applications = generate_applications_for_all_creditors(parsed_data)
        
        # Добавляем заявления к результату
        result['applications'] = applications
        result['applications_count'] = len(applications)
    
    return result