"""
Distribution Packager for Udayam Extractor.
Creates a clean, portable .zip distribution ready to copy to multiple client/worker machines.
Excludes virtual environments, huge historical logs, git history, and cache directories.
"""

import os
from pathlib import Path
import zipfile
from datetime import datetime


def create_portable_distribution():
    project_root = Path(__file__).parent
    dist_dir = project_root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    zip_path = dist_dir / f"UdayamExtractor_FleetPackage_{timestamp}.zip"

    exclude_dirs = {
        ".git", ".venv", "__pycache__", "build", "dist", "logs", "old",
        "downloaded_html", "results", "failed", "github-pages", ".tempmediaStorage", ".gemini"
    }

    exclude_extensions = {
        ".pyc", ".pyo", ".pyd", ".log", ".tmp"
    }

    # Also skip specific large historical files
    exclude_files = {
        "scraper_v2.exe",
    }

    print(f"Creating portable fleet distribution package: {zip_path.name}...")

    total_files = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_root):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in exclude_dirs]

            for file in files:
                fpath = Path(root) / file
                rel_path = fpath.relative_to(project_root)

                # Check exclusions
                if fpath.suffix.lower() in exclude_extensions:
                    continue
                if file in exclude_files:
                    continue
                if any(part in exclude_dirs for part in rel_path.parts):
                    continue
                # Skip log files
                if file.startswith("log_") or file.endswith(".log"):
                    continue

                zf.write(fpath, arcname=str(rel_path))
                total_files += 1

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[SUCCESS] Packaged {total_files} files into: {zip_path}")
    print(f"          Archive Size: {size_mb:.2f} MB")
    return zip_path


if __name__ == "__main__":
    create_portable_distribution()
