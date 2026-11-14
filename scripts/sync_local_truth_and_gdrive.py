"""
Sync all 39 discovered districts (1.86M verified records) from results/*.7z:
1. Bulk sync status to Master Google Sheet coordinator (action=bulk_sync_status)
2. Copy missing / larger archives to g:\\My Drive\\Udyam_Archives
"""

import csv
import json
import os
import shutil
import time
from pathlib import Path
import httpx

RESULTS_DIR = Path("results")
GDRIVE_DIR = Path(r"g:\My Drive\Udyam_Archives")
AUDIT_CSV = Path("results_discrepancies_audit.csv")

def get_coordinator_url() -> str:
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("COORDINATOR_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "https://script.google.com/macros/s/AKfycby3tmgH9PtjUhl6XfGrBfgRNZFQZaSLR0N4Dnff9tt9K5qjatyarJy_nnE0ulCtMNm2xA/exec"

def copy_to_gdrive(discrepancies):
    print("\n--- [Step 1] Checking & Updating Google Drive Archives ---")
    if not GDRIVE_DIR.exists():
        print(f"GDrive directory {GDRIVE_DIR} not accessible. Skipping copy.")
        return

    copied = 0
    skipped = 0
    for d in discrepancies:
        code = d["district_code"]
        local_file = Path(d["archive_path"])
        if not local_file.exists():
            continue

        target_file = GDRIVE_DIR / f"{code}.7z"
        need_copy = False
        if not target_file.exists():
            need_copy = True
        else:
            target_sz = target_file.stat().st_size
            local_sz = local_file.stat().st_size
            if local_sz > target_sz * 1.5 and local_sz > 1024 * 1024:
                need_copy = True

        if need_copy:
            try:
                print(f"  [GDrive Sync] Copying {local_file.name} ({d['file_size_mb']} MB) to Google Drive...")
                shutil.copy2(local_file, target_file)
                copied += 1
            except Exception as e:
                print(f"  [WARN] Failed to copy {local_file.name}: {e}")
        else:
            skipped += 1

    print(f"  Finished: Copied {copied} archives to Google Drive ({skipped} already present/adequate).")

def sync_to_sheet(discrepancies):
    print("\n--- [Step 2] Bulk Syncing Ground Truth to Master Google Sheet ---")
    coordinator_url = get_coordinator_url()
    print(f"Coordinator: {coordinator_url}")

    districts_map = {}
    for d in discrepancies:
        code = d["district_code"].strip().upper()
        info = {
            "total_extracted": int(d["archive_extracted"]),
            "total_failed": 0
        }
        if d.get("last_record"):
            info["last_record"] = d["last_record"].strip()
        if d.get("last_recorded_date"):
            info["last_recorded_date"] = d["last_recorded_date"].strip()
        districts_map[code] = info

    codes = list(districts_map.keys())
    batch_size = 20
    total_batches = (len(codes) + batch_size - 1) // batch_size

    for i in range(0, len(codes), batch_size):
        batch_codes = codes[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        print(f"  Sending Batch {batch_num}/{total_batches} ({len(batch_codes)} districts: {batch_codes})...")

        payload = {
            "action": "bulk_sync_status",
            "districts": {c: districts_map[c] for c in batch_codes}
        }

        success = False
        for attempt in range(1, 4):
            try:
                with httpx.Client(timeout=90.0, follow_redirects=True) as client:
                    resp = client.post(coordinator_url, json=payload)
                    if resp.status_code == 200:
                        try:
                            res_json = resp.json()
                            print(f"    Batch {batch_num} Success: {res_json.get('message', res_json)}")
                        except Exception:
                            print(f"    Batch {batch_num} Success: HTTP 200")
                        success = True
                        break
                    else:
                        print(f"    Attempt {attempt} failed: HTTP {resp.status_code} - {resp.text[:100]}")
            except Exception as e:
                print(f"    Attempt {attempt} error: {e}")
            time.sleep(2)

        if not success:
            print(f"    [ERROR] Batch {batch_num} failed all attempts.")
        time.sleep(1)

def main():
    if not AUDIT_CSV.exists():
        print(f"Audit CSV {AUDIT_CSV} not found.")
        return

    with open(AUDIT_CSV, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    print(f"Loaded {len(reader)} district discrepancies from {AUDIT_CSV}.")
    total_records = sum(int(r["diff"]) for r in reader)
    print(f"Total additional records: {total_records:,}")

    # 1. Sync to Google Sheet
    sync_to_sheet(reader)

    # 2. Copy archives to Google Drive
    copy_to_gdrive(reader)

    print("\n[ALL TASKS COMPLETED]")

if __name__ == "__main__":
    main()
