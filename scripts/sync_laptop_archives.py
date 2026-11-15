"""
Sync existing .7z archives from remote laptop (D:\\udayam_extract\\results)
to local Google Drive (g:\\My Drive\\Udyam_Archives) via LAN SFTP.
"""

import sys
import time
import shutil
from pathlib import Path
import paramiko

LAPTOP_HOST = "192.168.0.12"
LAPTOP_USER = "ELCOT"
PRIV_KEY = Path.home() / ".ssh" / "id_rsa"
REMOTE_DIR = "D:/udayam_extract/results"
STAGING_DIR = Path("staging")
GDRIVE_DIR = Path(r"g:\My Drive\Udyam_Archives")

# Archive mappings: (remote_file_name, target_gdrive_name)
ARCHIVES_TO_SYNC = [
    ("TR-02.7z", "TR-02.7z"),
    ("TR-03.7z", "TR-03.7z"),
    ("TR-04.7z", "TR-04.7z"),
    ("TR-05.7z", "TR-05.7z"),
    ("TR-06.7z", "TR-06.7z"),
    ("TR-07.7z", "TR-07.7z"),
    ("TR-08.7z", "TR-08.7z"),
    ("TN-03 (2).7z", "TN-03_historical.7z"),
    ("TN-03.7z", "TN-03_batch2.7z"),
]

def main():
    if not GDRIVE_DIR.exists():
        print(f"Error: Google Drive path {GDRIVE_DIR} does not exist!")
        sys.exit(1)

    STAGING_DIR.mkdir(exist_ok=True)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {LAPTOP_USER}@{LAPTOP_HOST}...")
    client.connect(LAPTOP_HOST, port=22, username=LAPTOP_USER, key_filename=str(PRIV_KEY))
    sftp = client.open_sftp()

    print(f"Found {len(ARCHIVES_TO_SYNC)} archives to transfer.\n")

    for remote_name, target_name in ARCHIVES_TO_SYNC:
        target_path = GDRIVE_DIR / target_name
        if target_path.exists() and target_path.stat().st_size > 10 * 1024 * 1024:
            print(f"⏩ {target_name} already exists in GDrive ({target_path.stat().st_size / (1024*1024):.2f} MB), skipping.")
            continue

        remote_path = f"{REMOTE_DIR}/{remote_name}"
        staged_path = STAGING_DIR / target_name

        print(f"📥 Downloading {remote_name} -> {staged_path.name}...")
        t0 = time.time()
        try:
            sftp.get(remote_path, str(staged_path))
        except Exception as e:
            print(f"❌ Failed to download {remote_name}: {e}")
            if staged_path.exists():
                staged_path.unlink()
            continue

        dt = time.time() - t0
        mb = staged_path.stat().st_size / (1024 * 1024)
        speed = mb / dt if dt > 0 else 0
        print(f"   Downloaded {mb:.2f} MB in {dt:.2f}s ({speed:.2f} MB/s)")

        print(f"   Copying to {target_path}...")
        shutil.copy2(str(staged_path), str(target_path))
        staged_path.unlink() # Free up local disk
        print(f"   ✅ Successfully synced {target_name} to Google Drive!\n")

    sftp.close()
    client.close()
    print("🎉 All designated archives successfully synced to Google Drive!")

if __name__ == "__main__":
    main()

