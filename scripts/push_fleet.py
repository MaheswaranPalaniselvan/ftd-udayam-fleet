#!/usr/bin/env python3
"""
Udayam Fleet Code Synchronizer & Multi-Target Push Tool.
Pushes latest local commits to:
1. Primary Git remote (origin/main)
2. All secondary GitHub accounts in .fleet_accounts.json / fleet_accounts.json
3. Remote Raspberry Pi / Edge workers (via SSH git pull & systemctl restart)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple

EXAMPLE_PATH = Path("fleet_accounts.example.json")


def get_config_path() -> Path:
    for p in (Path(".fleet_accounts.json"), Path("fleet_accounts.json")):
        if p.is_file():
            return p
    return Path(".fleet_accounts.json")


def load_config() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    cfg_file = get_config_path()
    if not cfg_file.is_file():
        return [], []
    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data, []
        elif isinstance(data, dict):
            return data.get("accounts", []), data.get("pi_workers", [])
    except Exception as e:
        print(f"⚠️ Error reading config file '{cfg_file}': {e}")
    return [], []


def push_to_origin(branch: str = "main", dry_run: bool = False) -> bool:
    print(f"\n=======================================================")
    print(f"📦 [1/3] Pushing to Repositories (origin/{branch} and fleet/{branch})")
    print(f"=======================================================")
    if dry_run:
        print(f"   [DRY-RUN] git push origin {branch}")
        print(f"   [DRY-RUN] git push --force fleet {branch}:{branch}")
        return True
    success = True
    try:
        proc = subprocess.run(["git", "push", "origin", branch], capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            print(f"   ✅ Successfully pushed to origin/{branch} (udayam-source)!")
        else:
            print(f"   ❌ git push origin failed:\n{proc.stderr.strip()}")
            success = False
    except Exception as e:
        print(f"   ❌ Error pushing to origin: {e}")
        success = False

    # Check if 'fleet' remote (public repository) exists
    try:
        proc_remotes = subprocess.run(["git", "remote"], capture_output=True, text=True)
        if "fleet" in proc_remotes.stdout.split():
            proc_fleet = subprocess.run(["git", "push", "--force", "fleet", f"{branch}:{branch}"], capture_output=True, text=True, timeout=60)
            if proc_fleet.returncode == 0:
                print(f"   ✅ Successfully pushed to fleet/{branch} (ftd-udayam-fleet)!")
            else:
                print(f"   ⚠️ git push fleet failed:\n{proc_fleet.stderr.strip()}")
    except Exception as e:
        print(f"   ⚠️ Could not push to fleet remote: {e}")

    return success


def push_to_accounts(accounts: List[Dict[str, Any]], branch: str = "main", dry_run: bool = False) -> int:
    print(f"\n=======================================================")
    print(f"🌐 [2/3] Pushing to GitHub Fleet Accounts ({len(accounts)} configured)")
    print(f"=======================================================")
    if not accounts:
        print("   ℹ️ No secondary GitHub accounts configured in .fleet_accounts.json. Skipping.")
        return 0

    success_count = 0
    for idx, acc in enumerate(accounts, start=1):
        user = acc.get("username", "").strip()
        repo = acc.get("repo", "ftd-udayam-fleet").strip()
        token = acc.get("token", "").strip()
        enabled = acc.get("enabled", True)

        if not enabled:
            print(f"   [{idx}/{len(accounts)}] ⏸️ {user}/{repo}: Disabled in config. Skipping.")
            continue

        if not token:
            print(f"   [{idx}/{len(accounts)}] ⚠️ {user}/{repo}: Missing token. Skipping.")
            continue

        auth_url = f"https://x-access-token:{token}@github.com/{user}/{repo}.git"
        print(f"   [{idx}/{len(accounts)}] 🚀 Pushing to {user}/{repo}...")

        if dry_run:
            print(f"      [DRY-RUN] git push https://***@github.com/{user}/{repo}.git {branch}:{branch}")
            success_count += 1
            continue

        try:
            proc = subprocess.run(
                ["git", "push", auth_url, f"{branch}:{branch}"],
                capture_output=True,
                text=True,
                timeout=60
            )
            if proc.returncode == 0:
                print(f"      ✅ Successfully pushed to {user}/{repo}!")
                success_count += 1
            else:
                err = proc.stderr.replace(token, "***").strip()
                print(f"      ❌ Push failed: {err}")
        except Exception as e:
            err = str(e).replace(token, "***")
            print(f"      ❌ Push error: {err}")

    return success_count


def update_pi_workers(workers: List[Dict[str, Any]], branch: str = "main", dry_run: bool = False) -> int:
    print(f"\n=======================================================")
    print(f"🍓 [3/3] Updating Raspberry Pi / Edge Workers")
    print(f"=======================================================")
    if not workers:
        print("   ℹ️ No Pi workers specified for direct SSH update.")
        print("   💡 Note: Pi workers running client/app.py with auto-update enabled will pull new code automatically on their next cycle!")
        return 0

    success_count = 0
    for idx, w in enumerate(workers, start=1):
        host = w.get("host", "").strip()
        user = w.get("user", "pi").strip()
        path = w.get("path", "~/udayam").strip()

        if not host:
            continue

        print(f"   [{idx}/{len(workers)}] 🔄 Connecting to {user}@{host}...")
        ssh_cmd = f"cd {path} && git pull origin {branch} && sudo systemctl restart udyam-worker"

        if dry_run:
            print(f"      [DRY-RUN] ssh {user}@{host} '{ssh_cmd}'")
            success_count += 1
            continue

        try:
            proc = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=accept-new", f"{user}@{host}", ssh_cmd],
                capture_output=True,
                text=True,
                timeout=30
            )
            if proc.returncode == 0:
                print(f"      ✅ Updated and restarted udyam-worker on {host}!")
                success_count += 1
            else:
                print(f"      ⚠️ SSH command failed on {host}: {proc.stderr.strip() or proc.stdout.strip()}")
        except subprocess.TimeoutExpired:
            print(f"      ⚠️ SSH connection timed out for {host}.")
        except Exception as e:
            print(f"      ⚠️ SSH error for {host}: {e}")

    return success_count


def main():
    parser = argparse.ArgumentParser(description="Push code updates across all fleet repositories and workers")
    parser.add_argument("--branch", type=str, default="main", help="Git branch to push (default: main)")
    parser.add_argument("--workers", type=str, default=None, help="Comma-separated Pi worker hosts (e.g. pi5.local,pi4.local)")
    parser.add_argument("--user", type=str, default="pi", help="SSH username for Pi workers (default: pi)")
    parser.add_argument("--path", type=str, default="~/udayam", help="Repository path on Pi workers (default: ~/udayam)")
    parser.add_argument("--origin-only", action="store_true", help="Push only to primary origin repository")
    parser.add_argument("--accounts-only", action="store_true", help="Push only to secondary GitHub accounts")
    parser.add_argument("--workers-only", action="store_true", help="Update only Pi workers via SSH")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without executing git push or SSH")

    args = parser.parse_args()

    # Get current commit hash
    try:
        commit_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        commit_msg = subprocess.check_output(["git", "log", "-1", "--pretty=%s"], text=True).strip()
        print(f"📌 HEAD Commit: {commit_hash} - \"{commit_msg}\"")
    except Exception:
        pass

    accounts, pi_workers = load_config()

    # If --workers passed via CLI, override config
    if args.workers:
        cli_hosts = [h.strip() for h in args.workers.split(",") if h.strip()]
        pi_workers = [{"host": h, "user": args.user, "path": args.path} for h in cli_hosts]

    run_all = not (args.origin_only or args.accounts_only or args.workers_only)

    if run_all or args.origin_only:
        push_to_origin(branch=args.branch, dry_run=args.dry_run)

    if run_all or args.accounts_only:
        push_to_accounts(accounts, branch=args.branch, dry_run=args.dry_run)

    if run_all or args.workers_only:
        update_pi_workers(pi_workers, branch=args.branch, dry_run=args.dry_run)

    print("\n🏁 Fleet Push Complete!")


if __name__ == "__main__":
    main()

