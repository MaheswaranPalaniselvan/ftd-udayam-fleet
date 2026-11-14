"""
Extracts ground truth record counts directly from Google Drive archives (Udyam_Archives)
for all districts where Google Sheet has an outdated or deflated count.
"""

import csv
import io
import os
import re
import subprocess
import sys
from pathlib import Path
import openpyxl

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from client.core.scraper import get_7z_binary

GDRIVE_DIR = Path(r"g:\My Drive\Udyam_Archives")
EXCEL_PATH = Path("public/udayam_latest.xlsx")
SUSPICIOUS_CSV = Path("gdrive_vs_sheet_audit.csv")
OUTPUT_CSV = Path("gdrive_truth_recovered.csv")
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

def extract_from_archive(seven_zip: str, archive_path: Path, code: str):
    """Extracts unique record count, last record, and last DOR from an archive."""
    try:
        proc = subprocess.run(
            [seven_zip, "e", str(archive_path), "-r", f"results_{code}.csv", "-so"],
            capture_output=True, text=True, errors="replace"
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            # Try generic results_*.csv
            proc = subprocess.run(
                [seven_zip, "e", str(archive_path), "-r", "results_*.csv", "-so"],
                capture_output=True, text=True, errors="replace"
            )

        if proc.returncode != 0 or not proc.stdout.strip():
            return 0, "", ""

        reader = csv.reader(io.StringIO(proc.stdout))
        records = {}
        header = None
        for row in reader:
            if not row:
                continue
            num = row[0].strip()
            if num.startswith(f"UDYAM-{code}-"):
                dor = row[3].strip() if len(row) > 3 else ""
                records[num] = dor

        if not records:
            return 0, "", ""

        # Sort by sequence number
        sorted_records = sorted(
            records.items(),
            key=lambda x: int(x[0].split("-")[-1]) if x[0].split("-")[-1].isdigit() else 0
        )
        last_num, last_dor = sorted_records[-1]
        return len(records), last_num, last_dor
    except Exception as e:
        print(f"Error reading {archive_path.name}: {e}")
        return 0, "", ""

def main():
    SCRATCH_DIR.mkdir(exist_ok=True)
    seven_zip = get_7z_binary()
    if not seven_zip:
        print("Error: 7z binary not found")
        sys.exit(1)

    print("=" * 70)
    print("🚀 EXTRACTING GROUND TRUTH COUNTS FROM GDRIVE ARCHIVES")
    print("=" * 70)

    # 1. Load suspicious districts from audit
    if not SUSPICIOUS_CSV.is_file():
        print(f"Error: Run audit_gdrive_vs_sheet.py first to create {SUSPICIOUS_CSV}")
        sys.exit(1)

    with open(SUSPICIOUS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        suspicious_list = [r for r in reader if r["is_suspicious"] == "True"]

    print(f"Loaded {len(suspicious_list)} suspicious target districts to verify.")

    recovered = []

    for idx, target in enumerate(suspicious_list, 1):
        code = target["district_code"]
        name = target["district_name"]
        state = target["state"]
        sheet_ext = clean_int(target["sheet_extracted"])
        total_ent = clean_int(target["total_enterprises"])
        is_multipart = target["is_multipart"] == "True"
        part_count = int(target["part_count"] or 0)

        print(f"[{idx:2d}/{len(suspicious_list)}] Processing {code} ({name}, {state})...", end="", flush=True)

        if is_multipart:
            # Stitch parts into scratch
            combined_path = SCRATCH_DIR / f"{code}_combined.7z"
            with open(combined_path, "wb") as outfile:
                for p_idx in range(1, part_count + 1):
                    part_file = GDRIVE_DIR / f"{code}.part{p_idx:02d}.7z"
                    if part_file.is_file():
                        with open(part_file, "rb") as infile:
                            outfile.write(infile.read())
            
            count, last_rec, last_dor = extract_from_archive(seven_zip, combined_path, code)
            source_file = f"{code}.part01-{part_count:02d}.7z"
            try:
                combined_path.unlink()
            except Exception:
                pass
        else:
            # Find largest archive for this code
            files = sorted(GDRIVE_DIR.glob(f"{code}*.7z"), key=lambda x: x.stat().st_size, reverse=True)
            if not files:
                print(" ❌ No files found")
                continue
            largest = files[0]
            count, last_rec, last_dor = extract_from_archive(seven_zip, largest, code)
            source_file = largest.name

        discrepancy = count - sheet_ext
        print(f" -> Found: {count:,} records (Sheet: {sheet_ext:,} | +{discrepancy:,})")

        recovered.append({
            "district_code": code,
            "state": state,
            "district_name": name,
            "total_enterprises": total_ent,
            "sheet_extracted": sheet_ext,
            "gdrive_verified_extracted": count,
            "discrepancy": discrepancy,
            "last_record": last_rec,
            "last_dor": last_dor,
            "archive_source": source_file
        })

    # Save to CSV
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "district_code", "state", "district_name", "total_enterprises",
            "sheet_extracted", "gdrive_verified_extracted", "discrepancy",
            "last_record", "last_dor", "archive_source"
        ])
        writer.writeheader()
        writer.writerows(recovered)

    print("\n" + "=" * 70)
    print(f"✅ Ground truth recovery complete! Saved to {OUTPUT_CSV.resolve()}")
    
    total_gdrive_records = sum(r["gdrive_verified_extracted"] for r in recovered)
    total_sheet_records = sum(r["sheet_extracted"] for r in recovered)
    total_missing = sum(r["discrepancy"] for r in recovered if r["discrepancy"] > 0)
    print(f"Total Sheet Extracted across these {len(recovered)} districts: {total_sheet_records:,}")
    print(f"Total True Extracted in Google Drive:                    {total_gdrive_records:,}")
    print(f"🚨 TOTAL DEFICIT (Records harvested but omitted in Sheet): {total_missing:,}")
    print("=" * 70)

if __name__ == "__main__":
    main()

