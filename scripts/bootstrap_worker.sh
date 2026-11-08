#!/usr/bin/env bash
# ==============================================================================
# FlawlessTech Data - 1-Click Universal Fleet Worker Bootstrap Installer
# Supports: Raspberry Pi 5 (Active Cooler), Pi 4, NVIDIA Jetson Nano, & Debian/Ubuntu
# ==============================================================================

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}   ⚡ FlawlessTech Data - Universal Fleet Worker 1-Click Installer    ${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

# 1. Architecture Check (Must be 64-bit ARM or x86_64)
ARCH=$(uname -m)
echo -e "${YELLOW}[1/7] Checking hardware architecture...${NC}"
echo "      Detected Architecture: $ARCH"

if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ] && [ "$ARCH" != "x86_64" ]; then
    echo -e "${RED}[ERROR] 32-bit architecture ($ARCH) is not supported!${NC}"
    echo "        Playwright and ONNX OCR require a 64-bit operating system."
    exit 1
fi
echo -e "${GREEN}      [OK] 64-bit OS confirmed.${NC}"
echo ""

# 2. Directory & Git Repository Verification
TARGET_DIR="$HOME/udayam"
echo -e "${YELLOW}[2/7] Checking project directory and code source...${NC}"

if [ ! -f "$PWD/extract_list.py" ] && [ ! -d "$TARGET_DIR" ]; then
    echo "      Cloning repository into $TARGET_DIR..."
    git clone https://github.com/MaheswaranPalaniselvan/udayam-source.git "$TARGET_DIR"
    cd "$TARGET_DIR"
elif [ -f "$PWD/extract_list.py" ]; then
    TARGET_DIR="$PWD"
    echo "      Running directly from current workspace: $TARGET_DIR"
else
    cd "$TARGET_DIR"
    echo "      Using existing directory: $TARGET_DIR"
fi
echo -e "${GREEN}      [OK] Working directory ready: $TARGET_DIR${NC}"
echo ""

# 3. Native System Dependencies (APT)
echo -e "${YELLOW}[3/7] Installing native Linux system libraries...${NC}"
sudo apt-get update -qq
sudo apt-get install -y -qq \
    curl git build-essential python3-dev python3-tk \
    libopenblas-dev libgomp1 p7zip-full \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 \
    libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 > /dev/null 2>&1 || true

# Dual-support for Debian/Ubuntu (t64 transition in Ubuntu 24.04 noble)
sudo apt-get install -y -qq libglib2.0-0t64 2>/dev/null || sudo apt-get install -y -qq libglib2.0-0 2>/dev/null || true
sudo apt-get install -y -qq libasound2t64 2>/dev/null || sudo apt-get install -y -qq libasound2 2>/dev/null || true
echo -e "${GREEN}      [OK] System packages verified.${NC}"
echo ""

# 4. Install / Verify 'uv' Package Manager
echo -e "${YELLOW}[4/7] Setting up ultra-fast 'uv' package manager...${NC}"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

if ! command -v uv &> /dev/null; then
    echo "      Downloading standalone uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
echo -e "${GREEN}      [OK] uv installed: $(uv --version)${NC}"
echo ""

# 5. Synchronize Python Virtual Environment & Playwright
echo -e "${YELLOW}[5/7] Synchronizing Python virtual environment & Playwright...${NC}"
cd "$TARGET_DIR"
uv sync

echo "      Installing Playwright Chromium browser binaries..."
uv run playwright install --with-deps chromium > /dev/null 2>&1
echo -e "${GREEN}      [OK] Python dependencies and browser automation ready.${NC}"
echo ""

# 6. Run Automated Concurrency Benchmark & Hardware Tuner
echo -e "${YELLOW}[6/7] Running hardware benchmark to determine optimal concurrency...${NC}"
uv run python scripts/benchmark_concurrency.py --apply --quick

RECOMMENDED_CONCURRENCY=2
if [ -f "$TARGET_DIR/optimal_config.json" ]; then
    RECOMMENDED_CONCURRENCY=$(grep -o '"recommended_concurrency": [0-9]*' optimal_config.json | awk '{print $2}' || echo "2")
fi

# Detect Host / Machine Name
MACHINE_NAME="$(hostname 2>/dev/null || echo 'Worker')-Daemon"
if grep -q "Raspberry Pi 5" /proc/cpuinfo 2>/dev/null; then
    MACHINE_NAME="Pi5-$(hostname)"
elif grep -q "Raspberry Pi 4" /proc/cpuinfo 2>/dev/null; then
    MACHINE_NAME="Pi4-$(hostname)"
elif grep -q -i "jetson" /proc/cpuinfo 2>/dev/null; then
    MACHINE_NAME="Jetson-$(hostname)"
fi

echo ""
echo -e "${GREEN}      [AUTO-TUNED] Optimal Concurrency for this board: ${YELLOW}$RECOMMENDED_CONCURRENCY worker(s)${NC}"
echo -e "${GREEN}      [MACHINE ID] Registered Name: ${YELLOW}$MACHINE_NAME${NC}"
echo ""

# 7. Configure and Enable Systemd Background Service
echo -e "${YELLOW}[7/7] Registering 24/7 background systemd service...${NC}"
CURRENT_USER=$(whoami)
SERVICE_FILE="/etc/systemd/system/udyam-worker.service"

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=FlawlessTech Autonomous Udayam Fleet Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$TARGET_DIR
ExecStart=$HOME/.local/bin/uv run python client/app.py --cli --machine "$MACHINE_NAME" --concurrency $RECOMMENDED_CONCURRENCY
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
echo -e "${GREEN}======================================================================${NC}"
echo -e "${GREEN}🎉 SETUP COMPLETE: Worker is now running autonomously 24/7!          ${NC}"
echo -e "${GREEN}======================================================================${NC}"
echo ""
echo " Management Commands:"
echo "   - View live logs:    journalctl -u udyam-worker -f"
echo "   - Check status:      sudo systemctl status udyam-worker"
echo "   - Restart worker:    sudo systemctl restart udyam-worker"
echo "   - Stop worker:       sudo systemctl stop udyam-worker"
echo ""
echo " Live Telemetry Dashboard:"
echo "   👉 https://ftd-udayam-fleet.pages.dev"
echo -e "${GREEN}======================================================================${NC}"

