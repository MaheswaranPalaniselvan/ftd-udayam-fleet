"""
Main Client Application Entrypoint for Udyam Scraper Worker.
Supports both Desktop GUI mode (default) and Headless CLI mode.
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables if .env exists
env_path = Path(".env")
if env_path.is_file():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run_headless_cli(args):
    """Headless CLI runner for servers or automated background workers."""
    from client.core.coordinator import CentralCoordinator, get_default_machine_name
    from client.core.scraper import execute_district_extraction
    from client.core.archiver import compress_and_upload_district

    machine = args.machine or os.getenv("WORKER_MACHINE_NAME") or get_default_machine_name()
    url = args.web_app_url or os.getenv("GOOGLE_APPS_SCRIPT_URL", "")

    logging.info(f"Starting headless worker for machine: {machine}")
    coordinator = CentralCoordinator(url, machine)

    districts_completed_count = 0
    start_time = time.time()
    max_duration_sec = (args.max_duration_minutes * 60) if getattr(args, 'max_duration_minutes', None) else None
    claim_attempts = 0

    async def main_loop():
        nonlocal districts_completed_count, claim_attempts
        while True:
            if max_duration_sec and (time.time() - start_time) >= max_duration_sec:
                logging.info(f"Reached max duration limit ({args.max_duration_minutes}m). Worker stopping gracefully.")
                break

            if getattr(args, 'max_districts', None) and districts_completed_count >= args.max_districts:
                logging.info(f"Target districts ({args.max_districts}) completed. Worker stopping gracefully.")
                break

            logging.info("Claiming next task from central coordinator...")
            claim_res = await coordinator.claim_task(preferred_state=args.state, preferred_district=args.district)

            dist_code = None
            start_num = 1
            limit = 500000

            if not claim_res.get("success"):
                claim_attempts += 1
                logging.warning(f"Could not claim task: {claim_res.get('message')}. (Attempt {claim_attempts}/3)")
                if args.state and claim_attempts >= 3:
                    st_prefix = args.state.upper().strip()
                    worker_offset = 1
                    m_num = re.search(r"Worker-(\d+)", machine, re.IGNORECASE)
                    if m_num:
                        worker_offset = int(m_num.group(1))
                    dist_code = f"{st_prefix}-{worker_offset:02d}"
                    logging.info(f"Autonomous fallback: Coordinator unindexed for state {st_prefix}. Claiming district {dist_code} directly.")
                else:
                    await asyncio.sleep(15)
                    if args.district:
                        logging.info("Requested district could not be claimed. Exiting.")
                        break
                    continue
            else:
                dist_code = claim_res.get("district_code")
                start_num = claim_res.get("start_num", 1)
                limit = claim_res.get("limit", 500000)

            logging.info(f"Task Claimed: {dist_code} | Start: #{start_num} | Limit: #{limit}")

            async def heartbeat(**kwargs):
                await coordinator.send_heartbeat(
                    district_code=dist_code,
                    current_record=kwargs.get("current_record", ""),
                    current_dor=kwargs.get("current_dor", ""),
                    total_extracted=kwargs.get("total_extracted", 0),
                    total_failed=kwargs.get("total_failed", 0),
                    speed_rpm=kwargs.get("speed_rpm", 0.0)
                )

            res = await execute_district_extraction(
                prefix=dist_code,
                start_num=start_num,
                limit=limit,
                concurrency=args.concurrency,
                heartbeat_callback=heartbeat
            )

            logging.info(f"District {dist_code} complete. Finalizing in Google Sheet...")
            await coordinator.complete_task(
                district_code=dist_code,
                final_record=res.get("last_record"),
                final_dor=res.get("last_dor"),
                total_extracted=res.get("total_extracted"),
                total_failed=res.get("total_failed")
            )

            logging.info(f"Compressing {dist_code} and uploading to Google Drive...")
            await compress_and_upload_district(dist_code, coordinator=coordinator)

            districts_completed_count += 1
            if getattr(args, 'max_districts', None) and districts_completed_count >= args.max_districts:
                logging.info(f"Target districts ({args.max_districts}) completed. Exiting.")
                break

    asyncio.run(main_loop())


def main():
    parser = argparse.ArgumentParser(description="Udyam Scraper Worker (GUI & CLI)")
    parser.add_argument("--cli", action="store_true", help="Run in headless CLI mode instead of GUI")
    parser.add_argument("--machine", type=str, default=None, help="Machine name identifier")
    parser.add_argument("--state", type=str, default=None, help="Preferred state code filter (e.g. TN)")
    parser.add_argument("--district", type=str, default=None, help="Specific district code to run (e.g. TN-05)")
    parser.add_argument("--concurrency", type=int, default=2, help="Browser worker concurrency")
    parser.add_argument("--max-districts", type=int, default=None, help="Maximum number of districts to process before stopping")
    parser.add_argument("--max-duration-minutes", type=int, default=None, help="Maximum worker runtime in minutes before stopping")
    parser.add_argument("--web-app-url", type=str, default=os.getenv("GOOGLE_APPS_SCRIPT_URL"), help="Google Apps Script Web App URL")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()]
    )

    if args.cli:
        run_headless_cli(args)
    else:
        from client.gui.dashboard import launch_dashboard
        launch_dashboard(web_app_url=args.web_app_url)


if __name__ == "__main__":
    main()
