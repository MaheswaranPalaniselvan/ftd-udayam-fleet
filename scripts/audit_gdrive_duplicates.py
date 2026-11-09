#!/usr/bin/env python3
"""
Audit Google Drive duplicates.
1. Checks local logs and manifests for duplicate uploads.
2. Provides remote check via Apps Script Web App (action=audit_duplicates).
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import httpx

WEB_APP_URL = "https://script.google.com/macros/s/AKfycby3tmgH9PtjUhl6XfGrBfgRNZFQZaSLR0N4Dnff9tt9K5qjatyarJy_nnE0ulCtMNm2xA/exec"


def audit_local_logs():
    print("=" * 65)
    print("🔍 AUDITING LOCAL LOGS & UPLOAD MANIFESTS FOR DUPLICATES")
    print("=" * 65)

    upload_records = defaultdict(list)

    # 1. Check .gdrive_uploads.json
    manifest_p = Path(".gdrive_uploads.json")
    if manifest_p.is_file():
        try:
            m_data = json.loads(manifest_p.read_text(encoding="utf-8"))
            for name, meta in m_data.items():
                upload_records[name].append({
                    "source": ".gdrive_uploads.json",
                    "file_id": meta.get("file_id"),
                    "size": meta.get("size_bytes")
                })
        except Exception as e:
            print(f"Error reading manifest: {e}")

    # 2. Check task logs
    task_dir = Path(r"C:\Users\Maheswaran\.gemini\antigravity\brain\2d58d7f2-1789-4fa3-87f6-5514fcd8fb19\.system_generated\tasks")
    log_files = list(Path(".").glob("*.log")) + list(Path("logs").glob("*.log"))
    if task_dir.is_dir():
        log_files += list(task_dir.glob("*.log"))

    for lf in log_files:
        try:
            text = lf.read_text(encoding="utf-8", errors="replace")
            # Find upload statements
            matches = re.findall(r"Uploading\s+([A-Za-z0-9_\-\.]+)\s+\(([0-9\.]+)\s+MB\).*?File ID:\s+([A-Za-z0-9_\-]+)", text, re.DOTALL)
            for name, mb, fid in matches:
                # Avoid adding identical log entries from same source
                if not any(x["file_id"] == fid and x["source"] == lf.name for x in upload_records[name]):
                    upload_records[name].append({
                        "source": lf.name,
                        "file_id": fid,
                        "size": f"{mb} MB"
                    })
        except Exception:
            pass

    print(f"Total distinct uploaded filenames tracked: {len(upload_records)}")

    # Check duplicates by filename with different file IDs (i.e. uploaded multiple times to Drive!)
    duplicate_uploads = {}
    for name, events in upload_records.items():
        distinct_fids = set(ev["file_id"] for ev in events if ev["file_id"])
        if len(distinct_fids) > 1:
            duplicate_uploads[name] = events

    if duplicate_uploads:
        print(f"\n⚠️ WARNING: Found {len(duplicate_uploads)} file(s) uploaded multiple times with different Drive File IDs:")
        for name, events in duplicate_uploads.items():
            print(f"  - {name}:")
            for ev in events:
                print(f"      File ID: {ev['file_id']} (from {ev['source']})")
    else:
        print("\n✅ Clean: No files were uploaded with multiple distinct Drive File IDs in local logs!")

    return duplicate_uploads


def check_remote_gdrive():
    print("\n" + "=" * 65)
    print("☁️ CHECKING REMOTE GOOGLE DRIVE ENDPOINT (Apps Script)")
    print("=" * 65)

    try:
        resp = httpx.get(f"{WEB_APP_URL}?action=audit_duplicates", timeout=30.0, follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("error"):
                print(f"ℹ️ Remote Web App response: {data.get('error')}")
                print("   (The Apps Script requires a 1-click update in the Apps Script Editor to enable direct Drive duplicate scanning).")
                return None
            else:
                print(f"✅ Remote Drive Audit Success:")
                print(f"   Total Files in Drive:     {data.get('total_files')}")
                print(f"   Unique Filenames:         {data.get('unique_filenames')}")
                print(f"   Duplicate Filenames:      {data.get('duplicate_count')}")
                dups = data.get("duplicates", {})
                if dups:
                    print("\nDuplicates found in Google Drive:")
                    for fname, flist in dups.items():
                        print(f"  - {fname}: {len(flist)} copies")
                        for f in flist:
                            print(f"      ID: {f['id']} | Size: {f.get('size', 0)} bytes | Created: {f.get('dateCreated')}")
                else:
                    print("   🎉 Zero duplicate files found in Google Drive!")
                return data
        else:
            print(f"Remote check returned HTTP {resp.status_code}")
    except Exception as e:
        print(f"Could not connect to remote Web App: {e}")
    return None


if __name__ == "__main__":
    audit_local_logs()
    check_remote_gdrive()
