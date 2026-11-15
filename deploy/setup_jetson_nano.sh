#!/usr/bin/env bash
# =============================================================================
# FlawlessTech Data - NVIDIA Jetson Nano Setup Initializer (glibc 2.27 Fix)
# Configures Node.js 16, system Chromium, and Playwright driver compatibility.
# =============================================================================

set -e

export PATH="$HOME/.local/bin:$HOME/.local/node-v16/bin:$HOME/.cargo/bin:$PATH"
export PLAYWRIGHT_NODEJS_PATH="$HOME/.local/node-v16/bin/node"
export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="/usr/bin/chromium-browser"

echo "====================================================================="
echo "   FlawlessTech Data - NVIDIA Jetson Nano Setup Initializer         "
echo "====================================================================="
echo ""

ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    echo "[ERROR] Detected architecture: $ARCH. Jetson Nano requires aarch64."
    exit 1
fi

# 1. Install glibc-2.27 compatible Node.js v16 (Bypasses GLIBC_2.28 missing error)
echo "[1/4] Installing glibc 2.27-compatible Node.js v16.20.2 for ARM64..."
mkdir -p "$HOME/.local/node-v16"
if [ ! -f "$HOME/.local/node-v16/bin/node" ]; then
    echo "      Downloading official node-v16.20.2-linux-arm64..."
    if command -v curl &>/dev/null; then
        curl -sSL https://nodejs.org/dist/v16.20.2/node-v16.20.2-linux-arm64.tar.xz | tar -xJ --strip-components=1 -C "$HOME/.local/node-v16"
    elif command -v wget &>/dev/null; then
        wget -qO- https://nodejs.org/dist/v16.20.2/node-v16.20.2-linux-arm64.tar.xz | tar -xJ --strip-components=1 -C "$HOME/.local/node-v16"
    else
        python3 -c "import urllib.request, sys; sys.stdout.buffer.write(urllib.request.urlopen('https://nodejs.org/dist/v16.20.2/node-v16.20.2-linux-arm64.tar.xz').read())" | tar -xJ --strip-components=1 -C "$HOME/.local/node-v16"
    fi
fi
export PLAYWRIGHT_NODEJS_PATH="$HOME/.local/node-v16/bin/node"
export PATH="$HOME/.local/node-v16/bin:$PATH"
echo "      [OK] Node.js installed: $($HOME/.local/node-v16/bin/node -v)"
echo ""

# 2. Install native system Chromium and dependencies
echo "[2/4] Installing native system Chromium & BLAS acceleration libraries..."
sudo apt-get update -y
sudo apt-get install -y chromium-browser libopenblas-dev libatomic1
echo "      [OK] System Chromium installed."
echo ""

# 3. Synchronize Python virtual environment
echo "[3/4] Synchronizing Python environment via uv..."
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
if command -v uv &>/dev/null; then
    uv sync
elif [ -f "$HOME/.local/bin/uv" ]; then
    "$HOME/.local/bin/uv" sync
fi
echo "      [OK] Python dependencies synchronized."
echo ""

# 4. Run hardware auto-tuning benchmark
echo "[4/4] Running Jetson Hardware Concurrency Auto-Tuner..."
if command -v uv &>/dev/null; then
    uv run python scripts/benchmark_concurrency.py --apply
elif [ -f "$HOME/.local/bin/uv" ]; then
    "$HOME/.local/bin/uv" run python scripts/benchmark_concurrency.py --apply
fi

echo ""
echo "====================================================================="
echo " [SUCCESS] NVIDIA JETSON NANO SETUP COMPLETE!                       "
echo "====================================================================="
echo ""
echo " Launch your worker using:"
echo "   bash deploy/run_pi_worker.sh"
echo ""

