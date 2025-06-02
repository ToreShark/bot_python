import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from datetime import datetime
import tempfile
import os
from reportlab.lib.styles import ParagraphStyle
import re

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

DEBUG_PRINT = os.getenv('DEBUG', 'False').lower() == 'true'

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
                # print(f"[INFO] Зарегистрирован шрифт: {font_path}")
                return 'RussianFont'
        
        # Если не нашли файл шрифта, пробуем встроенные шрифты ReportLab
        from reportlab.lib.fonts import addMapping
        addMapping('RussianFont', 0, 0, 'Times-Roman')
        # print("[INFO] Используем встроенный шрифт Times-Roman")
        return 'Times-Roman'
        
    except Exception as e:
        # print(f"[WARN] Ошибка регистрации шрифта: {e}")
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
        
        # print(f"[DEBUG] PDF создан успешно для {creditor_data['creditor']}")
        return pdf_content
        
    except Exception as e:
        # print(f"[ERROR] Ошибка создания PDF: {e}")
        return None
        
    finally:
        # Удаляем временный файл
        try:
            os.unlink(temp_file.name)
        except:
            pass

# Добавьте эту функцию в credit_application_generator.py ПОСЛЕ существующих функций

def generate_applications_from_parsed_data(parsed_data, user_id):
    """
    Генерирует заявления для кредиторов из уже готовых данных отчета
    
    Args:
        parsed_data: результат парсинга кредитного отчета (от GKBParser или других)
        user_id: ID пользователя для логирования
    
    Returns:
        dict: результат с applications или ошибкой
    """
    try:
        # Проверяем корректность данных
        if not parsed_data or parsed_data.get('parsing_error'):
            return {
                "status": "error",
                "message": "Некорректные данные отчета",
                "applications": [],
                "applications_count": 0
            }
        if DEBUG_PRINT:
            print(f"[INFO] Генерируем заявления из готовых данных для пользователя {user_id}")
            print(f"[INFO] Найдено {len(parsed_data.get('obligations', []))} кредиторов")
        
        # Импортируем format_summary для создания сообщения
        from credit_parser import format_summary
        
        # Генерируем заявления используя уже готовые данные
        applications = generate_applications_for_all_creditors(parsed_data)
        
        # Формируем результат в том же формате что ожидает main.py
        result = {
            "status": "success",
            "message": format_summary(parsed_data),
            "type": "credit_report", 
            "applications": applications,
            "applications_count": len(applications)
        }
        
        # print(f"[INFO] Успешно сгенерировано {len(applications)} заявлений")
        return result
        
    except Exception as e:
        print(f"[ERROR] Ошибка генерации заявлений из parsed_data: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            "status": "error", 
            "message": f"Ошибка генерации заявлений: {str(e)}",
            "type": "credit_report",
            "applications": [],
            "applications_count": 0
        }

def extract_contract_details(description):
    """
    Извлекает номер договора и дату из строки вида "Договор №123456 от 01.01.2022"
    """
    match = re.search(r'Договор\s+№(\d+)\s+от\s+(\d{2}\.\d{2}\.\d{4})', description)
    if match:
        return match.group(1), match.group(2)
    return '—', '—'

def generate_creditors_list_pdf(parsed_data):
    """
    ОБНОВЛЕННАЯ версия - использует данные от GKBParser
    """
    try:
        # print(f"\n🎯 [UPDATED] Создание PDF с полными данными:")
        # print(f"   📋 Ключи parsed_data: {list(parsed_data.keys())}")
        # print(f"   📄 report_type: {parsed_data.get('report_type')}")
        # print(f"   🎯 bankruptcy_ready: {parsed_data.get('bankruptcy_ready')}")
        # print(f"   📊 Количество obligations: {len(parsed_data.get('obligations', []))}")
        
        # Проверяем первое обязательство
        obligations = parsed_data.get('obligations', [])
        if obligations:
            first_obl = obligations[0]
            # print(f"   🔍 Поля первого обязательства: {list(first_obl.keys())}")
            # print(f"   📄 contract_number: {first_obl.get('contract_number', 'ОТСУТСТВУЕТ')}")
            # print(f"   📅 debt_origin_date: {first_obl.get('debt_origin_date', 'ОТСУТСТВУЕТ')}")
        
        
        # Проверяем, есть ли данные от GKBParser
        is_gkb_data = parsed_data.get('report_type') == 'GKB' or parsed_data.get('bankruptcy_ready', False)
        total_contracts_with_data = 0
        total_dates_with_data = 0
        
        # Подсчитываем, сколько данных у нас есть
        obligations = parsed_data.get('obligations', [])
        for obl in obligations:
            contract_number = obl.get('contract_number', 'НЕ НАЙДЕН')
            debt_origin_date = obl.get('debt_origin_date', 'НЕ НАЙДЕНА')
            
            if contract_number and contract_number != 'НЕ НАЙДЕН':
                total_contracts_with_data += 1
            if debt_origin_date and debt_origin_date != 'НЕ НАЙДЕНА':
                total_dates_with_data += 1
        
        # print(f"   📄 Номера договоров: {total_contracts_with_data}/{len(obligations)}")
        # print(f"   📅 Даты образования: {total_dates_with_data}/{len(obligations)}")
        
        # Определяем статус готовности
        is_bankruptcy_ready = (total_contracts_with_data > 0 and total_dates_with_data > 0)
        
        # РЕГИСТРИРУЕМ РУССКИЕ ШРИФТЫ
        font_name = register_fonts()
        
        # Создаем временный файл
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        doc = SimpleDocTemplate(tmp_file.name, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()

        # НАСТРАИВАЕМ СТИЛИ ДЛЯ РУССКОГО ШРИФТА
        title_style = ParagraphStyle(
            'RussianTitle',
            parent=styles['Title'],
            fontName=font_name,
            fontSize=16,
            alignment=1  # CENTER
        )
        
        normal_style = ParagraphStyle(
            'RussianNormal', 
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=10
        )
        
        # Стиль в зависимости от готовности данных
        if is_bankruptcy_ready:
            status_style = ParagraphStyle(
                'RussianSuccess',
                parent=styles['Normal'],
                fontName=font_name,
                fontSize=11,
                textColor=colors.green,
                alignment=1
            )
        else:
            status_style = ParagraphStyle(
                'RussianWarning',
                parent=styles['Normal'],
                fontName=font_name,
                fontSize=11,
                textColor=colors.red,
                alignment=1
            )

        # Заголовок документа
        title = Paragraph("ПЕРЕЧЕНЬ КРЕДИТОРОВ И ДЕБИТОРОВ", title_style)
        elements.append(title)
        elements.append(Spacer(1, 12))
        
        # СТАТУС В ЗАВИСИМОСТИ ОТ ГОТОВНОСТИ ДАННЫХ
        if is_bankruptcy_ready:
            status_text = (
                "<b>✅ ДАННЫЕ ДЛЯ БАНКРОТСТВА ГОТОВЫ!</b><br/>"
                f"Извлечено {total_contracts_with_data} номеров договоров и {total_dates_with_data} дат.<br/>"
                "Документ готов для подачи заявления о банкротстве."
            )
        else:
            status_text = (
                "<b>⚠️ ВНИМАНИЕ: НЕПОЛНЫЕ ДАННЫЕ</b><br/>"
                "Парсер не смог извлечь все данные из кредитного отчета.<br/>"
                "Некоторые номера договоров и даты нужно добавить вручную!"
            )
        
        status = Paragraph(status_text, status_style)
        elements.append(status)
        elements.append(Spacer(1, 20))

        # Информация о заемщике
        personal_info = parsed_data.get('personal_info', {})
        
        name = (personal_info.get('full_name') or 
                personal_info.get('name') or 
                'Не указано')
        
        iin = (personal_info.get('iin') or 
               'Не указано')
        
        phone = personal_info.get('mobile_phone', 'Не указано')
        email = personal_info.get('email', 'Не указано')

        debtor_text = f"""
        <b>Заемщик:</b> {name}<br/>
        <b>ИИН:</b> {iin}<br/>
        <b>Телефон:</b> {phone}<br/>
        <b>Email:</b> {email}<br/>
        <b>Дата составления:</b> {datetime.now().strftime('%d.%m.%Y')}
        """
        elements.append(Paragraph(debtor_text, normal_style))
        elements.append(Spacer(1, 12))

        # Заголовки таблицы
        headers = ['№', 'Кредитор', 'Сумма долга (тенге)', 'Дата образования', 'Номер договора', 'Статус']
        table_data = [headers]

        # Извлекаем данные с РЕАЛЬНЫМИ значениями
        total_debt = 0
        active_creditors = 0
        
        for i, obligation in enumerate(obligations, 1):
            creditor_name = obligation.get('creditor', 'Не указано').strip('"')
            debt_amount = obligation.get('balance', 0)
            overdue_status = obligation.get('overdue_status', 'Стандартные кредиты')
            
            # ✅ НОВЫЕ ПОЛЯ ОТ GKBParser:
            contract_number = obligation.get('contract_number', 'НЕ ИЗВЛЕЧЕНО')
            debt_origin_date = obligation.get('debt_origin_date', 'НЕ ИЗВЛЕЧЕНО')
            
            if debt_amount > 0:
                total_debt += debt_amount
                active_creditors += 1

            row = [
                str(i),
                creditor_name,
                f"{debt_amount:,.2f}".replace(',', ' '),
                debt_origin_date,    # ✅ ТЕПЕРЬ РЕАЛЬНАЯ ДАТА ИЛИ "НЕ ИЗВЛЕЧЕНО"
                contract_number,     # ✅ ТЕПЕРЬ РЕАЛЬНЫЙ НОМЕР ИЛИ "НЕ ИЗВЛЕЧЕНО"
                overdue_status
            ]
            table_data.append(row)

        # СОЗДАЕМ ТАБЛИЦУ
        table = Table(table_data, repeatRows=1)
        
        # Стиль таблицы в зависимости от готовности данных
        if is_bankruptcy_ready:
            table_bg_color = colors.lightgreen  # Зеленый = готово
            missing_data_color = colors.black
        else:
            table_bg_color = colors.beige       # Бежевый = не готово
            missing_data_color = colors.red     # Красный для отсутствующих данных
        
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), table_bg_color),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        # Выделяем красным только ячейки с "НЕ ИЗВЛЕЧЕНО"
        for row_idx in range(1, len(table_data)):
            # Проверяем дату образования (колонка 3)
            if table_data[row_idx][3] == "НЕ ИЗВЛЕЧЕНО":
                table.setStyle(TableStyle([
                    ('TEXTCOLOR', (3, row_idx), (3, row_idx), missing_data_color),
                ]))
            
            # Проверяем номер договора (колонка 4)
            if table_data[row_idx][4] == "НЕ ИЗВЛЕЧЕНО":
                table.setStyle(TableStyle([
                    ('TEXTCOLOR', (4, row_idx), (4, row_idx), missing_data_color),
                ]))

        elements.append(table)
        elements.append(Spacer(1, 24))

        # Итоги в зависимости от готовности данных
        if is_bankruptcy_ready:
            summary_text = f"""
            <b>ИТОГО:</b><br/>
            Общее количество кредиторов: {active_creditors}<br/>
            Общая сумма задолженности: {total_debt:,.2f} тенге<br/>
            <br/>
            <b>✅ ДАННЫЕ ДЛЯ БАНКРОТСТВА ГОТОВЫ:</b><br/>
            • ✅ Номера договоров извлечены ({total_contracts_with_data}/{len(obligations)})<br/>
            • ✅ Даты образования найдены ({total_dates_with_data}/{len(obligations)})<br/>
            • ✅ Суммы задолженности подтверждены<br/>
            • ⚠️ Контактные данные кредиторов требуют дополнительного уточнения<br/>
            <br/>
            <b>📋 ГОТОВО К ПОДАЧЕ:</b><br/>
            Документ содержит все необходимые данные для заявления о банкротстве<br/>
            согласно требованиям законодательства РК.
            """
        else:
            missing_contracts = len(obligations) - total_contracts_with_data  
            missing_dates = len(obligations) - total_dates_with_data
            
            summary_text = f"""
            <b>ИТОГО:</b><br/>
            Общее количество кредиторов: {active_creditors}<br/>
            Общая сумма задолженности: {total_debt:,.2f} тенге<br/>
            <br/>
            <b>❌ ОТСУТСТВУЮЩИЕ ДАННЫЕ ДЛЯ БАНКРОТСТВА:</b><br/>
            • Номера договоров: отсутствует {missing_contracts}<br/>
            • Даты образования: отсутствует {missing_dates}<br/>
            • Контактные данные кредиторов<br/>
            <br/>
            <b>💡 ДЕЙСТВИЯ:</b><br/>
            1. Запросить справки из банков с номерами договоров<br/>
            2. Уточнить даты образования задолженности<br/>
            3. Получить контактные данные кредиторов<br/>
            4. Обновить данные в системе
            """
        
        elements.append(Paragraph(summary_text, normal_style))

        # Сборка PDF
        doc.build(elements)
        
        print(f"✅ PDF создан: {tmp_file.name}")
        print(f"   Статус готовности: {'ГОТОВ К БАНКРОТСТВУ' if is_bankruptcy_ready else 'ТРЕБУЕТ ДОРАБОТКИ'}")
        
        return tmp_file.name

    except Exception as e:
        print(f"[ERROR] Не удалось создать PDF: {e}")
        import traceback
        traceback.print_exc()
        return None
          
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
    
    # 🔍 ОТЛАДКА: Откуда берутся 25 кредиторов?
    if DEBUG_PRINT:
        print(f"\n🔍 [DEBUG PDF] generate_applications_for_all_creditors получил:")
        print(f"   - parsed_data keys: {list(parsed_data.keys())}")
        print(f"   - obligations: {len(obligations)}")
        print(f"   - total_debt: {total_debt}")
    
    # print(f"\n📋 [DEBUG PDF] ВСЕ obligations для PDF ({len(obligations)}):")
    for i, obligation in enumerate(obligations, 1):
        creditor = obligation.get('creditor', 'Неизвестно')
        balance = obligation.get('balance', 0)
        print(f"   {i}. {creditor}: {balance} ₸")
    
    # Проверяем, есть ли другие источники кредиторов
    if 'creditor_groups' in parsed_data:
        creditor_groups = parsed_data['creditor_groups']
        print(f"\n🔍 [DEBUG PDF] Найдены creditor_groups: {len(creditor_groups)} групп")
        for group_name, group_data in creditor_groups.items():
            print(f"   - '{group_name}': {len(group_data)} договоров")
    
    if 'raw_creditors' in parsed_data:
        raw_creditors = parsed_data['raw_creditors']
        print(f"\n🔍 [DEBUG PDF] Найдены raw_creditors: {len(raw_creditors)}")

    generated_files = []
    
    # print(f"[DEBUG] Генерируем заявления для {len(obligations)} кредиторов")
    
    for i, obligation in enumerate(obligations, 1):
        try:
            # print(f"[DEBUG] Обрабатываем кредитора {i}: {obligation['creditor']}")
            
            # Генерируем PDF для каждого кредитора
            pdf_content = generate_credit_application_pdf(
                personal_info=personal_info,
                creditor_data=obligation,
                total_debt=total_debt
            )
            
            if pdf_content is None:
                # print(f"[ERROR] Не удалось создать PDF для {obligation['creditor']}")
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
            
            # print(f"[DEBUG] ✅ Заявление для {creditor_name} создано успешно")
            
        except Exception as e:
            # print(f"[ERROR] Ошибка при создании заявления для {obligation.get('creditor', 'неизвестно')}: {e}")
            continue
    
    # print(f"[DEBUG] Итого создано {len(generated_files)} заявлений")
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