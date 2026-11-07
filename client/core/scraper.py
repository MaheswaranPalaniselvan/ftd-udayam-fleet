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
import csv
import logging
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from scrapling.fetchers import AsyncStealthySession

from client.core.ocr import solve_captcha

HOME_URL = "https://www.udyamregistration.gov.in/Default.aspx"
VERIFY_URL = "https://www.udyamregistration.gov.in/Udyam_Verify.aspx"
MAX_RETRIES = 2


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
    if res_type in ["font", "media", "websocket"]:
        await route.abort()
    elif res_type == "image":
        if "captcha" not in url:
            await route.abort()
        else:
            await route.continue_()
    elif res_type == "stylesheet":
        referer = route.request.headers.get("referer", "").lower()
        if "printudyam" in referer.replace("_", ""):
            await route.abort()
        else:
            await route.continue_()
    else:
        await route.continue_()


async def process_udyam_number(page: Page, udyam_number: str) -> tuple[str, str, str, str, str]:
    """
    Submits a single Udyam registration number and extracts details if found.
    Returns: (status, enterprise_name, html_content, doi_text, dor_text)
    """
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

            udyam_input = page.locator('#ctl00_ContentPlaceHolder1_txtUdyamNo')
            await udyam_input.fill(udyam_number, timeout=2500)

            captcha_img = page.locator('#ctl00_ContentPlaceHolder1_imgCaptcha')
            await page.wait_for_function("document.getElementById('ctl00_ContentPlaceHolder1_imgCaptcha')?.complete")

            # Obtain captcha bytes
            image_bytes = await captcha_img.screenshot()
            captcha_text = await solve_captcha(image_bytes)

            await page.locator('#ctl00_ContentPlaceHolder1_txtCaptcha').fill(captcha_text)

            # Remove header to prevent pointer event interception
            try:
                await page.evaluate("document.querySelectorAll('header, #header, .navbar, #navmenu, .navmenu').forEach(el => el.remove());")
            except Exception:
                pass

            try:
                async with page.expect_navigation(wait_until="load", timeout=3500):
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

                # Fast return to Udyam_Verify.aspx via window.location (0.3s)
                try:
                    async with page.expect_navigation(wait_until="domcontentloaded", timeout=2500):
                        await page.evaluate("window.location = 'Udyam_Verify.aspx';")
                except Exception:
                    pass

                return "Success", ent_name, html_content, doi_text, dor_text
            else:
                error_captcha = page.locator('#ctl00_ContentPlaceHolder1_lblCaptchaMsg')
                if await error_captcha.is_visible() and (await error_captcha.inner_text()).strip():
                    continue  # Retry captcha
                else:
                    return "Failed (Not Found)", "", "", "", ""

        except Exception as e:
            if attempt == MAX_RETRIES:
                return f"Failed ({type(e).__name__})", "", "", "", ""
            await asyncio.sleep(0.5)

    return "Failed (Captcha)", "", "", "", ""


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

    # Group and append failures
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
                w.writerow(["Number", "Status", "TimeTaken(s)"])
            w.writerows(rows)


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
                    if row:
                        processed_failed.add(row[0].strip())

    processed_numbers = processed_success | processed_failed
    last_business_day = get_latest_valid_business_day()
    is_at_cutting_edge = False

    total_success = max(len(processed_success), int(initial_success_count or 0))
    total_failures = len(processed_failed)
    last_record_id = existing_last_record
    latest_dor_str = existing_last_dor

    results_batch = []
    failed_batch = []
    html_batch = {}
    BATCH_SIZE = 50

    start_time = time.perf_counter()
    consecutive_not_found = 0

    async with AsyncStealthySession(headless=True) as session:
        page = await session.context.new_page()
        await page.route("**/*", abort_unnecessary_resources)
        records_processed = 0

        current_num = start_num

        while current_num <= limit:
            if stop_event and stop_event.is_set():
                logging.info("Extraction stopped by user or coordinator.")
                break

            # Refresh page every 50 records to clear memory leaks
            if records_processed >= 50:
                try:
                    await page.close()
                except Exception:
                    pass
                page = await session.context.new_page()
                await page.route("**/*", abort_unnecessary_resources)
                records_processed = 0

            udyam_number = f"UDYAM-{clean_prefix}-{current_num:07d}"

            if udyam_number in processed_numbers:
                current_num += 1
                continue

            t0 = time.perf_counter()
            status, enterprise_name, html_content, _, dor_text = await process_udyam_number(page, udyam_number)
            elapsed = round(time.perf_counter() - t0, 2)
            records_processed += 1

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

                logging.info(f"[{udyam_number}] OK ({elapsed}s) -> {enterprise_name} | DOR: {dor_text}")
                current_num += 1

            else:
                total_failures += 1
                failed_batch.append([udyam_number, status, elapsed])
                consecutive_not_found += 1
                logging.info(f"[{udyam_number}] FAIL ({status}) ({elapsed}s)")

                # BOUNDARY DETECTION 1: Cutting Edge Early Exit
                if is_at_cutting_edge and consecutive_not_found >= 5:
                    logging.info(f"*** District {clean_prefix} completed: Reached today/Friday DOR ({latest_dor_str}) and hit 5 consecutive Not Founds. ***")
                    break

                # BOUNDARY DETECTION 2: Leapfrog Lookahead Probing
                if consecutive_not_found >= 5:
                    logging.info(f"Checking leapfrog probes (+10, +25, +50, +100) for {clean_prefix}...")
                    tail_empty = True
                    for probe_offset in (10, 25, 50, 100):
                        probe_num = current_num + probe_offset
                        if probe_num > limit:
                            break
                        probe_id = f"UDYAM-{clean_prefix}-{probe_num:07d}"
                        p_status, _, _, _, _ = await process_udyam_number(page, probe_id)
                        if p_status.startswith("Success"):
                            logging.info(f"Leapfrog probe found valid record at {probe_id}! Resuming from {probe_id}...")
                            current_num = probe_num - 1
                            tail_empty = False
                            consecutive_not_found = 0
                            break

                    if tail_empty:
                        logging.info(f"*** District {clean_prefix} completed: All leapfrog probes empty up to +100. Finishing district. ***")
                        break

                current_num += 1

            # Flush batch and invoke heartbeat
            if len(results_batch) + len(failed_batch) >= BATCH_SIZE:
                flush_results_batch(results_dir, failed_dir, results_batch, failed_batch, html_batch)
                results_batch.clear()
                failed_batch.clear()
                html_batch.clear()

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

        # Final flush
        if results_batch or failed_batch:
            flush_results_batch(results_dir, failed_dir, results_batch, failed_batch, html_batch)

    return {
        "district_code": clean_prefix,
        "last_record": last_record_id,
        "last_dor": latest_dor_str,
        "total_extracted": total_success,
        "total_failed": total_failures
    }
