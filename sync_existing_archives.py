"""
One-Time / On-Demand Sync Script for Existing Archives & Districts.
Extracts Last Record, Last Recorded Date, Total Records Extracted, and Total Failed Records
directly from .7z archives (via 7z stream reading without full extraction) and directories.
"""

import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
import httpx

# Load environment variables from .env if present
env_path = Path(".env")
if env_path.is_file():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))



def get_7z_binary() -> str:
    """Finds 7z executable on PATH or standard install locations."""
    for bin_name in ("7z", "7za", "7zr"):
        found = shutil.which(bin_name)
        if found:
            return found

    common_paths = [
        Path(r"C:\Program Files\7-Zip\7z.exe"),
        Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
    ]
    for p in common_paths:
        if p.is_file():
            return str(p)

    raise FileNotFoundError("7-Zip (7z.exe) not found. Please ensure 7-Zip is installed.")


def extract_csv_from_7z(archive_path: Path, csv_pattern: str, seven_zip_bin: str) -> str | None:
    """Extracts a CSV matching csv_pattern from a .7z archive directly to stdout (memory)."""
    # Use -r to extract directly with wildcard without listing first
    cmd_extract = [seven_zip_bin, "e", str(archive_path), "-r", csv_pattern, "-so"]
    try:
        proc_extract = subprocess.run(
            cmd_extract,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace"
        )
        return proc_extract.stdout
    except subprocess.CalledProcessError:
        return None


def extract_dor_from_html_in_7z(archive_path: Path, last_record: str, seven_zip_bin: str) -> str:
    """Extracts Date of Registration from the record's HTML file inside .7z when missing from CSV."""
    if not last_record:
        return ""
    cmd = [seven_zip_bin, "e", str(archive_path), "-r", f"{last_record}.html", "-so"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=True)
        html = proc.stdout
        m = re.search(r'lblACKNOWLEDGEMENT">([^<]+)<', html)
        if not m:
            m = re.search(r'Date of Udyam Registration.*?(\d{1,2}/\d{1,2}/\d{4})', html, re.DOTALL)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return ""


def parse_results_csv_content(csv_content: str) -> dict:
    """Parses results CSV text to determine highest record number, DOR, and total count."""
    reader = csv.reader(io.StringIO(csv_content))
    header = next(reader, None)

    dor_col_idx = -1
    if header:
        for idx, col in enumerate(header):
            cleaned = col.strip().lower()
            if "date" in cleaned or "dor" in cleaned:
                dor_col_idx = idx
                break

    total_extracted = 0
    max_num_val = -1
    last_record_id = ""
    last_dor = ""

    for row in reader:
        if not row or not row[0].strip():
            continue
        total_extracted += 1
        record_id = row[0].strip()

        dor = ""
        if dor_col_idx != -1 and len(row) > dor_col_idx:
            val = row[dor_col_idx].strip()
            # Verify if val looks like a date (e.g. DD/MM/YYYY or contains digits & / or -)
            if re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", val):
                dor = val
        elif len(row) > 3:
            # Fallback check on column 3 if it looks like a date
            val = row[3].strip()
            if re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", val):
                dor = val

        match = re.search(r"-(\d+)$", record_id)
        if match:
            num_val = int(match.group(1))
            if num_val > max_num_val:
                max_num_val = num_val
                last_record_id = record_id
                if dor:
                    last_dor = dor
        else:
            last_record_id = record_id
            if dor:
                last_dor = dor

    return {
        "total_extracted": total_extracted,
        "last_record": last_record_id,
        "last_recorded_date": last_dor,
    }


def parse_failed_csv_content(csv_content: str) -> int:
    """Counts failed records from CSV text."""
    reader = csv.reader(io.StringIO(csv_content))
    next(reader, None)
    count = 0
    for row in reader:
        if row and row[0].strip():
            count += 1
    return count


def scan_district_data(results_dir: Path, failed_dir: Path, seven_zip_bin: str) -> dict[str, dict]:
    """Scans all .7z archives and folders in results_dir and failed_dir."""
    district_data = {}

    if results_dir.exists():
        archive_files = sorted(results_dir.glob("*.7z"))
        print(f"Found {len(archive_files)} .7z archive(s) in '{results_dir}'...")

        for archive in archive_files:
            prefix_match = re.match(r"^([A-Z]{2}-\d{2})", archive.name)
            prefix = prefix_match.group(1) if prefix_match else archive.stem
            print(f"  [7z] Reading {archive.name} ({prefix})...")

            res_csv_text = extract_csv_from_7z(archive, f"results_{prefix}.csv", seven_zip_bin)
            if not res_csv_text:
                res_csv_text = extract_csv_from_7z(archive, "results_*.csv", seven_zip_bin)

            if res_csv_text:
                stats = parse_results_csv_content(res_csv_text)
            else:
                stats = {"total_extracted": 0, "last_record": "", "last_recorded_date": ""}

            if not stats.get("last_recorded_date") and stats.get("last_record"):
                html_dor = extract_dor_from_html_in_7z(archive, stats["last_record"], seven_zip_bin)
                if html_dor:
                    stats["last_recorded_date"] = html_dor
                    print(f"    -> Extracted DOR from HTML: {html_dor}")

            failed_csv_text = extract_csv_from_7z(archive, f"failed_{prefix}.csv", seven_zip_bin)
            if not failed_csv_text:
                failed_csv_text = extract_csv_from_7z(archive, "failed_*.csv", seven_zip_bin)

            total_failed = parse_failed_csv_content(failed_csv_text) if failed_csv_text else 0

            stats["total_failed"] = total_failed
            stats["is_archive"] = True
            stats["path"] = str(archive)
            district_data[prefix] = stats

    if results_dir.exists():
        for folder in sorted(results_dir.iterdir()):
            if folder.is_dir():
                prefix = folder.name
                res_csv = folder / f"results_{prefix}.csv"
                if res_csv.is_file():
                    print(f"  [Folder] Reading {folder.name}...")
                    with open(res_csv, "r", encoding="utf-8", errors="replace") as f:
                        stats = parse_results_csv_content(f.read())
                    stats["is_archive"] = False
                    stats["path"] = str(folder)
                    stats["total_failed"] = 0
                    district_data[prefix] = stats

    if failed_dir.exists():
        for item in failed_dir.iterdir():
            prefix = item.name.replace("failed_", "").replace(".csv", "").replace(".7z", "")
            failed_csv = None
            if item.is_dir():
                csv_candidate = item / f"failed_{prefix}.csv"
                if csv_candidate.is_file():
                    failed_csv = csv_candidate
            elif item.is_file() and item.suffix == ".csv":
                failed_csv = item

            if failed_csv and prefix in district_data:
                with open(failed_csv, "r", encoding="utf-8", errors="replace") as f:
                    district_data[prefix]["total_failed"] = parse_failed_csv_content(f.read())

    return district_data


def sync_to_google_sheet(web_app_url: str, district_data: dict[str, dict], chunk_size: int = 25):
    """Sends aggregated district status to Google Apps Script Web App in safe chunks."""
    if not web_app_url:
        print("[!] No Google Apps Script Web App URL provided. Skipping remote sync.")
        return False

    items = list(district_data.items())
    total_districts = len(items)
    print(f"\nSending status for {total_districts} districts to Google Sheet in batches of {chunk_size}...")

    total_updated = 0
    for i in range(0, total_districts, chunk_size):
        chunk = dict(items[i:i + chunk_size])
        batch_num = (i // chunk_size) + 1
        total_batches = (total_districts + chunk_size - 1) // chunk_size
        print(f"  Pushing batch {batch_num}/{total_batches} ({len(chunk)} districts)...")

        payload = {
            "action": "bulk_sync_status",
            "districts": chunk,
        }

        try:
            resp = httpx.post(web_app_url, json=payload, timeout=120.0, follow_redirects=True)
            if resp.status_code == 200:
                res_json = resp.json()
                count = res_json.get("updated_count", 0)
                total_updated += count
                print(f"    -> Batch {batch_num} success: {count} rows updated.")
            else:
                print(f"    -> [ERROR] Batch {batch_num} failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"    -> [ERROR] Connection error on batch {batch_num}: {e}")

    print(f"[SUCCESS] Google Sheet sync complete: {total_updated} total rows updated.")
    return total_updated > 0


def main():
    parser = argparse.ArgumentParser(description="Sync existing .7z archives and folders with Google Sheets.")
    parser.add_argument("--results-dir", type=str, default="results", help="Directory containing .7z files and results folders")
    parser.add_argument("--failed-dir", type=str, default="failed", help="Directory containing failure logs")
    parser.add_argument("--web-app-url", type=str, default=os.getenv("GOOGLE_APPS_SCRIPT_URL"), help="Google Apps Script Web App URL")
    parser.add_argument("--export-csv", type=str, default="sync_report.csv", help="Output path for local CSV summary")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    failed_dir = Path(args.failed_dir)

    try:
        seven_zip_bin = get_7z_binary()
        print(f"Using 7-Zip binary: {seven_zip_bin}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    district_data = scan_district_data(results_dir, failed_dir, seven_zip_bin)
    print(f"\nScanned {len(district_data)} districts successfully.")

    report_path = Path(args.export_csv)
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["District Code", "Last Record", "Last Recorded Date", "Total Extracted", "Total Failed", "Is Archive", "Source Path"])
        for prefix, d in sorted(district_data.items()):
            writer.writerow([
                prefix,
                d.get("last_record", ""),
                d.get("last_recorded_date", ""),
                d.get("total_extracted", 0),
                d.get("total_failed", 0),
                d.get("is_archive", False),
                d.get("path", "")
            ])
    print(f"[SUCCESS] Local summary written to: {report_path.resolve()}")

    if args.web_app_url:
        sync_to_google_sheet(args.web_app_url, district_data)
    else:
        print("\nNote: To push directly to your Google Sheet, supply --web-app-url or set GOOGLE_APPS_SCRIPT_URL in .env")


if __name__ == "__main__":
    main()
