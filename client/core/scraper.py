"""
Optimized Udyam Scraper Engine.
Features:
- Zero failure screenshotting (clean, fast, zero disk bloat).
- High-performance OCR with adaptive preprocessing.
- Dynamic business day / Friday / today DOR thresholding.
- Fast leapfrog lookahead probing (replaces slow 100 consecutive failure wait).
- Direct integration with central coordinator and batch heartbeat updates.
"""

import asyncio
import base64
import csv
import io
import logging
import os
import re
import shutil
import subprocess
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from scrapling.fetchers import AsyncStealthySession

from client.core.ocr import solve_captcha

HOME_URL = "https://www.udyamregistration.gov.in/Default.aspx"
VERIFY_URL = "https://www.udyamregistration.gov.in/Udyam_Verify.aspx"
MAX_RETRIES = 2


def get_7z_binary() -> str | None:
    """Finds 7-Zip binary across PATH and standard install locations."""
    for bin_name in ("7z", "7za", "7zr"):
        found = shutil.which(bin_name)
        if found:
            return found
    common_paths = [
        Path(r"C:\Program Files\7-Zip\7z.exe"),
        Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
        Path("/usr/bin/7z"),
        Path("/usr/local/bin/7z"),
    ]
    for p in common_paths:
        if p.is_file():
            return str(p)
    return None


def get_latest_valid_business_day() -> date:
    """
    Computes the most recent active registration business day (Friday on weekends/Mondays).
    """
    today = date.today()
    weekday = today.weekday()  # Monday is 0, Sunday is 6
    if weekday == 6:  # Sunday -> Friday
        return today - timedelta(days=2)
    elif weekday == 5:  # Saturday -> Friday
        return today - timedelta(days=1)
    elif weekday == 0:  # Monday -> Friday
        return today - timedelta(days=3)
    else:  # Tuesday through Friday -> yesterday or today
        return today - timedelta(days=1)


def parse_dor(dor_str: str) -> date | None:
    """Parses Date of Registration string into a date object."""
    if not dor_str:
        return None
    cleaned = dor_str.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    return None


async def abort_unnecessary_resources(route):
    """Aborts heavy assets to maximize browser throughput."""
    url = route.request.url.lower()
    blocked_keywords = [
        "googletagmanager.com", "google-analytics.com", "printdiv.css",
        "vendor/main.css", "analytics.js", "bootstrap-icons.css",
        "bootstrap.min.css", "icofont.min.css", "msmelogo.png",
        "style.css", "slick-theme.css", "scriptresource.axd",
        "contact.js", "script.js", "slick.min.js", "webresource.axd",
        "website_translation_utility.js", "bootstrap.min.js",
        "jquery.counterup.min.js", "shuffle.min.js", "map.js",
        "jquery.js", "popper.js", "jquery.waypoints.min.js",
        "jquery.easing.js", "slick.css", "vendor/main.js"
    ]
    if any(k in url for k in blocked_keywords):
        await route.abort()
        return

    res_type = route.request.resource_type
    if res_type in ["font", "media", "websocket", "stylesheet"]:
        await route.abort()
    elif res_type == "image":
        if "captcha" not in url:
            await route.abort()
        else:
            await route.continue_()
    else:
        await route.continue_()


async def detect_failure_reason(page: Page, default_reason: str = "") -> str:
    """
    Extracts the exact failure, cancellation, or rejection reason from the current page.
    Captures:
    - JavaScript alert dialog messages (e.g. invalid format, cancellation)
    - ASP.NET validation labels (lblMsg, lblMessage, lblError, lblCancellationMsg)
    - Semantic keyword detection (Cancelled, Deregistered, Migrated, Not Found, Timeout)
    """
    # 1. Dialog alert captured
    if hasattr(page, "_last_dialog_message") and page._last_dialog_message:
        msg = page._last_dialog_message.strip()
        page._last_dialog_message = ""
        return f"Portal Alert: {msg}"

    # 2. Check for explicit error/status labels in the page DOM
    error_selectors = [
        "#ctl00_ContentPlaceHolder1_lblMsg",
        "#ctl00_ContentPlaceHolder1_lblMessage",
        "#ctl00_ContentPlaceHolder1_lblError",
        "#ctl00_ContentPlaceHolder1_lblCancellationMsg",
        "#ctl00_ContentPlaceHolder1_lblCancel",
        "#ctl00_ContentPlaceHolder1_ValidationSummary1",
        ".alert-danger",
        ".alert-warning",
        ".text-danger",
    ]
    for sel in error_selectors:
        try:
            loc = page.locator(sel)
            if await loc.is_visible(timeout=250):
                txt = (await loc.inner_text()).strip()
                if txt and "enter" not in txt.lower() and "captcha" not in txt.lower():
                    return f"Portal Message: {txt}"
        except Exception:
            pass

    # 3. Check full page body content for known status states
    try:
        body_text = (await page.locator("body").inner_text()).lower()
        if "cancelled" in body_text or "canceled" in body_text or "cancellation" in body_text:
            return "Registration Cancelled / De-registered"
        if "migrated" in body_text:
            return "Registration Migrated / Re-classified"
        if "does not exist" in body_text or "no record found" in body_text or "record not found" in body_text:
            return "Record Not Found / Does Not Exist in Portal"
        if "invalid" in body_text and ("udyam" in body_text or "registration" in body_text or "number" in body_text):
            return "Invalid Registration Number Format"
        if "suspended" in body_text:
            return "Registration Suspended"
        if "server error" in body_text or "runtime error" in body_text:
            return "Portal Server Error (500/Runtime)"
    except Exception:
        pass

    return default_reason or "Record Not Found / Unregistered Number"


async def process_udyam_number(page: Page, udyam_number: str) -> tuple[str, str, str, str, str]:
    """
    Submits a single Udyam registration number and extracts details if found.
    Returns: (status, enterprise_name, html_content, failure_reason, dor_text)
    """
    # Ensure dialog listener is attached to capture portal alert messages
    if not hasattr(page, "_dialog_attached"):
        def handle_dialog(dialog):
            page._last_dialog_message = dialog.message
            asyncio.create_task(dialog.accept())
        page.on("dialog", handle_dialog)
        page._dialog_attached = True
        page._last_dialog_message = ""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if "Udyam_Verify.aspx" not in page.url:
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=3000)
                await page.goto(VERIFY_URL, wait_until="domcontentloaded", timeout=3000)

            if "Default.aspx" in page.url:
                menu_btn = page.locator('a:has-text("Print/Verify")').first
                await menu_btn.hover()
                await asyncio.sleep(0.2)
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=3000):
                    await page.locator('a:has-text("Verify Udyam Registration")').first.click()

            # Clean navbar to accelerate rendering
            try:
                await page.evaluate("document.querySelectorAll('header, #header, .navbar, #navmenu, .navmenu').forEach(el => el.remove());")
            except Exception:
                pass

            # High-speed in-memory canvas capture (2-5ms) vs heavy CDP screenshot (150-300ms)
            image_bytes = None
            try:
                b64_str = await page.evaluate('''() => {
                    const img = document.getElementById('ctl00_ContentPlaceHolder1_imgCaptcha');
                    if (!img || !img.complete) return null;
                    const canvas = document.createElement('canvas');
                    canvas.width = img.naturalWidth || img.width || 150;
                    canvas.height = img.naturalHeight || img.height || 50;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    const dataUrl = canvas.toDataURL('image/png');
                    return dataUrl.indexOf(',') !== -1 ? dataUrl.split(',')[1] : null;
                }''')
                if b64_str:
                    image_bytes = base64.b64decode(b64_str)
            except Exception:
                pass

            if not image_bytes:
                captcha_img = page.locator('#ctl00_ContentPlaceHolder1_imgCaptcha')
                await page.wait_for_function("document.getElementById('ctl00_ContentPlaceHolder1_imgCaptcha')?.complete", timeout=2000)
                image_bytes = await captcha_img.screenshot()

            captcha_text = await solve_captcha(image_bytes)

            await page.locator('#ctl00_ContentPlaceHolder1_txtUdyamNo').fill(udyam_number, timeout=2500)
            await page.locator('#ctl00_ContentPlaceHolder1_txtCaptcha').fill(captcha_text)

            try:
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=3500):
                    await page.locator('#ctl00_ContentPlaceHolder1_btnVerify').click(force=True, timeout=2500)
            except PlaywrightTimeoutError:
                pass

            enterprise_name_locator = page.locator('#ctl00_ContentPlaceHolder1_lblEnterpriseName')

            if await enterprise_name_locator.is_visible():
                html_content = await page.content()
                ent_name = (await enterprise_name_locator.inner_text()).strip()

                doi_locator = page.locator('#ctl00_ContentPlaceHolder1_lbldateofincorporation')
                doi_text = (await doi_locator.inner_text()).strip() if await doi_locator.is_visible() else ""

                dor_locator = page.locator('#ctl00_ContentPlaceHolder1_lblACKNOWLEDGEMENT')
                dor_text = (await dor_locator.inner_text()).strip() if await dor_locator.is_visible() else ""

                # Fast return to Udyam_Verify.aspx via window.location (0.2s)
                try:
                    async with page.expect_navigation(wait_until="domcontentloaded", timeout=2500):
                        await page.evaluate("window.location = 'Udyam_Verify.aspx';")
                except Exception:
                    pass

                return "Success", ent_name, html_content, "Extracted", dor_text
            else:
                error_captcha = page.locator('#ctl00_ContentPlaceHolder1_lblCaptchaMsg')
                if await error_captcha.is_visible() and (await error_captcha.inner_text()).strip():
                    continue  # Retry captcha
                else:
                    reason = await detect_failure_reason(page, "Record Not Found / Unregistered")
                    # High-speed optimization: on failure, the portal response is already on Udyam_Verify.aspx with a new captcha ready!
                    # Do NOT reload window.location if already on Udyam_Verify.aspx
                    if "Udyam_Verify.aspx" not in page.url:
                        try:
                            async with page.expect_navigation(wait_until="domcontentloaded", timeout=2000):
                                await page.evaluate("window.location = 'Udyam_Verify.aspx';")
                        except Exception:
                            pass
                    return f"Failed ({reason})", "", "", reason, ""

        except PlaywrightTimeoutError:
            if attempt == MAX_RETRIES:
                return "Failed (Timeout)", "", "", "Page Request Timeout / Server Slow", ""
            await asyncio.sleep(0.5)
        except Exception as e:
            if attempt == MAX_RETRIES:
                return f"Failed ({type(e).__name__})", "", "", f"{type(e).__name__}: {str(e)[:60]}", ""
            await asyncio.sleep(0.5)

    return "Failed (Captcha)", "", "", "Captcha Verification Failed after Max Retries", ""


def flush_results_batch(results_dir: Path, failed_dir: Path, results_batch: list, failed_batch: list, html_batch: dict):
    """Flushes buffered records to local CSV files and saves HTML documents."""
    for udyam_num, html in html_batch.items():
        m = re.match(r"^(UDYAM-[A-Z]{2}-\d{2})-", udyam_num)
        prefix = m.group(1).replace("UDYAM-", "") if m else "UNKNOWN"
        folder = results_dir / prefix
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / f"{udyam_num}.html", "w", encoding="utf-8") as f:
            f.write(html)

    # Group and append results
    res_grouped = defaultdict(list)
    for row in results_batch:
        m = re.match(r"^(UDYAM-[A-Z]{2}-\d{2})-", row[0])
        prefix = m.group(1).replace("UDYAM-", "") if m else "UNKNOWN"
        res_grouped[prefix].append(row)

    for prefix, rows in res_grouped.items():
        folder = results_dir / prefix
        folder.mkdir(parents=True, exist_ok=True)
        csv_path = folder / f"results_{prefix}.csv"
        write_header = not csv_path.exists() or csv_path.stat().st_size == 0
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["Number", "Status", "EnterpriseName", "DateOfRegistration", "TimeTaken(s)"])
            w.writerows(rows)

    # Group and append failures with Reason and Timestamp
    fail_grouped = defaultdict(list)
    for row in failed_batch:
        m = re.match(r"^(UDYAM-[A-Z]{2}-\d{2})-", row[0])
        prefix = m.group(1).replace("UDYAM-", "") if m else "UNKNOWN"
        fail_grouped[prefix].append(row)

    for prefix, rows in fail_grouped.items():
        folder = failed_dir / prefix
        folder.mkdir(parents=True, exist_ok=True)
        csv_path = folder / f"failed_{prefix}.csv"
        write_header = not csv_path.exists() or csv_path.stat().st_size == 0
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["Number", "Status", "Reason", "Timestamp", "TimeTaken(s)"])
            for r in rows:
                if len(r) == 5:
                    w.writerow(r)
                elif len(r) == 3:
                    # Backward compatibility for 3-item rows: [num, status, elapsed]
                    st_str = str(r[1])
                    reason_extracted = st_str.replace("Failed (", "").rstrip(")")
                    w.writerow([r[0], r[1], reason_extracted, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), r[2]])
                else:
                    w.writerow(r)


async def execute_district_extraction(
    prefix: str,
    start_num: int,
    limit: int,
    concurrency: int = 2,
    results_dir: Path = Path("results"),
    failed_dir: Path = Path("failed"),
    heartbeat_callback = None,
    stop_event: asyncio.Event = None,
    ignore_local_lookup: bool = False,
    initial_success_count: int = 0,
    existing_last_record: str = "",
    existing_last_dor: str = ""
) -> dict:
    """
    Executes high-throughput extraction for a single district prefix (e.g. 'UDYAM-TN-05').
    Utilizes leapfrog probing and business day DOR threshold for early boundary detection.
    Supports incremental resume on previously extracted districts to harvest newly registered MSMEs.
    """
    clean_prefix = prefix.replace("UDYAM-", "")
    results_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    # Load already processed numbers (if local lookup enabled)
    processed_success = set()
    processed_failed = set()
    if not ignore_local_lookup:
        res_csv = results_dir / clean_prefix / f"results_{clean_prefix}.csv"
        if res_csv.exists():
            with open(res_csv, "r", encoding="utf-8", errors="replace") as f:
                r = csv.reader(f)
                next(r, None)
                for row in r:
                    if row:
                        processed_success.add(row[0].strip())

        fail_csv = failed_dir / clean_prefix / f"failed_{clean_prefix}.csv"
        if fail_csv.exists():
            with open(fail_csv, "r", encoding="utf-8", errors="replace") as f:
                r = csv.reader(f)
                next(r, None)
                for row in r:
                    if row and len(row) > 0:
                        uid = row[0].strip()
                        # Differentiate true portal Not Found from transient network/captcha errors
                        status = row[1].lower() if len(row) > 1 else ""
                        reason = row[2].lower() if len(row) > 2 else ""
                        is_transient = any(k in status or k in reason for k in ("captcha", "timeout", "server slow", "playwright", "connection"))
                        # Only skip if it was a verified true portal miss; allow transient errors to be re-attempted
                        if not is_transient:
                            processed_failed.add(uid)

    processed_numbers = processed_success | processed_failed
    last_business_day = get_latest_valid_business_day()
    is_at_cutting_edge = False

    total_success = max(len(processed_success), int(initial_success_count or 0))
    total_failures = len(processed_failed)
    last_record_id = existing_last_record
    latest_dor_str = existing_last_dor
    if latest_dor_str:
        init_dor = parse_dor(latest_dor_str)
        if init_dor and init_dor >= last_business_day:
            is_at_cutting_edge = True

    results_batch = []
    failed_batch = []
    html_batch = {}
    BATCH_SIZE = 50

    start_time = time.perf_counter()
    consecutive_not_found = 0

    num_workers = max(1, int(concurrency or 2))
    next_num = start_num
    num_lock = asyncio.Lock()
    batch_lock = asyncio.Lock()
    probe_lock = asyncio.Lock()
    stop_event_local = asyncio.Event()

    async def get_next_job():
        nonlocal next_num
        async with num_lock:
            while next_num <= limit:
                if stop_event and stop_event.is_set():
                    return None, None
                if stop_event_local.is_set():
                    return None, None
                num = next_num
                next_num += 1
                udyam_id = f"UDYAM-{clean_prefix}-{num:07d}"
                if udyam_id not in processed_numbers:
                    return num, udyam_id
            return None, None

    async def worker_loop(worker_id: int, page: Page):
        nonlocal total_success, total_failures, last_record_id, latest_dor_str
        nonlocal consecutive_not_found, is_at_cutting_edge
        records_processed = 0

        while True:
            if stop_event and stop_event.is_set():
                break
            if stop_event_local.is_set():
                break

            current_n, udyam_number = await get_next_job()
            if current_n is None:
                break

            # Refresh page every 60 records to prevent memory leaks on SBCs
            if records_processed >= 60:
                try:
                    await page.close()
                except Exception:
                    pass
                page = await session.context.new_page()
                await page.route("**/*", abort_unnecessary_resources)
                try:
                    await page.goto(VERIFY_URL, wait_until="domcontentloaded", timeout=4000)
                except Exception:
                    pass
                records_processed = 0

            t0 = time.perf_counter()
            status, enterprise_name, html_content, failure_reason, dor_text = await process_udyam_number(page, udyam_number)
            elapsed = round(time.perf_counter() - t0, 2)
            records_processed += 1

            should_flush = False
            async with batch_lock:
                if status.startswith("Success"):
                    total_success += 1
                    last_record_id = udyam_number
                    consecutive_not_found = 0
                    results_batch.append([udyam_number, status, enterprise_name, dor_text, elapsed])
                    html_batch[udyam_number] = html_content

                    if dor_text:
                        latest_dor_str = dor_text
                        dor_date = parse_dor(dor_text)
                        if dor_date and dor_date >= last_business_day:
                            is_at_cutting_edge = True

                    logging.info(f"[W-{worker_id}] [{udyam_number}] OK ({elapsed}s) -> {enterprise_name} | DOR: {dor_text}")

                else:
                    total_failures += 1
                    reason = failure_reason or status.replace("Failed (", "").rstrip(")")
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    failed_batch.append([udyam_number, status, reason, ts, elapsed])
                    
                    # ONLY increment consecutive_not_found on true "Record Not Found" responses from portal!
                    # Do NOT increment on Timeout, Captcha failure, or network errors!
                    is_true_miss = any(k in reason.lower() for k in ("not found", "unregistered", "portal message", "invalid", "does not exist"))
                    if is_true_miss:
                        consecutive_not_found += 1
                    logging.info(f"[W-{worker_id}] [{udyam_number}] FAIL -> Reason: {reason} ({elapsed}s)")

                    # BOUNDARY DETECTION 1: Live Cutting Edge Exit
                    # ONLY exit if we have verified records from TODAY or recent business days (last 4 days)
                    if is_at_cutting_edge and consecutive_not_found >= 10:
                        logging.info(f"*** District {clean_prefix} caught up with live portal! Latest DOR: {latest_dor_str} with {consecutive_not_found} consecutive tail misses. Finished live pass. ***")
                        stop_event_local.set()

                    # BOUNDARY DETECTION 2: Historical Gap Leapfrog Probing
                    # If date is historical (e.g. 2020-2025) or unstarted, a sequence gap does NOT mean the district is complete!
                    elif consecutive_not_found >= 10 and not stop_event_local.is_set():
                        async with probe_lock:
                            if consecutive_not_found >= 10 and not stop_event_local.is_set():
                                logging.info(f"[W-{worker_id}] Encountered sequence gap at #{current_n} for {clean_prefix} (Last DOR: {latest_dor_str or 'None'}). Initiating wide lookahead probe...")
                                found_probe_num = None
                                prev_offset = 0
                                
                                # Exponential probe ladder up to district limit (from +25 up to +100,000)
                                probe_ladder = [25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]
                                for offset in probe_ladder:
                                    target_p = current_n + offset
                                    if target_p > limit:
                                        target_p = limit
                                    probe_id = f"UDYAM-{clean_prefix}-{target_p:07d}"
                                    p_status, p_name, _, _, p_dor = await process_udyam_number(page, probe_id)
                                    if p_status.startswith("Success"):
                                        logging.info(f"✨ Wide probe HIT at {probe_id} ({p_name} | DOR: {p_dor})! Pinpointing first valid record after gap...")
                                        
                                        # Binary search between (current_n + prev_offset) and target_p to find the first valid record
                                        low = current_n + prev_offset + 1
                                        high = target_p
                                        first_valid = target_p
                                        while low <= high:
                                            mid = (low + high) // 2
                                            mid_id = f"UDYAM-{clean_prefix}-{mid:07d}"
                                            m_status, _, _, _, _ = await process_udyam_number(page, mid_id)
                                            if m_status.startswith("Success"):
                                                first_valid = mid
                                                high = mid - 1
                                            else:
                                                low = mid + 1
                                        
                                        found_probe_num = first_valid
                                        break
                                    
                                    if target_p >= limit:
                                        break
                                    prev_offset = offset

                                if found_probe_num is not None:
                                    logging.info(f"🚀 Leapfrogged sequence gap! Resuming {clean_prefix} from #{found_probe_num}...")
                                    async with num_lock:
                                        nonlocal next_num
                                        if next_num < found_probe_num:
                                            next_num = found_probe_num
                                    consecutive_not_found = 0
                                else:
                                    # All probes up to limit / 100,000 were empty!
                                    if is_at_cutting_edge:
                                        logging.info(f"*** District {clean_prefix} completed: Reached cutting edge DOR and no further records exist. ***")
                                    else:
                                        logging.warning(f"*** District {clean_prefix} sequence end: All wide probes up to #{limit} empty. Last DOR: {latest_dor_str}. ***")
                                    stop_event_local.set()

                if len(results_batch) + len(failed_batch) >= BATCH_SIZE:
                    should_flush = True
                    flush_res = list(results_batch)
                    flush_fail = list(failed_batch)
                    flush_html = dict(html_batch)
                    results_batch.clear()
                    failed_batch.clear()
                    html_batch.clear()

            if should_flush:
                flush_results_batch(results_dir, failed_dir, flush_res, flush_fail, flush_html)
                if heartbeat_callback:
                    total_time = max(1.0, time.perf_counter() - start_time)
                    speed_rpm = round((total_success / total_time) * 60, 1)
                    await heartbeat_callback(
                        district_code=clean_prefix,
                        current_record=last_record_id,
                        current_dor=latest_dor_str,
                        total_extracted=total_success,
                        total_failed=total_failures,
                        speed_rpm=speed_rpm
                    )

    async with AsyncStealthySession(headless=True) as session:
        pages = []
        for _ in range(num_workers):
            p = await session.context.new_page()
            await p.route("**/*", abort_unnecessary_resources)
            try:
                await p.goto(VERIFY_URL, wait_until="domcontentloaded", timeout=4000)
            except Exception:
                pass
            pages.append(p)

        logging.info(f"🚀 Initialized {num_workers} parallel extraction workers for district {clean_prefix}...")
        worker_tasks = [
            asyncio.create_task(worker_loop(w_idx + 1, pages[w_idx]))
            for w_idx in range(num_workers)
        ]
        await asyncio.gather(*worker_tasks)

    # Final flush
    async with batch_lock:
        if results_batch or failed_batch:
            flush_results_batch(results_dir, failed_dir, results_batch, failed_batch, html_batch)
            results_batch.clear()
            failed_batch.clear()
            html_batch.clear()

    return {
        "district_code": clean_prefix,
        "last_record": last_record_id,
        "last_dor": latest_dor_str,
        "total_extracted": total_success,
        "total_failed": total_failures
    }


def get_district_failed_and_missing(
    prefix: str,
    results_dir: Path = Path("results"),
    failed_dir: Path = Path("failed")
) -> dict:
    """
    Scans a district's results and failures to identify:
    1. All logged failed records from failed_<prefix>.csv (or .7z archive).
    2. All sequence gap records missing between 1 and max_record_num.
    3. The complete set of numbers missing from verified results.
    """
    clean_prefix = prefix.replace("UDYAM-", "").strip().upper()
    seven_zip = get_7z_binary()

    success_numbers = set()
    max_record_num = 0

    # 1. Inspect Results (Folder first, then .7z archive)
    res_csv = results_dir / clean_prefix / f"results_{clean_prefix}.csv"
    res_content = None

    if res_csv.is_file():
        try:
            with open(res_csv, "r", encoding="utf-8", errors="replace") as f:
                res_content = f.read()
        except Exception:
            pass
    elif seven_zip:
        archive_path = results_dir / f"{clean_prefix}.7z"
        if archive_path.is_file():
            try:
                proc = subprocess.run(
                    [seven_zip, "e", str(archive_path), "-r", f"results_{clean_prefix}.csv", "-so"],
                    capture_output=True,
                    text=True,
                    errors="replace"
                )
                if proc.stdout:
                    res_content = proc.stdout
            except Exception:
                pass

    if res_content:
        reader = csv.reader(io.StringIO(res_content))
        next(reader, None)
        for row in reader:
            if row and row[0].strip():
                num_id = row[0].strip()
                m = re.search(r"-(\d+)$", num_id)
                if m:
                    val = int(m.group(1))
                    success_numbers.add(val)
                    if val > max_record_num:
                        max_record_num = val

    # 2. Inspect Failed (Folder first, then .7z archive)
    failed_records = {}  # seq_num -> row data
    fail_csv = failed_dir / clean_prefix / f"failed_{clean_prefix}.csv"
    fail_content = None

    if fail_csv.is_file():
        try:
            with open(fail_csv, "r", encoding="utf-8", errors="replace") as f:
                fail_content = f.read()
        except Exception:
            pass
    elif seven_zip:
        archive_path = results_dir / f"{clean_prefix}.7z"
        if archive_path.is_file():
            try:
                proc = subprocess.run(
                    [seven_zip, "e", str(archive_path), "-r", f"failed_{clean_prefix}.csv", "-so"],
                    capture_output=True,
                    text=True,
                    errors="replace"
                )
                if proc.stdout:
                    fail_content = proc.stdout
            except Exception:
                pass

    if fail_content:
        reader = csv.reader(io.StringIO(fail_content))
        next(reader, None)
        for row in reader:
            if row and row[0].strip():
                num_id = row[0].strip()
                m = re.search(r"-(\d+)$", num_id)
                if m:
                    val = int(m.group(1))
                    failed_records[val] = row

    failed_numbers = sorted(list(failed_records.keys()))
    failed_set = set(failed_numbers)

    # 3. Calculate sequence gaps in range 1..max_record_num
    all_sequence = set(range(1, max_record_num + 1)) if max_record_num > 0 else set()
    missing_gaps = sorted(list(all_sequence - success_numbers - failed_set))
    all_missing_from_results = sorted(list(all_sequence - success_numbers))

    has_archive = (results_dir / f"{clean_prefix}.7z").is_file()

    return {
        "district_code": clean_prefix,
        "total_extracted": len(success_numbers),
        "max_record_num": max_record_num,
        "failed_numbers": failed_numbers,
        "failed_count": len(failed_numbers),
        "failed_records": failed_records,
        "missing_gaps": missing_gaps,
        "missing_gaps_count": len(missing_gaps),
        "all_missing_from_results": all_missing_from_results,
        "all_missing_count": len(all_missing_from_results),
        "has_archive": has_archive
    }


async def execute_district_rerun(
    prefix: str,
    rerun_type: str = "failed",
    concurrency: int = 2,
    results_dir: Path = Path("results"),
    failed_dir: Path = Path("failed"),
    heartbeat_callback = None,
    stop_event: asyncio.Event = None,
    update_archive: bool = True
) -> dict:
    """
    Reruns failed or missing records for a district, capturing the exact failure reason
    if any record remains unextractable.

    Rerun types:
    - 'failed': Targets records listed in failed_<prefix>.csv. If extracted, moves to results and removes from failed.
    - 'missing': Targets sequence gap numbers (between 1 and max_record) that were skipped.
    - 'all': Targets both failed records and sequence gaps.
    """
    clean_prefix = prefix.replace("UDYAM-", "").strip().upper()
    logging.info(f"[{clean_prefix}] Initializing rerun task (Mode: {rerun_type.upper()})...")

    audit = get_district_failed_and_missing(clean_prefix, results_dir, failed_dir)

    if rerun_type == "failed":
        target_seq_nums = audit["failed_numbers"]
    elif rerun_type == "missing":
        target_seq_nums = audit["missing_gaps"]
    elif rerun_type == "all":
        target_seq_nums = audit["all_missing_from_results"]
    else:
        raise ValueError(f"Unknown rerun_type: {rerun_type}. Must be 'failed', 'missing', or 'all'.")

    total_targets = len(target_seq_nums)
    if total_targets == 0:
        logging.info(f"[{clean_prefix}] Zero {rerun_type} records found. District dataset is 100% complete!")
        return {
            "district_code": clean_prefix,
            "rerun_type": rerun_type,
            "total_targeted": 0,
            "recovered": 0,
            "still_failed": 0,
            "reasons": {}
        }

    logging.info(f"[{clean_prefix}] Found {total_targets} target {rerun_type} record(s) to rerun.")

    seven_zip = get_7z_binary()
    archive_file = results_dir / f"{clean_prefix}.7z"

    # If working on an archived district and local CSV is absent, unpack CSVs
    dist_results_folder = results_dir / clean_prefix
    dist_results_folder.mkdir(parents=True, exist_ok=True)
    res_csv_path = dist_results_folder / f"results_{clean_prefix}.csv"

    if not res_csv_path.exists() and archive_file.exists() and seven_zip:
        subprocess.run([seven_zip, "e", str(archive_file), "-r", f"results_{clean_prefix}.csv", f"-o{dist_results_folder}", "-y"], capture_output=True)

    dist_failed_folder = failed_dir / clean_prefix
    dist_failed_folder.mkdir(parents=True, exist_ok=True)
    fail_csv_path = dist_failed_folder / f"failed_{clean_prefix}.csv"

    if not fail_csv_path.exists() and archive_file.exists() and seven_zip:
        subprocess.run([seven_zip, "e", str(archive_file), "-r", f"failed_{clean_prefix}.csv", f"-o{dist_failed_folder}", "-y"], capture_output=True)

    # Load existing failed map so we can update or remove recovered records
    failed_map = {}
    if fail_csv_path.exists():
        with open(fail_csv_path, "r", encoding="utf-8", errors="replace") as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                if row and row[0].strip():
                    failed_map[row[0].strip()] = row

    recovered_success = 0
    still_failed = 0
    failure_reasons = []

    results_batch = []
    html_batch = {}

    start_time = time.perf_counter()

    async with AsyncStealthySession(headless=True) as session:
        page = await session.context.new_page()
        await page.route("**/*", abort_unnecessary_resources)
        records_processed = 0

        for idx, seq_num in enumerate(target_seq_nums, start=1):
            if stop_event and stop_event.is_set():
                logging.info(f"[{clean_prefix}] Rerun stopped by user request.")
                break

            if records_processed >= 50:
                try:
                    await page.close()
                except Exception:
                    pass
                page = await session.context.new_page()
                await page.route("**/*", abort_unnecessary_resources)
                records_processed = 0

            udyam_number = f"UDYAM-{clean_prefix}-{seq_num:07d}"
            t0 = time.perf_counter()
            status, enterprise_name, html_content, failure_reason, dor_text = await process_udyam_number(page, udyam_number)
            elapsed = round(time.perf_counter() - t0, 2)
            records_processed += 1

            if status.startswith("Success"):
                recovered_success += 1
                results_batch.append([udyam_number, status, enterprise_name, dor_text, elapsed])
                html_batch[udyam_number] = html_content
                # If was previously logged as failed, remove from failed map
                if udyam_number in failed_map:
                    del failed_map[udyam_number]

                logging.info(f"[{clean_prefix}] [{idx}/{total_targets}] RECOVERED: {udyam_number} -> {enterprise_name} ({elapsed}s)")
            else:
                still_failed += 1
                reason = failure_reason or status.replace("Failed (", "").rstrip(")")
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                failed_map[udyam_number] = [udyam_number, status, reason, ts, elapsed]
                failure_reasons.append(reason)

                logging.info(f"[{clean_prefix}] [{idx}/{total_targets}] UNEXTRACTABLE: {udyam_number} -> Reason: {reason} ({elapsed}s)")

            # Periodic batch flush every 25 records
            if len(results_batch) >= 25:
                flush_results_batch(results_dir, failed_dir, results_batch, [], html_batch)
                results_batch.clear()
                html_batch.clear()

        # Final batch flush
        if results_batch:
            flush_results_batch(results_dir, failed_dir, results_batch, [], html_batch)
            results_batch.clear()
            html_batch.clear()

    # Rewrite failed CSV with updated statuses and reasons
    with open(fail_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Number", "Status", "Reason", "Timestamp", "TimeTaken(s)"])
        for udyam_id, row in sorted(failed_map.items()):
            if len(row) == 5:
                w.writerow(row)
            elif len(row) == 3:
                w.writerow([row[0], row[1], row[1].replace("Failed (", "").replace(")", ""), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row[2]])
            else:
                w.writerow(row)

    # Ingest new HTMLs and updated CSVs into the .7z archive if present
    if update_archive and archive_file.exists() and seven_zip:
        logging.info(f"[{clean_prefix}] Updating .7z archive with rerun results...")
        try:
            # 1. Update results CSV and new HTML files
            subprocess.run([seven_zip, "u", str(archive_file), str(dist_results_folder)], capture_output=True, check=True)
            # 2. Update failed CSV inside archive
            subprocess.run([seven_zip, "u", str(archive_file), str(fail_csv_path)], capture_output=True, check=True)
            logging.info(f"[{clean_prefix}] Archive {archive_file.name} successfully updated!")
        except Exception as e:
            logging.warning(f"[{clean_prefix}] Could not update archive: {e}")

    reasons_summary = dict(Counter(failure_reasons))
    logging.info(
        f"[{clean_prefix}] Rerun complete: {total_targets} targeted | {recovered_success} recovered | "
        f"{still_failed} remaining unextractable. Reasons: {reasons_summary}"
    )

    return {
        "district_code": clean_prefix,
        "rerun_type": rerun_type,
        "total_targeted": total_targets,
        "recovered": recovered_success,
        "still_failed": still_failed,
        "reasons": reasons_summary,
        "total_extracted": audit["total_extracted"] + recovered_success,
        "total_failed": len(failed_map)
    }
