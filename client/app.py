"""
Main Client Application Entrypoint for Udyam Scraper Worker.
Supports both Desktop GUI mode (default) and Headless CLI mode.
"""

import argparse
import asyncio
import logging
import os
import re
import subprocess
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

# Auto-configure git local config with GITHUB_TOKEN to prevent interactive terminal prompts
token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
if token and Path(".git").is_dir():
    try:
        subprocess.run(
            ["git", "config", "--local", f"url.https://x-access-token:{token}@github.com/.insteadOf", "https://github.com/"],
            capture_output=True,
            timeout=3
        )
    except Exception:
        pass


def get_git_auth_args() -> list[str]:
    """
    Returns ephemeral git CLI arguments (-c url...) to authenticate seamlessly
    using GITHUB_TOKEN or GH_TOKEN from environment variables or .fleet_accounts.json,
    completely preventing interactive Git Credential Manager / browser login prompts.
    """
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        fleet_json = Path(".fleet_accounts.json")
        if fleet_json.is_file():
            try:
                import json
                data = json.loads(fleet_json.read_text(encoding="utf-8"))
                for acc in data.get("accounts", []):
                    if acc.get("token") and acc.get("enabled", True):
                        token = acc["token"]
                        break
            except Exception:
                pass

    if token:
        os.environ.setdefault("GITHUB_TOKEN", token)
        return ["-c", f"url.https://x-access-token:{token}@github.com/.insteadOf=https://github.com/"]
    return []


def check_and_apply_git_update() -> bool:
    """
    Checks if upstream commits are available on origin/main.
    If updates are found, performs a fast-forward git pull and returns True.
    """
    try:
        if not Path(".git").is_dir():
            return False

        auth_args = get_git_auth_args()

        # Fetch quietly from origin without interactive prompts
        res = subprocess.run(
            ["git"] + auth_args + ["fetch", "origin", "main", "--quiet"],
            capture_output=True,
            timeout=20
        )
        if res.returncode != 0:
            return False

        local_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=5).strip()
        remote_head = subprocess.check_output(["git", "rev-parse", "origin/main"], text=True, timeout=5).strip()

        if local_head != remote_head:
            logging.info(f"🚀 [AUTO-UPDATE] Codebase update detected on origin/main ({local_head[:7]} -> {remote_head[:7]})!")
            pull_res = subprocess.run(
                ["git"] + auth_args + ["pull", "--ff-only", "origin", "main"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if pull_res.returncode == 0:
                logging.info(f"✅ [AUTO-UPDATE] Successfully updated to {remote_head[:7]}!")
                return True
            else:
                logging.warning(f"⚠️ [AUTO-UPDATE] git pull failed: {pull_res.stderr.strip()}")
    except Exception as e:
        logging.debug(f"[AUTO-UPDATE] Check skipped: {e}")
    return False


def restart_worker():
    """Restarts current worker process to reload updated code."""
    try:
        # If running as systemd service, exit 0 lets systemd Restart=always handle clean restart
        if os.environ.get("INVOCATION_ID") or os.environ.get("JOURNAL_STREAM"):
            logging.info("🔄 [AUTO-UPDATE] Exiting to let systemd restart service with fresh code...")
            sys.exit(0)
        # If running interactively in terminal, re-execute process
        logging.info("🔄 [AUTO-UPDATE] Re-launching worker process...")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        sys.exit(0)


def run_headless_cli(args):
    """Headless CLI runner for servers or automated background workers."""
    from client.core.coordinator import CentralCoordinator, get_default_machine_name
    from client.core.scraper import execute_district_extraction
    from client.core.archiver import compress_and_upload_district

    machine = args.machine or os.getenv("WORKER_MACHINE_NAME") or get_default_machine_name()
    url = args.web_app_url or os.getenv("GOOGLE_APPS_SCRIPT_URL", "")

    logging.info(f"Starting headless worker for machine: {machine}")
    coordinator = CentralCoordinator(url, machine)

    # Check for git updates at worker startup
    if not getattr(args, "no_auto_update", False):
        if check_and_apply_git_update():
            restart_worker()
            return

    districts_completed_count = 0
    start_time = time.time()
    max_duration_sec = (args.max_duration_minutes * 60) if getattr(args, 'max_duration_minutes', None) else None
    claim_attempts = 0

    rerun_mode = None
    if getattr(args, "rerun_type", "none") != "none":
        rerun_mode = args.rerun_type
    elif getattr(args, "rerun_failed", False):
        rerun_mode = "failed"
    elif getattr(args, "rerun_missing", False):
        rerun_mode = "missing"

    if rerun_mode:
        from client.core.scraper import execute_district_rerun, get_district_failed_and_missing

        logging.info(f"*** RERUN MODE ACTIVATED: {rerun_mode.upper()} ***")

        # Determine target districts
        target_districts = []
        if args.district:
            target_districts = [args.district.strip().upper()]
        elif args.state:
            st = args.state.strip().upper()
            res_dir = Path("results")
            fail_dir = Path("failed")
            found = set()
            for p in res_dir.glob(f"{st}-*.7z"):
                found.add(p.stem)
            for p in res_dir.glob(f"{st}-*"):
                if p.is_dir():
                    found.add(p.name)
            for p in fail_dir.glob(f"{st}-*"):
                if p.is_dir():
                    found.add(p.name)
            target_districts = sorted(list(found))
            if not target_districts:
                from client.core.district_manager import get_districts_for_state
                target_districts = get_districts_for_state(st)
        else:
            res_dir = Path("results")
            fail_dir = Path("failed")
            found = set()
            for p in res_dir.glob("*.7z"):
                found.add(p.stem)
            for p in fail_dir.iterdir():
                if p.is_dir():
                    found.add(p.name)
            target_districts = sorted(list(found))

        logging.info(f"Districts queued for rerun ({len(target_districts)}): {target_districts}")

        async def rerun_loop():
            nonlocal districts_completed_count
            for dist_code in target_districts:
                if max_duration_sec and (time.time() - start_time) >= max_duration_sec:
                    logging.info(f"Reached max duration limit ({args.max_duration_minutes}m). Stopping.")
                    break
                if getattr(args, 'max_districts', None) and districts_completed_count >= args.max_districts:
                    logging.info(f"Target districts ({args.max_districts}) processed. Stopping.")
                    break

                res = await execute_district_rerun(
                    prefix=dist_code,
                    rerun_type=rerun_mode,
                    concurrency=args.concurrency,
                    update_archive=True
                )

                if res.get("recovered", 0) > 0 and url:
                    audit = get_district_failed_and_missing(dist_code)
                    await coordinator.complete_task(
                        district_code=dist_code,
                        final_record="",
                        final_dor="",
                        total_extracted=audit["total_extracted"],
                        total_failed=audit["failed_count"]
                    )
                    logging.info(f"[{dist_code}] {res.get('recovered')} records recovered! Uploading updated archive to Google Drive...")
                    await compress_and_upload_district(dist_code, coordinator=coordinator, overwrite=True)

                districts_completed_count += 1

        asyncio.run(rerun_loop())
        return

    from client.core.district_manager import (
        find_district_last_number,
        get_districts_for_state,
        get_states_by_least_pending,
        get_districts_by_least_pending,
        discover_stale_or_unstarted_districts
    )

    # Initialize priority queue: default to least pending records across India if no specific state given
    state_queue = []
    preferred_state_arg = args.state
    if args.state and args.state.strip().lower() != "least_pending":
        state_queue = get_districts_for_state(args.state)
        logging.info(f"Target state queue initialized for {args.state.upper()} ({len(state_queue)} districts, ordered by least pending): {state_queue[:10]}...")
    else:
        # Nationwide least pending priority
        least_pending_dists = get_districts_by_least_pending()
        state_queue = [d["code"] for d in least_pending_dists]
        preferred_state_arg = "least_pending"
        logging.info(f"Priority queue initialized nationwide by MINIMUM PENDING RECORDS ({len(state_queue)} districts): {[d['code'] + ' (' + str(d['pending']) + ')' for d in least_pending_dists[:8]]}...")

    async def main_loop():
        nonlocal districts_completed_count, claim_attempts
        while True:
            if max_duration_sec and (time.time() - start_time) >= max_duration_sec:
                logging.info(f"Reached max duration limit ({args.max_duration_minutes}m). Worker stopping gracefully.")
                break

            if getattr(args, 'max_districts', None) and districts_completed_count >= args.max_districts:
                logging.info(f"Target districts ({args.max_districts}) completed. Worker stopping gracefully.")
                break

            dist_code = None
            start_num = 1
            limit = 500000
            prev_extracted = 0
            last_record = ""
            last_dor = ""
            claim_succeeded = False

            # Attempt to claim with coordinator in order of least pending
            while state_queue or args.district:
                target_cand = args.district or (state_queue[0] if state_queue else None)
                logging.info(f"Requesting task lease from central coordinator: {target_cand or preferred_state_arg or 'any'} (least pending priority)...")
                claim_res = await coordinator.claim_task(
                    preferred_state=(None if target_cand else preferred_state_arg),
                    preferred_district=target_cand
                )
                if claim_res.get("success"):
                    dist_code = claim_res.get("district_code")
                    start_num = claim_res.get("start_num", 1)
                    limit = claim_res.get("limit", 500000)
                    prev_extracted = int(claim_res.get("prev_extracted") or 0)
                    last_record = claim_res.get("last_record", "")
                    last_dor = claim_res.get("last_dor", "")
                    pending_count = claim_res.get("pending", "N/A")
                    claim_attempts = 0
                    claim_succeeded = True
                    if state_queue and state_queue[0] == dist_code:
                        state_queue.pop(0)
                    logging.info(f"Coordinator Assigned Task: {dist_code} (Pending: {pending_count}, Resuming #{start_num})")
                    break
                else:
                    msg = claim_res.get("message", "No available districts matching criteria.")
                    logging.warning(f"Coordinator claim rejected for {target_cand}: {msg}")
                    if args.district:
                        break  # User requested specific district, don't fallback to another district
                    if state_queue:
                        skipped = state_queue.pop(0)
                        logging.info(f"Skipping already leased/unavailable {skipped}, checking next least-pending candidate...")
                    else:
                        break

            if not claim_succeeded:
                claim_attempts += 1
                logging.warning(f"Coordinator could not grant lease. Attempt {claim_attempts}")

                if args.district:
                    # DIRECT DISTRICT OVERRIDE:
                    dist_code = args.district.upper().strip()
                    last_info = find_district_last_number(dist_code)
                    start_num = max(1, last_info.get("max_number", 0) + 1)
                    last_record = last_info.get("last_record", "")
                    last_dor = last_info.get("last_dor", "")
                    prev_extracted = last_info.get("max_number", 0)
                    logging.info(f"Direct District Override: Proceeding with {dist_code} (Resuming from #{start_num}, Last DOR: {last_dor or 'None'}).")
                elif state_queue:
                    # LOCAL LEAST-PENDING PRIORITY QUEUE:
                    dist_code = state_queue.pop(0)
                    last_info = find_district_last_number(dist_code)
                    start_num = max(1, last_info.get("max_number", 0) + 1)
                    last_record = last_info.get("last_record", "")
                    last_dor = last_info.get("last_dor", "")
                    prev_extracted = last_info.get("max_number", 0)
                    logging.info(f"Local Least-Pending Sequence: Claiming {dist_code} ({len(state_queue)} remaining in queue, Resuming from #{start_num}).")
                else:
                    # FLEET AUTONOMOUS FALLBACK:
                    uncompleted = [d for d in get_districts_by_least_pending() if d.get("status", "").lower() != "completed" and d.get("pending", 0) > 0]
                    if uncompleted:
                        import hashlib
                        m_hash = int(hashlib.md5(machine.encode()).hexdigest(), 16)
                        pool_size = min(5, len(uncompleted))
                        pick_idx = (m_hash + districts_completed_count) % pool_size
                        cand = uncompleted[pick_idx]
                        dist_code = cand["code"]
                        last_info = find_district_last_number(dist_code)
                        start_num = max(1, last_info.get("max_number", 0) + 1)
                        last_record = last_info.get("last_record", "")
                        last_dor = last_info.get("last_dor", "")
                        prev_extracted = last_info.get("max_number", 0)
                        logging.info(f"Fleet Autonomous Fallback: Claiming least-pending district {dist_code} ({cand['district_name']}, {cand['state_name']} - pending: {cand['pending']}) for worker '{machine}' (Resuming from #{start_num}).")
                    else:
                        logging.info("No tasks available from coordinator and no direct targets queued. Waiting 20s before retry...")
                        if not getattr(args, "no_auto_update", False):
                            if check_and_apply_git_update():
                                logging.info("🔄 [AUTO-UPDATE] Codebase updated while idle. Restarting worker...")
                                restart_worker()
                                return
                        await asyncio.sleep(20)
                        continue

            logging.info(f"Task Claimed: {dist_code} | Start: #{start_num} | Limit: #{limit} | Prev Extracted: {prev_extracted}")

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
                heartbeat_callback=heartbeat,
                initial_success_count=prev_extracted,
                existing_last_record=last_record,
                existing_last_dor=last_dor
            )

            # Automatic Cleanup & Recovery Pass: Rerun ONLY timed-out / transient failed records from this session
            if not getattr(args, "no_auto_rerun", False):
                from client.core.scraper import get_district_failed_and_missing, execute_district_rerun
                audit = get_district_failed_and_missing(dist_code, min_seq_num=start_num)
                failed_count = audit.get("failed_count", 0)
                if failed_count > 0:
                    logging.info(
                        f"[{dist_code}] 🔍 Initiating auto-recovery pass on {failed_count} transient timeout/failed records "
                        f"(skipping sequence gaps & {audit.get('dereg_unreg_count', 0)} settled deregistered/unregistered)..."
                    )
                    try:
                        rerun_res = await execute_district_rerun(
                            prefix=dist_code,
                            rerun_type="failed",
                            concurrency=args.concurrency,
                            update_archive=False,
                            min_seq_num=start_num
                        )
                        recovered = rerun_res.get("recovered", 0)
                        if recovered > 0:
                            logging.info(f"[{dist_code}] 🎉 Auto-recovery recovered {recovered} records!")
                        updated_audit = get_district_failed_and_missing(dist_code, min_seq_num=start_num)
                        res["total_extracted"] = res.get("total_extracted", 0) + recovered
                        res["total_failed"] = updated_audit["failed_count"]
                        res["total_dereg_unreg"] = updated_audit["dereg_unreg_count"]
                    except Exception as e:
                        logging.warning(f"[{dist_code}] Auto-recovery pass encountered error: {e}")
                else:
                    logging.info(f"[{dist_code}] Clean run! 0 transient failures to recover.")
                    res["total_failed"] = 0
                    res["total_dereg_unreg"] = audit.get("dereg_unreg_count", 0)

            final_record = res.get("last_record") or last_record
            final_dor = res.get("last_dor") or last_dor
            
            # Ensure total_extracted reflects true nationwide ground truth (archive or accumulated)
            final_audit = get_district_failed_and_missing(dist_code, min_seq_num=start_num)
            archived_count = final_audit.get("total_extracted", 0)
            base_count = int(prev_extracted or 0)
            session_extracted = res.get("total_extracted", 0)

            if archived_count > base_count:
                total_extracted = archived_count
            else:
                total_extracted = base_count + session_extracted

            total_failed = final_audit.get("failed_count", 0)

            logging.info(f"District {dist_code} complete. Finalizing in Google Sheet (Total: {total_extracted}, Failures: {total_failed}, DOR: {final_dor})...")
            await coordinator.complete_task(
                district_code=dist_code,
                final_record=final_record,
                final_dor=final_dor,
                total_extracted=total_extracted,
                total_failed=total_failed
            )

            logging.info(f"Compressing {dist_code} and uploading to Google Drive...")
            await compress_and_upload_district(dist_code, coordinator=coordinator)

            # Check for git updates before starting next district
            if not getattr(args, "no_auto_update", False):
                if check_and_apply_git_update():
                    logging.info("🔄 [AUTO-UPDATE] Codebase updated. Restarting worker...")
                    restart_worker()
                    return

            districts_completed_count += 1
            if args.district:
                logging.info(f"Target district {args.district} completed. Exiting.")
                break
            if getattr(args, 'max_districts', None) and districts_completed_count >= args.max_districts:
                logging.info(f"Target districts ({args.max_districts}) completed. Exiting.")
                break
            if args.state and not state_queue:
                logging.info(f"All districts in state {args.state} have been processed! Exiting.")
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
    parser.add_argument("--rerun-failed", action="store_true", help="Rerun all previously failed records for district(s)")
    parser.add_argument("--rerun-missing", action="store_true", help="Detect and rerun all sequence gap records for district(s)")
    parser.add_argument("--rerun-type", type=str, choices=["none", "failed", "missing", "all"], default="none", help="Rerun mode for records")
    parser.add_argument("--no-auto-rerun", action="store_true", help="Disable automatic post-extraction recovery pass on failed and missing records")
    parser.add_argument("--no-auto-update", action="store_true", help="Disable automatic git check and reload between tasks")
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
