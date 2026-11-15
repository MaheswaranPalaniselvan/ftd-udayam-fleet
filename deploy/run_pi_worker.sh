#!/usr/bin/env bash
# =============================================================================
# FlawlessTech Data - Raspberry Pi Worker Launcher
# =============================================================================

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Auto-detect legacy GLIBC (e.g. Jetson Nano glibc 2.27 on Ubuntu 18.04)
GLIBC_VER=$(ldd --version 2>/dev/null | head -n1 | grep -oE '[0-9]+\.[0-9]+' | head -n1)
if [ -n "$GLIBC_VER" ] && [ "$(printf '%s\n' "2.28" "$GLIBC_VER" | sort -V | head -n1)" != "2.28" ]; then
    if [ -f "$HOME/.local/node-v16/bin/node" ]; then
        export PLAYWRIGHT_NODEJS_PATH="$HOME/.local/node-v16/bin/node"
        export PATH="$HOME/.local/node-v16/bin:$PATH"
    elif command -v node &>/dev/null; then
        export PLAYWRIGHT_NODEJS_PATH="$(command -v node)"
    fi
    if [ -f "/usr/bin/chromium-browser" ]; then
        export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="/usr/bin/chromium-browser"
    fi
fi

# Load auto-tuned concurrency if available from optimal_config.json
DEFAULT_CONCURRENCY=2
if [ -f "optimal_config.json" ]; then
    CONF_CONC=$(grep -oE '"recommended_concurrency":\s*[0-9]+' optimal_config.json | grep -oE '[0-9]+' | head -n1)
    if [ -n "$CONF_CONC" ] && [ "$CONF_CONC" -gt 0 ]; then
        DEFAULT_CONCURRENCY=$CONF_CONC
    fi
fi

echo "====================================================================="
echo "   FlawlessTech Data - Raspberry Pi Worker Launcher                 "
echo "====================================================================="
echo ""
echo "Select Mode:"
echo "  [1] Headless District Incremental (e.g. TN-02)"
echo "  [2] Fleet Worker (Connects to Google Sheet Coordinator)"
echo "  [3] Re-check Failed Records (results.xlsx)"
echo "  [4] Desktop GUI Mode (Requires monitor or VNC desktop)"
echo "  [5] Run Hardware Concurrency Benchmark & Active Cooler Test"
echo ""
read -p "Enter choice [1-5] (default 1): " CHOICE
CHOICE=${CHOICE:-1}

case $CHOICE in
    1)
        read -p "Enter District Code (default TN-02): " DIST
        DIST=${DIST:-TN-02}
        read -p "Enter Batch Count (default 50): " CNT
        CNT=${CNT:-50}
        echo "Starting incremental extraction for $DIST (Count: $CNT, Concurrency: 2)..."
        uv run python extract_list.py --district "$DIST" --incremental --count "$CNT" --concurrency 2 --output results.xlsx --html
        ;;
    2)
        HOSTNAME=$(hostname)
        MACHINE_PREFIX="Pi"
        if [[ "$HOSTNAME" =~ [Jj]etson ]] || [ -f "/etc/nv_tegra_release" ]; then
            MACHINE_PREFIX="Jetson"
        fi
        read -p "Enter Target State (e.g. TN, KL, MP, UP, or Enter for auto): " ST
        read -p "Enter Target District (e.g. TN-02, or Enter for auto): " DIST
        CMD="uv run python client/app.py --cli --machine \"${MACHINE_PREFIX}-$HOSTNAME\" --concurrency $DEFAULT_CONCURRENCY"
        if [ -n "$ST" ]; then
            CMD="$CMD --state $ST"
        fi
        if [ -n "$DIST" ]; then
            CMD="$CMD --district $DIST"
        fi
        echo "Launching: $CMD"
        eval $CMD
        ;;
    3)
        echo "Re-checking failed records in results.xlsx..."
        uv run python extract_list.py --recheck-failed --output results.xlsx --html --concurrency 2
        ;;
    4)
        echo "Launching Desktop GUI..."
        uv run python client/gui/extractor_gui.py
        ;;
    5)
        echo "Running Hardware Concurrency Benchmark & Thermal Health Check..."
        uv run python scripts/benchmark_concurrency.py --apply
        ;;
    *)
        echo "Invalid selection. Exiting."
        exit 1
        ;;
esac
