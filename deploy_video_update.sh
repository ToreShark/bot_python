#!/bin/bash
# Скрипт для быстрого развертывания обновления видеоканала

echo "🚀 РАЗВЕРТЫВАНИЕ ОБНОВЛЕНИЯ ВИДЕОКАНАЛА"
echo "========================================"

# Проверка, что мы на правильном сервере
read -p "⚠️  Это продакшн сервер? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "❌ Развертывание отменено"
    exit 1
fi

echo "📥 1. Обновляем код..."
git pull origin main || git fetch && git merge

echo "📊 2. Проверяем текущее состояние..."
python quick_prod_check.py
if [ $? -eq 0 ]; then
    echo "✅ Система уже обновлена!"
    exit 0
fi

echo "🔄 3. Обновляем базу данных..."
python seed_video_production.py

echo "🔄 4. Перезапускаем бота..."
pkill -f "python main.py"
sleep 2
nohup python main.py > bot.log 2>&1 &
echo "✅ Бот перезапущен (PID: $!)"

echo "🔍 5. Финальная проверка..."
sleep 3
python quick_prod_check.py

if [ $? -eq 0 ]; then
    echo "🎉 РАЗВЕРТЫВАНИЕ УСПЕШНО ЗАВЕРШЕНО!"
else
    echo "⚠️  Развертывание завершено с предупреждениями"
    echo "📋 Смотрите инструкции в PRODUCTION_DEPLOY.md"
fi