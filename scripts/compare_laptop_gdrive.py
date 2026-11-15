import os
import json
from pathlib import Path

gdrive = Path(r"g:\My Drive\Udyam_Archives")
gdrive_files = set(os.listdir(gdrive)) if gdrive.exists() else set()

with open("scripts/laptop_extracts_audit.json") as f:
    audit = json.load(f)

print("=== 1. LAPTOP ARCHIVES vs GDRIVE ===")
for a in audit["archives"]:
    name = a["name"]
    base = name.replace(".7z", "").split(" ")[0].replace("result", "")
    matching = [g for g in gdrive_files if g.startswith(base)]
    print(f"Archive: {name:<15} ({a['size_mb']:>7.2f} MB) -> GDrive matches: {matching}")

print("\n=== 2. LAPTOP FOLDERS vs GDRIVE ===")
for f in audit["folders"]:
    dist = f["district"]
    targets = [dist]
    if dist.startswith("OD-"):
        targets.append(dist.replace("OD-", "OR-"))
    
    matches = []
    for t in targets:
        matches.extend([g for g in gdrive_files if g.startswith(t)])
    
    status = "MISSING IN GDRIVE!" if not matches else f"Found {len(matches)} files in GDrive"
    print(f"Folder {dist:<6} ({f['html_count']:>7,} HTMLs) -> {status} {matches}")

