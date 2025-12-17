#!/bin/bash

# ═══════════════════════════════════════════════════════════════
#  Futures Bot - Management Panel
# ═══════════════════════════════════════════════════════════════

set -e

# Конфигурация
SSH_HOST="kpeezy"
REMOTE_DIR="/root/futures-bot"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="futures-bot"
PYTHON_VERSION="python3"

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_header() {
    echo -e "${CYAN}"
    echo "╔════════════════════════════════════════════╗"
    echo "║       🤖 Futures Bot Management            ║"
    echo "╚════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_menu() {
    echo -e "${YELLOW}Выберите действие:${NC}"
    echo ""
    echo -e "  ${GREEN}1)${NC} deploy   - Полный деплой (sync + venv + deps + restart)"
    echo -e "  ${GREEN}2)${NC} start    - Запустить бота"
    echo -e "  ${GREEN}3)${NC} restart  - Перезапустить бота"
    echo -e "  ${GREEN}4)${NC} stop     - Остановить бота"
    echo -e "  ${GREEN}5)${NC} status   - Статус сервиса"
    echo -e "  ${GREEN}6)${NC} logs     - Логи (realtime + 500 последних)"
    echo -e "  ${GREEN}7)${NC} errors   - Просмотр errors.log"
    echo -e "  ${GREEN}8)${NC} sync     - Только rsync файлов"
    echo -e "  ${GREEN}9)${NC} ssh      - Подключиться к серверу"
    echo -e "  ${GREEN}0)${NC} exit     - Выход"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
#  Функции
# ═══════════════════════════════════════════════════════════════

do_sync() {
    echo -e "${BLUE}📦 Синхронизация файлов...${NC}"
    rsync -avz --progress \
        --exclude 'venv/' \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude '.git/' \
        --exclude '*.log' \
        --exclude '.claude/' \
        --exclude 'storage/charts/' \
        --exclude '*.db' \
        "$LOCAL_DIR/" "$SSH_HOST:$REMOTE_DIR/"
    echo -e "${GREEN}✅ Синхронизация завершена${NC}"
}

do_setup_venv() {
    echo -e "${BLUE}🐍 Настройка виртуального окружения...${NC}"
    ssh "$SSH_HOST" "cd $REMOTE_DIR && \
        if [ ! -d 'venv' ]; then \
            echo 'Создание venv...' && \
            $PYTHON_VERSION -m venv venv; \
        fi && \
        ./venv/bin/pip install --upgrade pip && \
        ./venv/bin/pip install -r requirements.txt"
    echo -e "${GREEN}✅ Зависимости установлены${NC}"
}

do_setup_service() {
    echo -e "${BLUE}⚙️ Настройка systemd сервиса...${NC}"
    ssh "$SSH_HOST" << 'SERVICEEOF'
cat > /etc/systemd/system/futures-bot.service << 'EOF'
[Unit]
Description=Futures Trading Bot
After=network.target redis.service postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/futures-bot
Environment=PATH=/root/futures-bot/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/root/futures-bot/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=append:/root/futures-bot/bot.log
StandardError=append:/root/futures-bot/errors.log

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable futures-bot
SERVICEEOF
    echo -e "${GREEN}✅ Сервис настроен${NC}"
}

do_deploy() {
    echo -e "${CYAN}🚀 Запуск полного деплоя...${NC}"
    echo ""
    do_sync
    echo ""
    do_setup_venv
    echo ""
    do_setup_service
    echo ""
    do_restart
    echo ""
    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo -e "${GREEN}✅ Деплой успешно завершён!${NC}"
    echo -e "${GREEN}════════════════════════════════════════${NC}"
}

do_start() {
    echo -e "${BLUE}▶️ Запуск бота...${NC}"
    ssh "$SSH_HOST" "systemctl start $SERVICE_NAME"
    sleep 2
    do_status
}

do_restart() {
    echo -e "${BLUE}🔄 Перезапуск бота...${NC}"
    ssh "$SSH_HOST" "systemctl restart $SERVICE_NAME"
    sleep 2
    do_status
}

do_stop() {
    echo -e "${BLUE}⏹️ Остановка бота...${NC}"
    ssh "$SSH_HOST" "systemctl stop $SERVICE_NAME"
    echo -e "${YELLOW}Бот остановлен${NC}"
}

do_status() {
    echo -e "${BLUE}📊 Статус сервиса:${NC}"
    echo ""
    ssh "$SSH_HOST" "systemctl status $SERVICE_NAME --no-pager" || true
}

do_logs() {
    echo -e "${BLUE}📜 Логи (Ctrl+C для выхода):${NC}"
    echo -e "${YELLOW}--- Последние 500 строк + realtime ---${NC}"
    echo ""
    ssh "$SSH_HOST" "tail -n 500 -f $REMOTE_DIR/bot.log"
}

do_errors() {
    echo -e "${RED}❌ Errors.log (последние 200 строк):${NC}"
    echo ""
    ssh "$SSH_HOST" "tail -n 200 $REMOTE_DIR/errors.log"
    echo ""
    echo -e "${YELLOW}Для realtime: ssh $SSH_HOST 'tail -f $REMOTE_DIR/errors.log'${NC}"
}

do_ssh() {
    echo -e "${BLUE}🔗 Подключение к серверу...${NC}"
    ssh "$SSH_HOST"
}

# ═══════════════════════════════════════════════════════════════
#  Обработка аргументов
# ═══════════════════════════════════════════════════════════════

if [ $# -gt 0 ]; then
    case "$1" in
        deploy)  do_deploy ;;
        start)   do_start ;;
        restart) do_restart ;;
        stop)    do_stop ;;
        status)  do_status ;;
        logs)    do_logs ;;
        errors)  do_errors ;;
        sync)    do_sync ;;
        ssh)     do_ssh ;;
        *)
            echo -e "${RED}Неизвестная команда: $1${NC}"
            echo "Использование: $0 {deploy|start|restart|stop|status|logs|errors|sync|ssh}"
            exit 1
            ;;
    esac
    exit 0
fi

# ═══════════════════════════════════════════════════════════════
#  Интерактивное меню
# ═══════════════════════════════════════════════════════════════

while true; do
    clear
    print_header
    print_menu

    read -p "Выбор: " choice
    echo ""

    case $choice in
        1|deploy)  do_deploy; read -p "Нажмите Enter..." ;;
        2|start)   do_start; read -p "Нажмите Enter..." ;;
        3|restart) do_restart; read -p "Нажмите Enter..." ;;
        4|stop)    do_stop; read -p "Нажмите Enter..." ;;
        5|status)  do_status; read -p "Нажмите Enter..." ;;
        6|logs)    do_logs ;;
        7|errors)  do_errors; read -p "Нажмите Enter..." ;;
        8|sync)    do_sync; read -p "Нажмите Enter..." ;;
        9|ssh)     do_ssh ;;
        0|exit|q)  echo -e "${GREEN}👋 До свидания!${NC}"; exit 0 ;;
        *)         echo -e "${RED}Неверный выбор${NC}"; sleep 1 ;;
    esac
done
