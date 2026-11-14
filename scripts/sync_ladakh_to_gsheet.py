"""
One-off script to sync verified Ladakh (LA-01 & LA-02) numbers to central coordinator / Google Sheet.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from client.core.coordinator import CentralCoordinator

env_path = Path(".env")
if env_path.is_file():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

url = os.getenv("GOOGLE_APPS_SCRIPT_URL", "")
print(f"Connecting to Google Apps Script Coordinator: {url[:45]}...")

async def main():
    coord = CentralCoordinator(url, machine_name="Master-PC")
    
    # 1. Complete LA-01
    print("\nUpdating LA-01 (Kargil)...")
    res1 = await coord.complete_task(
        district_code="LA-01",
        final_record="UDYAM-LA-01-0006826",
        final_dor="12/11/2026",
        total_extracted=6443,
        total_failed=0
    )
    print(f"  [LA-01] Result: {res1} (Status: Live, Total Extracted: 6,443)")
    
    # 2. Complete LA-02
    print("\nUpdating LA-02 (Leh Ladakh)...")
    res2 = await coord.complete_task(
        district_code="LA-02",
        final_record="UDYAM-LA-02-0010120",
        final_dor="09/09/2026",
        total_extracted=9982,
        total_failed=0
    )
    print(f"  [LA-02] Result: {res2} (Status: Completed, Total Extracted: 9,982)")
    
    await coord.close()

if __name__ == "__main__":
    asyncio.run(main())
