from credit_parser import create_parser_chain

def test_full_integration():
    with open('debug_text_output_376068212_972e044a.txt', 'r', encoding='utf-8') as f:
        text = f.read()
    
    parser = create_parser_chain()
    result = parser.parse(text)
    
    print("🔍 ПРОВЕРКА ПОЛНОЙ ИНТЕГРАЦИИ:")
    print(f"  Тип отчета: {result.get('report_type')}")
    print(f"  Готовность к банкротству: {result.get('bankruptcy_ready')}")
    
    # Проверяем все обязательства
    contracts_with_data = 0
    for obl in result['obligations']:
        if (obl.get('contract_number', 'НЕ НАЙДЕН') != 'НЕ НАЙДЕН' and 
            obl.get('debt_origin_date', 'НЕ НАЙДЕНА') != 'НЕ НАЙДЕНА'):
            contracts_with_data += 1
    
    print(f"  Договоров с полными данными: {contracts_with_data}/{len(result['obligations'])}")
    
    if contracts_with_data == len(result['obligations']):
        print("  🎯 ИНТЕГРАЦИЯ УСПЕШНА!")
        return True
    else:
        print("  ⚠️ Некоторые данные отсутствуют")
        return False

if __name__ == "__main__":
    test_full_integration()