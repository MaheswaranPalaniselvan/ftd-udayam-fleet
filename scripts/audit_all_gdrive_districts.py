"""
Comprehensive nationwide ground truth recovery for all 718 districts in Google Drive (Udyam_Archives).
Reads archives using multi-threading to extract exact unique record counts, last records, and dates.
"""

import csv
import io
import os
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import openpyxl

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from client.core.scraper import get_7z_binary

GDRIVE_DIR = Path(r"g:\My Drive\Udyam_Archives")
EXCEL_PATH = Path("public/udayam_latest.xlsx")
OUTPUT_CSV = Path("nationwide_gdrive_truth.csv")
SCRATCH_DIR = Path("scratch")

def clean_int(val) -> int:
    if val is None or val == "":
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    cleaned = str(val).replace(",", "").strip()
    try:
        return int(float(cleaned))
    except ValueError:
        digits = re.sub(r"[^\d]", "", cleaned.split(".")[0])
        return int(digits) if digits else 0

def extract_archive_info(seven_zip: str, archive_path: Path, code: str):
    """Extracts unique record count, last record, and last DOR from an archive."""
    try:
        proc = subprocess.run(
            [seven_zip, "e", str(archive_path), "-r", f"results_{code}.csv", "-so"],
            capture_output=True, text=True, errors="replace"
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            proc = subprocess.run(
                [seven_zip, "e", str(archive_path), "-r", "results_*.csv", "-so"],
                capture_output=True, text=True, errors="replace"
            )

        if proc.returncode != 0 or not proc.stdout.strip():
            return 0, "", ""

        reader = csv.reader(io.StringIO(proc.stdout))
        records = {}
        for row in reader:
            if not row:
                continue
            num = row[0].strip()
            if num.startswith(f"UDYAM-{code}-"):
                dor = row[3].strip() if len(row) > 3 else ""
                records[num] = dor

        if not records:
            return 0, "", ""

        sorted_records = sorted(
            records.items(),
            key=lambda x: int(x[0].split("-")[-1]) if x[0].split("-")[-1].isdigit() else 0
        )
        last_num, last_dor = sorted_records[-1]
        return len(records), last_num, last_dor
    except Exception:
        return 0, "", ""

def process_district(code: str, files: list, sheet_info: dict, seven_zip: str):
    total_size = sum(f.stat().st_size for f in files)
    parts = sorted([f for f in files if ".part" in f.name.lower()])
    is_multipart = len(parts) > 1

    if is_multipart:
        combined_path = SCRATCH_DIR / f"{code}_combined_audit.7z"
        with open(combined_path, "wb") as outfile:
            for p in parts:
                with open(p, "rb") as infile:
                    outfile.write(infile.read())
        count, last_rec, last_dor = extract_archive_info(seven_zip, combined_path, code)
        source_file = f"{code}.part01-{len(parts):02d}.7z"
        try:
            combined_path.unlink()
        except Exception:
            pass
    else:
        # Choose the largest archive
        largest = max(files, key=lambda x: x.stat().st_size)
        count, last_rec, last_dor = extract_archive_info(seven_zip, largest, code)
        source_file = largest.name

    sheet_ext = sheet_info.get("sheet_extracted", 0)
    discrepancy = count - sheet_ext

    return {
        "district_code": code,
        "state": sheet_info.get("state", "Unknown"),
        "district_name": sheet_info.get("name", "Unknown"),
        "total_enterprises": sheet_info.get("total_enterprises", 0),
        "sheet_extracted": sheet_ext,
        "gdrive_verified_extracted": count,
        "discrepancy": discrepancy,
        "last_record": last_rec or sheet_info.get("last_record", ""),
        "last_dor": last_dor or sheet_info.get("last_date", ""),
        "gdrive_size_mb": round(total_size / (1024 * 1024), 2),
        "archive_source": source_file,
        "is_underreported": discrepancy > 0
    }

def main():
    SCRATCH_DIR.mkdir(exist_ok=True)
    seven_zip = get_7z_binary()
    if not seven_zip:
        print("Error: 7z binary not found")
        sys.exit(1)

    print("=" * 70)
    print("🌍 NATIONWIDE GDRIVE AUDIT (ALL 718 DISTRICTS)")
    print("=" * 70)

    # 1. Load Google Sheet data
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    ws = wb.active
    sheet_data = {}
    for r in range(2, ws.max_row + 1):
        code = ws.cell(row=r, column=2).value
        if code and re.match(r"^[A-Z]{2}-\d{2}$", str(code)):
            code = str(code).strip().upper()
            sheet_data[code] = {
                "row": r,
                "state": ws.cell(row=r, column=3).value,
                "name": ws.cell(row=r, column=4).value,
                "total_enterprises": clean_int(ws.cell(row=r, column=8).value),
                "last_record": ws.cell(row=r, column=10).value or "",
                "last_date": str(ws.cell(row=r, column=11).value or ""),
                "sheet_extracted": clean_int(ws.cell(row=r, column=12).value),
                "sheet_failed": clean_int(ws.cell(row=r, column=13).value),
                "sheet_status": ws.cell(row=r, column=14).value or "Pending"
            }

    # 2. Group all files in GDrive
    all_7z = list(GDRIVE_DIR.glob("*.7z"))
    dist_files = defaultdict(list)
    for f in all_7z:
        m = re.match(r"^([A-Z]{2}-\d{2})", f.name)
        if m:
            dist_files[m.group(1).upper()].append(f)

    print(f"Found {len(all_7z)} archives across {len(dist_files)} districts. Scanning with 8 threads...")

    results = []
    # Separate multipart (run sequentially to avoid high disk I/O) from single-file
    multipart_districts = {c: f for c, f in dist_files.items() if len([x for x in f if ".part" in x.name.lower()]) > 1}
    single_districts = {c: f for c, f in dist_files.items() if c not in multipart_districts}

    # 3. Process multiparts first
    for code, files in sorted(multipart_districts.items()):
        sheet_info = sheet_data.get(code, {})
        res = process_district(code, files, sheet_info, seven_zip)
        results.append(res)
        print(f"  [Multipart] {code} ({res['district_name']}): Found {res['gdrive_verified_extracted']:,} vs Sheet {res['sheet_extracted']:,}")

    # 4. Process single archives in parallel
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(process_district, code, files, sheet_data.get(code, {}), seven_zip): code
            for code, files in single_districts.items()
        }
        for future in as_completed(futures):
            res = future.result()
            results.append(res)

    results.sort(key=lambda x: x["discrepancy"], reverse=True)

    # 5. Write CSV
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "district_code", "state", "district_name", "total_enterprises",
            "sheet_extracted", "gdrive_verified_extracted", "discrepancy",
            "last_record", "last_dor", "gdrive_size_mb", "archive_source", "is_underreported"
        ])
        writer.writeheader()
        writer.writerows(results)

    underreported = [r for r in results if r["is_underreported"]]
    total_recovered = sum(r["discrepancy"] for r in underreported)

    print("\n" + "=" * 70)
    print(f"🏁 AUDIT COMPLETE! Processed {len(results)} districts.")
    print(f"   Districts where Google Drive has MORE records than Sheet: {len(underreported)}")
    print(f"   🚨 TOTAL UNDERREPORTED RECORDS RECOVERED:                 {total_recovered:,}")
    print(f"   Full report saved to: {OUTPUT_CSV.resolve()}")
    print("=" * 70)

if __name__ == "__main__":
    main()

