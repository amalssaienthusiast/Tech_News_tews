#!/bin/sh
# ==============================================================================
# Start Tech News Scraper in background using nohup (pure POSIX /bin/sh compliant)
# ==============================================================================

# Resolve project root
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

if [ ! -f "$PROJECT_DIR/main_engine.py" ]; then
    if [ -f "$PWD/main_engine.py" ]; then
        PROJECT_DIR="$PWD"
    elif [ -f "$PWD/../main_engine.py" ]; then
        PROJECT_DIR=$(cd "$PWD/.." && pwd)
    elif [ -d "/home/pi/Tech_News_Scrapper" ]; then
        PROJECT_DIR="/home/pi/Tech_News_Scrapper"
    fi
fi

cd "$PROJECT_DIR"

# Use virtualenv python if available, otherwise default python3
if [ -f "$PROJECT_DIR/env/bin/python3" ]; then
    PYTHON_BIN="$PROJECT_DIR/env/bin/python3"
elif [ -f "$PROJECT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
else
    PYTHON_BIN=$(command -v python3 || echo "python3")
fi

mkdir -p "$PROJECT_DIR/logs"

echo "🧹 Cleaning up any existing instances..."
pkill -f "main_engine.py" 2>/dev/null || true
pkill -f "telegram_feeder_bot.py" 2>/dev/null || true
sleep 1

echo "🚀 Starting Main Engine in background..."
nohup $PYTHON_BIN main_engine.py --port 8080 > logs/engine.log 2>&1 &
ENGINE_PID=$!
echo $ENGINE_PID > logs/engine.pid
echo "   Engine started (PID: $ENGINE_PID). Logs at logs/engine.log"

echo "⏳ Waiting 3 seconds for Engine to initialize..."
sleep 3

echo "🤖 Starting Telegram Feeder Bot in background..."
nohup $PYTHON_BIN telegram_feeder_bot.py --engine-url http://localhost:8080 > logs/bot.log 2>&1 &
BOT_PID=$!
echo $BOT_PID > logs/bot.pid
echo "   Telegram Bot started (PID: $BOT_PID). Logs at logs/bot.log"

echo "
================================================================
✅ Both processes are now running in the background!
   You can safely close/terminate your SSH terminal.
================================================================
Commands to monitor:
   tail -f logs/engine.log
   tail -f logs/bot.log

To stop processes:
   sh scripts/stop_background.sh
================================================================
"
