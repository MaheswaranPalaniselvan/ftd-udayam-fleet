"""
Audit and inventory all extracted districts, HTML dumps, and 7z archives
located in D:\\udayam_extract\\results on the remote laptop.
"""

import os
import re
import json
from pathlib import Path

BASE_DIR = Path(r"D:\udayam_extract\results")

def audit_results():
    if not BASE_DIR.is_dir():
        print(f"Error: {BASE_DIR} not found.")
        return

    items = sorted(os.listdir(BASE_DIR))
    archives = []
    folders = []

    for item in items:
        p = BASE_DIR / item
        if p.is_file() and p.suffix.lower() == ".7z":
            archives.append({
                "name": item,
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "mtime": str(p.stat().st_mtime)
            })
        elif p.is_dir():
            html_count = 0
            xlsx_files = []
            min_seq = None
            max_seq = None

            try:
                sub_items = os.listdir(p)
            except Exception:
                sub_items = []

            for sub in sub_items:
                if sub.lower().endswith(".html"):
                    html_count += 1
                    m = re.search(r"-(\d{5,7})\.html$", sub, re.IGNORECASE)
                    if m:
                        seq = int(m.group(1))
                        if min_seq is None or seq < min_seq:
                            min_seq = seq
                        if max_seq is None or seq > max_seq:
                            max_seq = seq
                elif sub.lower().endswith(".xlsx"):
                    xlsx_files.append(sub)

            folders.append({
                "district": item,
                "html_count": html_count,
                "xlsx_files": xlsx_files,
                "min_seq": min_seq,
                "max_seq": max_seq
            })

    report = {
        "total_archives": len(archives),
        "archives": archives,
        "total_folders": len(folders),
        "folders": folders
    }

    out_file = Path("C:/Users/ELCOT/udayam/laptop_extracts_audit.json")
    with open(out_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Found {len(archives)} .7z archives and {len(folders)} district folders.")
    print("\n--- ARCHIVES ---")
    for a in archives:
        print(f"  {a['name']:<22} : {a['size_mb']:>8.2f} MB")

    print("\n--- DISTRICT FOLDERS ---")
    for f in folders:
        seq_str = f"#{f['min_seq']} -> #{f['max_seq']}" if f['min_seq'] else "No seq"
        xlsx_str = f" [XLSX: {', '.join(f['xlsx_files'])}]" if f['xlsx_files'] else ""
        print(f"  {f['district']:<8} : {f['html_count']:>7,} HTML files | {seq_str}{xlsx_str}")

if __name__ == "__main__":
    audit_results()

