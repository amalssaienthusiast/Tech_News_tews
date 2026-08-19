#!/bin/sh
# ==============================================================================
# Tech News Scrapper — Quick Service Management Helper for Raspberry Pi
# Pure POSIX /bin/sh compliant
# ==============================================================================

ACTION="${1:-status}"

case "$ACTION" in
    status)
        echo "📊 Main Engine Service Status:"
        sudo systemctl status technews-engine.service --no-pager -n 5 2>/dev/null || true
        echo ""
        echo "🤖 Telegram Bot Service Status:"
        sudo systemctl status technews-bot.service --no-pager -n 5 2>/dev/null || true
        ;;
    logs)
        echo "📜 Showing live unified logs (Ctrl+C to exit)..."
        sudo journalctl -u technews-engine.service -u technews-bot.service -f -o short-iso
        ;;
    logs-engine)
        echo "📜 Showing Main Engine logs (Ctrl+C to exit)..."
        sudo journalctl -u technews-engine.service -f -o short-iso
        ;;
    logs-bot)
        echo "📜 Showing Telegram Bot logs (Ctrl+C to exit)..."
        sudo journalctl -u technews-bot.service -f -o short-iso
        ;;
    start)
        echo "🚀 Starting services..."
        sudo systemctl start technews-engine.service technews-bot.service
        echo "✅ Services started."
        ;;
    stop|maintenance|stop-all)
        echo "🛑 Executing full system shutdown..."
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
        if [ -f "$SCRIPT_DIR/stop_entire_system.sh" ]; then
            sh "$SCRIPT_DIR/stop_entire_system.sh"
        else
            sudo systemctl stop technews-bot.service technews-engine.service 2>/dev/null || true
            pkill -f "main_engine.py" 2>/dev/null || true
            pkill -f "telegram_feeder_bot.py" 2>/dev/null || true
            echo "✅ Services stopped."
        fi
        ;;
    restart)
        echo "🔄 Restarting services..."
        sudo systemctl restart technews-engine.service
        sleep 2
        sudo systemctl restart technews-bot.service
        echo "✅ Services restarted."
        ;;
    disable)
        echo "⚠️ Disabling auto-start on boot..."
        sudo systemctl disable technews-engine.service technews-bot.service
        echo "✅ Auto-start disabled."
        ;;
    enable)
        echo "🚀 Enabling auto-start on boot..."
        sudo systemctl enable technews-engine.service technews-bot.service
        echo "✅ Auto-start enabled."
        ;;
    *)
        echo "Usage: sh scripts/services.sh [status|logs|logs-engine|logs-bot|start|stop|restart|enable|disable]"
        exit 1
        ;;
esac
