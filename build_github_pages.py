"""
Build script for GitHub Pages Dashboard.
Downloads the latest state from the master Google Sheet,
converts it into an interactive HTML viewer, and places it in public/index.html.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
import httpx

DEFAULT_GSHEET_EXPORT = "https://docs.google.com/spreadsheets/d/1dwWvxENHxF5Lxz9BLCzwXR_rL09CuD9jU8FvDEAVN-E/export?format=xlsx"


def build_pages(output_dir: Path = Path("public"), gsheet_url: str = None):
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_xlsx = output_dir / "udayam_latest.xlsx"
    target_html = output_dir / "index.html"

    export_url = gsheet_url or os.getenv("GSHEET_EXPORT_URL") or DEFAULT_GSHEET_EXPORT

    print(f"[1/3] Downloading latest live data from Google Sheet...")
    try:
        resp = httpx.get(export_url, follow_redirects=True, timeout=60.0)
        resp.raise_for_status()
        with open(temp_xlsx, "wb") as f:
            f.write(resp.content)
        print(f"      [OK] Downloaded {len(resp.content):,} bytes to {temp_xlsx}")
    except Exception as e:
        print(f"      [WARN] Failed to fetch live Google Sheet: {e}")
        # Fallback to local results.xlsx if present
        local_fallback = Path("results.xlsx")
        if local_fallback.exists():
            print(f"      [INFO] Using local fallback: {local_fallback}")
            shutil.copy2(local_fallback, temp_xlsx)
        else:
            raise RuntimeError("No Google Sheet connection and no local results.xlsx fallback available.")

    print(f"[2/3] Generating interactive HTML viewer...")
    from xlsx_to_html import convert_xlsx_to_html
    convert_xlsx_to_html(xlsx_path=temp_xlsx, html_path=target_html)
    print(f"      [OK] Generated {target_html} ({target_html.stat().st_size:,} bytes)")

    # Copy static assets if they exist
    print(f"[3/3] Copying static assets...")
    assets_src = Path("assets")
    if assets_src.exists():
        assets_dst = output_dir / "assets"
        shutil.copytree(assets_src, assets_dst, dirs_exist_ok=True)
        print(f"      [OK] Copied assets folder to {assets_dst}")

    logo_src = Path("flawless_logo.png")
    if logo_src.exists():
        shutil.copy2(logo_src, output_dir / "flawless_logo.png")
        print(f"      [OK] Copied logo to {output_dir}")

    print(f"\n[SUCCESS] GitHub Pages bundle ready in: {output_dir.resolve()}")


if __name__ == "__main__":
    build_pages()
