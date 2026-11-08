#!/usr/bin/env bash
# =============================================================================
# FlawlessTech Data - Raspberry Pi Worker Launcher
# =============================================================================

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
cd "$(dirname "$0")"

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
        echo "Starting fleet worker as Pi-$HOSTNAME..."
        uv run python client/app.py --cli --machine "Pi-$HOSTNAME" --concurrency 2
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
