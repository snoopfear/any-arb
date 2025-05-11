#!/bin/bash

# Подгружаем переменные окружения
source ~/.bashrc

# Название папки и screen-сессии
PROJECT_DIR=~/any-arb
SESSION_NAME="any-arb"

echo "Создание папки проекта..."
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

echo "Скачивание main.py..."
curl -s https://raw.githubusercontent.com/yourusername/any-arb-installer/main/main.py -o main.py

echo "Установка завершена ✅"

echo "Запуск в новой screen-сессии '$SESSION_NAME'..."
screen -S "$SESSION_NAME" -X quit 2>/dev/null
screen -dmS "$SESSION_NAME" bash -c "cd $PROJECT_DIR && python3 main.py"

echo "✅ Скрипт запущен в screen!"
echo "Подключиться: screen -r $SESSION_NAME"
echo "Отключиться: Ctrl+A, затем D"
