import argparse
import asyncio
import base64
import csv
import logging
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
import ddddocr
import httpx
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from scrapling.fetchers import AsyncStealthySession

# Load .env file if present
if os.path.exists(".env"):
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass

MAX_RETRIES = 2
HOME_URL = "https://www.udyamregistration.gov.in/Default.aspx"
VERIFY_URL = "https://www.udyamregistration.gov.in/Udyam_Verify.aspx"
RESULTS_DIR = "results"
FAILED_DIR = "failed"

# Initialize OCR instance once globally
OCR = ddddocr.DdddOcr(show_ad=False)

def _sync_solve_captcha(image_bytes: bytes) -> str:
    """CPU-bound synchronous OCR classification."""
    return OCR.classification(image_bytes)

async def solve_captcha(image_bytes: bytes) -> str:
    return await asyncio.to_thread(_sync_solve_captcha, image_bytes)

def parse_dor(dor_str: str) -> date | None:
    if not dor_str:
        return None
    cleaned = dor_str.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    return None

async def send_telegram_message(bot_token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logging.error(f"Telegram notification failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        logging.error(f"Error sending Telegram message: {e}")

async def telegram_reporter(bot_token: str, chat_id: str, progress_info: dict, interval_seconds: int = 1800):
    if not bot_token or not chat_id:
        return

    state = progress_info.get("state", "N/A")
    await send_telegram_message(
        bot_token,
        chat_id,
        f"🚀 <b>Udyam Scraper Started</b>\n"
        f"📍 <b>State:</b> {state}\n"
        f"⏱ <b>Update Frequency:</b> Every {interval_seconds // 60} mins"
    )

    try:
        while True:
            await asyncio.sleep(interval_seconds)
            state = progress_info.get("state", "N/A")
            prefix = progress_info.get("prefix", "N/A")
            district = prefix.replace("UDYAM-", "") if prefix != "N/A" else "N/A"
            latest_dor = progress_info.get("latest_dor", "N/A")
            last_num = progress_info.get("last_number", "N/A")
            successes = progress_info.get("success_count", 0)
            failures = progress_info.get("fail_count", 0)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            msg = (
                f"📊 <b>Udyam Scraper Progress Update</b>\n\n"
                f"📍 <b>State:</b> {state}\n"
                f"🏛 <b>District Code:</b> {district}\n"
                f"📅 <b>DOR:</b> {latest_dor}\n"
                f"🔢 <b>Current Number:</b> {last_num}\n"
                f"✅ <b>Success:</b> {successes:,}\n"
                f"❌ <b>Failures:</b> {failures:,}\n"
                f"⏰ <b>Time:</b> {now_str}"
            )
            await send_telegram_message(bot_token, chat_id, msg)
    except asyncio.CancelledError:
        state = progress_info.get("state", "N/A")
        prefix = progress_info.get("prefix", "N/A")
        district = prefix.replace("UDYAM-", "") if prefix != "N/A" else "N/A"
        latest_dor = progress_info.get("latest_dor", "N/A")
        last_num = progress_info.get("last_number", "N/A")
        successes = progress_info.get("success_count", 0)
        failures = progress_info.get("fail_count", 0)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        msg = (
            f"🏁 <b>Udyam Scraper Completed / Stopped</b>\n\n"
            f"📍 <b>State:</b> {state}\n"
            f"🏛 <b>District Code:</b> {district}\n"
            f"📅 <b>Final DOR:</b> {latest_dor}\n"
            f"🔢 <b>Final Number:</b> {last_num}\n"
            f"✅ <b>Total Success:</b> {successes:,}\n"
            f"❌ <b>Total Failures:</b> {failures:,}\n"
            f"⏰ <b>Time:</b> {now_str}"
        )
        await send_telegram_message(bot_token, chat_id, msg)

async def save_failure_screenshot(page: Page, udyam_number: str, reason: str):
    try:
        match = re.match(r"^(UDYAM-[A-Z]{2}-\d{2})-", udyam_number)
        prefix = match.group(1).replace("UDYAM-", "") if match else "UNKNOWN"
        folder_path = os.path.join(FAILED_DIR, prefix)
        os.makedirs(folder_path, exist_ok=True)
        
        clean_reason = re.sub(r"[^\w\-_\.]", "_", reason).strip("_")
        file_path = os.path.join(folder_path, f"{udyam_number}_{clean_reason}.png")
        await page.screenshot(path=file_path, full_page=False)
    except Exception:
        pass

async def abort_unnecessary_resources(route):
    url = route.request.url.lower()
    
    BLOCKED_KEYWORDS = [
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
    
    if any(keyword in url for keyword in BLOCKED_KEYWORDS):
        await route.abort()
        return

    if route.request.resource_type in ["font", "media", "websocket", "stylesheet"]:
        await route.abort()
    elif route.request.resource_type == "image":
        if "captcha" not in url:
            await route.abort()
        else:
            await route.continue_()
    else:
        await route.continue_()

def get_already_processed_numbers(state_code: str, start_code: int, end_code: int) -> set[str]:
    processed = set()
    for state_idx in range(start_code, end_code + 1):
        prefix = f"{state_code}-{state_idx:02d}"
        
        # Check results CSV
        results_csv = os.path.join(RESULTS_DIR, prefix, f"results_{prefix}.csv")
        if os.path.exists(results_csv):
            with open(results_csv, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if row:
                        processed.add(row[0].strip())

        # Check failed CSV
        failed_csv = os.path.join(FAILED_DIR, prefix, f"failed_{prefix}.csv")
        if os.path.exists(failed_csv):
            with open(failed_csv, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if row:
                        processed.add(row[0].strip())
    return processed

async def process_udyam_number(page: Page, udyam_number: str) -> tuple[str, str, str, str]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if "Udyam_Verify.aspx" not in page.url:
                # Step 1: Initial navigation to Home Page
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=2500)
                # Step 2: Navigate to Verify Page
                await page.goto(VERIFY_URL, wait_until="domcontentloaded", timeout=2500)

            # Step 3: Handle hover dropdown navigation if redirected back to Default.aspx
            if "Default.aspx" in page.url:
                menu_btn = page.locator('a:has-text("Print/Verify")').first
                await menu_btn.hover()
                await asyncio.sleep(0.3)
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=2500):
                    await page.locator('a:has-text("Verify Udyam Registration")').first.click()

            # Delete the navbar/header to declutter and speed up rendering
            try:
                await page.evaluate("document.querySelectorAll('header, #header, .navbar, #navmenu, .navmenu').forEach(el => el.remove());")
            except Exception:
                pass

            udyam_input = page.locator('#ctl00_ContentPlaceHolder1_txtUdyamNo')
            await udyam_input.fill(udyam_number, timeout=2500)

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
                await page.wait_for_function("document.getElementById('ctl00_ContentPlaceHolder1_imgCaptcha').complete", timeout=2000)
                image_bytes = await captcha_img.screenshot()

            raw_text = await solve_captcha(image_bytes)
            captcha_text = raw_text.upper().strip()

            await page.locator('#ctl00_ContentPlaceHolder1_txtCaptcha').fill(captcha_text)
            
            # Click verify and wait for domcontentloaded
            try:
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=2500):
                    await page.locator('#ctl00_ContentPlaceHolder1_btnVerify').click(force=True)
            except PlaywrightTimeoutError:
                pass

            enterprise_name_locator = page.locator('#ctl00_ContentPlaceHolder1_lblEnterpriseName')
            error_captcha = page.locator('#ctl00_ContentPlaceHolder1_lblCaptchaMsg')

            if await enterprise_name_locator.is_visible():
                # Delete the navbar/header on the Print Application page as well
                try:
                    await page.evaluate("document.querySelectorAll('header, #header, .navbar, #navmenu, .navmenu').forEach(el => el.remove());")
                except Exception:
                    pass
                
                html_content = await page.content()
                ent_name = (await enterprise_name_locator.inner_text()).strip()
                
                doi_locator = page.locator('#ctl00_ContentPlaceHolder1_lbldateofincorporation')
                doi_text = ""
                if await doi_locator.is_visible():
                    doi_text = (await doi_locator.inner_text()).strip()
                
                dor_locator = page.locator('#ctl00_ContentPlaceHolder1_lblACKNOWLEDGEMENT')
                dor_text = ""
                if await dor_locator.is_visible():
                    dor_text = (await dor_locator.inner_text()).strip()
                
                try:
                    async with page.expect_navigation(wait_until="domcontentloaded", timeout=2500):
                        await page.locator('#ctl00_ContentPlaceHolder1_btnBack').click()
                except Exception:
                    pass
                    
                return "Success", ent_name, html_content, doi_text, dor_text
            else:
                error_captcha = page.locator('#ctl00_ContentPlaceHolder1_lblCaptchaMsg')
                if await error_captcha.is_visible() and (await error_captcha.inner_text()).strip():
                    continue
                else:
                    return "Failed (Not Found)", "", "", "", ""

        except Exception as e:
            if attempt == MAX_RETRIES:
                # await save_failure_screenshot(page, udyam_number, f"Exception_{type(e).__name__}")
                return f"Failed (Exception: {type(e).__name__})", "", "", "", ""
            await asyncio.sleep(1.0)

    # await save_failure_screenshot(page, udyam_number, "CaptchaExhausted")
    return "Failed (Captcha)", "", "", "", ""

def flush_batches(results_batch, failed_batch, html_batch):
    for udyam_num, html in html_batch.items():
        match = re.match(r"^(UDYAM-[A-Z]{2}-\d{2})-", udyam_num)
        prefix = match.group(1).replace("UDYAM-", "") if match else "UNKNOWN"
        folder_path = os.path.join(RESULTS_DIR, prefix)
        os.makedirs(folder_path, exist_ok=True)
        with open(os.path.join(folder_path, f"{udyam_num}.html"), "w", encoding="utf-8") as f:
            f.write(html)
            
    res_grouped = defaultdict(list)
    for row in results_batch:
        match = re.match(r"^(UDYAM-[A-Z]{2}-\d{2})-", row[0])
        prefix = match.group(1).replace("UDYAM-", "") if match else "UNKNOWN"
        res_grouped[prefix].append(row)
        
    for prefix, rows in res_grouped.items():
        folder_path = os.path.join(RESULTS_DIR, prefix)
        os.makedirs(folder_path, exist_ok=True)
        csv_path = os.path.join(folder_path, f"results_{prefix}.csv")
        write_header = not os.path.exists(csv_path) or os.stat(csv_path).st_size == 0
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["Number", "Status", "EnterpriseName", "DateOfRegistration", "TimeTaken(s)"])
            w.writerows(rows)
            
    fail_grouped = defaultdict(list)
    for row in failed_batch:
        match = re.match(r"^(UDYAM-[A-Z]{2}-\d{2})-", row[0])
        prefix = match.group(1).replace("UDYAM-", "") if match else "UNKNOWN"
        fail_grouped[prefix].append(row)

    for prefix, rows in fail_grouped.items():
        folder_path = os.path.join(FAILED_DIR, prefix)
        os.makedirs(folder_path, exist_ok=True)
        csv_path = os.path.join(folder_path, f"failed_{prefix}.csv")
        write_header = not os.path.exists(csv_path) or os.stat(csv_path).st_size == 0
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["Number", "Status", "TimeTaken(s)"])
            w.writerows(rows)

async def worker(
    worker_id: int,
    queue: asyncio.Queue,
    results_batch: list,
    failed_batch: list,
    html_batch: dict,
    batch_lock: asyncio.Lock,
    state_status: dict,
    consecutive_failures: dict,
    BATCH_SIZE: int,
    progress_info: dict = None
):
    async with AsyncStealthySession(headless=True) as session:
        page = await session.context.new_page()
        await page.route("**/*", abort_unnecessary_resources)
        records_processed_by_page = 0

        while True:
            if records_processed_by_page >= 50:
                try:
                    await page.close()
                except Exception:
                    pass
                page = await session.context.new_page()
                await page.route("**/*", abort_unnecessary_resources)
                records_processed_by_page = 0

            udyam_number = await queue.get()
            if udyam_number is None:
                queue.task_done()
                break

            match = re.match(r"^(UDYAM-[A-Z]{2}-\d{2})-", udyam_number)
            prefix = match.group(1) if match else "UNKNOWN"

            if state_status.get(prefix) == "skip":
                queue.task_done()
                continue

            start_time = time.perf_counter()
            status, enterprise_name, html_content, _, dor_text = await process_udyam_number(page, udyam_number)
            elapsed_time = round(time.perf_counter() - start_time, 2)

            async with batch_lock:
                if progress_info is not None:
                    progress_info["prefix"] = prefix
                    progress_info["last_number"] = udyam_number

                if status.startswith("Success"):
                    if progress_info is not None:
                        progress_info["success_count"] = progress_info.get("success_count", 0) + 1
                        if dor_text:
                            progress_info["latest_dor"] = dor_text

                    logging.info(f"[Worker-{worker_id}] [{udyam_number}] OK ({elapsed_time}s) -> {enterprise_name} | DOR: {dor_text}")
                    results_batch.append([udyam_number, status, enterprise_name, dor_text, elapsed_time])
                    html_batch[udyam_number] = html_content
                    consecutive_failures[prefix] = 0

                    dor_date = parse_dor(dor_text)
                    if dor_date:
                        yesterday = date.today() - timedelta(days=1)
                        if dor_date >= yesterday:
                            if state_status.get(prefix) != "skip":
                                logging.info(
                                    f"*** Stopping counter for {prefix} as DOR ({dor_text}) "
                                    f"reached yesterday's date ({yesterday.strftime('%d/%m/%Y')}) ***"
                                )
                                state_status[prefix] = "skip"
                else:
                    if progress_info is not None:
                        progress_info["fail_count"] = progress_info.get("fail_count", 0) + 1

                    logging.info(f"[Worker-{worker_id}] [{udyam_number}] FAIL ({status}) ({elapsed_time}s)")
                    failed_batch.append([udyam_number, status, elapsed_time])
                    consecutive_failures[prefix] = consecutive_failures.get(prefix, 0) + 1

                    if consecutive_failures[prefix] >= 100:
                        if state_status.get(prefix) != "skip":
                            logging.info(f"*** Skipping remaining for {prefix} due to 100 consecutive failures ***")
                            state_status[prefix] = "skip"

                if len(results_batch) + len(failed_batch) >= BATCH_SIZE:
                    flush_batches(results_batch, failed_batch, html_batch)
                    results_batch.clear()
                    failed_batch.clear()
                    html_batch.clear()

            records_processed_by_page += 1
            queue.task_done()

async def main(
    state_code: str,
    start_code: int,
    end_code: int,
    limit: int,
    concurrency: int,
    telegram_token: str = None,
    telegram_chat_id: str = None,
    telegram_interval: int = 1800,
    ignore_local_lookup: bool = False
):
    os.makedirs(FAILED_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    if ignore_local_lookup:
        logging.info("Web-only mode enabled: ignoring local lookup (will not skip already processed numbers).")
        processed_numbers = set()
    else:
        logging.info(f"Loading already processed numbers for {state_code}-{start_code:02d} to {state_code}-{end_code:02d}...")
        processed_numbers = get_already_processed_numbers(state_code, start_code, end_code)
        logging.info(f"Already done: {len(processed_numbers)}")

    state_status = {}
    consecutive_failures = {}

    results_batch = []
    failed_batch = []
    html_batch = {}
    BATCH_SIZE = 50
    batch_lock = asyncio.Lock()
    queue = asyncio.Queue(maxsize=10000)

    progress_info = {
        "state": state_code,
        "prefix": "N/A",
        "last_number": "N/A",
        "latest_dor": "N/A",
        "success_count": 0,
        "fail_count": 0,
    }

    reporter_task = None
    if telegram_token and telegram_chat_id:
        logging.info(f"Telegram reporting enabled: notifying {telegram_chat_id} every {telegram_interval // 60} mins.")
        reporter_task = asyncio.create_task(
            telegram_reporter(telegram_token, telegram_chat_id, progress_info, interval_seconds=telegram_interval)
        )

    # Start workers
    tasks = []
    for i in range(concurrency):
        tasks.append(
            asyncio.create_task(
                worker(
                    i + 1,
                    queue,
                    results_batch,
                    failed_batch,
                    html_batch,
                    batch_lock,
                    state_status,
                    consecutive_failures,
                    BATCH_SIZE,
                    progress_info
                )
            )
        )

    # Producer
    for state_idx in range(start_code, end_code + 1):
        prefix = f"UDYAM-{state_code}-{state_idx:02d}"
        for num in range(1, limit + 1):
            if state_status.get(prefix) == "skip":
                break
                
            udyam_number = f"{prefix}-{num:07d}"
            if udyam_number in processed_numbers:
                continue

            await queue.put(udyam_number)

    # Signal workers to finish
    for _ in range(concurrency):
        await queue.put(None)

    await asyncio.gather(*tasks)

    # Stop Telegram reporter
    if reporter_task:
        reporter_task.cancel()
        try:
            await reporter_task
        except asyncio.CancelledError:
            pass

    # Final flush
    if results_batch or failed_batch:
        flush_batches(results_batch, failed_batch, html_batch)

    logging.info("All tasks completed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Udyam Scraper v3 (Lightweight Concurrency)")
    parser.add_argument("--state", type=str, default="TN", help="State code to run for (e.g., TN, MH, KA)")
    parser.add_argument("--code", type=int, default=None, help="Specific state code to run (e.g., 2 for TN-02). Overrides start/end if provided.")
    parser.add_argument("--start", type=int, default=0, help="Start state code index (e.g., 0 for TN-00)")
    parser.add_argument("--end", type=int, default=99, help="End state code index (inclusive, e.g., 99 for TN-99)")
    parser.add_argument("--limit", type=int, default=100, help="Number of records to process per state code")
    parser.add_argument("--concurrency", type=int, default=2, help="Number of concurrent workers")
    parser.add_argument("--telegram-token", type=str, default=os.getenv("TELEGRAM_BOT_TOKEN"), help="Telegram Bot API Token")
    parser.add_argument("--telegram-chat-id", type=str, default=os.getenv("TELEGRAM_CHAT_ID"), help="Telegram Chat / Channel ID")
    parser.add_argument("--telegram-interval", type=int, default=1800, help="Telegram update interval in seconds (default: 1800 = 30m)")
    parser.add_argument("--ignore-local-lookup", "--web-only", action="store_true", help="Extract fresh from web only, ignoring local results/failed lookup")
    args = parser.parse_args()
    
    if args.code is not None:
        start_code = args.code
        end_code = args.code
        log_filename = f"log_scraper_v3_{args.state}_{start_code:02d}.log"
    else:
        start_code = args.start
        end_code = args.end
        log_filename = f"log_scraper_v3_{args.state}_{start_code:02d}_to_{end_code:02d}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_filename, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )

    asyncio.run(
        main(
            args.state,
            start_code,
            end_code,
            args.limit,
            args.concurrency,
            telegram_token=args.telegram_token,
            telegram_chat_id=args.telegram_chat_id,
            telegram_interval=args.telegram_interval,
            ignore_local_lookup=args.ignore_local_lookup
        )
    )
