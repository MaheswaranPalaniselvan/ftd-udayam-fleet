#!/usr/bin/env bash
# ==============================================================================
# Udayam Autonomous Scraper Worker - 1-Click Daemon Installer for ARM64 SBCs
# Supports: Raspberry Pi 5, Raspberry Pi 4, NVIDIA Jetson Nano, & Debian/Ubuntu
# ==============================================================================

set -e

echo "=========================================================="
echo "⚡ Udayam Scraper Daemon Setup (Raspberry Pi & Jetson Nano)"
echo "=========================================================="

# 1. Determine default machine name and concurrency
HOST=$(hostname 2>/dev/null || echo "ARM-Worker")
MODEL="SBC"

if grep -q "Raspberry Pi 5" /proc/cpuinfo 2>/dev/null; then
    MODEL="Pi5"
    DEFAULT_MACHINE="Pi5-Worker"
    DEFAULT_CONCURRENCY=2
elif grep -q "Raspberry Pi 4" /proc/cpuinfo 2>/dev/null; then
    MODEL="Pi4"
    DEFAULT_MACHINE="Pi4-Worker"
    DEFAULT_CONCURRENCY=2
elif grep -q -i "jetson" /proc/cpuinfo 2>/dev/null || [ -d "/usr/local/cuda" ]; then
    MODEL="Jetson"
    DEFAULT_MACHINE="Jetson-Worker"
    DEFAULT_CONCURRENCY=1
else
    DEFAULT_MACHINE="${HOST}-Worker"
    DEFAULT_CONCURRENCY=2
fi

read -p "Enter Machine Name [$DEFAULT_MACHINE]: " MACHINE_NAME
MACHINE_NAME=${MACHINE_NAME:-$DEFAULT_MACHINE}

read -p "Enter Concurrency (Pi5: 2-3, Pi4: 1-2, Jetson: 1) [$DEFAULT_CONCURRENCY]: " CONCURRENCY
CONCURRENCY=${CONCURRENCY:-$DEFAULT_CONCURRENCY}

WORK_DIR=$(pwd)
CURRENT_USER=$(whoami)

echo ""
echo "Configuring Daemon:"
echo "  Machine Name: $MACHINE_NAME"
echo "  Concurrency:  $CONCURRENCY"
echo "  Work Dir:      $WORK_DIR"
echo "  User:          $CURRENT_USER"
echo ""

# 2. Install System Dependencies
echo "[1/5] Installing native libraries and 7-Zip..."
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-pip python3-venv p7zip-full \
    libopenblas-dev libgomp1 libglib2.0-0 > /dev/null 2>&1 || true

# Configure clean fast-forward git pulls for autonomous updates
git config pull.rebase false 2>/dev/null || true
git config pull.ff only 2>/dev/null || true

# 3. Setup Python Virtual Environment
echo "[2/5] Setting up Python virtual environment (.venv)..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

# 4. Install Python Dependencies
echo "[3/5] Installing Scrapling, ddddocr, Playwright..."
pip install -q --upgrade pip
pip install -q "scrapling[all]>=0.4.15" "ddddocr>=1.6.1" "playwright>=1.62.0" "httpx>=0.28.1" "openpyxl>=3.1.5"

# 5. Install Playwright Chromium
echo "[4/5] Installing Playwright Chromium browser..."
playwright install --with-deps chromium > /dev/null 2>&1

# 6. Create systemd Service Unit
echo "[5/5] Registering and enabling systemd background service..."
SERVICE_FILE="/etc/systemd/system/udyam-worker.service"

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=Udayam Autonomous Distributed Scraper Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$WORK_DIR
ExecStart=$WORK_DIR/.venv/bin/python client/app.py --cli --machine "$MACHINE_NAME" --concurrency $CONCURRENCY
Restart=always
RestartSec=10
Environment="GOOGLE_APPS_SCRIPT_URL=https://script.google.com/macros/s/AKfycby3tmgH9PtjUhl6XfGrBfgRNZFQZaSLR0N4Dnff9tt9K5qjatyarJy_nnE0ulCtMNm2xA/exec"
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable udyam-worker.service
sudo systemctl restart udyam-worker.service

echo ""
echo "=========================================================="
echo "🎉 SUCCESS: Udayam Scraper is now running as a background daemon!"
echo "=========================================================="
echo "Useful Commands:"
echo "  - Check Status:  sudo systemctl status udyam-worker"
echo "  - View Live Log: journalctl -u udyam-worker -f"
echo "  - Stop Worker:   sudo systemctl stop udyam-worker"
echo "  - Start Worker:  sudo systemctl start udyam-worker"
echo "=========================================================="

