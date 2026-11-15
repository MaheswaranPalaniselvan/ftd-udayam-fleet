"""
Udyam Custom List Extractor (CLI Mode)
Two-Stage Extraction Pipeline:
  Stage 1: Web Scraping First (Playwright Stealth + Fast OCR) -> Saves HTMLs to disk
  Stage 2: HTML Parsing & CSV Generation Second (BeautifulSoup) -> Extracts 28+ fields to CSV

Usage Examples:
  # Scrape from a file with Udyam numbers:
  uv run python extract_list.py --input numbers.txt --output results.csv

  # Scrape directly specified numbers:
  uv run python extract_list.py --numbers UDYAM-TN-02-0000001 UDYAM-TN-02-0000002

  # Increase concurrency (e.g. 4 browser workers):
  uv run python extract_list.py -i numbers.txt -o results.csv -c 4

  # Parse previously downloaded HTML files only without hitting the web:
  uv run python extract_list.py --parse-only --html-dir downloaded_html --output results.csv
"""

import argparse
import asyncio
import csv
import logging
import os
import re
import sys
import time
from pathlib import Path

# Force UTF-8 on Windows console if supported
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from client.core.parser import parse_udyam_html
from client.core.scraper import process_udyam_number, abort_unnecessary_resources
from client.core.district_manager import (
    find_district_last_number,
    generate_district_udyam_numbers,
    get_failed_udyam_numbers_from_file,
    save_or_update_records_file,
    normalize_district_code
)
from scrapling.fetchers import AsyncStealthySession

CSV_FIELDS = [
    "Udyam Number", "Enterprise Name", "Organisation Type", "Major Activity",
    "Gender", "Social Category", "Date of Incorporation", "Date of Commencement",
    "Date of Registration", "Enterprise Type", "Classification Date", "Unit Names",
    "Flat / Door / Block", "Premises / Building", "Village / Town", "Block",
    "Road / Street", "City", "State", "District", "Pin Code",
    "Mobile", "Email", "DIC", "MSME-DFO",
    "Primary NIC Code", "Primary NIC Activity", "All NIC Details", "Status"
]


def load_numbers_from_file(filepath: Path) -> list[str]:
    """Reads Udyam numbers from a text or CSV file."""
    if not filepath.exists():
        raise FileNotFoundError(f"Input file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    tokens = re.split(r"[\s,;]+", content)
    seen = set()
    valid = []
    for t in tokens:
        cleaned = t.strip().upper()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            valid.append(cleaned)
    return valid


async def run_stage1_web_scraping(
    numbers: list[str],
    html_dir: Path,
    concurrency: int = 2,
    save_html: bool = True
) -> list[dict]:
    """
    Stage 1: Web Extraction First.
    Checks downloaded_html first: if already downloaded, skips web scraping.
    Otherwise queries portal via high-speed stealth workers (1-2s per record).
    """
    total = len(numbers)
    print(f"\n========================================================")
    print(f"[STAGE 1] WEB SCRAPING FIRST ({total} records, {concurrency} workers)")
    print(f"HTML Output Directory: {html_dir.resolve()}")
    print(f"========================================================")

    if save_html:
        html_dir.mkdir(parents=True, exist_ok=True)

    results = []
    to_scrape = []

    # 1. Check if HTML is already downloaded locally
    for num in numbers:
        html_path = html_dir / f"{num}.html"
        if html_path.exists() and html_path.stat().st_size > 100:
            results.append({
                "udyam_number": num,
                "status": "Success",
                "enterprise_name": "",
                "html_content": None,
                "html_path": html_path
            })
            print(f"[Cached] Already downloaded: {num}")
        else:
            to_scrape.append(num)

    cached_count = len(results)
    if cached_count > 0:
        print(f"-> Found {cached_count} / {total} records already downloaded in {html_dir.name} (skipping web query for them).")

    if not to_scrape:
        print(f"All {total} records are already downloaded locally. Proceeding immediately to Stage 2.")
        return results

    print(f"-> Fetching remaining {len(to_scrape)} records live from portal ({concurrency} workers)...")

    queue = asyncio.Queue()
    for num in to_scrape:
        await queue.put(num)

    res_lock = asyncio.Lock()
    processed_count = cached_count

    HOME_URL = "https://www.udyamregistration.gov.in/Default.aspx"
    VERIFY_URL = "https://www.udyamregistration.gov.in/Udyam_Verify.aspx"

    async def worker_task(worker_id: int):
        nonlocal processed_count
        async with AsyncStealthySession(headless=True) as session:
            page = await session.context.new_page()
            await page.route("**/*", abort_unnecessary_resources)

            # Pre-navigate to Udyam_Verify.aspx once per worker
            try:
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=4000)
                await page.goto(VERIFY_URL, wait_until="domcontentloaded", timeout=4000)
                if "Default.aspx" in page.url:
                    menu_btn = page.locator('a:has-text("Print/Verify")').first
                    await menu_btn.hover()
                    await asyncio.sleep(0.2)
                    async with page.expect_navigation(wait_until="domcontentloaded", timeout=4000):
                        await page.locator('a:has-text("Verify Udyam Registration")').first.click()
                await page.evaluate("document.querySelectorAll('header, #header, .navbar, #navmenu, .navmenu').forEach(el => el.remove());")
            except Exception as e:
                logging.warning(f"[W-{worker_id}] Initial worker navigation warning: {e}")

            page_uses = 0

            while not queue.empty():
                try:
                    num = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                # Recycle page every 60 records to clear memory
                if page_uses >= 60:
                    try:
                        await page.close()
                    except Exception:
                        pass
                    page = await session.context.new_page()
                    await page.route("**/*", abort_unnecessary_resources)
                    try:
                        await page.goto(VERIFY_URL, wait_until="domcontentloaded", timeout=4000)
                        await page.evaluate("document.querySelectorAll('header, #header, .navbar, #navmenu, .navmenu').forEach(el => el.remove());")
                    except Exception:
                        pass
                    page_uses = 0

                t0 = time.perf_counter()
                status, ent_name, html_content, _, _ = await process_udyam_number(page, num)
                elapsed = round(time.perf_counter() - t0, 2)
                page_uses += 1

                html_file_path = None
                if status.startswith("Success") and html_content:
                    if save_html:
                        html_file_path = html_dir / f"{num}.html"
                        try:
                            with open(html_file_path, "w", encoding="utf-8") as f:
                                f.write(html_content)
                        except Exception as e:
                            logging.error(f"Failed to save HTML for {num}: {e}")

                async with res_lock:
                    processed_count += 1
                    results.append({
                        "udyam_number": num,
                        "status": status,
                        "enterprise_name": ent_name,
                        "html_content": html_content if html_content else None,
                        "html_path": html_file_path
                    })

                    pct = (processed_count / total) * 100
                    if status.startswith("Success"):
                        print(f"[{processed_count}/{total} - {pct:.1f}%] [W-{worker_id}] OK ({elapsed}s): {num} -> {ent_name or 'Found'}")
                    else:
                        print(f"[{processed_count}/{total} - {pct:.1f}%] [W-{worker_id}] {status} ({elapsed}s): {num}")

                queue.task_done()

    workers = [asyncio.create_task(worker_task(i + 1)) for i in range(concurrency)]
    await asyncio.gather(*workers)
    return results


def export_records_to_excel(records: list[dict], out_path: Path):
    """
    Exports structured records to a beautifully styled Excel workbook (.xlsx):
    - Corporate navy styled header (#1B365D)
    - Auto-filter enabled across all columns
    - Top row frozen for effortless scrolling
    - Auto-fitted column widths
    - Thin borders and alternating row styling
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Udyam Registrations"
    ws.views.sheetView[0].showGridLines = True

    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    data_font = Font(name="Segoe UI", size=10)
    data_align_left = Alignment(horizontal="left", vertical="center")
    data_align_center = Alignment(horizontal="center", vertical="center")

    thin_border = Border(
        left=Side(style="thin", color="D0D7DE"),
        right=Side(style="thin", color="D0D7DE"),
        top=Side(style="thin", color="D0D7DE"),
        bottom=Side(style="thin", color="D0D7DE")
    )

    alt_fill = PatternFill(start_color="F6F8FA", end_color="F6F8FA", fill_type="solid")

    ws.row_dimensions[1].height = 28
    for col_idx, col_name in enumerate(CSV_FIELDS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    center_cols = {
        "Udyam Number", "Gender", "Social Category", "Date of Incorporation",
        "Date of Commencement", "Date of Registration", "Enterprise Type",
        "Classification Date", "Pin Code", "Mobile", "Status"
    }

    for row_idx, rec in enumerate(records, start=2):
        ws.row_dimensions[row_idx].height = 20
        use_alt = (row_idx % 2 == 1)

        for col_idx, col_name in enumerate(CSV_FIELDS, start=1):
            val = rec.get(col_name, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = data_font
            cell.border = thin_border
            if use_alt:
                cell.fill = alt_fill

            if col_name in center_cols:
                cell.alignment = data_align_center
            else:
                cell.alignment = data_align_left

    for col_idx, col_name in enumerate(CSV_FIELDS, start=1):
        col_letter = get_column_letter(col_idx)
        max_len = len(str(col_name))
        for row in range(2, len(records) + 2):
            v = ws.cell(row=row, column=col_idx).value
            if v:
                line_len = max(len(l) for l in str(v).split("\n"))
                max_len = max(max_len, line_len)

        col_width = max(13, min(max_len + 3, 50))
        ws.column_dimensions[col_letter].width = col_width

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def run_stage2_export(results: list[dict], out_path: Path, html_dir: Path, update_in_place: bool = False):
    """
    Stage 2: HTML Extraction & File Export Second.
    Parses downloaded HTML documents and writes all 28+ fields to XLSX or CSV.
    If update_in_place is True, existing rows matching Udyam Number are updated in-place.
    """
    total = len(results)
    is_xlsx = out_path.suffix.lower() == ".xlsx"
    format_name = "XLSX" if is_xlsx else "CSV"

    print(f"\n========================================================")
    print(f"[STAGE 2] PARSING HTML & GENERATING {format_name} ({total} records)")
    print(f"Output Destination: {out_path.resolve()}")
    if update_in_place:
        print(f"Merge Mode: In-Place Update Enabled (preserving existing rows)")
    print(f"========================================================")

    parsed_records = []

    for idx, item in enumerate(results, start=1):
        num = item["udyam_number"]
        status = item["status"]
        html_content = item.get("html_content")

        # Load from disk if not in memory
        if not html_content and item.get("html_path") and Path(item["html_path"]).exists():
            try:
                with open(item["html_path"], "r", encoding="utf-8", errors="replace") as hf:
                    html_content = hf.read()
            except Exception:
                pass
        elif not html_content:
            potential_path = html_dir / f"{num}.html"
            if potential_path.exists():
                try:
                    with open(potential_path, "r", encoding="utf-8", errors="replace") as hf:
                        html_content = hf.read()
                except Exception:
                    pass

        pct = (idx / total) * 100
        if status.startswith("Success") and html_content:
            rec = parse_udyam_html(html_content)
            rec["Udyam Number"] = num
            rec["Status"] = "Success"
            parsed_records.append(rec)

            name = rec.get("Enterprise Name", item.get("enterprise_name") or "N/A")
            ent_type = rec.get("Enterprise Type", "N/A")
            city = rec.get("City", "N/A")
            print(f"[{idx}/{total} - {pct:.1f}%] Extracted: {num} -> {name} | {ent_type} | {city}")
        else:
            fail_rec = {f: "" for f in CSV_FIELDS}
            fail_rec["Udyam Number"] = num
            fail_rec["Enterprise Name"] = status
            fail_rec["Status"] = status
            parsed_records.append(fail_rec)
            print(f"[{idx}/{total} - {pct:.1f}%] Status Recorded: {num} -> {status}")

    if update_in_place and out_path.exists():
        updated, appended = save_or_update_records_file(out_path, parsed_records, update_in_place=True)
        print(f"\n[MERGED] Updated {updated} existing records in-place, appended {appended} new records.")
    elif is_xlsx:
        export_records_to_excel(parsed_records, out_path)
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(parsed_records)


def run_parse_only(html_dir: Path, out_path: Path, input_file: Path = None):
    """Parses existing .html files in html_dir directly to XLSX without web scraping."""
    results = []
    if input_file and input_file.exists():
        numbers = load_numbers_from_file(input_file)
        print(f"Loading {len(numbers)} numbers from {input_file.name} to preserve input order...")
        for num in numbers:
            hf = html_dir / f"{num}.html"
            if hf.exists() and hf.stat().st_size > 100:
                results.append({
                    "udyam_number": num,
                    "status": "Success",
                    "html_content": None,
                    "html_path": hf
                })
            else:
                results.append({
                    "udyam_number": num,
                    "status": "Not Found / Failed",
                    "html_content": None,
                    "html_path": None
                })
    else:
        html_files = sorted(list(html_dir.glob("*.html")))
        if not html_files:
            print(f"[ERROR] No .html files found in {html_dir.resolve()}")
            sys.exit(1)
        print(f"Found {len(html_files)} HTML files in {html_dir.resolve()}.")
        for hf in html_files:
            results.append({
                "udyam_number": hf.stem,
                "status": "Success",
                "html_content": None,
                "html_path": hf
            })

    run_stage2_export(results, out_path, html_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Udyam Custom List Extractor (Two-Stage: Web Scraping First -> HTML Extraction to XLSX/CSV Second)"
    )
    parser.add_argument("-i", "--input", type=str, default=None, help="Path to text or CSV file containing Udyam numbers")
    parser.add_argument("-n", "--numbers", nargs="+", default=None, help="List of Udyam numbers passed directly on CLI")
    parser.add_argument("-o", "--output", type=str, default="results.xlsx", help="Output file path (.xlsx or .csv, default: results.xlsx)")
    parser.add_argument("--html-dir", type=str, default="downloaded_html", help="Directory to save/read raw HTML files (default: downloaded_html)")
    parser.add_argument("-c", "--concurrency", type=int, default=2, help="Number of concurrent browser workers (1-4, default: 2)")
    parser.add_argument("--no-save-html", action="store_true", help="Do not save raw HTML files to disk")
    parser.add_argument("--parse-only", action="store_true", help="Skip web scraping and parse existing HTML files from --html-dir directly to XLSX/CSV")
    parser.add_argument("--html", action="store_true", help="Automatically generate an interactive FlawlessTech Data HTML viewer alongside XLSX")

    # New flags
    parser.add_argument("--recheck-failed", "--retry-failed", action="store_true", help="Re-check failed records from existing results file and update in-place")
    parser.add_argument("--district", type=str, default=None, help="District code for incremental load (e.g. TN-02)")
    parser.add_argument("--incremental", action="store_true", help="Auto-detect last Udyam number for --district and run incremental load")
    parser.add_argument("--count", type=int, default=50, help="Number of incremental records to scrape (default: 50)")
    parser.add_argument("--start", type=int, default=None, help="Manual start sequence number for district incremental load")

    args = parser.parse_args()

    out_path = Path(args.output).resolve()
    html_dir = Path(args.html_dir).resolve()
    input_file = Path(args.input).resolve() if args.input else None

    # Mode 1: Parse Only
    if args.parse_only:
        t0 = time.perf_counter()
        run_parse_only(html_dir, out_path, input_file)
        elapsed = round(time.perf_counter() - t0, 1)
        print(f"\n[DONE] Standalone HTML parsing complete in {elapsed}s!")
        print(f"Result File: {out_path}")
        if args.html and out_path.suffix.lower() == ".xlsx" and out_path.exists():
            from xlsx_to_html import convert_xlsx_to_html
            html_out = out_path.with_suffix(".html")
            convert_xlsx_to_html(out_path, html_out)
            print(f"Interactive HTML Report: {html_out}")
        return

    numbers = []
    is_recheck = False
    is_incremental = False

    # Mode 2: Re-check Failed
    if args.recheck_failed:
        target_check_file = out_path if out_path.exists() else input_file
        if not target_check_file or not target_check_file.exists():
            print(f"[ERROR] Cannot re-check failed records: neither output file ({out_path}) nor input file exists.")
            sys.exit(1)

        failed_records = get_failed_udyam_numbers_from_file(target_check_file)
        if not failed_records:
            print(f"[INFO] No failed records found in {target_check_file.name} (all are Success). Nothing to retry.")
            return

        numbers = [item[0] for item in failed_records]
        is_recheck = True
        print(f"[RE-CHECK] Found {len(numbers)} failed records in {target_check_file.name} to re-verify live.")

    # Mode 3: District Incremental Load
    elif args.incremental or args.district:
        if not args.district:
            print("[ERROR] Please specify a district code via --district (e.g. --district TN-02) when using --incremental.")
            sys.exit(1)

        clean_dist = normalize_district_code(args.district)
        if args.start is not None:
            start_num = max(1, args.start)
            print(f"[INCREMENTAL] Using manual start #{start_num} for district {clean_dist}.")
        else:
            info = find_district_last_number(clean_dist)
            start_num = info["next_start"]
            print(f"[INCREMENTAL] Auto-detected last number: {info['last_record']} (#{info['max_number']:,}) from {info['source']}.")
            print(f"[INCREMENTAL] Starting incremental sequence at #{start_num:,}.")

        count = max(1, args.count)
        numbers = generate_district_udyam_numbers(clean_dist, start_num, count)
        is_incremental = True
        print(f"[INCREMENTAL] Generated {len(numbers)} numbers ({numbers[0]} -> {numbers[-1]}).")

    # Mode 4: Normal List from File or Arguments
    elif args.input:
        numbers = load_numbers_from_file(Path(args.input))
    elif args.numbers:
        seen = set()
        for num in args.numbers:
            cleaned = num.strip().upper()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                numbers.append(cleaned)
    else:
        print("[ERROR] Please provide an input file via --input <file>, numbers via --numbers, --recheck-failed, or --incremental.")
        print("Run with --help to see all available options.")
        sys.exit(1)

    if not numbers:
        print("[ERROR] No valid Udyam registration numbers found.")
        sys.exit(1)

    concurrency = max(1, min(4, args.concurrency))
    save_html = not args.no_save_html

    t0 = time.perf_counter()

    # STAGE 1: Web Scraping First (force live fetch if re-checking)
    web_results = asyncio.run(
        run_stage1_web_scraping(numbers, html_dir, concurrency=concurrency, save_html=save_html)
    )

    success_count = sum(1 for r in web_results if r["status"].startswith("Success"))
    failed_count = len(web_results) - success_count
    print(f"\n[STAGE 1 COMPLETE] {success_count} HTMLs downloaded ({failed_count} not found / failed).")

    # STAGE 2: HTML Extraction to XLSX/CSV Second (in-place if recheck or incremental)
    update_in_place = (is_recheck or is_incremental) and out_path.exists()
    run_stage2_export(web_results, out_path, html_dir, update_in_place=update_in_place)

    total_time = round(time.perf_counter() - t0, 1)

    print(f"\n========================================================")
    print(f"=== EXTRACTION PIPELINE COMPLETED SUCCESSFULLY ===")
    print(f"Total Time: {total_time}s")
    print(f"Successful Records: {success_count} / {len(numbers)}")
    print(f"Failed / Not Found: {failed_count} / {len(numbers)}")
    print(f"Final Exported File: {out_path}")
    if save_html:
        print(f"Raw HTML Files: {html_dir}")

    if args.html and out_path.suffix.lower() == ".xlsx" and out_path.exists():
        from xlsx_to_html import convert_xlsx_to_html
        html_out = out_path.with_suffix(".html")
        convert_xlsx_to_html(out_path, html_out)
        print(f"Interactive HTML Report: {html_out}")
    print(f"========================================================\n")


if __name__ == "__main__":
    main()
