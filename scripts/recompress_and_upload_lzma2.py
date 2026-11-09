#!/usr/bin/env python3
"""
Audit archives in results/ for LZMA2 compression.
If any archive is not compressed with LZMA2, extracts and recompresses it
with LZMA2 (-m0=lzma2 -mx=7 -mmt=on) and uploads it to Google Drive.
"""

import argparse
import base64
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

DEFAULT_WEB_APP_URL = os.getenv(
    "GOOGLE_APPS_SCRIPT_URL",
    "https://script.google.com/macros/s/AKfycby3tmgH9PtjUhl6XfGrBfgRNZFQZaSLR0N4Dnff9tt9K5qjatyarJy_nnE0ulCtMNm2xA/exec"
)
MAX_UPLOAD_CHUNK_BYTES = 22 * 1024 * 1024  # 22 MB per chunk

def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_7z_binary() -> str:
    for candidate in [
        shutil.which("7z"),
        shutil.which("7za"),
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise FileNotFoundError("7-Zip executable not found.")


def check_archive_method(seven_zip: str, archive_path: Path) -> str:
    """Returns the compression Method reported in the 7z archive header."""
    proc = subprocess.run(
        [seven_zip, "l", "-slt", str(archive_path)],
        capture_output=True,
        text=True,
        errors="replace"
    )
    header = proc.stdout.split("----------")[0]
    m = re.search(r"^Method\s*=\s*(.+)$", header, re.MULTILINE)
    return m.group(1).strip() if m else "Unknown"


def recompress_to_lzma2(seven_zip: str, archive_path: Path, work_dir: Path) -> Path:
    """Extracts an archive and recompresses it using LZMA2."""
    stem = archive_path.stem
    temp_extract = work_dir / f"_extract_{stem}"
    if temp_extract.exists():
        shutil.rmtree(temp_extract, ignore_errors=True)
    temp_extract.mkdir(parents=True, exist_ok=True)

    log(f"  📂 Extracting {archive_path.name}...")
    subprocess.run(
        [seven_zip, "x", str(archive_path.resolve()), f"-o{temp_extract.resolve()}", "-y"],
        check=True,
        capture_output=True
    )

    # Check extracted content
    top_items = [item.name for item in temp_extract.iterdir()]
    if not top_items:
        raise RuntimeError(f"Extraction of {archive_path.name} produced empty directory.")

    new_archive = work_dir / f"{stem}_lzma2.7z"
    if new_archive.exists():
        new_archive.unlink()

    log(f"  ⚡ Recompressing with LZMA2 (-m0=lzma2 -mx=7 -mmt=on)...")
    cmd = [seven_zip, "a", "-t7z", "-m0=lzma2", "-mx=7", "-mmt=on", str(new_archive.resolve())] + top_items
    subprocess.run(cmd, cwd=str(temp_extract), check=True, capture_output=True)

    # Test integrity
    log(f"  🔍 Testing integrity of new LZMA2 archive...")
    test_proc = subprocess.run([seven_zip, "t", str(new_archive)], capture_output=True, text=True)
    if test_proc.returncode != 0:
        raise RuntimeError(f"Integrity test failed for {new_archive.name}: {test_proc.stderr}")

    # Verify method
    new_method = check_archive_method(seven_zip, new_archive)
    log(f"  ✅ Verified new compression method: {new_method}")
    if not new_method.upper().startswith("LZMA2"):
        raise RuntimeError(f"Recompression did not result in LZMA2 (got {new_method})")

    # Clean up extracted temp files
    shutil.rmtree(temp_extract, ignore_errors=True)
    return new_archive


def upload_chunk_to_drive(web_app_url: str, file_path: Path, upload_filename: str) -> bool:
    size_mb = file_path.stat().st_size / (1024 * 1024)
    log(f"    ☁️ Uploading {upload_filename} ({size_mb:.2f} MB) to Google Drive...")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    base64_data = base64.b64encode(file_bytes).decode("utf-8")
    payload = {
        "action": "upload_archive",
        "filename": upload_filename,
        "data": base64_data
    }

    try:
        resp = httpx.post(web_app_url, json=payload, timeout=180.0, follow_redirects=True)
        if resp.status_code == 200:
            res_json = resp.json()
            if res_json.get("success"):
                log(f"      ✅ Drive Upload OK! File ID: {res_json.get('file_id')}")
                return True
            else:
                log(f"      ❌ Drive error: {res_json.get('message')}")
        else:
            log(f"      ❌ HTTP {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        log(f"      ❌ Connection error: {e}")

    return False


def upload_archive_smart(web_app_url: str, archive_path: Path) -> bool:
    size_bytes = archive_path.stat().st_size
    if size_bytes <= MAX_UPLOAD_CHUNK_BYTES:
        return upload_chunk_to_drive(web_app_url, archive_path, archive_path.name)

    num_parts = math.ceil(size_bytes / MAX_UPLOAD_CHUNK_BYTES)
    log(f"    ⚠️ Archive is {size_bytes / (1024*1024):.1f} MB (exceeds single upload threshold). Splitting into {num_parts} parts...")

    success = True
    with open(archive_path, "rb") as f:
        for part_idx in range(1, num_parts + 1):
            chunk_data = f.read(MAX_UPLOAD_CHUNK_BYTES)
            part_name = f"{archive_path.stem}.part{part_idx:02d}{archive_path.suffix}"
            part_tmp = archive_path.parent / f"_tmp_{part_name}"
            part_tmp.write_bytes(chunk_data)

            ok = upload_chunk_to_drive(web_app_url, part_tmp, part_name)
            try:
                part_tmp.unlink()
            except Exception:
                pass

            if not ok:
                success = False
                break

    return success


def main():
    parser = argparse.ArgumentParser(description="Check archives for LZMA2 compression, recompress if needed, and upload to Google Drive.")
    parser.add_argument("--results-dir", type=str, default="results", help="Directory containing .7z archives")
    parser.add_argument("--url", type=str, default=DEFAULT_WEB_APP_URL, help="Google Apps Script Coordinator URL")
    parser.add_argument("--dry-run", action="store_true", help="Audit only without recompressing or uploading")
    parser.add_argument("--only", nargs="*", help="Process only specific district archives (e.g. PY-04 DD-02)")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    seven_zip = get_7z_binary()
    log(f"Using 7-Zip binary: {seven_zip}")

    archives = sorted(results_dir.glob("*.7z"))
    if args.only:
        filter_set = {f"{item.upper()}.7Z" if not item.upper().endswith(".7Z") else item.upper() for item in args.only}
        archives = [a for a in archives if a.name.upper() in filter_set]

    log(f"Auditing {len(archives)} archive(s) in '{results_dir}' for LZMA2 compression...")

    lzma2_list = []
    non_lzma2_list = []

    for a in archives:
        method = check_archive_method(seven_zip, a)
        if method.upper().startswith("LZMA2"):
            lzma2_list.append((a, method))
        else:
            non_lzma2_list.append((a, method))

    log("=" * 65)
    log(f"📊 COMPRESSION AUDIT SUMMARY")
    log("=" * 65)
    log(f"  Total Archives Audited:      {len(archives)}")
    log(f"  LZMA2 Compressed:            {len(lzma2_list)}")
    log(f"  Non-LZMA2 Compressed:        {len(non_lzma2_list)}")
    log("=" * 65)

    if non_lzma2_list:
        log("Non-LZMA2 Archives to be Recompressed:")
        # Sort by file size ascending so smaller ones finish first
        non_lzma2_list.sort(key=lambda x: x[0].stat().st_size)
        for a, m in non_lzma2_list:
            size_mb = a.stat().st_size / (1024 * 1024)
            log(f"  - {a.name:<12} ({size_mb:>6.2f} MB) -> Current Method: {m}")
    else:
        log("🎉 All archives in results/ are already compressed with LZMA2!")
        return

    if args.dry_run:
        log("\n[DRY RUN] Exiting without making changes.")
        return

    # Processing Non-LZMA2 archives
    work_dir = Path("_recompress_work")
    work_dir.mkdir(exist_ok=True)
    backup_dir = results_dir / "backup_non_lzma2"
    backup_dir.mkdir(exist_ok=True)

    summary = []

    for a, old_method in non_lzma2_list:
        old_size_mb = a.stat().st_size / (1024 * 1024)
        log("\n" + "-" * 60)
        log(f"▶️ Processing: {a.name} ({old_size_mb:.2f} MB | {old_method})")

        try:
            # 1. Recompress
            new_archive = recompress_to_lzma2(seven_zip, a, work_dir)
            new_size_mb = new_archive.stat().st_size / (1024 * 1024)
            log(f"  💾 New archive size: {new_size_mb:.2f} MB (Change: {new_size_mb - old_size_mb:+.2f} MB)")

            # 2. Backup original and replace with LZMA2 archive
            backup_path = backup_dir / a.name
            shutil.copy2(a, backup_path)
            shutil.move(str(new_archive), str(a))
            log(f"  📦 Replaced {a.name} in results/ (Original backed up to {backup_path.name})")

            # 3. Upload to Google Drive
            log(f"  🚀 Uploading LZMA2 archive {a.name} to Google Drive...")
            upload_ok = upload_archive_smart(args.url, a)

            summary.append({
                "archive": a.name,
                "old_size": f"{old_size_mb:.2f} MB",
                "new_size": f"{new_size_mb:.2f} MB",
                "status": "Success" if upload_ok else "Recompressed, Upload Failed",
                "drive": "✅ Done" if upload_ok else "❌ Failed"
            })
        except Exception as e:
            log(f"  ❌ Error processing {a.name}: {e}")
            summary.append({
                "archive": a.name,
                "old_size": f"{old_size_mb:.2f} MB",
                "new_size": "N/A",
                "status": f"Failed: {e}",
                "drive": "❌ Skipped"
            })

    # Clean up work dir
    shutil.rmtree(work_dir, ignore_errors=True)

    log("\n" + "=" * 65)
    log("🏁 FINAL RECOMPRESSION & UPLOAD SUMMARY")
    log("=" * 65)
    for s in summary:
        log(f"  {s['archive']:<12} | Old: {s['old_size']:<9} | New: {s['new_size']:<9} | Drive: {s['drive']}")
    log("=" * 65)


if __name__ == "__main__":
    main()
