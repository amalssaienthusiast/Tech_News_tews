#!/bin/sh
# ==============================================================================
# Tech News Scrapper — 1-Click Systemd Auto-Start Installer for Raspberry Pi
# Pure POSIX /bin/sh compliant (works with sh, dash, bash, zsh)
# ==============================================================================

set -e

# 1. Resolve project directory robustly (pure POSIX sh)
PRG="$0"
while [ -L "$PRG" ]; do
    ls=$(ls -ld "$PRG")
    link=$(expr "$ls" : '.*-> \(.*\)$')
    if expr "$link" : '/.*' > /dev/null; then
        PRG="$link"
    else
        PRG=$(dirname "$PRG")/"$link"
    fi
done

SCRIPT_DIR=$(cd "$(dirname "$PRG")" 2>/dev/null && pwd)
PROJECT_DIR=$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)

# Safety fallback: if main_engine.py is in PWD or PWD/..
if [ ! -f "$PROJECT_DIR/main_engine.py" ]; then
    if [ -f "$PWD/main_engine.py" ]; then
        PROJECT_DIR="$PWD"
    elif [ -f "$PWD/../main_engine.py" ]; then
        PROJECT_DIR=$(cd "$PWD/.." && pwd)
    elif [ -d "/home/pi/Tech_News_Scrapper" ]; then
        PROJECT_DIR="/home/pi/Tech_News_Scrapper"
    fi
fi

CURRENT_USER=$(whoami)

echo "================================================================"
echo "  Tech News Scrapper — Auto-Start Setup (Systemd Boot Service)  "
echo "================================================================"
echo "📁 Project Directory: $PROJECT_DIR"
echo "👤 User:               $CURRENT_USER"

# 2. Detect Python Binary
if [ -f "$PROJECT_DIR/env/bin/python3" ]; then
    PYTHON_BIN="$PROJECT_DIR/env/bin/python3"
elif [ -f "$PROJECT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
else
    PYTHON_BIN=$(command -v python3 || echo "/usr/bin/python3")
fi
echo "🐍 Python Interpreter: $PYTHON_BIN"

# 3. Stop any old nohup instances before switching to systemd
echo "🧹 Stopping any existing background processes..."
pkill -f "main_engine.py" 2>/dev/null || true
pkill -f "telegram_feeder_bot.py" 2>/dev/null || true

# 4. Create Main Engine Systemd Service Unit
ENGINE_SERVICE="/etc/systemd/system/technews-engine.service"
echo "⚙️ Creating Engine service at $ENGINE_SERVICE..."

sudo tee "$ENGINE_SERVICE" > /dev/null <<EOF
[Unit]
Description=Tech News Scraper Main Engine
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN main_engine.py --port 8080
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# 5. Create Telegram Bot Systemd Service Unit
BOT_SERVICE="/etc/systemd/system/technews-bot.service"
echo "⚙️ Creating Telegram Bot service at $BOT_SERVICE..."

sudo tee "$BOT_SERVICE" > /dev/null <<EOF
[Unit]
Description=Tech News Scraper Telegram Feeder Bot
After=network-online.target technews-engine.service
Wants=network-online.target technews-engine.service

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN telegram_feeder_bot.py --engine-url http://localhost:8080
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# 6. Reload systemd daemon and enable services for automatic boot
echo "🔄 Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "🚀 Enabling services to start automatically on Raspberry Pi boot..."
sudo systemctl enable technews-engine.service
sudo systemctl enable technews-bot.service

echo "▶️ Starting services now..."
sudo systemctl restart technews-engine.service
sleep 3
sudo systemctl restart technews-bot.service

echo "
================================================================
✅ SUCCESS! Auto-start is fully configured.
================================================================
Both services are now managed by Raspberry Pi's systemd:
 • They will start automatically whenever the Raspberry Pi turns ON.
 • You DO NOT need to SSH into the Pi to start them.
 • If a crash or network drop occurs, systemd restarts them automatically.
 • You can safely close your SSH terminal right now.

Useful commands on your Pi:
 • Check status:   sh scripts/services.sh status
 • View live logs: sh scripts/services.sh logs
 • Restart:        sh scripts/services.sh restart
 • Stop:           sh scripts/services.sh stop
================================================================
"
