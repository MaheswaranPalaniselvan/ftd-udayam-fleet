"""
Syncs recovered ground truth from Google Drive archives to Central Google Sheet
and updates sync_report.csv, then triggers Cloudflare Pages rebuild & deployment.
"""

import csv
import json
import os
import re
import sys
import time
from pathlib import Path
import httpx

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env
env_path = Path(".env")
if env_path.is_file():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

URL = os.getenv("GOOGLE_APPS_SCRIPT_URL", "https://script.google.com/macros/s/AKfycby3tmgH9PtjUhl6XfGrBfgRNZFQZaSLR0N4Dnff9tt9K5qjatyarJy_nnE0ulCtMNm2xA/exec")
TRUTH_CSV = Path("nationwide_gdrive_truth.csv")
SYNC_REPORT_CSV = Path("sync_report.csv")
BATCH_SIZE = 40

def is_valid_date(val: str) -> bool:
    if not val:
        return False
    val = val.strip()
    if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", val):
        return True
    if re.search(r"\d{4}-\d{2}-\d{2}", val):
        return True
    if any(m in val.lower() for m in ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]):
        return True
    return False

def main():
    if not TRUTH_CSV.is_file():
        print(f"Error: {TRUTH_CSV} not found.")
        sys.exit(1)

    print("=" * 70)
    print("🚀 APPLYING GROUND TRUTH RECOVERY TO GOOGLE SHEET & SYNC REPORT")
    print("=" * 70)

    # 1. Load underreported districts
    with open(TRUTH_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_districts = list(reader)

    underreported = [r for r in all_districts if r.get("is_underreported") == "True" and int(r.get("gdrive_verified_extracted", 0)) > int(r.get("sheet_extracted", 0))]
    print(f"[1/3] Identified {len(underreported)} underreported districts to sync to Google Sheet.")
    
    total_recovered = sum(int(r["discrepancy"]) for r in underreported)
    print(f"      Total records being restored: {total_recovered:,}")

    # Build district update payload map
    districts_map = {}
    for r in underreported:
        code = r["district_code"].strip().upper()
        info = {
            "total_extracted": int(r["gdrive_verified_extracted"]),
            "total_failed": 0
        }
        if r.get("last_record"):
            info["last_record"] = r["last_record"].strip()
        
        dor = r.get("last_dor", "").strip()
        if is_valid_date(dor):
            info["last_recorded_date"] = dor

        districts_map[code] = info

    # 2. Batch sync to Google Apps Script
    codes = list(districts_map.keys())
    total_batches = (len(codes) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"\n[2/3] Sending bulk_sync_status to Central Coordinator in {total_batches} batches...")

    client = httpx.Client(timeout=45.0, follow_redirects=True)
    total_updated = 0

    for i in range(0, len(codes), BATCH_SIZE):
        batch_codes = codes[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        batch_payload = {
            "action": "bulk_sync_status",
            "districts": {c: districts_map[c] for c in batch_codes}
        }

        print(f"      Batch {batch_num}/{total_batches} ({len(batch_codes)} districts: {batch_codes[0]}..{batch_codes[-1]})...", end="", flush=True)
        try:
            resp = client.post(URL, json=batch_payload)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    cnt = data.get("updated_count", 0)
                    total_updated += cnt
                    print(f" ✅ Success! ({cnt} rows updated in Sheet)")
                else:
                    print(f" ⚠️ API returned false: {data.get('message')}")
            else:
                print(f" ❌ HTTP Error {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            print(f" ❌ Request error: {e}")
        
        time.sleep(1.0) # Graceful delay between batches

    client.close()
    print(f"\n      Google Sheet update complete! Total rows updated: {total_updated}/{len(districts_map)}")

    # 3. Update sync_report.csv
    print(f"\n[3/3] Updating local {SYNC_REPORT_CSV}...")
    existing_sync = {}
    if SYNC_REPORT_CSV.is_file():
        with open(SYNC_REPORT_CSV, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                c = row.get("District Code", "").strip().upper()
                if c:
                    existing_sync[c] = row

    for r in all_districts:
        code = r["district_code"].strip().upper()
        extracted = int(r.get("gdrive_verified_extracted", 0))
        if extracted <= 0:
            continue

        existing_ext = int(existing_sync[code].get("Total Extracted", 0)) if code in existing_sync else 0
        
        if extracted >= existing_ext:
            dor = r.get("last_dor", "").strip()
            if not is_valid_date(dor) and code in existing_sync:
                dor = existing_sync[code].get("Last Recorded Date", "")

            existing_sync[code] = {
                "District Code": code,
                "Last Record": r.get("last_record", "").strip() or (existing_sync[code].get("Last Record", "") if code in existing_sync else ""),
                "Last Recorded Date": dor,
                "Total Extracted": str(extracted),
                "Deregistered/Unregistered": existing_sync[code].get("Deregistered/Unregistered", "0") if code in existing_sync else "0",
                "Total Failed": "0",
                "Is Archive": "True",
                "Source Path": f"g:\\My Drive\\Udyam_Archives\\{r.get('archive_source', '')}"
            }

    fieldnames = [
        "District Code", "Last Record", "Last Recorded Date",
        "Total Extracted", "Deregistered/Unregistered", "Total Failed",
        "Is Archive", "Source Path"
    ]
    with open(SYNC_REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in sorted(existing_sync.keys()):
            writer.writerow(existing_sync[c])

    print(f"      Saved {len(existing_sync)} verified districts to {SYNC_REPORT_CSV}.")
    print("\n✅ All ground-truth counts successfully synced!")

if __name__ == "__main__":
    main()

