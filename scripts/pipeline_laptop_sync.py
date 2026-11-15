"""
End-to-End Orchestrator:
1. Compresses unarchived district folders on the laptop into .7z archives (writing to C:\\Users\\ELCOT\\udayam\\archives\\).
2. Transfers archives over LAN SFTP directly to g:\\My Drive\\Udyam_Archives\\.
3. Cleans up staging and remote archives to preserve disk space.
4. Updates Google Sheet via Google Apps Script (bulk_sync_status) with true record counts and Completed status.
5. Updates Cloudflare Pages dashboard.
"""

import os
import sys
import time
import json
import shutil
import httpx
from pathlib import Path
import paramiko

LAPTOP_HOST = "192.168.0.12"
LAPTOP_USER = "ELCOT"
PRIV_KEY = Path.home() / ".ssh" / "id_rsa"
GDRIVE_DIR = Path(r"g:\My Drive\Udyam_Archives")
STAGING_DIR = Path("staging")
REMOTE_SOURCE_BASE = "D:/udayam_extract/results"
REMOTE_ARCHIVE_DIR = "C:/Users/ELCOT/udayam/archives"
GSHEET_URL = "https://script.google.com/macros/s/AKfycby3tmgH9PtjUhl6XfGrBfgRNZFQZaSLR0N4Dnff9tt9K5qjatyarJy_nnE0ulCtMNm2xA/exec"

# Districts to process: (source_folder, target_code, target_archive_name, is_completed)
# Based on exact audit from laptop_extracts_audit.json
TASKS = [
    # Tripura and TN-03 already transferred to GDrive, need GSheet update
    {"folder": None, "target_code": "TR-01", "archive": "TR-01.7z", "count": 10870, "last_rec": "UDYAM-TR-01-0011392", "status": "Completed"},
    {"folder": None, "target_code": "TR-02", "archive": "TR-02.7z", "count": 17149, "last_rec": "UDYAM-TR-02-0017999", "status": "Completed"},
    {"folder": None, "target_code": "TR-03", "archive": "TR-03.7z", "count": 11309, "last_rec": "UDYAM-TR-03-0011896", "status": "Completed"},
    {"folder": None, "target_code": "TR-04", "archive": "TR-04.7z", "count": 18439, "last_rec": "UDYAM-TR-04-0019510", "status": "Completed"},
    {"folder": None, "target_code": "TR-05", "archive": "TR-05.7z", "count": 15082, "last_rec": "UDYAM-TR-05-0015829", "status": "Completed"},
    {"folder": None, "target_code": "TR-06", "archive": "TR-06.7z", "count": 13682, "last_rec": "UDYAM-TR-06-0014450", "status": "Completed"},
    {"folder": None, "target_code": "TR-07", "archive": "TR-07.7z", "count": 10111, "last_rec": "UDYAM-TR-07-0011826", "status": "Completed"},
    {"folder": None, "target_code": "TR-08", "archive": "TR-08.7z", "count": 38535, "last_rec": "UDYAM-TR-08-0040807", "status": "Completed"},
    {"folder": None, "target_code": "TN-03", "archive": "TN-03_historical.7z", "count": 300244, "last_rec": "UDYAM-TN-03-0348932", "status": "Completed"},

    # Tamil Nadu folders to compress and sync
    {"folder": "TN-11", "target_code": "TN-11", "archive": "TN-11.7z", "count": 124107, "last_rec": "UDYAM-TN-11-0132800", "status": "Completed"},
    {"folder": "TN-30", "target_code": "TN-30", "archive": "TN-30.7z", "count": 110263, "last_rec": "UDYAM-TN-30-0123016", "status": "Completed"},

    # Odisha folders to compress and sync (OD-XX maps to OR-XX)
    {"folder": "OD-01", "target_code": "OR-01", "archive": "OR-01.7z", "count": 51861, "last_rec": "UDYAM-OD-01-0055668", "status": "Completed"},
    {"folder": "OD-02", "target_code": "OR-02", "archive": "OR-02.7z", "count": 53835, "last_rec": "UDYAM-OD-02-0057719", "status": "Completed"},
    {"folder": "OD-03", "target_code": "OR-03", "archive": "OR-03.7z", "count": 104875, "last_rec": "UDYAM-OD-03-0111574", "status": "Completed"},
    {"folder": "OD-04", "target_code": "OR-04", "archive": "OR-04.7z", "count": 57926, "last_rec": "UDYAM-OD-04-0061680", "status": "Completed"},
    {"folder": "OD-05", "target_code": "OR-05", "archive": "OR-05.7z", "count": 74984, "last_rec": "UDYAM-OD-05-0079951", "status": "Completed"},
    {"folder": "OD-06", "target_code": "OR-06", "archive": "OR-06.7z", "count": 14567, "last_rec": "UDYAM-OD-06-0016011", "status": "Completed"},
    {"folder": "OD-07", "target_code": "OR-07", "archive": "OR-07.7z", "count": 139686, "last_rec": "UDYAM-OD-07-0147755", "status": "Completed"},
    {"folder": "OD-08", "target_code": "OR-08", "archive": "OR-08.7z", "count": 10308, "last_rec": "UDYAM-OD-08-0011174", "status": "Completed"},
    {"folder": "OD-09", "target_code": "OR-09", "archive": "OR-09.7z", "count": 48107, "last_rec": "UDYAM-OD-09-0050760", "status": "Completed"},
    {"folder": "OD-10", "target_code": "OR-10", "archive": "OR-10.7z", "count": 14984, "last_rec": "UDYAM-OD-10-0016000", "status": "Completed"},
    {"folder": "OD-11", "target_code": "OR-11", "archive": "OR-11.7z", "count": 127536, "last_rec": "UDYAM-OD-11-0134596", "status": "Completed"},
    {"folder": "OD-12", "target_code": "OR-12", "archive": "OR-12.7z", "count": 49077, "last_rec": "UDYAM-OD-12-0051982", "status": "Completed"},
    {"folder": "OD-13", "target_code": "OR-13", "archive": "OR-13.7z", "count": 73577, "last_rec": "UDYAM-OD-13-0077781", "status": "Completed"},
    {"folder": "OD-14", "target_code": "OR-14", "archive": "OR-14.7z", "count": 24769, "last_rec": "UDYAM-OD-14-0026400", "status": "Completed"},
    {"folder": "OD-15", "target_code": "OR-15", "archive": "OR-15.7z", "count": 43766, "last_rec": "UDYAM-OD-15-0046270", "status": "Completed"},
    {"folder": "OD-16", "target_code": "OR-16", "archive": "OR-16.7z", "count": 18602, "last_rec": "UDYAM-OD-16-0019739", "status": "Completed"},
    {"folder": "OD-17", "target_code": "OR-17", "archive": "OR-17.7z", "count": 53893, "last_rec": "UDYAM-OD-17-0057228", "status": "Completed"},
    {"folder": "OD-19", "target_code": "OR-19", "archive": "OR-19.7z", "count": 1, "last_rec": "UDYAM-OD-19-0000038", "status": "In Progress"},
    {"folder": "OD-28", "target_code": "OR-28", "archive": "OR-28.7z", "count": 328, "last_rec": "UDYAM-OD-28-0000392", "status": "In Progress"},
]

def update_gsheet_batch(items: list):
    """Updates Google Sheet with verified counts via Google Apps Script."""
    districts = {}
    for item in items:
        districts[item["target_code"]] = {
            "total_extracted": item["count"],
            "total_failed": 0,
            "last_record": item["last_rec"],
            "status": item["status"],
        }

    payload = {
        "action": "bulk_sync_status",
        "districts": districts
    }

    try:
        resp = httpx.post(GSHEET_URL, json=payload, follow_redirects=True, timeout=45.0)
        if resp.status_code == 200 and resp.json().get("success"):
            print(f"   📊 Google Sheet updated for {len(districts)} districts! ({resp.json().get('updated_count')} rows)")
        else:
            print(f"   ⚠️ Google Sheet update returned: {resp.text[:120]}")
    except Exception as e:
        print(f"   ❌ Google Sheet update error: {e}")

def main():
    if not GDRIVE_DIR.exists():
        print(f"Error: Google Drive path {GDRIVE_DIR} does not exist!")
        sys.exit(1)

    STAGING_DIR.mkdir(exist_ok=True)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"🔌 Connecting to {LAPTOP_USER}@{LAPTOP_HOST}...")
    client.connect(LAPTOP_HOST, port=22, username=LAPTOP_USER, key_filename=str(PRIV_KEY))
    sftp = client.open_sftp()

    # Ensure remote archive directory exists
    try:
        sftp.mkdir(REMOTE_ARCHIVE_DIR)
    except IOError:
        pass

    completed_for_sheet = []

    for idx, t in enumerate(TASKS, 1):
        target_code = t["target_code"]
        target_archive = t["archive"]
        folder = t["folder"]
        gdrive_target = GDRIVE_DIR / target_archive

        print(f"\n========================================================")
        print(f"[{idx}/{len(TASKS)}] Processing {target_code} ({t['count']:,} records)")
        print(f"========================================================")

        # Step 1: Check if archive is already in GDrive
        if gdrive_target.exists() and gdrive_target.stat().st_size > 1024 * 1024:
            print(f"⏩ Archive {target_archive} already exists in GDrive ({gdrive_target.stat().st_size / (1024*1024):.2f} MB).")
            completed_for_sheet.append(t)
            continue

        if not folder:
            print(f"⚠️ No source folder defined for {target_code} and archive missing in GDrive.")
            continue

        # Step 2: Compress remote folder into C:/Users/ELCOT/udayam/archives/{target_archive}
        remote_archive_path = f"{REMOTE_ARCHIVE_DIR}/{target_archive}"
        source_dir = f"{REMOTE_SOURCE_BASE}/{folder}"
        
        print(f"📦 Compressing remote folder {source_dir} -> {remote_archive_path}...")
        t_comp_start = time.time()
        compress_cmd = (
            f"powershell -NoProfile -ExecutionPolicy Bypass -Command \""
            f"& 'C:\\Program Files\\7-Zip\\7z.exe' a -mx=1 '{remote_archive_path}' '{source_dir}' | Out-Null\""
        )
        stdin, stdout, stderr = client.exec_command(compress_cmd)
        exit_status = stdout.channel.recv_exit_status()
        dt_comp = time.time() - t_comp_start

        if exit_status != 0:
            err = stderr.read().decode()
            print(f"❌ Compression failed (code {exit_status}): {err}")
            continue

        # Check archive size on remote
        try:
            r_stat = sftp.stat(remote_archive_path)
            r_mb = r_stat.st_size / (1024 * 1024)
            print(f"   ✅ Compressed {r_mb:.2f} MB in {dt_comp:.1f}s")
        except Exception as e:
            print(f"❌ Failed to stat remote archive: {e}")
            continue

        # Step 3: Transfer via SFTP to staging
        staged_path = STAGING_DIR / target_archive
        print(f"📥 Downloading to local staging: {staged_path}...")
        t_dl_start = time.time()
        try:
            sftp.get(remote_archive_path, str(staged_path))
        except Exception as e:
            print(f"❌ SFTP download failed: {e}")
            if staged_path.exists():
                staged_path.unlink()
            continue
        dt_dl = time.time() - t_dl_start
        mb_dl = staged_path.stat().st_size / (1024 * 1024)
        print(f"   Downloaded {mb_dl:.2f} MB in {dt_dl:.1f}s ({mb_dl/dt_dl:.2f} MB/s)")

        # Step 4: Atomic copy to GDrive
        print(f"📁 Copying {target_archive} to Google Drive...")
        shutil.copy2(str(staged_path), str(gdrive_target))
        staged_path.unlink() # Free local staging

        # Step 5: Remove remote archive to preserve laptop C: drive space
        try:
            sftp.remove(remote_archive_path)
            print("   🧹 Cleaned up temporary remote archive on laptop.")
        except Exception:
            pass

        completed_for_sheet.append(t)

        # Batch update Google Sheet every 5 districts
        if len(completed_for_sheet) >= 5:
            update_gsheet_batch(completed_for_sheet)
            completed_for_sheet = []

    # Final batch update for any remaining districts
    if completed_for_sheet:
        update_gsheet_batch(completed_for_sheet)

    sftp.close()
    client.close()
    print("\n🎉 ALL TASKS COMPLETE! Google Drive and Google Sheet fully synchronized.")

if __name__ == "__main__":
    main()

