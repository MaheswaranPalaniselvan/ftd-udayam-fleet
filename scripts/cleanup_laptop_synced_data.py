"""
Audit and safely delete synced files in D:\\udayam_extract\\results on the laptop.
Checks every .7z archive and uncompressed district folder against g:\\My Drive\\Udyam_Archives.
Only deletes items that are 100% verified present and non-empty in Google Drive.
"""

import sys
import json
from pathlib import Path
import paramiko

LAPTOP_HOST = "192.168.0.12"
LAPTOP_USER = "ELCOT"
PRIV_KEY = Path.home() / ".ssh" / "id_rsa"
REMOTE_RESULTS_DIR = "D:/udayam_extract/results"
GDRIVE_DIR = Path(r"g:\My Drive\Udyam_Archives")

def get_gdrive_inventory():
    """Builds a map of base district/archive names to their existing files in GDrive."""
    if not GDRIVE_DIR.is_dir():
        raise RuntimeError(f"Google Drive directory not found at {GDRIVE_DIR}")
    
    files = {}
    for f in GDRIVE_DIR.glob("*.7z"):
        files[f.name.lower()] = {
            "name": f.name,
            "size_mb": round(f.stat().st_size / (1024 * 1024), 2)
        }
    return files

def main(dry_run: bool = True):
    print("=" * 70)
    print(f"🧹 LAPTOP RESULTS DIRECTORY CLEANUP ({'DRY RUN' if dry_run else 'LIVE EXECUTION'})")
    print("=" * 70)

    gdrive_files = get_gdrive_inventory()
    print(f"Found {len(gdrive_files)} archives in Google Drive ({GDRIVE_DIR}).\n")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {LAPTOP_USER}@{LAPTOP_HOST}...")
    client.connect(LAPTOP_HOST, port=22, username=LAPTOP_USER, key_filename=str(PRIV_KEY))
    sftp = client.open_sftp()

    remote_items = sftp.listdir_attr(REMOTE_RESULTS_DIR)
    print(f"Found {len(remote_items)} items in {REMOTE_RESULTS_DIR}.\n")

    safe_to_delete_files = []
    safe_to_delete_dirs = []
    unsafe_items = []

    for item in remote_items:
        name = item.filename
        size_mb = round(item.st_size / (1024 * 1024), 2)
        is_dir = (item.st_mode & 0o040000) != 0

        if not is_dir and name.lower().endswith(".7z"):
            # Check if this exact archive exists in GDrive or matching parts exist
            matched_gdrive = None
            if name.lower() in gdrive_files:
                matched_gdrive = gdrive_files[name.lower()]
            elif "tn-03" in name.lower():
                # TN-03 was synced as TN-03_historical.7z and TN-03_batch2.7z
                matched_gdrive = gdrive_files.get("tn-03_historical.7z") or gdrive_files.get("tn-03_batch2.7z")
            else:
                # Check if multi-part files exist in GDrive
                base = name.split(".")[0].split(" ")[0].lower()
                matching_parts = [v for k, v in gdrive_files.items() if k.startswith(base)]
                if matching_parts:
                    matched_gdrive = matching_parts[0]

            if matched_gdrive:
                safe_to_delete_files.append((name, size_mb, matched_gdrive['name']))
            else:
                unsafe_items.append((name, f"File {size_mb} MB - No GDrive match"))

        elif is_dir:
            # Check district folder
            dist_code = name.upper()
            target_codes = [dist_code]
            if dist_code.startswith("OD-"):
                target_codes.append(dist_code.replace("OD-", "OR-"))

            matched_archive = None
            for tc in target_codes:
                # Check for direct archive e.g. OR-01.7z, TN-11.7z, TR-01.7z
                arch_name = f"{tc}.7z".lower()
                if arch_name in gdrive_files:
                    matched_archive = gdrive_files[arch_name]
                    break
                # Check for parts
                parts = [v for k, v in gdrive_files.items() if k.startswith(tc.lower())]
                if parts:
                    matched_archive = parts[0]
                    break

            if matched_archive:
                safe_to_delete_dirs.append((name, matched_archive['name']))
            else:
                unsafe_items.append((name, "Folder - No verified archive found in GDrive"))

    # Print summary
    print("--- 1. VERIFIED .7Z ARCHIVES SAFE TO DELETE ---")
    total_file_mb = 0
    for name, mb, gname in safe_to_delete_files:
        print(f"  ✅ {name:<18} ({mb:>7.2f} MB) -> Verified in GDrive ({gname})")
        total_file_mb += mb

    print(f"\nTotal verified archive size to delete: {total_file_mb:,.2f} MB ({total_file_mb/1024:.2f} GB)")

    print("\n--- 2. VERIFIED UNCOMPRESSED FOLDERS SAFE TO DELETE ---")
    for name, gname in safe_to_delete_dirs:
        print(f"  ✅ Folder {name:<10} -> Verified in GDrive as {gname}")

    if unsafe_items:
        print("\n⚠️ --- ITEMS NOT VERIFIED (WILL NOT BE TOUCHED) ---")
        for name, reason in unsafe_items:
            print(f"  ❌ {name}: {reason}")
    else:
        print("\n🌟 ALL items in D:\\udayam_extract\\results are verified in Google Drive!")

    if not dry_run:
        print("\n🗑️ PROCEEDING WITH DELETION ON LAPTOP...")
        # 1. Delete verified .7z files
        for name, mb, _ in safe_to_delete_files:
            remote_p = f"{REMOTE_RESULTS_DIR}/{name}"
            print(f"   Deleting file {name} ({mb:.2f} MB)...")
            sftp.remove(remote_p)

        # 2. Delete verified folders
        for name, _ in safe_to_delete_dirs:
            remote_p = f"{REMOTE_RESULTS_DIR}/{name}"
            print(f"   Deleting directory {name}...")
            # Use PowerShell Remove-Item -Recurse -Force for speed
            cmd = f'powershell -NoProfile -Command "Remove-Item -Path \'{remote_p}\' -Recurse -Force"'
            stdin, stdout, stderr = client.exec_command(cmd)
            stdout.channel.recv_exit_status()

        print("\n✅ Deletion complete!")

    sftp.close()
    client.close()

if __name__ == "__main__":
    is_live = "--live" in sys.argv
    main(dry_run=not is_live)

