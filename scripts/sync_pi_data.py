#!/usr/bin/env python3
"""
Turnkey Raspberry Pi 5 / Edge Device Data Archiver & Cloud Sync Script.
Scans results/ and failed/ folders, compresses them into archives,
uploads the archives to Google Drive, and syncs status to the Central Google Sheet Coordinator.
"""

import argparse
import base64
import csv
import io
import math
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

DEFAULT_WEB_APP_URL = "https://script.google.com/macros/s/AKfycby3tmgH9PtjUhl6XfGrBfgRNZFQZaSLR0N4Dnff9tt9K5qjatyarJy_nnE0ulCtMNm2xA/exec"
MAX_UPLOAD_CHUNK_BYTES = 22 * 1024 * 1024  # 22 MB per chunk to stay safely below Apps Script 50MB limits


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_district_stats(folder: Path, failed_dir: Path) -> dict:
    prefix = folder.name
    total_extracted = 0
    max_num = -1
    last_record_id = ""
    last_dor = ""

    # 1. Search for results CSV
    csv_candidates = [
        folder / f"results_{prefix}.csv",
        folder / "results.csv",
        folder.parent / f"results_{prefix}.csv",
    ]
    csv_file = None
    for c in csv_candidates:
        if c.is_file():
            csv_file = c
            break

    if csv_file:
        log(f"  📄 Found results CSV: {csv_file.name}")
        try:
            with open(csv_file, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                dor_idx = -1
                if header:
                    for i, col in enumerate(header):
                        c_lower = col.strip().lower()
                        if "date" in c_lower or "dor" in c_lower:
                            dor_idx = i
                            break

                for row in reader:
                    if not row:
                        continue
                    total_extracted += 1
                    num_str = row[0].strip()
                    m = re.search(r"-(\d+)$", num_str)
                    if m:
                        val = int(m.group(1))
                        if val > max_num:
                            max_num = val
                            last_record_id = num_str
                            if dor_idx != -1 and len(row) > dor_idx:
                                raw_dor = row[dor_idx].strip()
                                if raw_dor:
                                    last_dor = raw_dor
        except Exception as e:
            log(f"  ⚠️ Warning reading CSV {csv_file}: {e}")

    # 2. Check HTML files
    html_files = list(folder.glob("*.html"))
    if not html_files:
        html_files = list(folder.glob(f"UDYAM-{prefix}-*.html"))

    if html_files:
        if len(html_files) > total_extracted:
            total_extracted = len(html_files)

        for h in html_files:
            m = re.search(r"-(\d+)\.html$", h.name)
            if m:
                val = int(m.group(1))
                if val > max_num:
                    max_num = val
                    last_record_id = h.stem

        # Extract DOR from latest HTML if missing
        if not last_dor and last_record_id:
            target_html = folder / f"{last_record_id}.html"
            if target_html.is_file():
                try:
                    content = target_html.read_text(encoding="utf-8", errors="replace")
                    m_dor = re.search(r'lblACKNOWLEDGEMENT">([^<]+)<', content)
                    if not m_dor:
                        m_dor = re.search(r'Date of Udyam Registration.*?(\d{1,2}/\d{1,2}/\d{4})', content, re.DOTALL)
                    if m_dor:
                        last_dor = m_dor.group(1).strip()
                except Exception:
                    pass

    # Ensure canonical Udayam format
    if last_record_id and not last_record_id.upper().startswith("UDYAM-"):
        m_num = re.search(r"\d+", last_record_id)
        if m_num:
            seq = int(m_num.group(0))
            last_record_id = f"UDYAM-{prefix.upper()}-{seq:07d}"

    if not last_record_id and max_num > 0:
        last_record_id = f"UDYAM-{prefix.upper()}-{max_num:07d}"

    # 3. Check failed records
    total_failed = 0
    fail_candidates = [
        failed_dir / f"failed_{prefix}" / f"failed_{prefix}.csv",
        failed_dir / prefix / f"failed_{prefix}.csv",
        failed_dir / f"failed_{prefix}.csv",
    ]
    for fc in fail_candidates:
        if fc.is_file():
            try:
                with open(fc, "r", encoding="utf-8", errors="replace") as f:
                    r = csv.reader(f)
                    next(r, None)
                    total_failed = sum(1 for row in r if row)
                log(f"  ❌ Found failure log: {fc.name} ({total_failed} records)")
                break
            except Exception:
                pass

    return {
        "district": prefix,
        "total_extracted": total_extracted,
        "last_record": last_record_id,
        "last_recorded_date": last_dor or time.strftime("%d/%m/%Y"),
        "total_failed": total_failed,
        "html_count": len(html_files)
    }


def create_archive(folder: Path, failed_dir: Path, out_dir: Path) -> Tuple[Path, str]:
    prefix = folder.name
    out_dir.mkdir(parents=True, exist_ok=True)

    has_7z = shutil.which("7z") is not None
    if has_7z:
        archive_path = out_dir / f"{prefix}.7z"
        log(f"  📦 Creating 7z archive: {archive_path.name} (LZMA2 high compression)...")
        # Build 7z command
        cmd = ["7z", "a", "-mx=7", str(archive_path), f"{folder}/*"]
        # Add failed files if any
        for f_path in [failed_dir / f"failed_{prefix}", failed_dir / prefix]:
            if f_path.is_dir():
                cmd.append(f"{f_path}/*")

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and archive_path.is_file():
            return archive_path, "7z"
        log(f"  ⚠️ 7z failed, falling back to built-in zip: {proc.stderr[:100]}")

    # Fallback to Python zipfile
    archive_path = out_dir / f"{prefix}.zip"
    log(f"  📦 Creating zip archive: {archive_path.name}...")
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, _, files in os.walk(folder):
            for file in files:
                full_p = Path(root) / file
                rel_p = full_p.relative_to(folder.parent)
                zf.write(full_p, arcname=str(rel_p))

        # Include failure logs if present
        for f_cand in [failed_dir / f"failed_{prefix}", failed_dir / prefix]:
            if f_cand.is_dir():
                for root, _, files in os.walk(f_cand):
                    for file in files:
                        full_p = Path(root) / file
                        rel_p = full_p.relative_to(failed_dir)
                        zf.write(full_p, arcname=f"failed/{rel_p}")

    return archive_path, "zip"


def upload_file_to_drive(web_app_url: str, file_path: Path, upload_filename: str) -> bool:
    size_bytes = file_path.stat().st_size
    log(f"  ☁️ Uploading {upload_filename} ({size_bytes / (1024*1024):.2f} MB) to Google Drive...")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    base64_data = base64.b64encode(file_bytes).decode("utf-8")
    payload = {
        "action": "upload_archive",
        "filename": upload_filename,
        "data": base64_data
    }

    try:
        resp = httpx.post(web_app_url, json=payload, timeout=120.0, follow_redirects=True)
        if resp.status_code == 200:
            res_json = resp.json()
            if res_json.get("success"):
                log(f"    ✅ Drive Upload OK! File ID: {res_json.get('file_id')}")
                return True
            else:
                log(f"    ❌ Drive error: {res_json.get('message')}")
        else:
            log(f"    ❌ HTTP Error {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        log(f"    ❌ Connection error uploading to Drive: {e}")

    return False


def upload_archive_smart(web_app_url: str, archive_path: Path) -> bool:
    size_bytes = archive_path.stat().st_size
    if size_bytes <= MAX_UPLOAD_CHUNK_BYTES:
        return upload_file_to_drive(web_app_url, archive_path, archive_path.name)

    # File exceeds safe single-request threshold, split into chunks
    num_parts = math.ceil(size_bytes / MAX_UPLOAD_CHUNK_BYTES)
    log(f"  ⚠️ Archive is {size_bytes / (1024*1024):.1f} MB (exceeds single upload threshold). Splitting into {num_parts} parts...")

    success = True
    with open(archive_path, "rb") as f:
        for part_idx in range(1, num_parts + 1):
            chunk_data = f.read(MAX_UPLOAD_CHUNK_BYTES)
            part_name = f"{archive_path.stem}.part{part_idx:02d}{archive_path.suffix}"
            part_tmp = archive_path.parent / f"_tmp_{part_name}"
            part_tmp.write_bytes(chunk_data)

            ok = upload_file_to_drive(web_app_url, part_tmp, part_name)
            try:
                part_tmp.unlink()
            except Exception:
                pass

            if not ok:
                success = False
                break

    return success


def sync_district_to_sheet(web_app_url: str, stats: dict) -> bool:
    log(f"  📊 Updating Google Sheet for {stats['district']}...")
    payload = {
        "action": "bulk_sync_status",
        "districts": {
            stats["district"]: {
                "last_record": stats["last_record"],
                "last_recorded_date": stats["last_recorded_date"],
                "total_extracted": stats["total_extracted"],
                "total_failed": stats["total_failed"]
            }
        }
    }
    try:
        resp = httpx.post(web_app_url, json=payload, timeout=60.0, follow_redirects=True)
        if resp.status_code == 200:
            res_json = resp.json()
            if res_json.get("success"):
                log(f"    ✅ Google Sheet updated successfully: {stats['district']} Marked 'Completed' ({stats['total_extracted']:,} records).")
                return True
        log(f"    ❌ Sheet update returned: {resp.status_code} - {resp.text[:120]}")
    except Exception as e:
        log(f"    ❌ Connection error updating sheet: {e}")

    return False


def main():
    parser = argparse.ArgumentParser(description="Archive Pi 5 scraped data and sync to Google Drive & Sheet.")
    parser.add_argument("--results-dir", type=str, default="results", help="Path to results directory")
    parser.add_argument("--failed-dir", type=str, default="failed", help="Path to failed directory")
    parser.add_argument("--out-dir", type=str, default="archives", help="Output directory for zip/7z archives")
    parser.add_argument("--url", type=str, default=DEFAULT_WEB_APP_URL, help="Google Apps Script Coordinator URL")
    parser.add_argument("--districts", nargs="*", help="Specific district codes to sync (e.g. MN-05 MN-06). Defaults to all found in results/.")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    failed_dir = Path(args.failed_dir)
    out_dir = Path(args.out_dir)

    if not results_dir.exists():
        log(f"❌ Error: Results directory '{results_dir}' not found.")
        sys.exit(1)

    log("=" * 65)
    log("🚀 UDAYAM EDGE SYNC: Archive to Google Drive & Update Master Sheet")
    log("=" * 65)

    # Discover district folders
    candidates = [f for f in sorted(results_dir.iterdir()) if f.is_dir()]
    if args.districts:
        filter_set = {d.upper() for d in args.districts}
        folders_to_process = [f for f in candidates if f.name.upper() in filter_set]
    else:
        folders_to_process = candidates

    if not folders_to_process:
        log("ℹ️ No district subfolders found to archive in results/.")
        sys.exit(0)

    log(f"Found {len(folders_to_process)} district folders: {[f.name for f in folders_to_process]}")
    print()

    summary = []

    for folder in folders_to_process:
        prefix = folder.name
        log(f"▶️ Processing District: {prefix}...")

        # 1. Parse stats
        stats = parse_district_stats(folder, failed_dir)
        log(f"  📈 Stats: Extracted={stats['total_extracted']:,} | Last={stats['last_record']} | DOR={stats['last_recorded_date']} | Failed={stats['total_failed']:,}")

        # 2. Compress
        archive_path, fmt = create_archive(folder, failed_dir, out_dir)
        size_mb = archive_path.stat().st_size / (1024 * 1024)
        log(f"  💾 Archive created: {archive_path.name} ({size_mb:.2f} MB)")

        # 3. Upload to Google Drive
        upload_ok = upload_archive_smart(args.url, archive_path)

        # 4. Update Google Sheet
        sheet_ok = False
        if upload_ok:
            sheet_ok = sync_district_to_sheet(args.url, stats)

        summary.append({
            "district": prefix,
            "extracted": stats["total_extracted"],
            "last_record": stats["last_record"],
            "archive": archive_path.name,
            "size_mb": f"{size_mb:.2f} MB",
            "drive": "✅ Done" if upload_ok else "❌ Failed",
            "sheet": "✅ Done" if sheet_ok else "❌ Failed"
        })
        print()

    log("=" * 65)
    log("🏁 SYNC SUMMARY")
    log("=" * 65)
    for s in summary:
        log(f"District {s['district']:6}: Extracted={s['extracted']:,} | Last={s['last_record']} | Archive={s['archive']} ({s['size_mb']}) | Drive={s['drive']} | Sheet={s['sheet']}")

    log("\n[SUCCESS] Edge archival and synchronization complete!")


if __name__ == "__main__":
    main()
