#!/usr/bin/env python3
"""
Multi-Account GitHub Actions Fleet Dispatcher.
Launches, monitors, and manages Udayam extraction workers concurrently across
multiple GitHub accounts to maximize parallelism and free runner quotas.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Any
import httpx

CONFIG_PATH = Path(".fleet_accounts.json")
EXAMPLE_PATH = Path("fleet_accounts.example.json")
WORKFLOW_FILE = "udyam_worker.yml"


def create_example_config():
    """Generates an example configuration file if it does not exist."""
    example_content = [
        {
            "username": "YourFirstGitHubAccount",
            "repo": "ftd-udayam-fleet",
            "token": "ghp_YourPersonalAccessToken1",
            "enabled": True,
            "default_workers": 10
        },
        {
            "username": "YourSecondGitHubAccount",
            "repo": "ftd-udayam-fleet",
            "token": "ghp_YourPersonalAccessToken2",
            "enabled": True,
            "default_workers": 10
        }
    ]
    with open(EXAMPLE_PATH, "w", encoding="utf-8") as f:
        json.dump(example_content, f, indent=2)


def get_config_path() -> Path:
    for p in (Path(".fleet_accounts.json"), Path("fleet_accounts.json")):
        if p.is_file():
            return p
    return Path(".fleet_accounts.json")


def load_accounts() -> List[Dict[str, Any]]:
    """Loads accounts from .fleet_accounts.json or fleet_accounts.json."""
    cfg_file = get_config_path()
    if not cfg_file.is_file():
        create_example_config()
        print(f"⚠️ Configuration file not found at '.fleet_accounts.json' or 'fleet_accounts.json'!")
        print(f"📄 Created template at: '{EXAMPLE_PATH.resolve()}'")
        print(f"👉 Copy '{EXAMPLE_PATH}' to '.fleet_accounts.json', add your GitHub accounts and tokens, then rerun.\n")
        sys.exit(1)

    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            accounts = data
        elif isinstance(data, dict):
            accounts = data.get("accounts", [])
        else:
            accounts = []

        if not accounts:
            print(f"❌ '{cfg_file}' must contain a non-empty list of account objects.")
            sys.exit(1)
        return accounts
    except Exception as e:
        print(f"❌ Failed to parse '{cfg_file}': {e}")
        sys.exit(1)


def get_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Udayam-Fleet-Dispatcher"
    }


def verify_account(client: httpx.Client, acc: Dict[str, Any]) -> bool:
    """Tests if token has access to the target repository."""
    user = acc.get("username", "")
    repo = acc.get("repo", "")
    token = acc.get("token", "")

    url = f"https://api.github.com/repos/{user}/{repo}"
    try:
        r = client.get(url, headers=get_headers(token), timeout=15.0)
        if r.status_code == 200:
            return True
        elif r.status_code == 404:
            print(f"   ❌ {user}/{repo}: Repository not found or token lacks 'repo' scope (HTTP 404).")
        elif r.status_code == 401:
            print(f"   ❌ {user}/{repo}: Bad credentials or token expired (HTTP 401).")
        else:
            print(f"   ❌ {user}/{repo}: GitHub API error {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"   ❌ {user}/{repo}: Connection error: {e}")
    return False


def dispatch_fleet(args):
    """Dispatches workflow across all enabled accounts."""
    accounts = load_accounts()
    active_accounts = [a for a in accounts if a.get("enabled", True)]

    if not active_accounts:
        print("⚠️ No enabled accounts found in .fleet_accounts.json.")
        return

    print("=================================================================")
    print("🚀 DISPATCHING UDAYAM FLEET ACROSS MULTIPLE GITHUB ACCOUNTS")
    print("=================================================================")
    print(f"Target Accounts: {len(active_accounts)}")
    print(f"Workers / Account: {args.workers}")
    if args.state:
        print(f"Target State: {args.state.upper()}")
    if args.district:
        print(f"Target District: {args.district.upper()}")
    if args.rerun_type != "none":
        print(f"Rerun Mode: {args.rerun_type.upper()}")
    print("-----------------------------------------------------------------")

    total_dispatched_workers = 0
    successful_accounts = 0

    with httpx.Client(timeout=30.0) as client:
        for idx, acc in enumerate(active_accounts, 1):
            user = acc.get("username", "").strip()
            repo = acc.get("repo", "").strip()
            token = acc.get("token", "").strip()
            workers = str(args.workers or acc.get("default_workers", 10))

            print(f"[{idx}/{len(active_accounts)}] Verifying & dispatching {user}/{repo}...")

            if not verify_account(client, acc):
                print(f"      ⏭️ Skipping {user}/{repo} due to verification failure.\n")
                continue

            dispatch_url = f"https://api.github.com/repos/{user}/{repo}/actions/workflows/{WORKFLOW_FILE}/dispatches"
            payload = {
                "ref": args.ref,
                "inputs": {
                    "workers": workers,
                    "state": args.state or "",
                    "district": args.district or "",
                    "max_districts": str(args.max_districts),
                    "max_duration_minutes": str(args.max_duration_minutes),
                    "rerun_type": args.rerun_type
                }
            }

            try:
                r = client.post(dispatch_url, json=payload, headers=get_headers(token))
                if r.status_code == 204:
                    num_workers = int(workers)
                    total_dispatched_workers += num_workers
                    successful_accounts += 1
                    print(f"      ✅ Successfully dispatched {workers} parallel workers!")
                else:
                    print(f"      ❌ Dispatch failed (HTTP {r.status_code}): {r.text[:200]}")
            except Exception as e:
                print(f"      ❌ Error triggering dispatch: {e}")

            time.sleep(1.0)  # Brief delay between account dispatches

    print("\n=================================================================")
    print("🏁 DISPATCH SUMMARY")
    print("=================================================================")
    print(f"✅ Accounts Activated: {successful_accounts} / {len(active_accounts)}")
    print(f"⚡ Total Active Cloud Workers: {total_dispatched_workers} parallel runners")
    print("📊 Central Coordinator: All workers automatically coordinate via master Google Sheet")
    print("=================================================================")


def show_status(args):
    """Displays active and recent workflow runs across all accounts."""
    accounts = load_accounts()
    active_accounts = [a for a in accounts if a.get("enabled", True)]

    print("=================================================================")
    print("📡 LIVE FLEET STATUS ACROSS ALL GITHUB ACCOUNTS")
    print("=================================================================")

    with httpx.Client(timeout=20.0) as client:
        for acc in active_accounts:
            user = acc.get("username", "").strip()
            repo = acc.get("repo", "").strip()
            token = acc.get("token", "").strip()

            url = f"https://api.github.com/repos/{user}/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?per_page=3"
            print(f"\n🏢 Account: {user}/{repo}")
            try:
                r = client.get(url, headers=get_headers(token))
                if r.status_code == 200:
                    runs = r.json().get("workflow_runs", [])
                    if not runs:
                        print("   (No workflow runs found)")
                    for run in runs:
                        st = run.get("status")
                        conc = run.get("conclusion")
                        r_id = run.get("id")
                        r_url = run.get("html_url")
                        created = run.get("created_at")
                        badge = "🟡" if st in ("queued", "in_progress") else ("🟢" if conc == "success" else "🔴")
                        print(f"   {badge} Run #{r_id} | Status: {st.upper()} | Conclusion: {conc or 'RUNNING'} | Started: {created}")
                        print(f"      🔗 {r_url}")
                else:
                    print(f"   ❌ HTTP {r.status_code}: {r.text[:120]}")
            except Exception as e:
                print(f"   ❌ Could not fetch status: {e}")
    print("\n=================================================================")


def cancel_fleet(args):
    """Cancels running workflow runs across all configured accounts."""
    accounts = load_accounts()
    active_accounts = [a for a in accounts if a.get("enabled", True)]

    print("=================================================================")
    print("🛑 CANCELLING ACTIVE FLEET RUNS ACROSS ALL ACCOUNTS")
    print("=================================================================")

    cancelled_count = 0
    with httpx.Client(timeout=20.0) as client:
        for acc in active_accounts:
            user = acc.get("username", "").strip()
            repo = acc.get("repo", "").strip()
            token = acc.get("token", "").strip()

            url = f"https://api.github.com/repos/{user}/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?status=in_progress"
            try:
                r = client.get(url, headers=get_headers(token))
                if r.status_code == 200:
                    runs = r.json().get("workflow_runs", [])
                    for run in runs:
                        r_id = run.get("id")
                        c_url = f"https://api.github.com/repos/{user}/{repo}/actions/runs/{r_id}/cancel"
                        cr = client.post(c_url, headers=get_headers(token))
                        if cr.status_code in (202, 200):
                            print(f"   ✅ Cancelled Run #{r_id} on {user}/{repo}")
                            cancelled_count += 1
                        else:
                            print(f"   ⚠️ Could not cancel Run #{r_id}: HTTP {cr.status_code}")
                # Also check queued
                url_q = f"https://api.github.com/repos/{user}/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?status=queued"
                rq = client.get(url_q, headers=get_headers(token))
                if rq.status_code == 200:
                    runs_q = rq.json().get("workflow_runs", [])
                    for run in runs_q:
                        r_id = run.get("id")
                        c_url = f"https://api.github.com/repos/{user}/{repo}/actions/runs/{r_id}/cancel"
                        client.post(c_url, headers=get_headers(token))
                        print(f"   ✅ Cancelled Queued Run #{r_id} on {user}/{repo}")
                        cancelled_count += 1
            except Exception as e:
                print(f"   ❌ Error checking {user}/{repo}: {e}")

    print(f"\n🏁 Finished: Cancelled {cancelled_count} active run(s).")


def init_interactive():
    """Interactive CLI to configure account credentials."""
    print("=================================================================")
    print("⚙️ CONFIGURE GITHUB FLEET ACCOUNTS")
    print("=================================================================")
    print("Enter credentials for each GitHub account.")
    print("Tokens require 'repo' or 'workflow' scope from GitHub Settings -> Developer settings -> Personal access tokens.\n")

    accounts = []
    if CONFIG_PATH.is_file():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                accounts = json.load(f)
            print(f"Found {len(accounts)} existing accounts in {CONFIG_PATH}.\n")
        except Exception:
            pass

    while True:
        user = input("GitHub Username (or press Enter to finish): ").strip()
        if not user:
            break
        repo = input(f"Repository name for {user} (default 'ftd-udayam-fleet'): ").strip() or "ftd-udayam-fleet"
        token = input(f"Personal Access Token for {user}: ").strip()
        workers = input("Default parallel workers for this account [1-10] (default 10): ").strip() or "10"

        accounts.append({
            "username": user,
            "repo": repo,
            "token": token,
            "enabled": True,
            "default_workers": int(workers)
        })
        print(f"✅ Added {user}/{repo}!\n")

    if accounts:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)
        print(f"🎉 Saved {len(accounts)} accounts to '{CONFIG_PATH}'.")
    else:
        print("No accounts added.")


def main():
    parser = argparse.ArgumentParser(description="Multi-Account GitHub Actions Fleet Dispatcher")
    parser.add_argument("--launch", action="store_true", help="Launch fleet workflow across all accounts")
    parser.add_argument("--status", action="store_true", help="View recent workflow run statuses across accounts")
    parser.add_argument("--cancel", action="store_true", help="Cancel active workflow runs across accounts")
    parser.add_argument("--init", action="store_true", help="Interactively add accounts to .fleet_accounts.json")
    parser.add_argument("--push", action="store_true", help="Push latest code to origin and all fleet accounts")
    parser.add_argument("--push-and-launch", action="store_true", help="Push code to all accounts and immediately launch workflows")

    # Workflow parameters
    parser.add_argument("--workers", type=str, default="10", choices=["2", "3", "5", "8", "10"], help="Parallel workers per account (default 10)")
    parser.add_argument("--state", type=str, default="", help="Filter by state code (e.g. TN, KL - leave blank for all)")
    parser.add_argument("--district", type=str, default="", help="Specific district code (leave blank for auto)")
    parser.add_argument("--max-districts", type=int, default=1, help="Max districts per worker (default 1)")
    parser.add_argument("--max-duration-minutes", type=int, default=120, help="Max worker run duration in minutes")
    parser.add_argument("--rerun-type", type=str, choices=["none", "failed", "missing", "all"], default="none", help="Rerun mode")
    parser.add_argument("--ref", type=str, default="main", help="Git branch ref (default main)")

    args = parser.parse_args()

    if args.push or args.push_and_launch:
        from scripts.push_fleet import push_to_origin, push_to_accounts, load_config
        accounts, _ = load_config()
        push_to_origin(branch=args.ref)
        push_to_accounts(accounts, branch=args.ref)
        if args.push and not args.push_and_launch:
            return

    if args.init:
        init_interactive()
    elif args.status:
        show_status(args)
    elif args.cancel:
        cancel_fleet(args)
    else:
        # Default action is launch
        dispatch_fleet(args)


if __name__ == "__main__":
    main()
