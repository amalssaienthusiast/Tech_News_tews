# 🍓 Raspberry Pi Zero 2W 24/7 Deployment Guide

This guide walks you through deploying **Tech_News_Scrapper** in headless mode on a **Raspberry Pi** to run **24/7 automatically on boot** without requiring an SSH session.

---

## ⚡ 1-Click Auto-Start on Boot (Recommended)

Once you pull the repository onto your Raspberry Pi, run **one command** to install the background boot services:

```bash
chmod +x scripts/*.sh
./scripts/setup_autostart.sh
```

**What this does automatically:**
- Configures `systemd` background services for **Main Engine** and **Telegram Bot**.
- Enables both services so they start automatically **every time the Raspberry Pi powers on**.
- Sets up automatic crash/network recovery.
- You can **close/terminate your SSH terminal immediately**.

### Service Management Commands:
```bash
./scripts/services.sh status       # Check if Engine & Bot are running
./scripts/services.sh logs         # View live streaming logs
./scripts/services.sh restart      # Restart both services
./scripts/services.sh stop         # Stop both services
```

---

## 📋 Prerequisites

1. **Raspberry Pi Zero 2W** running Raspberry Pi OS (32-bit or 64-bit Lite/Desktop).
2. **Telegram Bot Token**: Created via [@BotFather](https://t.me/BotFather).
   - Your Bot Username: `@tewsavailable_bot`
   - Token: `<YOUR_TELEGRAM_BOT_TOKEN>` *(obtain from @BotFather and store outside version control)*
3. **Telegram Channel**:
   - Create a Telegram Channel (Public or Private).
   - Add `@tewsavailable_bot` as an **Administrator** of your channel with "Post Messages" permission.
   - Channel Chat ID: `@your_channel_username` (for public channels) or numeric ID like `-1001234567890`.

---

## 🐋 Docker Installation on Raspberry Pi

If you plan to run Tech News Scraper using **Docker Compose** (Option C), follow these steps to install Docker and Docker Compose on Raspberry Pi OS:

```bash
# 1. Update package index and system
sudo apt update && sudo apt upgrade -y

# 2. Download and run the official Docker convenience script
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
rm get-docker.sh

# 3. Add your current user ('pi') to the docker group to run docker without 'sudo'
sudo usermod -aG docker $USER

# 4. Install Docker Compose plugin
sudo apt install -y docker-compose-plugin

# 5. Apply the group change immediately (or log out and reconnect SSH)
newgrp docker

# 6. Verify Docker installation
docker --version
docker compose version
docker run hello-world
```

---

## 🛠️ Step-by-Step Setup

### 1. Clone & Setup Project on Raspberry Pi

```bash
# Clone the repository
git clone https://github.com/yourusername/Tech_News_Scrapper.git
cd Tech_News_Scrapper

# Create Python Virtual Environment
python3 -m venv env
source env/bin/activate

# Install Lightweight Dependencies for Pi Zero 2W
pip install -r requirements-pi.txt
```

---

### 2. Configure Environment (`.env`)

Create or edit `.env` in the root of the project directory:

```bash
nano .env
```

Add your Telegram credentials:

```ini
TELEGRAM_BOT_TOKEN=<YOUR_TELEGRAM_BOT_TOKEN>
TELEGRAM_CHAT_ID=@your_channel_username
```

---

### 3. Verify Connection (Test Mode)

Run the test command to confirm your bot can post to your channel:

```bash
python3 telegram_feeder_bot.py --test
```

If successful, you will see a test post in your Telegram channel!

---

### 4. Running 24/7 in Background (Survives Terminal Close & Reboots)

You have **3 options** to run both the Main Engine and Telegram Bot in the background on your Raspberry Pi:

---

#### Option A: Systemd Services (Recommended for Production 24/7)
Systemd automatically starts both services on Pi boot, keeps them running in the background, and restarts them automatically if they crash or network drops.

**Step 1: Create Engine Service**
```bash
sudo nano /etc/systemd/system/technews-engine.service
```
Paste this configuration (replace `pi` with your Pi username if different):
```ini
[Unit]
Description=Tech News Scraper Main Engine
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Tech_News_Scrapper
ExecStart=/home/pi/Tech_News_Scrapper/env/bin/python3 main_engine.py --port 8080
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

**Step 2: Create Telegram Bot Service**
```bash
sudo nano /etc/systemd/system/technews-bot.service
```
Paste this configuration:
```ini
[Unit]
Description=Tech News Scraper Telegram Bot
After=network-online.target technews-engine.service
Wants=network-online.target technews-engine.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Tech_News_Scrapper
ExecStart=/home/pi/Tech_News_Scrapper/env/bin/python3 telegram_feeder_bot.py --engine-url http://localhost:8080
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

**Step 3: Enable & Start Both Services**
```bash
# Reload systemd configuration
sudo systemctl daemon-reload

# Enable both services to launch automatically on boot
sudo systemctl enable technews-engine.service technews-bot.service

# Start both services immediately
sudo systemctl start technews-engine.service technews-bot.service

# Verify statuses
sudo systemctl status technews-engine.service technews-bot.service
```

---

#### Option B: Simple Background Script (Quick Setup)
If you don't want to configure systemd, use the provided helper scripts:

```bash
# Start both in background (survives SSH terminal exit)
./scripts/start_background.sh

# View live logs
tail -f logs/engine.log
tail -f logs/bot.log

# Stop both services
./scripts/stop_background.sh
```

---

#### Option C: Docker Compose (`docker compose up -d`)
If Docker is installed on your Raspberry Pi:

```bash
# Start stack in detached background mode
docker compose up -d

# View live logs
docker compose logs -f

# Stop stack
docker compose down
```

---

## 🔍 Useful Management Commands

```bash
# View live real-time logs (Systemd)
sudo journalctl -u technews-engine.service -u technews-bot.service -f

# Restart both services
sudo systemctl restart technews-engine.service technews-bot.service

# Stop both services
sudo systemctl stop technews-engine.service technews-bot.service
```

---

## ⚡ Raspberry Pi Zero 2W Optimization Notes

- **Concurrency**: Set `--concurrency 1` (default) to keep RAM usage under 100MB.
- **Headless**: Runs zero GUI/PySide components for ultra-fast performance.
- **Auto-Recovery**: Systemd automatically restarts the service if network connectivity temporarily drops.

