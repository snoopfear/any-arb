#!/bin/bash

# Подгружаем переменные окружения
source ~/.bashrc


# Проверка и установка Python3 и pip
if ! command -v python3 &>/dev/null; then
    echo "Python3 не найден. Устанавливаю..."
    sudo apt update && sudo apt install -y python3
fi

if ! command -v pip3 &>/dev/null; then
    echo "pip3 не найден. Устанавливаю..."
    sudo apt update && sudo apt install -y python3-pip
fi

# Проверка и установка Python-библиотек web3 и requests
if ! python3 -c "import web3" &>/dev/null; then
    echo "Python-библиотека 'web3' не найдена. Устанавливаю..."
    python3 -m pip install --upgrade pip
    python3 -m pip install web3 requests
fi


# Название папки и screen-сессии
PROJECT_DIR=~/any-arb
SESSION_NAME="any-arb"

echo "Создание папки проекта..."
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

echo "Скачивание main.py..."
curl -s https://raw.githubusercontent.com/snoopfear/any-arb/refs/heads/main/main.py -o main.py

echo "Установка завершена ✅"

echo "Запуск в новой screen-сессии '$SESSION_NAME'..."
screen -S "$SESSION_NAME" -X quit 2>/dev/null
screen -dmS "$SESSION_NAME"
sleep 1  # Дать screen время запуститься
screen -S "$SESSION_NAME" -X stuff "cd $PROJECT_DIR && python3 main.py\n"

echo "✅ Скрипт запущен в screen!"
echo "Подключиться: screen -r $SESSION_NAME"
echo "Отключиться: Ctrl+A, затем D"
