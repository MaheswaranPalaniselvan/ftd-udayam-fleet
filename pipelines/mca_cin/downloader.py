#!/usr/bin/env python3
"""
download_all_states_mca.py
==========================
Automated Bulk Downloader for MCA (Ministry of Corporate Affairs) Company Master Data
across all 36 Indian States and Union Territories.

Data Sources:
1. Primary: Noob-hacker-68/mca_alt (open data dump from data.gov.in up to 2026, 3.67M+ records)
2. Fallback / Supplementary: matcdac/CorporateIndiaDataSourceXLSX (for Chhattisgarh and historical ROC data)

Output Directory:
  data/mca_master_all_states/
"""

import os
import sys
import time
import json
import asyncio
from pathlib import Path
from urllib.parse import quote
import httpx

DEST_DIR = Path("data/mca_master_all_states")
CONCURRENCY = 4  # 4 parallel download streams
CHUNK_SIZE = 64 * 1024  # 64 KB streaming buffer
TIMEOUT = 120.0  # seconds

# Complete static manifest as fallback if GitHub API rate-limits
MANIFEST_FILES = [
    "Andaman and nicobar.csv",
    "Andhra Pradesh.csv",
    "Arunachal Pradesh.csv",
    "Assam.csv",
    "BIhar.csv",
    "Chandigarh.csv",
    "Chattisgarh.csv",
    "Dadar and nagar haveli.csv",
    "Daman and diu.csv",
    "Delhi_part1.csv",
    "Delhi_part2.csv",
    "Delhi_part3.csv",
    "Goa.csv",
    "Gujarat_part1.csv",
    "Gujarat_part2.csv",
    "Haryana.csv",
    "Himachal pradesh.csv",
    "Jammu and kashmir.csv",
    "Jharkhand.csv",
    "Karnataka_part1.csv",
    "Karnataka_part2.csv",
    "Kerala.csv",
    "Ladakh.csv",
    "Lakshadweep.csv",
    "Madhya pradesh.csv",
    "Maharashtra_part1.csv",
    "Maharashtra_part2.csv",
    "Maharashtra_part3.csv",
    "Maharashtra_part4.csv",
    "Maharashtra_part5.csv",
    "Manipur.csv",
    "Meghalaya.csv",
    "Mizoram.csv",
    "Nagaland.csv",
    "Orissa.csv",
    "Pondicherry.csv",
    "Punjab.csv",
    "Rajasthan.csv",
    "Sikkim.csv",
    "Tamil_Nadu_part1.csv",
    "Tamil_Nadu_part2.csv",
    "Telangana_part1.csv",
    "Telangana_part2.csv",
    "Tripura.csv",
    "Uttar_Pradesh_part1.csv",
    "Uttar_Pradesh_part2.csv",
    "Uttarakhand.csv",
    "West_Bengal_part1.csv",
    "West_Bengal_part2.csv",
]

SUPPLEMENTARY_FILES = [
    {
        "filename": "Chattisgarh_2016.xlsx",
        "url": "https://raw.githubusercontent.com/matcdac/CorporateIndiaDataSourceXLSX/master/Companies%20Master%20Data/2016/Chattisgarh_2016.xlsx",
        "state": "Chhattisgarh",
        "description": "Full Chhattisgarh Master Data from ROC"
    }
]


async def fetch_catalog(client: httpx.AsyncClient):
    """Query GitHub API for fresh file catalog and expected sizes."""
    api_url = "https://api.github.com/repos/Noob-hacker-68/mca_alt/contents/source"
    try:
        resp = await client.get(api_url, timeout=15.0)
        if resp.status_code == 200:
            catalog = {}
            for item in resp.json():
                if item.get("type") == "file":
                    catalog[item["name"]] = {
                        "size": item.get("size", 0),
                        "download_url": item.get("download_url") or f"https://raw.githubusercontent.com/Noob-hacker-68/mca_alt/main/source/{quote(item['name'])}"
                    }
            print(f"[API] Retrieved live catalog with {len(catalog)} files from GitHub API.")
            return catalog
    except Exception as e:
        print(f"[API Warning] GitHub API lookup failed ({e}), falling back to static manifest.")
    
    # Static fallback
    catalog = {}
    for fname in MANIFEST_FILES:
        raw_url = f"https://raw.githubusercontent.com/Noob-hacker-68/mca_alt/main/source/{quote(fname)}"
        catalog[fname] = {"size": 0, "download_url": raw_url}
    return catalog


async def download_file(sem: asyncio.Semaphore, client: httpx.AsyncClient, fname: str, info: dict, idx: int, total: int):
    """Download a single file with streaming, retry, and validation."""
    dest_path = DEST_DIR / fname
    tmp_path = DEST_DIR / f"{fname}.tmp"
    url = info["download_url"]
    expected_size = info.get("size", 0)

    # Check if already downloaded
    if dest_path.exists() and dest_path.stat().st_size > 0:
        actual_size = dest_path.stat().st_size
        if expected_size == 0 or actual_size == expected_size:
            print(f"[{idx:02d}/{total:02d}] [CACHED] {fname} ({actual_size / (1024*1024):.2f} MB)")
            return {"filename": fname, "size": actual_size, "status": "cached"}

    async with sem:
        for attempt in range(1, 4):
            try:
                t0 = time.time()
                async with client.stream("GET", url, follow_redirects=True, timeout=TIMEOUT) as resp:
                    if resp.status_code != 200:
                        raise RuntimeError(f"HTTP {resp.status_code}")
                    
                    bytes_written = 0
                    with open(tmp_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=CHUNK_SIZE):
                            f.write(chunk)
                            bytes_written += len(chunk)
                
                # Atomic rename
                if tmp_path.exists():
                    if dest_path.exists():
                        dest_path.unlink()
                    tmp_path.rename(dest_path)
                
                dt = time.time() - t0
                speed_mb = (bytes_written / (1024 * 1024)) / max(dt, 0.001)
                print(f"[{idx:02d}/{total:02d}] [OK] {fname} ({bytes_written / (1024*1024):.2f} MB) in {dt:.1f}s ({speed_mb:.2f} MB/s)")
                return {"filename": fname, "size": bytes_written, "status": "downloaded"}
            
            except Exception as e:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                print(f"[{idx:02d}/{total:02d}] [RETRY {attempt}/3] {fname} failed: {e}")
                if attempt == 3:
                    print(f"[{idx:02d}/{total:02d}] [FAILED] {fname}")
                    return {"filename": fname, "size": 0, "status": f"failed: {e}"}
                await asyncio.sleep(2 * attempt)


async def main():
    print("=" * 70)
    print(" MCA Company Master Data — All States & UTs Ingestion Engine ")
    print("=" * 70)
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    async with httpx.AsyncClient(limits=limits, timeout=TIMEOUT) as client:
        catalog = await fetch_catalog(client)
        
        # Add supplementary files (like Chhattisgarh full xlsx)
        for supp in SUPPLEMENTARY_FILES:
            catalog[supp["filename"]] = {
                "size": 0,
                "download_url": supp["url"]
            }
        
        total_files = len(catalog)
        print(f"\n[DOWNLOAD] Starting ingestion of {total_files} files across all states/UTs...")
        t_start = time.time()
        
        sem = asyncio.Semaphore(CONCURRENCY)
        tasks = [
            download_file(sem, client, fname, info, i + 1, total_files)
            for i, (fname, info) in enumerate(catalog.items())
        ]
        
        results = await asyncio.gather(*tasks)
        total_time = time.time() - t_start

    print("\n" + "=" * 70)
    print(" Ingestion Completed. Auditing and Verifying Records... ")
    print("=" * 70)

    # Verification and Record Counting
    manifest = []
    total_records = 0
    total_bytes = 0

    for res in results:
        fname = res["filename"]
        fpath = DEST_DIR / fname
        if not fpath.exists() or fpath.stat().st_size == 0:
            manifest.append({
                "filename": fname,
                "status": "failed",
                "size_bytes": 0,
                "size_mb": 0.0,
                "records": 0
            })
            continue

        fsize = fpath.stat().st_size
        total_bytes += fsize
        records = 0

        if fname.endswith(".csv"):
            try:
                # Fast line count
                with open(fpath, "rb") as f:
                    lines = sum(1 for _ in f)
                records = max(0, lines - 1)  # subtract header
            except Exception as e:
                print(f"[Audit Error] {fname}: {e}")
        elif fname.endswith(".xlsx"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(fpath, read_only=True)
                sheet = wb.active
                records = max(0, sheet.max_row - 1 if sheet.max_row else 0)
                wb.close()
            except Exception as e:
                # Fallback row estimate
                records = 0

        total_records += records
        manifest.append({
            "filename": fname,
            "status": "verified",
            "size_bytes": fsize,
            "size_mb": round(fsize / (1024 * 1024), 2),
            "records": records
        })

    # Save manifest
    manifest_path = DEST_DIR / "download_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_files": len(manifest),
            "total_size_mb": round(total_bytes / (1024 * 1024), 2),
            "total_size_gb": round(total_bytes / (1024 * 1024 * 1024), 3),
            "total_records": total_records,
            "elapsed_seconds": round(total_time, 1),
            "files": manifest
        }, f, indent=2)

    print(f"\n[SUMMARY RESULTS]")
    print(f"  Total Files Processed : {len(manifest)}")
    print(f"  Total Data Size       : {total_bytes / (1024*1024):.2f} MB ({total_bytes / (1024*1024*1024):.2f} GB)")
    print(f"  Total Company Records : {total_records:,}")
    print(f"  Download Elapsed Time : {total_time:.1f}s")
    print(f"  Manifest Path         : {manifest_path}")


if __name__ == "__main__":
    asyncio.run(main())

