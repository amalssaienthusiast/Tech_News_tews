#!/bin/sh
# ==============================================================================
# Stop background nohup processes (pure POSIX /bin/sh compliant)
# ==============================================================================

echo "🛑 Stopping background Tech News Scraper processes..."

if [ -f "logs/engine.pid" ]; then
    PID=$(cat logs/engine.pid 2>/dev/null || true)
    if [ -n "$PID" ]; then
        kill "$PID" 2>/dev/null || true
        echo "   Stopped Main Engine (PID: $PID)"
    fi
    rm -f logs/engine.pid
fi

if [ -f "logs/bot.pid" ]; then
    PID=$(cat logs/bot.pid 2>/dev/null || true)
    if [ -n "$PID" ]; then
        kill "$PID" 2>/dev/null || true
        echo "   Stopped Telegram Bot (PID: $PID)"
    fi
    rm -f logs/bot.pid
fi

# Fallback cleanup
pkill -f "main_engine.py" 2>/dev/null || true
pkill -f "telegram_feeder_bot.py" 2>/dev/null || true

echo "✅ Background processes stopped."
