"""
Script to audit all archives in results/ and sync ground-truth records to Google Sheet and Google Drive.
"""

import csv
import io
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
import httpx
import openpyxl

SCRATCH_DIR = Path("scratch")
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

RESULTS_DIR = Path("results")
GDRIVE_DIR = Path(r"g:\My Drive\Udyam_Archives")
SEVEN_ZIP = r"C:\Program Files\7-Zip\7z.exe"
EXCEL_PATH = Path("public/udayam_latest.xlsx")

def get_coordinator_url() -> str:
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("COORDINATOR_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "https://script.google.com/macros/s/AKfycby3tmgH9PtjUhl6XfGrBfgRNZFQZaSLR0N4Dnff9tt9K5qjatyarJy_nnE0ulCtMNm2xA/exec"

def extract_archive_details(archive_path: Path, code: str):
    """Extract unique record count, last record, and last DOR from an archive."""
    try:
        proc = subprocess.run(
            [SEVEN_ZIP, "e", str(archive_path), "-r", f"results_{code}.csv", "-so"],
            capture_output=True, text=True, errors="replace"
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            proc = subprocess.run(
                [SEVEN_ZIP, "e", str(archive_path), "-r", "results_*.csv", "-so"],
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

        def parse_seq(rec):
            try:
                return int(rec[0].split("-")[-1])
            except:
                return 0

        sorted_records = sorted(records.items(), key=parse_seq)
        last_num, last_dor = sorted_records[-1]
        return len(records), last_num, last_dor
    except Exception as e:
        print(f"Error reading {archive_path}: {e}")
        return 0, "", ""

def main():
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    ws = wb["Universe"]
    sheet_data = {}
    for r in range(2, ws.max_row + 1):
        code = ws.cell(row=r, column=2).value
        ext = ws.cell(row=r, column=12).value
        name = ws.cell(row=r, column=4).value
        status = ws.cell(row=r, column=14).value
        tot = ws.cell(row=r, column=8).value
        if code:
            code_str = str(code).strip()
            try:
                ext_int = int(float(str(ext).replace(",", "").strip())) if ext else 0
            except:
                ext_int = 0
            try:
                tot_int = int(float(str(tot).replace(",", "").strip())) if tot else 0
            except:
                tot_int = 0
            sheet_data[code_str] = {
                "name": name,
                "extracted": ext_int,
                "total": tot_int,
                "status": status,
                "row": r
            }

    print(f"Loaded {len(sheet_data)} districts from sheet.")

    discrepancies = []
    
    local_files = [f for f in RESULTS_DIR.iterdir() if f.suffix == ".7z" and not f.name.startswith(".")]
    print(f"Scanning {len(local_files)} archives in {RESULTS_DIR}...")

    for f in local_files:
        code = f.stem
        if code not in sheet_data:
            continue

        sheet_info = sheet_data[code]
        sheet_ext = sheet_info["extracted"]

        count, last_rec, last_dor = extract_archive_details(f, code)
        if count > sheet_ext:
            diff = count - sheet_ext
            status = "Completed" if count >= sheet_info["total"] * 0.9 or count > 500 else sheet_info["status"]
            discrepancies.append({
                "district_code": code,
                "district_name": sheet_info["name"],
                "sheet_extracted": sheet_ext,
                "archive_extracted": count,
                "diff": diff,
                "last_record": last_rec,
                "last_recorded_date": last_dor,
                "status": status or "Completed",
                "archive_path": str(f),
                "file_size_mb": round(f.stat().st_size / (1024 * 1024), 2)
            })

    print(f"\nFound {len(discrepancies)} districts with local archives > sheet extracted:")
    total_added = sum(d["diff"] for d in discrepancies)
    for d in sorted(discrepancies, key=lambda x: x["diff"], reverse=True):
        print(f"  {d['district_code']:<8} ({d['district_name']:<18}): Sheet = {d['sheet_extracted']:<8} | Local = {d['archive_extracted']:<8} (+{d['diff']:<8}) [{d['file_size_mb']} MB] -> {d['last_record']} ({d['last_recorded_date']})")

    print(f"\nTotal additional verified records to restore: {total_added:,}")

    # Write audit log to CSV
    audit_csv = Path("results_discrepancies_audit.csv")
    with open(audit_csv, "w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=[
            "district_code", "district_name", "sheet_extracted", "archive_extracted", 
            "diff", "last_record", "last_recorded_date", "status", "file_size_mb", "archive_path"
        ])
        writer.writeheader()
        writer.writerows(discrepancies)
    print(f"Saved audit log to {audit_csv}")

if __name__ == "__main__":
    main()
