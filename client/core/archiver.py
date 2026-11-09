"""
Archiver and Google Drive Auto-Uploader.
Compresses completed district folders into .7z archives with ultra-compression (-mx=9)
and uploads them to Google Drive via the central coordinator.
"""

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path

from client.core.coordinator import CentralCoordinator


def get_7z_binary() -> str:
    """Finds 7z executable on system PATH or default Windows install directories."""
    for bin_name in ("7z", "7za", "7zr"):
        found = shutil.which(bin_name)
        if found:
            return found

    common_paths = [
        Path(r"C:\Program Files\7-Zip\7z.exe"),
        Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
    ]
    for p in common_paths:
        if p.is_file():
            return str(p)

    raise FileNotFoundError("7-Zip executable not found. Ensure 7-Zip is installed.")


def compress_district_folder(folder_path: Path, delete_source_after: bool = False, mx: int = 9) -> Path | None:
    """
    Compresses a district folder into {prefix}.7z using 7-Zip.
    Returns the path to the created archive or None on failure.
    """
    if not folder_path.is_dir():
        logging.error(f"Cannot compress non-existent folder: {folder_path}")
        return None

    seven_zip_bin = get_7z_binary()
    archive_path = folder_path.with_suffix(".7z")

    cmd = [
        seven_zip_bin,
        "a",
        f"-mx={mx}",
        archive_path.name,
        folder_path.name
    ]

    logging.info(f"Compressing {folder_path.name} -> {archive_path.name} (level -mx={mx})...")
    try:
        subprocess.run(
            cmd,
            cwd=folder_path.parent,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        logging.info(f"[SUCCESS] Created archive: {archive_path}")

        if delete_source_after:
            shutil.rmtree(folder_path)
            logging.info(f"Removed source folder: {folder_path}")

        return archive_path
    except subprocess.CalledProcessError as e:
        logging.error(f"Compression failed for '{folder_path.name}': {e.stderr}")
        return None


async def compress_and_upload_district(
    prefix: str,
    results_dir: Path = Path("results"),
    coordinator: CentralCoordinator = None,
    delete_source_after: bool = False,
    overwrite: bool = False
) -> bool:
    """
    Compresses a completed district and uploads it to Google Drive.
    """
    folder_path = results_dir / prefix
    if not folder_path.is_dir():
        archive_candidate = results_dir / f"{prefix}.7z"
        if archive_candidate.is_file():
            archive_path = archive_candidate
        else:
            logging.warning(f"No results folder or archive found for {prefix}")
            return False
    else:
        archive_path = await asyncio.to_thread(compress_district_folder, folder_path, delete_source_after)

    if not archive_path or not archive_path.is_file():
        return False

    if coordinator:
        logging.info(f"Uploading {archive_path.name} ({archive_path.stat().st_size / (1024*1024):.1f} MB) to Google Drive (overwrite={overwrite})...")
        res = await coordinator.upload_archive_to_drive(archive_path, overwrite=overwrite)
        if res.get("success"):
            logging.info(f"[SUCCESS] Archive uploaded to Google Drive: {res.get('url')}")
            return True
        else:
            logging.error(f"Google Drive upload failed: {res.get('message')}")
            return False

    return True
