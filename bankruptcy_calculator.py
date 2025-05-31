import logging
import os
from typing import Dict, List, Tuple
from datetime import datetime

# Настройка логирования
DEBUG_MODE = os.getenv('DEBUG', 'False').lower() == 'true'

if DEBUG_MODE:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
else:
    logging.basicConfig(level=logging.CRITICAL)
    logger = logging.getLogger(__name__)
    logger.disabled = True

class BankruptcyCalculator:
    """Калькулятор для определения подходящей процедуры банкротства"""
    
    def __init__(self):
        # МРП на 2025 год в Казахстане = 3932 тенге
        self.MRP_2025 = 3932
        # Пороговая сумма для внесудебного банкротства: 1600 МРП
        self.THRESHOLD_AMOUNT = 1600 * self.MRP_2025  # 6,291,200 тенге
        # Минимальный срок просрочки для банкротства: 365 дней (12 месяцев)
        self.MIN_OVERDUE_DAYS = 365
    
    def analyze_bankruptcy_eligibility(self, parsed_data: Dict) -> Dict:
        """
        Анализирует возможность применения процедур банкротства
        
        Args:
            parsed_data: результат парсинга кредитного отчета
        
        Returns:
            Dict с рекомендациями по процедуре
        """
        try:
            # Извлекаем основные данные
            total_debt = parsed_data.get('total_debt', 0.0)
            obligations = parsed_data.get('obligations', [])
            collaterals = parsed_data.get('collaterals', [])
            personal_info = parsed_data.get('personal_info', {})

            # 🔁 Автоматический пересчёт, если total_debt отсутствует или равен 0
            if total_debt == 0 and obligations:
                total_debt = sum(o.get('balance', 0) for o in obligations)
                logger.warning("💡 total_debt рассчитан автоматически по сумме обязательств")
            
            logger.info(f"Анализ банкротства: долг={total_debt}, обязательств={len(obligations)}, залогов={len(collaterals)}")
            
            # Анализируем просрочку
            overdue_analysis = self._analyze_overdue_obligations(obligations)
            
            # Анализируем залоги
            collateral_analysis = self._analyze_collaterals(collaterals)
            
            # Определяем подходящую процедуру
            recommendation = self._determine_procedure(
                total_debt=total_debt,
                overdue_analysis=overdue_analysis,
                collateral_analysis=collateral_analysis
            )
            
            # Формируем детальный анализ
            detailed_analysis = self._create_detailed_analysis(
                total_debt=total_debt,
                obligations=obligations,
                collaterals=collaterals,
                overdue_analysis=overdue_analysis,
                collateral_analysis=collateral_analysis,
                recommendation=recommendation,
                personal_info=personal_info
            )
            
            return detailed_analysis
            
        except Exception as e:
            logger.error(f"Ошибка анализа банкротства: {e}")
            return {
                "error": True,
                "message": f"Ошибка при анализе: {str(e)}"
            }
    
    def _analyze_overdue_obligations(self, obligations: List[Dict]) -> Dict:
        """Анализирует просроченные обязательства"""
        
        total_overdue_creditors = 0
        max_overdue_days = 0
        min_overdue_days = float('inf')
        zero_days_creditors = []
        overdue_creditors = []
        
        for obligation in obligations:
            overdue_days = obligation.get('overdue_days', 0)
            creditor = obligation.get('creditor', 'Неизвестный')
            balance = obligation.get('balance', 0)
            
            if overdue_days > 0:
                total_overdue_creditors += 1
                max_overdue_days = max(max_overdue_days, overdue_days)
                min_overdue_days = min(min_overdue_days, overdue_days)
                overdue_creditors.append({
                    'creditor': creditor,
                    'days': overdue_days,
                    'amount': balance
                })
            elif overdue_days == 0 and balance > 0:
                zero_days_creditors.append({
                    'creditor': creditor,
                    'amount': balance
                })
        
        # Исправляем min_overdue_days если не было просрочек
        if min_overdue_days == float('inf'):
            min_overdue_days = 0
        
        meets_overdue_requirement = max_overdue_days > self.MIN_OVERDUE_DAYS
        
        return {
            'total_overdue_creditors': total_overdue_creditors,
            'max_overdue_days': max_overdue_days,
            'min_overdue_days': min_overdue_days,
            'meets_overdue_requirement': meets_overdue_requirement,
            'zero_days_creditors': zero_days_creditors,
            'overdue_creditors': overdue_creditors
        }
    
    def _analyze_collaterals(self, collaterals: List[Dict]) -> Dict:
        """Анализирует залоговое имущество с исключением ломбардов"""
        
        # Фильтруем залоги - исключаем ломбарды и мелкие залоги
        significant_collaterals = []
        excluded_collaterals = []
        
        # Минимальная стоимость залога для учета в банкротстве (1 млн тенге)
        MIN_COLLATERAL_VALUE = 1000000
        
        for collateral in collaterals:
            creditor_name = collateral.get('creditor', '').lower()
            collateral_value = collateral.get('market_value', 0)
            
            # Определяем, является ли это ломбардом или мелким залогом
            is_pawnshop = any(keyword in creditor_name for keyword in [
                'ломбард', 'lombard', 'pawnshop', 'залог', 
                'заложи', 'золото', 'ювели'
            ])
            
            is_small_collateral = collateral_value < MIN_COLLATERAL_VALUE
            
            # Исключаем ломбарды и мелкие залоги
            if is_pawnshop or is_small_collateral:
                excluded_collaterals.append({
                    'creditor': collateral.get('creditor', 'Неизвестный'),
                    'type': collateral.get('collateral_type', 'Неизвестный тип'),
                    'value': collateral_value,
                    'exclusion_reason': 'ломбард' if is_pawnshop else 'мелкий залог'
                })
            else:
                significant_collaterals.append({
                    'creditor': collateral.get('creditor', 'Неизвестный'),
                    'type': collateral.get('collateral_type', 'Неизвестный тип'),
                    'value': collateral_value
                })
        
        # Считаем только значимые залоги
        has_significant_collaterals = len(significant_collaterals) > 0
        total_significant_value = sum(c['value'] for c in significant_collaterals)
        total_excluded_value = sum(c['value'] for c in excluded_collaterals)
        
        logger.info(f"Залоги: значимых={len(significant_collaterals)}, исключено={len(excluded_collaterals)}")
        logger.info(f"Стоимость: значимых={total_significant_value:,.0f}, исключено={total_excluded_value:,.0f}")
        
        return {
            'has_collaterals': has_significant_collaterals,  # Только значимые залоги влияют на банкротство
            'total_value': total_significant_value,
            'count': len(significant_collaterals),
            'details': significant_collaterals,
            'excluded_collaterals': excluded_collaterals,  # Для информации
            'excluded_count': len(excluded_collaterals),
            'excluded_value': total_excluded_value
        }
    
    def _determine_procedure(self, total_debt: float, overdue_analysis: Dict, collateral_analysis: Dict) -> Dict:
        """Определяет подходящую процедуру банкротства"""
        
        debt_below_threshold = total_debt < self.THRESHOLD_AMOUNT
        meets_overdue_requirement = overdue_analysis['meets_overdue_requirement']
        has_collaterals = collateral_analysis['has_collaterals']
        has_zero_days_creditors = len(overdue_analysis['zero_days_creditors']) > 0
        
        logger.info(f"Критерии: долг<порога={debt_below_threshold}, просрочка>365={meets_overdue_requirement}, залоги={has_collaterals}")
        
        # Логика определения процедуры
        if not meets_overdue_requirement:
            # Если просрочка меньше 365 дней
            return {
                'procedure': 'restoration',
                'title': 'Восстановление платежеспособности',
                'reason': 'insufficient_overdue',
                'description': 'Максимальная просрочка менее 365 дней'
            }
        
        elif debt_below_threshold and not has_collaterals:
            # Внесудебное банкротство
            return {
                'procedure': 'extrajudicial',
                'title': 'Внесудебное банкротство',
                'reason': 'meets_extrajudicial_criteria',
                'description': 'Долг менее 6,291,200 ₸, просрочка более 365 дней, нет залогов'
            }
        
        else:
            # Судебное банкротство
            reasons = []
            if not debt_below_threshold:
                reasons.append('долг превышает 6,291,200 ₸')
            if has_collaterals:
                reasons.append('имеется залоговое имущество')
            
            return {
                'procedure': 'judicial',
                'title': 'Судебное банкротство',
                'reason': 'requires_judicial',
                'description': f"Требуется судебная процедура: {', '.join(reasons)}"
            }
    
    def _create_detailed_analysis(self, total_debt: float, obligations: List[Dict], 
                                collaterals: List[Dict], overdue_analysis: Dict, 
                                collateral_analysis: Dict, recommendation: Dict,
                                personal_info: Dict) -> Dict:
        """Создает детальный анализ с рекомендациями"""
        
        return {
            'personal_info': personal_info,
            'financial_summary': {
                'total_debt': total_debt,
                'threshold_amount': self.THRESHOLD_AMOUNT,
                'debt_below_threshold': total_debt < self.THRESHOLD_AMOUNT,
                'total_obligations': len(obligations)
            },
            'overdue_analysis': overdue_analysis,
            'collateral_analysis': collateral_analysis,
            'recommendation': recommendation,
            'detailed_conditions': self._check_all_conditions(total_debt, overdue_analysis, collateral_analysis),
            'next_steps': self._generate_next_steps(recommendation, overdue_analysis),
            'warnings': self._generate_warnings(overdue_analysis, collateral_analysis)
        }
    
    def _check_all_conditions(self, total_debt: float, overdue_analysis: Dict, collateral_analysis: Dict) -> Dict:
        """Проверяет все условия для разных процедур"""
        
        return {
            'extrajudicial': {
                'debt_requirement': {
                    'met': total_debt < self.THRESHOLD_AMOUNT,
                    'description': f'Долг менее {self.THRESHOLD_AMOUNT:,.0f} ₸',
                    'current_value': total_debt
                },
                'overdue_requirement': {
                    'met': overdue_analysis['meets_overdue_requirement'],
                    'description': 'Просрочка более 365 дней',
                    'current_value': overdue_analysis['max_overdue_days']
                },
                'collateral_requirement': {
                    'met': not collateral_analysis['has_collaterals'],
                    'description': 'Отсутствие залогового имущества',
                    'current_value': collateral_analysis['count']
                }
            },
            'judicial': {
                'debt_or_collateral': {
                    'met': total_debt >= self.THRESHOLD_AMOUNT or collateral_analysis['has_collaterals'],
                    'description': 'Долг свыше 6,291,200 ₸ или наличие залогов',
                    'current_debt': total_debt,
                    'has_collaterals': collateral_analysis['has_collaterals']
                },
                'overdue_requirement': {
                    'met': overdue_analysis['meets_overdue_requirement'],
                    'description': 'Просрочка более 365 дней',
                    'current_value': overdue_analysis['max_overdue_days']
                }
            },
            'restoration': {
                'applicable_when': 'Просрочка менее 365 дней или есть стабильный доход'
            }
        }
    
    def _generate_next_steps(self, recommendation: Dict, overdue_analysis: Dict) -> List[str]:
        """Генерирует рекомендации по дальнейшим действиям"""
        
        steps = []
        procedure = recommendation['procedure']
        
        if procedure == 'extrajudicial':
            steps = [
                "1. Убедитесь, что выполнены процедуры урегулирования с кредиторами",
                "2. Подготовьте документы для подачи в уполномоченный орган",
                "3. Подайте заявление о внесудебном банкротстве",
                "4. Дождитесь рассмотрения заявления (до 6 месяцев)"
            ]
        
        elif procedure == 'judicial':
            steps = [
                "1. Проведите процедуры урегулирования с кредиторами",
                "2. Подготовьте полный пакет документов",
                "3. Подайте заявление в суд о банкротстве",
                "4. Участвуйте в судебном процессе"
            ]
        
        else:  # restoration
            steps = [
                "1. Обратитесь к кредиторам для переговоров",
                "2. Предложите план реструктуризации долга",
                "3. Рассмотрите возможность рефинансирования",
                "4. При необходимости подайте на восстановление платежеспособности"
            ]
        
        # Добавляем специальные рекомендации для случаев с нулевой просрочкой
        if overdue_analysis['zero_days_creditors']:
            steps.append("⚠️ Уточните фактические дни просрочки у кредиторов с нулевыми показателями")
        
        return steps
    
    def _generate_warnings(self, overdue_analysis: Dict, collateral_analysis: Dict) -> List[str]:
        """Генерирует предупреждения и замечания"""
        
        warnings = []
        
        # Предупреждения о кредиторах с нулевой просрочкой
        if overdue_analysis['zero_days_creditors']:
            creditor_names = [c['creditor'] for c in overdue_analysis['zero_days_creditors']]
            warnings.append(
                f"⚠️ Обнаружены кредиторы без указания дней просрочки: {', '.join(creditor_names)}. "
                "Рекомендуется уточнить фактическое состояние задолженности."
            )
        
        # В функции _generate_warnings замените раздел с залогами на:

        # Предупреждения о значимых залогах
        if collateral_analysis['has_collaterals']:
            warnings.append(
                f"🔒 Обнаружено {collateral_analysis['count']} значимых залоговых объектов на сумму "
                f"{collateral_analysis['total_value']:,.2f} ₸. При банкротстве залоги могут быть реализованы."
            )

        # Информация об исключенных залогах
        excluded_count = collateral_analysis.get('excluded_count', 0)
        if excluded_count > 0:
            warnings.append(
                f"📝 Исключено из анализа {excluded_count} мелких залогов/ломбардов на сумму "
                f"{collateral_analysis.get('excluded_value', 0):,.2f} ₸ (не влияют на процедуру)."
            )
        
        # Общие предупреждения
        warnings.append(
            "📋 Данный расчет носит предварительный характер. "
            "Окончательное решение принимается уполномоченными органами."
        )
        
        return warnings

def format_bankruptcy_analysis(analysis: Dict) -> str:
    """Форматирует результат анализа банкротства для пользователя"""
    
    if analysis.get('error'):
        return f"❌ Ошибка анализа банкротства: {analysis.get('message', 'Неизвестная ошибка')}"
    
    # Заголовок
    result = "🧮 **БАНКРОТНЫЙ КАЛЬКУЛЯТОР**\n\n"
    
    # Основная рекомендация
    recommendation = analysis['recommendation']
    procedure_icons = {
        'extrajudicial': '⚖️',
        'judicial': '🏛️',
        'restoration': '🔄'
    }
    
    icon = procedure_icons.get(recommendation['procedure'], '📋')
    result += f"{icon} **РЕКОМЕНДАЦИЯ: {recommendation['title'].upper()}**\n"
    result += f"📄 Основание: {recommendation['description']}\n\n"
    
    # Финансовая сводка
    financial = analysis['financial_summary']
    result += "💰 **Финансовые показатели:**\n"
    result += f"— Общая задолженность: {financial['total_debt']:,.2f} ₸\n"
    result += f"— Пороговая сумма (1600 МРП): {financial['threshold_amount']:,.2f} ₸\n"
    result += f"— Всего обязательств: {financial['total_obligations']}\n\n"
    
    # Анализ просрочки
    overdue = analysis['overdue_analysis']
    result += "⏰ **Анализ просрочки:**\n"
    result += f"— Максимальная просрочка: {overdue['max_overdue_days']} дней\n"
    result += f"— Кредиторов с просрочкой: {overdue['total_overdue_creditors']}\n"
    
    if overdue['zero_days_creditors']:
        result += f"— ⚠️ Кредиторов без указания просрочки: {len(overdue['zero_days_creditors'])}\n"
    
    result += f"— Требование по просрочке (>365 дней): {'✅ Выполнено' if overdue['meets_overdue_requirement'] else '❌ Не выполнено'}\n\n"
    
    # Анализ залогов (замените этот раздел в функции format_bankruptcy_analysis)
    collateral = analysis['collateral_analysis']

    if collateral['has_collaterals'] or collateral.get('excluded_count', 0) > 0:
        result += "🔒 **Залоговое имущество:**\n"
        
        # Показываем значимые залоги (влияющие на банкротство)
        if collateral['has_collaterals']:
            result += f"— Значимых объектов: {collateral['count']}\n"
            result += f"— Общая стоимость: {collateral['total_value']:,.2f} ₸\n"
            for detail in collateral['details']:
                result += f"  • {detail['creditor']}: {detail['type']} ({detail['value']:,.2f} ₸)\n"
        
        # Показываем исключенные залоги (не влияющие на банкротство)
        excluded = collateral.get('excluded_collaterals', [])
        if excluded:
            result += f"\n📝 Исключено из анализа ({collateral['excluded_count']} объектов на {collateral['excluded_value']:,.2f} ₸):\n"
            for exc in excluded[:3]:  # Показываем только первые 3
                reason = "🏪 ломбард" if exc['exclusion_reason'] == 'ломбард' else "💰 < 1 млн ₸"
                result += f"  • {exc['creditor']}: {exc['type']} ({reason})\n"
            
            if len(excluded) > 3:
                result += f"  • ... и еще {len(excluded) - 3} объектов\n"
            
            result += f"\n💡 *Мелкие залоги и ломбарды не влияют на выбор процедуры банкротства*\n"
        
        result += "\n"
    else:
        result += "🔒 **Залоговое имущество:** Отсутствует\n\n"
    
    # Детальная проверка условий
    conditions = analysis['detailed_conditions']
    if recommendation['procedure'] in ['extrajudicial', 'judicial']:
        result += f"📋 **Проверка условий для {recommendation['title'].lower()}:**\n"
        
        if recommendation['procedure'] == 'extrajudicial':
            ext_conditions = conditions['extrajudicial']
            result += f"— Размер долга: {'✅' if ext_conditions['debt_requirement']['met'] else '❌'} "
            result += f"({ext_conditions['debt_requirement']['current_value']:,.2f} ₸)\n"
            
            result += f"— Срок просрочки: {'✅' if ext_conditions['overdue_requirement']['met'] else '❌'} "
            result += f"({ext_conditions['overdue_requirement']['current_value']} дней)\n"
            
            result += f"— Отсутствие залогов: {'✅' if ext_conditions['collateral_requirement']['met'] else '❌'} "
            result += f"({ext_conditions['collateral_requirement']['current_value']} объектов)\n"
        
        else:  # judicial
            jud_conditions = conditions['judicial']
            result += f"— Долг или залоги: {'✅' if jud_conditions['debt_or_collateral']['met'] else '❌'}\n"
            result += f"— Срок просрочки: {'✅' if jud_conditions['overdue_requirement']['met'] else '❌'} "
            result += f"({jud_conditions['overdue_requirement']['current_value']} дней)\n"
        
        result += "\n"
    
    # Следующие шаги
    result += "📝 **Рекомендуемые действия:**\n"
    for step in analysis['next_steps']:
        result += f"{step}\n"
    result += "\n"
    
    # Предупреждения
    if analysis['warnings']:
        result += "⚠️ **Важные замечания:**\n"
        for warning in analysis['warnings']:
            result += f"{warning}\n"
    
    return result

def analyze_credit_report_for_bankruptcy(parsed_data: Dict) -> str:
    """
    Основная функция для анализа кредитного отчета на предмет банкротства
    
    Args:
        parsed_data: результат парсинга кредитного отчета
    
    Returns:
        str: отформатированный анализ для пользователя
    """
    calculator = BankruptcyCalculator()
    analysis = calculator.analyze_bankruptcy_eligibility(parsed_data)
    return format_bankruptcy_analysis(analysis)

# Интеграционная функция для использования в document_processor
def process_credit_report_with_bankruptcy_analysis(filepath: str, user_id: int) -> Dict:
    """
    Обрабатывает кредитный отчет с анализом банкротства
    Функция для интеграции в document_processor.py
    """
    from document_processor import process_uploaded_file
    from credit_parser import extract_credit_data_with_total
    from text_extractor import extract_text_from_pdf
    from ocr import ocr_file
    
    # Сначала обрабатываем как обычно
    result = process_uploaded_file(filepath, user_id)
    
    if result.get("type") == "credit_report":
        try:
            # Извлекаем текст
            text = extract_text_from_pdf(filepath)
            if not text.strip():
                text = ocr_file(filepath)
            
            # Парсим данные
            parsed_data = extract_credit_data_with_total(text)
            
            # Добавляем анализ банкротства
            bankruptcy_analysis = analyze_credit_report_for_bankruptcy(parsed_data)
            
            # Добавляем к результату
            result['bankruptcy_analysis'] = bankruptcy_analysis
            result['bankruptcy_data'] = parsed_data
            
        except Exception as e:
            logger.error(f"Ошибка анализа банкротства: {e}")
            result['bankruptcy_analysis'] = f"❌ Ошибка анализа банкротства: {str(e)}"
    
    return result