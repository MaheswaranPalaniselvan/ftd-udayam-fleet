#!/usr/bin/env bash
# =============================================================================
# FlawlessTech Data - Raspberry Pi (ARM64 / aarch64) Automated Setup Script
# Configures Python environment, Playwright Chromium, OCR, and fleet worker tools.
# =============================================================================

set -e

echo "====================================================================="
echo "   FlawlessTech Data - Raspberry Pi Automated Setup Initializer     "
echo "====================================================================="
echo ""

# 1. Architecture Check (Must be 64-bit OS)
ARCH=$(uname -m)
echo "[1/5] Checking hardware and OS architecture..."
echo "      Detected architecture: $ARCH"

if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
    echo ""
    echo "[ERROR] 32-bit architecture ($ARCH) detected!"
    echo "        Playwright and ONNX (ddddocr) require a 64-bit operating system."
    echo "        Please install Raspberry Pi OS (64-bit) or Ubuntu Server (64-bit) on this Pi."
    echo "        Download: https://www.raspberrypi.com/software/operating-systems/#raspberry-pi-os-64-bit"
    exit 1
fi
echo "      [OK] 64-bit ARM architecture confirmed."
echo ""

# 2. Update APT and install essential native libraries
echo "[2/5] Installing required Linux system libraries via apt..."
sudo apt-get update -y
sudo apt-get install -y \
    curl \
    git \
    python3-tk \
    python3-dev \
    build-essential \
    libopenblas-dev \
    libatlas-base-dev \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2

echo "      [OK] System libraries installed."
echo ""

# 3. Check / Install uv package manager
echo "[3/5] Setting up high-speed 'uv' package manager..."
if ! command -v uv &> /dev/null; then
    echo "      Downloading standalone uv for aarch64..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv &> /dev/null; then
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "      [OK] uv installed: $(uv --version)"
echo ""

# 4. Sync Python virtual environment & dependencies
echo "[4/5] Synchronizing Python environment and dependencies..."
cd "$(dirname "$0")"
uv sync

echo "      [OK] Python dependencies synchronized."
echo ""

# 5. Install Playwright browser automation binaries
echo "[5/5] Installing Playwright Chromium browser for ARM64..."
uv run playwright install --with-deps chromium

echo ""
echo "====================================================================="
echo " [SUCCESS] RASPBERRY PI SETUP COMPLETE!                             "
echo "====================================================================="
echo ""
echo " You can now run extractions on this Raspberry Pi:"
echo ""
echo " 1. Headless CLI Extraction (Recommended for 24/7 operation):"
echo "    uv run python extract_list.py --district TN-02 --incremental --count 50 --output results.xlsx"
echo ""
echo " 2. Fleet Worker Mode (Connect to central coordinator):"
echo "    uv run python client/app.py --cli --machine \"Pi-$(hostname)\""
echo ""
echo " 3. Desktop GUI Mode (If connected to a monitor / VNC):"
echo "    uv run python client/gui/extractor_gui.py"
echo "====================================================================="
echo ""
