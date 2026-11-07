"""
Standalone Utility: Rerun Failed and Missing Udyam Records.
Identifies and retries:
1. Failed records from failed_<prefix>.csv (capturing exact failure reasons).
2. Missing sequence gaps (numbers skipped between 1 and max_record_num).
3. Both failed and missing gaps combined.

Usage examples:
  python scripts/rerun_records.py --district AR-01 --inspect-only
  python scripts/rerun_records.py --district AR-01 --type failed
  python scripts/rerun_records.py --district HP-07 --type missing
  python scripts/rerun_records.py --state AR --type all
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from client.core.scraper import get_district_failed_and_missing, execute_district_rerun


def main():
    parser = argparse.ArgumentParser(description="Rerun Failed or Missing Udyam Records")
    parser.add_argument("--district", type=str, default=None, help="Specific district code (e.g. AR-01, TN-02)")
    parser.add_argument("--state", type=str, default=None, help="State code filter to process all districts in state (e.g. AR)")
    parser.add_argument("--all-districts", action="store_true", help="Process all available districts in results/failed")
    parser.add_argument("--type", type=str, choices=["failed", "missing", "all"], default="failed", help="Type of records to rerun (default: failed)")
    parser.add_argument("--concurrency", type=int, default=2, help="Browser concurrency (default: 2)")
    parser.add_argument("--inspect-only", action="store_true", help="Only audit and display failed/missing counts without running extraction")
    parser.add_argument("--no-archive-update", action="store_true", help="Skip updating .7z archives")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()]
    )

    results_dir = Path("results")
    failed_dir = Path("failed")

    # Discover target districts
    target_districts = []
    if args.district:
        target_districts = [args.district.strip().upper()]
    elif args.state:
        st = args.state.strip().upper()
        found = set()
        for p in results_dir.glob(f"{st}-*.7z"):
            found.add(p.stem)
        for p in results_dir.glob(f"{st}-*"):
            if p.is_dir():
                found.add(p.name)
        for p in failed_dir.glob(f"{st}-*"):
            if p.is_dir():
                found.add(p.name)
        target_districts = sorted(list(found))
    elif args.all_districts:
        found = set()
        for p in results_dir.glob("*.7z"):
            found.add(p.stem)
        for p in failed_dir.iterdir():
            if p.is_dir():
                found.add(p.name)
        target_districts = sorted(list(found))
    else:
        print("Please specify --district <CODE>, --state <STATE>, or --all-districts.")
        print("Use --help for more information.")
        sys.exit(1)

    print(f"\n==================================================")
    print(f"UDYAM RECORD RERUN MANAGER")
    print(f"Target Districts: {len(target_districts)} | Mode: {args.type.upper()}")
    print(f"==================================================\n")

    if args.inspect_only:
        print(f"{'District':<12} | {'Extracted':<10} | {'Max Rec':<10} | {'Failed':<8} | {'Gaps':<8} | {'Total Missing':<14} | {'Archive'}")
        print("-" * 80)
        total_failed_all = 0
        total_gaps_all = 0
        total_missing_all = 0
        for code in target_districts:
            audit = get_district_failed_and_missing(code, results_dir, failed_dir)
            total_failed_all += audit["failed_count"]
            total_gaps_all += audit["missing_gaps_count"]
            total_missing_all += audit["all_missing_count"]
            has_arc = "Yes" if audit["has_archive"] else "No"
            print(f"{code:<12} | {audit['total_extracted']:<10} | {audit['max_record_num']:<10} | {audit['failed_count']:<8} | {audit['missing_gaps_count']:<8} | {audit['all_missing_count']:<14} | {has_arc}")
        print("-" * 80)
        print(f"TOTALS: {total_failed_all} failed records | {total_gaps_all} sequence gaps | {total_missing_all} missing from results\n")
        return

    async def run_all():
        total_recovered_fleet = 0
        total_failed_fleet = 0
        all_reasons = {}

        for code in target_districts:
            res = await execute_district_rerun(
                prefix=code,
                rerun_type=args.type,
                concurrency=args.concurrency,
                results_dir=results_dir,
                failed_dir=failed_dir,
                update_archive=not args.no_archive_update
            )
            total_recovered_fleet += res.get("recovered", 0)
            total_failed_fleet += res.get("still_failed", 0)
            for r, cnt in res.get("reasons", {}).items():
                all_reasons[r] = all_reasons.get(r, 0) + cnt

        print("\n==================================================")
        print("RERUN EXECUTION SUMMARY")
        print(f"Total Targeted Districts: {len(target_districts)}")
        print(f"Successfully Recovered:   {total_recovered_fleet:,}")
        print(f"Remaining Unextractable:  {total_failed_fleet:,}")
        print("Captured Failure Reasons Breakdown:")
        for r, cnt in sorted(all_reasons.items(), key=lambda x: x[1], reverse=True):
            print(f"  • {r}: {cnt:,}")
        print("==================================================\n")

    asyncio.run(run_all())


if __name__ == "__main__":
    main()
