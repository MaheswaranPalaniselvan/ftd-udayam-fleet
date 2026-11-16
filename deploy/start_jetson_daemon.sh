#!/usr/bin/env bash
# ==============================================================================
# FlawlessTech Data - Jetson Nano Autonomous Scraper Background Daemon
# Runs client/app.py directly using the virtualenv Python (no uv run),
# logs output to daemon.log, and auto-restarts indefinitely if terminated.
# ==============================================================================

WORK_DIR="/home/mahesp93/udayam"
cd "$WORK_DIR" || exit 1

export PATH="$HOME/.local/bin:$HOME/.local/node-v16/bin:$PATH"
export PYTHONUNBUFFERED=1

# Lower minimumMajorNodeVersion check for legacy Node on Jetson
sed -i 's/minimumMajorNodeVersion = 20/minimumMajorNodeVersion = 16/g' \
    "$WORK_DIR/.venv/lib/python3.13/site-packages/patchright/driver/package/lib/coreBundle.js" \
    "$WORK_DIR/.venv/lib/python3.13/site-packages/patchright/driver/package/lib/bootstrap.js" 2>/dev/null || true

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Starting Jetson Nano Scraper Daemon ===" >> daemon.log

while true; do
    "$WORK_DIR/.venv/bin/python" client/app.py --cli --machine "Jetson-jetson-nano" --concurrency 1 --state AP --district AP-02 --no-auto-update >> daemon.log 2>&1
    EXIT_CODE=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Worker stopped with code $EXIT_CODE. Restarting in 5s..." >> daemon.log
    sleep 5
done

