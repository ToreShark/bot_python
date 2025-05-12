import openai
import os
import json
import re
from typing import Dict

def filter_important_sections(text):
    """Извлекает только необходимые разделы из кредитного отчета"""
    # Определяем язык отчета
    is_kazakh = "Жеке кредиттік есеп" in text or "ҚОЛДАНЫСТАҒЫ ШАРТТАР" in text
    
    if is_kazakh:
        # Фильтрация для казахскоязычных отчетов
        header_match = re.search(r"Жеке кредиттік есеп.*?МІНДЕТТЕМЕЛЕР БОЙЫНША ЖАЛПЫ АҚПАРАТ", text, re.DOTALL)
        header = header_match.group(0) if header_match else ""
        
        contracts_match = re.search(r"ҚОЛДАНЫСТАҒЫ ШАРТТАР БОЙЫНША ТОЛЫҚ АҚПАРАТ.*?Міндеттеме \d+", text, re.DOTALL)
        contracts = contracts_match.group(0) if contracts_match else ""
        
        # Добавляем данные по обязательствам
        obligations_match = re.search(r"Міндеттеме \d+.*?(Міндеттеме \d+|$)", text, re.DOTALL)
        obligations = obligations_match.group(0) if obligations_match else ""
        
        # Составляем отфильтрованный текст
        filtered_text = f"{header}\n\n{contracts}\n\n{obligations}"
    else:
        # Фильтрация для русскоязычных отчетов
        header_match = re.search(r"ПОЛНЫЙ ПЕРСОНАЛЬНЫЙ КРЕДИТНЫЙ ОТЧЕТ.*?ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ КРЕДИТНЫМ ДОГОВОРАМ", text, re.DOTALL)
        header = header_match.group(0) if header_match else ""
        
        credits_match = re.search(r"ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ КРЕДИТНЫМ ДОГОВОРАМ.*?СВЕДЕНИЯ О БАНКРОТСТВЕ", text, re.DOTALL)
        credits = credits_match.group(0) if credits_match else ""
        
        # Составляем отфильтрованный текст
        filtered_text = f"{header}\n\n{credits}"
    
    # Проверяем, что у нас есть какие-то данные
    if not filtered_text.strip():
        # Если регулярные выражения не сработали, возьмем первые 30000 символов
        filtered_text = text[:30000]
    
    # Если текст все еще слишком большой, берем только первые 30000 символов
    if len(filtered_text) > 30000:
        return filtered_text[:30000] + "...[текст сокращен]"
    
    return filtered_text

def analyze_with_openai(text: str) -> Dict:
    """Анализирует кредитный отчет с помощью OpenAI GPT-3.5-turbo-16k"""
    try:
        # Фильтруем только важные разделы
        filtered_text = filter_important_sections(text)
        
        # Определяем язык отчета
        is_kazakh = "Жеке кредиттік есеп" in text or "ҚОЛДАНЫСТАҒЫ ШАРТТАР" in text
        
        # Формируем системное сообщение
        system_message = """
        Ты - эксперт по анализу кредитных отчетов Первого Кредитного Бюро (ПКБ) Казахстана, как на русском, так и на казахском языках.
        ВАЖНО: Текст, который будет предоставлен - это содержимое кредитного отчета, а НЕ запрос прикрепить файл.
        
        Проанализируй предоставленный кредитный отчет и верни ТОЛЬКО следующую информацию в формате JSON без дополнительного текста:
        {
            "personal_info": {
                "full_name": "ФИО клиента",
                "iin": "ИИН клиента (12 цифр)"
            },
            "total_debt": 0, // Общая сумма задолженности в тенге (включая мерзімі өткен жарналар сомасы)
            "total_monthly_payment": 0, // Примерный ежемесячный платеж по всем кредитам в тенге (ай сайынғы төлем)
            "total_obligations": 0, // Общее количество активных кредитов (Қолданыстағы міндеттемелер)
            "overdue_obligations": 0, // Количество кредитов с просрочкой
            "obligations": [
                {
                    "creditor": "Название кредитора",
                    "balance": 0, // Сумма долга в тенге (берешек қалдығы, шарт бойынша берешек)
                    "monthly_payment": 0, // Ежемесячный платеж в тенге (ай сайынғы төлем)
                    "overdue_days": 0 // Дни просрочки (мерзімі өткен күндер)
                }
            ],
            "language": "russian" // или "kazakh" в зависимости от языка отчета
        }
        
        ВСЁ, ЧТО ТЫ ДОЛЖЕН ВЕРНУТЬ - ЭТО ТОЛЬКО JSON ОБЪЕКТ БЕЗ КАКИХ-ЛИБО ПРЕДШЕСТВУЮЩИХ ИЛИ ПОСЛЕДУЮЩИХ СЛОВ.
        """
        
        # Формируем пользовательское сообщение
        user_message = """
        Ниже приведено содержимое кредитного отчета, который я уже загрузил. Пожалуйста, проанализируй его и извлеки информацию о кредитах и задолженностях.
        Верни ТОЛЬКО JSON объект с данными, без каких-либо дополнительных пояснений или текста.
        
        """
        
        # Добавляем первые 200 символов для отладки
        print(f"[DEBUG] First 200 chars of filtered text: {filtered_text[:200]}...")
        
        # Создаем клиент OpenAI с API ключом
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Запрос к OpenAI с новым синтаксисом
        response = client.chat.completions.create(
            model="gpt-3.5-turbo-16k",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message + filtered_text}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}  # Принудительно запрашиваем JSON
        )
        
        # Получаем содержимое ответа
        content = response.choices[0].message.content
        
        # Добавляем отладочный вывод
        print(f"[DEBUG] OpenAI response content: {content[:200]}...")
        
        # Проверка на пустой ответ
        if not content or content.isspace():
            print("[ERROR] OpenAI returned empty response")
            return {
                "personal_info": {},
                "total_debt": 0.0,
                "total_monthly_payment": 0.0,
                "total_obligations": 0,
                "overdue_obligations": 0,
                "obligations": [],
                "parsing_error": True,
                "error_message": "Получен пустой ответ от OpenAI"
            }
        
        # Очищаем и парсим JSON
        content = content.strip()
        result = json.loads(content)
        
        # Убедимся, что результат соответствует ожидаемой структуре
        if "personal_info" not in result or "total_debt" not in result:
            print("[ERROR] Incomplete JSON response from OpenAI")
            return {
                "personal_info": result.get("personal_info", {}),
                "total_debt": result.get("total_debt", 0.0),
                "total_monthly_payment": result.get("total_monthly_payment", 0.0),
                "total_obligations": result.get("total_obligations", 0),
                "overdue_obligations": result.get("overdue_obligations", 0),
                "obligations": result.get("obligations", []),
                "language": result.get("language", "russian")
            }
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON parsing error: {e}")
        return {
            "personal_info": {},
            "total_debt": 0.0,
            "total_monthly_payment": 0.0,
            "total_obligations": 0,
            "overdue_obligations": 0,
            "obligations": [],
            "parsing_error": True,
            "error_message": "Не удалось распарсить ответ OpenAI"
        }
    except Exception as e:
        print(f"[ERROR] OpenAI analysis error: {e}")
        return {
            "personal_info": {},
            "total_debt": 0.0,
            "total_monthly_payment": 0.0,
            "total_obligations": 0,
            "overdue_obligations": 0,
            "obligations": [],
            "parsing_error": True,
            "error_message": str(e)
        }