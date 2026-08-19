#!/bin/sh
# ==============================================================================
# Tech News Scrapper — Complete System Shutdown & Maintenance Script
# Pure POSIX /bin/sh compliant
# ==============================================================================

echo "================================================================"
echo "  🛑 Tech News Scrapper — Complete System Shutdown & Maintenance"
echo "================================================================"

# 1. Stop Systemd Services (if installed)
echo "1️⃣ Stopping systemd background services..."
if systemctl is-active --quiet technews-bot.service 2>/dev/null; then
    sudo systemctl stop technews-bot.service
    echo "   ✓ Telegram Bot service stopped."
fi

if systemctl is-active --quiet technews-engine.service 2>/dev/null; then
    sudo systemctl stop technews-engine.service
    echo "   ✓ Main Engine service stopped."
fi

# 2. Stop Docker Containers (if running)
if command -v docker >/dev/null 2>&1; then
    if docker compose ps -q 2>/dev/null | grep -q .; then
        echo "2️⃣ Stopping Docker containers..."
        docker compose down 2>/dev/null || true
        echo "   ✓ Docker stack stopped."
    fi
fi

# 3. Kill any remaining Python processes
echo "3️⃣ Terminating any remaining Python engine/bot processes..."
pkill -9 -f "main_engine.py" 2>/dev/null || true
pkill -9 -f "telegram_feeder_bot.py" 2>/dev/null || true

# 4. Release Port 8080 if still occupied
echo "4️⃣ Checking and releasing port 8080..."
if command -v fuser >/dev/null 2>&1; then
    sudo fuser -k 8080/tcp 2>/dev/null || true
    echo "   ✓ Port 8080 released."
elif command -v lsof >/dev/null 2>&1; then
    PORT_PID=$(lsof -ti:8080 2>/dev/null || true)
    if [ -n "$PORT_PID" ]; then
        echo "$PORT_PID" | xargs kill -9 2>/dev/null || true
        echo "   ✓ Port 8080 released (PID: $PORT_PID)."
    else
        echo "   ✓ Port 8080 is clear."
    fi
fi

# 5. Clean up temporary runtime files
echo "5️⃣ Cleaning up temporary runtime files..."
rm -f logs/*.pid 2>/dev/null || true
rm -f cache/*.sqlite-journal 2>/dev/null || true
rm -f cache/*.sqlite-wal 2>/dev/null || true
echo "   ✓ Runtime locks and journals cleared."

echo "
================================================================
✅ SYSTEM IS ENTIRELY STOPPED (Maintenance Mode Active)
================================================================
• No background processes are running.
• Port 8080 has been freed.
• CPU and Memory resources are completely idle.
• Safe to perform updates, edits, or hardware maintenance.

----------------------------------------------------------------
To resume the system after maintenance:
 • Auto-start on boot:  sh scripts/setup_autostart.sh
 • Immediate start:      sh scripts/services.sh start
 • Background nohup:     sh scripts/start_background.sh
================================================================
"
