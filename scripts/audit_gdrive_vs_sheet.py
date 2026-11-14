"""
Audit Google Drive archives against Google Sheet (udayam_latest.xlsx).
Detects all districts where Google Drive contains substantial extracted data
but Google Sheet has an outdated, deflated, or near-zero count due to historical
partial-batch overwrites.
"""

import csv
import io
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
import openpyxl

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from client.core.scraper import get_7z_binary

GDRIVE_DIR = Path(r"g:\My Drive\Udyam_Archives")
EXCEL_PATH = Path("public/udayam_latest.xlsx")
OUTPUT_CSV = Path("gdrive_vs_sheet_audit.csv")

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

def main():
    if not GDRIVE_DIR.is_dir():
        print(f"Error: Google Drive archives directory not found at {GDRIVE_DIR}")
        sys.exit(1)

    if not EXCEL_PATH.is_file():
        print(f"Error: Master sheet {EXCEL_PATH} not found")
        sys.exit(1)

    seven_zip = get_7z_binary()
    if not seven_zip:
        print("Error: 7z binary not found")
        sys.exit(1)

    print("=" * 70)
    print("🔍 AUDITING GDRIVE ARCHIVES VS GOOGLE SHEET (NATIONWIDE)")
    print("=" * 70)

    # 1. Load Google Sheet
    print("[1/4] Loading master Google Sheet...")
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    ws = wb.active
    sheet_data = {}
    for r in range(2, ws.max_row + 1):
        level = ws.cell(row=r, column=1).value
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
    print(f"      Loaded {len(sheet_data)} districts from sheet.")

    # 2. Discover all .7z files in GDrive
    print("\n[2/4] Indexing Google Drive archives in Udyam_Archives...")
    all_7z = list(GDRIVE_DIR.glob("*.7z"))
    print(f"      Found {len(all_7z)} archive files in Google Drive.")

    dist_files = defaultdict(list)
    for f in all_7z:
        m = re.match(r"^([A-Z]{2}-\d{2})", f.name)
        if m:
            code = m.group(1).upper()
            dist_files[code].append(f)

    print(f"      Grouped into {len(dist_files)} distinct district codes.")

    # 3. Analyze each district
    print("\n[3/4] Analyzing file sizes, parts, and discrepancies...")
    results = []
    
    for code, files in sorted(dist_files.items()):
        total_size = sum(f.stat().st_size for f in files)
        total_size_mb = total_size / (1024 * 1024)
        
        # Check if multipart (.part01.7z, etc.)
        parts = [f for f in files if ".part" in f.name.lower()]
        has_multipart = len(parts) > 1
        
        sheet_info = sheet_data.get(code, {})
        sheet_ext = sheet_info.get("sheet_extracted", 0)
        dist_name = sheet_info.get("name", "Unknown")
        state_name = sheet_info.get("state", "Unknown")
        total_ent = sheet_info.get("total_enterprises", 0)
        
        # Determine if this district has a severe discrepancy
        # e.g., archive is > 1MB but sheet has < 1000, or archive is > 5MB but sheet has < 5000, or total_size_mb > 10
        is_suspicious = False
        if total_size_mb >= 10.0 and sheet_ext < 5000:
            is_suspicious = True
        elif total_size_mb >= 2.0 and sheet_ext < 500:
            is_suspicious = True
        elif total_size_mb >= 0.5 and sheet_ext < 100:
            is_suspicious = True

        results.append({
            "district_code": code,
            "state": state_name,
            "district_name": dist_name,
            "total_enterprises": total_ent,
            "sheet_extracted": sheet_ext,
            "sheet_status": sheet_info.get("sheet_status", ""),
            "gdrive_file_count": len(files),
            "total_size_mb": round(total_size_mb, 2),
            "is_multipart": has_multipart,
            "part_count": len(parts),
            "is_suspicious": is_suspicious,
            "files": sorted([f.name for f in files])
        })

    # Sort suspicious districts by size descending
    suspicious = [r for r in results if r["is_suspicious"]]
    print(f"\n[4/4] Analysis complete!")
    print(f"      Total districts with archives: {len(results)}")
    print(f"      ⚠️ Districts with severe discrepancy (Large GDrive file vs Near-Zero Sheet Extracted): {len(suspicious)}")

    # Write full audit CSV
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "district_code", "state", "district_name", "total_enterprises",
            "sheet_extracted", "sheet_status", "total_size_mb", "gdrive_file_count",
            "is_multipart", "part_count", "is_suspicious", "files"
        ])
        writer.writeheader()
        for r in results:
            row_copy = dict(r)
            row_copy["files"] = "; ".join(row_copy["files"])
            writer.writerow(row_copy)

    print(f"\nSaved full audit to: {OUTPUT_CSV.resolve()}")

    # Print top 25 suspicious districts
    print("\n" + "=" * 80)
    print("🚨 TOP DISTRICTS WITH DEFLATED SHEET COUNTS (CRITICAL AUDIT TARGETS)")
    print("=" * 80)
    print(f"{'Code':<8} | {'State':<20} | {'District Name':<20} | {'Sheet Ext':<10} | {'GDrive Size':<12} | {'Parts'}")
    print("-" * 80)
    for s in sorted(suspicious, key=lambda x: x["total_size_mb"], reverse=True)[:35]:
        parts_str = f"{s['part_count']} parts" if s["is_multipart"] else f"{s['gdrive_file_count']} files"
        print(f"{s['district_code']:<8} | {s['state'][:20]:<20} | {s['district_name'][:20]:<20} | {s['sheet_extracted']:<10} | {s['total_size_mb']:>8.1f} MB | {parts_str}")

if __name__ == "__main__":
    main()
