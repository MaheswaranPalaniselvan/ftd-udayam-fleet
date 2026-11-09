"""
Reset Stale Districts in Google Sheets Coordinator.
Calls the Apps Script Web App endpoint with action=reset_stale_districts
to set all prematurely marked "Completed" districts with stale dates (< 4 days from today)
back to "Outdated" so the fleet can advance them to 2026.
"""

import os
import sys
import httpx

WEB_APP_URL = os.getenv(
    "GOOGLE_APPS_SCRIPT_URL",
    "https://script.google.com/macros/s/AKfycby3tmgH9PtjUhl6XfGrBfgRNZFQZaSLR0N4Dnff9tt9K5qjatyarJy_nnE0ulCtMNm2xA/exec"
)

def reset_stale_districts():
    print("=================================================================")
    print("🔄 RESETTING STALE DISTRICTS IN MASTER GOOGLE SHEET")
    print("=================================================================")
    print(f"Connecting to: {WEB_APP_URL[:60]}...")
    
    try:
        r = httpx.get(f"{WEB_APP_URL}?action=reset_stale_districts", timeout=60.0, follow_redirects=True)
        if r.status_code == 200:
            try:
                data = r.json()
                if data.get("success"):
                    print(f"\n✅ SUCCESS: {data.get('message', 'Reset complete')}")
                    print(f"   Districts reset to Outdated/Pending: {data.get('reset_count')}")
                else:
                    print(f"\n⚠️ Notice from Web App: {data}")
            except Exception:
                print(f"\nResponse (non-JSON): {r.text[:300]}")
        else:
            print(f"\n❌ HTTP Error {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"\n❌ Request failed: {e}")

if __name__ == "__main__":
    reset_stale_districts()
