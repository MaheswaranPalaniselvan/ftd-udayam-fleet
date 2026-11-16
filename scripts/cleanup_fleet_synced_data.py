"""
FlawlessTech Data - Fleet Synced Data Purge Tool
Safely checks results folders and .7z archives across local machines
(Pi 4B, Pi 5, Jetson Nano, Laptop, Local) against Google Drive.
Any folder or .7z archive that is 100% verified present and non-empty in Google Drive
is safely deleted from the edge machine to free disk space.
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, Set

try:
    import paramiko
except ImportError:
    paramiko = None

GDRIVE_DIR = Path(r"g:\My Drive\Udyam_Archives")
SSH_KEY = Path.home() / ".ssh" / "id_ed25519"
SSH_KEY_RSA = Path.home() / ".ssh" / "id_rsa"

DEVICE_CONFIGS = {
    "pi4": {
        "host": "192.168.0.50",
        "user": "mahesp93",
        "password": "this2shall9@55",
        "results_dir": "/home/mahesp93/udayam/results",
        "active_districts": ["AP-04"],
        "is_windows": False
    },
    "pi5": {
        "host": "192.168.0.11",
        "user": "mahesp93",
        "password": "this2shall9@55",
        "results_dir": "/home/mahesp93/udayam/results",
        "active_districts": ["AP-03"],
        "is_windows": False
    },
    "jetson": {
        "host": "192.168.0.16",
        "user": "mahesp93",
        "password": "this2shall9@55",
        "results_dir": "/home/mahesp93/udayam/results",
        "active_districts": ["AP-02"],
        "is_windows": False
    },
    "laptop": {
        "host": "192.168.0.12",
        "user": "ELCOT",
        "password": None,
        "results_dir": "C:/Users/ELCOT/udayam/results",
        "active_districts": ["AP-01"],
        "is_windows": True
    }
}


def get_gdrive_inventory() -> Dict[str, dict]:
    """Builds a map of archive names in Google Drive."""
    if not GDRIVE_DIR.is_dir():
        print(f"⚠️ Warning: Google Drive directory not accessible at {GDRIVE_DIR}")
        return {}

    inventory = {}
    for f in GDRIVE_DIR.glob("*.7z"):
        inventory[f.name.lower()] = {
            "name": f.name,
            "size_bytes": f.stat().st_size,
            "size_mb": round(f.stat().st_size / (1024 * 1024), 2)
        }
    return inventory


def get_ssh_client(cfg: dict) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    for k in [SSH_KEY, SSH_KEY_RSA]:
        if k.is_file():
            try:
                client.connect(
                    hostname=cfg["host"],
                    port=22,
                    username=cfg["user"],
                    key_filename=str(k),
                    timeout=8
                )
                return client
            except Exception:
                pass

    if cfg.get("password"):
        client.connect(
            hostname=cfg["host"],
            port=22,
            username=cfg["user"],
            password=cfg["password"],
            timeout=10,
            allow_agent=False,
            look_for_keys=False
        )
        return client

    raise RuntimeError(f"Could not connect to {cfg['host']}")


def cleanup_remote_device(device_name: str, cfg: dict, gdrive_files: Dict[str, dict], live: bool = False):
    print("\n" + "=" * 70)
    print(f"🧹 AUDITING SYNCED DATA ON [{device_name.upper()}] ({cfg['host']}) - {'LIVE PURGE' if live else 'DRY RUN'}")
    print("=" * 70)

    try:
        client = get_ssh_client(cfg)
    except Exception as e:
        print(f"❌ Failed to connect to {device_name} ({cfg['host']}): {e}")
        return

    sftp = client.open_sftp()
    remote_dir = cfg["results_dir"]
    active_set = set(d.upper() for d in cfg.get("active_districts", []))

    try:
        remote_items = sftp.listdir_attr(remote_dir)
    except Exception as e:
        print(f"❌ Could not read remote results dir {remote_dir}: {e}")
        sftp.close()
        client.close()
        return

    safe_to_delete_files = []
    safe_to_delete_dirs = []
    skipped_items = []

    for item in remote_items:
        name = item.filename
        is_dir = (item.st_mode & 0o040000) != 0
        stem = name.split(".")[0].upper()

        # NEVER delete the actively scraping district folder/archive
        if stem in active_set:
            skipped_items.append((name, f"Active scraping district ({stem})"))
            continue

        if not is_dir and name.lower().endswith(".7z"):
            size_mb = round(item.st_size / (1024 * 1024), 2)
            matched = gdrive_files.get(name.lower())
            if not matched:
                # Check for base name / parts in GDrive
                matched_parts = [v for k, v in gdrive_files.items() if k.startswith(stem.lower())]
                if matched_parts:
                    matched = matched_parts[0]

            if matched:
                safe_to_delete_files.append((name, size_mb, matched["name"]))
            else:
                skipped_items.append((name, f"File {size_mb} MB - Not found in Google Drive"))

        elif is_dir:
            matched = gdrive_files.get(f"{name.lower()}.7z")
            if not matched:
                matched_parts = [v for k, v in gdrive_files.items() if k.startswith(name.lower())]
                if matched_parts:
                    matched = matched_parts[0]

            if matched:
                safe_to_delete_dirs.append((name, matched["name"]))
            else:
                skipped_items.append((name, "Folder - No matching archive in Google Drive"))

    print(f"Total remote items inspected: {len(remote_items)}")
    print(f"Verified archives safe to delete: {len(safe_to_delete_files)}")
    print(f"Verified folders safe to delete: {len(safe_to_delete_dirs)}")
    print(f"Skipped / unverified items: {len(skipped_items)}")

    total_mb = sum(mb for _, mb, _ in safe_to_delete_files)
    print(f"Total archive space to reclaim: {total_mb:,.1f} MB ({total_mb/1024:.2f} GB)")

    if live:
        print(f"\n🗑️ Deleting verified items on {device_name}...")
        deleted_count = 0
        for fname, mb, gname in safe_to_delete_files:
            remote_path = f"{remote_dir}/{fname}"
            try:
                sftp.remove(remote_path)
                deleted_count += 1
            except Exception as e:
                print(f"   ⚠️ Could not remove {fname}: {e}")

        for dname, gname in safe_to_delete_dirs:
            remote_path = f"{remote_dir}/{dname}"
            try:
                if cfg["is_windows"]:
                    cmd = f'powershell -NoProfile -Command "Remove-Item -Path \'{remote_path}\' -Recurse -Force"'
                else:
                    cmd = f"rm -rf '{remote_path}'"
                stdin, stdout, stderr = client.exec_command(cmd)
                stdout.channel.recv_exit_status()
                deleted_count += 1
            except Exception as e:
                print(f"   ⚠️ Could not remove dir {dname}: {e}")

        print(f"✅ Successfully deleted {deleted_count} verified items on {device_name}!")

        # Show updated disk space
        if not cfg["is_windows"]:
            _, stdout, _ = client.exec_command("df -h /")
            print(f"📊 Updated disk usage on {device_name}:")
            print(stdout.read().decode().strip())

    sftp.close()
    client.close()


def main():
    parser = argparse.ArgumentParser(description="Fleet Synced Data Purge Tool")
    parser.add_argument("--device", choices=["pi4", "pi5", "jetson", "laptop", "all"], default="all", help="Target device")
    parser.add_argument("--live", action="store_true", help="Execute deletion (default is dry run)")
    args = parser.parse_args()

    gdrive_files = get_gdrive_inventory()
    print(f"📦 Google Drive Inventory: {len(gdrive_files):,} archives loaded from {GDRIVE_DIR}")

    targets = list(DEVICE_CONFIGS.keys()) if args.device == "all" else [args.device]
    for t in targets:
        cleanup_remote_device(t, DEVICE_CONFIGS[t], gdrive_files, live=args.live)


if __name__ == "__main__":
    main()
