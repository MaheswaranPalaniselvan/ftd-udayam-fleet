#!/usr/bin/env python3
"""
cleanup_workspace.py
====================
Reclaims ~22.6 GB of disk space in C:\\python_works\\udayam by safely purging:
- 192 MB of loose root scraper logs
- 563 MB of legacy build and dist artifacts
- Temporary HTML / CSV audit dumps
- 8.17 GB of failed scrape dumps
- 13.72 GB of raw local HTML results (already archived in GDrive LZMA2/7z)
"""

import os
import shutil
import time
from pathlib import Path

WORKSPACE = Path(r"C:\python_works\udayam")

ROOT_FILES_TO_DELETE = [
    # Loose historical scraper logs
    "log_scraper_v3_AS_01_to_35.log",
    "log_scraper_v3_KL_02_to_15.log",
    "log_scraper_v3_KL_04_to_15.log",
    "log_scraper_v3_KL_06_to_15.log",
    "log_scraper_v3_TN_31.log",
    "log_scraper_v3_TN_32.log",
    "scraper_v3_KL_02_to_14.log",
    # Temporary test HTML views
    "Demo Data.html",
    "results.html",
    "live_dashboard.html",
    "sample_drilldown_viewer.html",
    "sample_integrated_dashboard.html",
    # Temporary audit / reconciliation CSVs and Excel dumps
    "gdrive_truth_recovered.csv",
    "gdrive_vs_sheet_audit.csv",
    "nationwide_gdrive_truth.csv",
    "results_discrepancies_audit.csv",
    "sync_report.csv",
    "results.csv",
    "results.xlsx",
    "udyam_extracted_data.csv",
    "udyam_web_extracted.csv",
    "live_udayam_extract.xlsx",
    "numbers.txt",
]

DIRS_TO_PURGE_AND_RECREATE = [
    "failed",
    "results",
    "downloaded_html",
    "scratch",
]

DIRS_TO_DELETE = [
    "build",
    "dist",
]


def clean():
    print("=" * 65)
    print(" FlawlessTechData Workspace Deep Cleanup Engine ")
    print("=" * 65)
    t0 = time.time()
    total_reclaimed_bytes = 0

    # 1. Delete individual root files
    print("\n[1/3] Deleting loose root logs and temporary audit files...")
    for fname in ROOT_FILES_TO_DELETE:
        fpath = WORKSPACE / fname
        if fpath.exists():
            try:
                sz = fpath.stat().st_size
                fpath.unlink()
                total_reclaimed_bytes += sz
                print(f"  🗑️ Deleted: {fname} ({sz / (1024*1024):.2f} MB)")
            except Exception as e:
                print(f"  ⚠️ Could not delete {fname}: {e}")

    # 2. Delete legacy build directories
    print("\n[2/3] Removing legacy build and dist directories...")
    for dname in DIRS_TO_DELETE:
        dpath = WORKSPACE / dname
        if dpath.exists():
            try:
                dir_sz = sum(f.stat().st_size for f in dpath.rglob("*") if f.is_file())
                shutil.rmtree(dpath, ignore_errors=True)
                total_reclaimed_bytes += dir_sz
                print(f"  🗑️ Removed folder: {dname}/ ({dir_sz / (1024*1024):.2f} MB)")
            except Exception as e:
                print(f"  ⚠️ Could not remove {dname}: {e}")

    # 3. Purge and recreate heavy dump directories
    print("\n[3/3] Purging heavy scrape dumps (failed/ and results/)...")
    for dname in DIRS_TO_PURGE_AND_RECREATE:
        dpath = WORKSPACE / dname
        if dpath.exists():
            try:
                dir_sz = 0
                for f in dpath.rglob("*"):
                    if f.is_file():
                        try:
                            dir_sz += f.stat().st_size
                        except Exception:
                            pass
                shutil.rmtree(dpath, ignore_errors=True)
                dpath.mkdir(exist_ok=True)
                total_reclaimed_bytes += dir_sz
                print(f"  🗑️ Purged & Recreated: {dname}/ ({dir_sz / (1024*1024):.2f} MB)")
            except Exception as e:
                print(f"  ⚠️ Could not purge {dname}: {e}")

    dt = time.time() - t0
    reclaimed_mb = total_reclaimed_bytes / (1024 * 1024)
    reclaimed_gb = total_reclaimed_bytes / (1024 * 1024 * 1024)
    print("\n" + "=" * 65)
    print(f"Cleanup Complete in {dt:.2f}s!")
    print(f"Total Disk Space Reclaimed: {reclaimed_mb:,.2f} MB ({reclaimed_gb:.2f} GB)")
    print("=" * 65)


if __name__ == "__main__":
    clean()

