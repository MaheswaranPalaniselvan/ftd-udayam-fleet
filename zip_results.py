import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def get_7z_executable() -> str:
    """Finds the available 7z binary on the system PATH."""
    for cmd in ("7z", "7za", "7zr"):
        found = shutil.which(cmd)
        if found:
            return found

    # Common Windows default path check if not in system PATH
    default_win_path = Path(r"C:\Program Files\7-Zip\7z.exe")
    if default_win_path.is_file():
        return str(default_win_path)

    raise FileNotFoundError(
        "Could not find 7-Zip executable. Ensure '7z' is installed and in your PATH."
    )


def compress_subfolders(
    target_dir: Path,
    dry_run: bool = False,
    delete_after: bool = False,
    mx: int = 9,
) -> None:
    if not target_dir.is_dir():
        print(f"Error: '{target_dir}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    try:
        seven_zip_bin = get_7z_executable()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Find all immediate subdirectories
    subfolders = [p for p in target_dir.iterdir() if p.is_dir()]

    if not subfolders:
        print(f"No subdirectories found in '{target_dir}'.")
        return

    processed = 0
    skipped = 0

    for folder in sorted(subfolders):
        archive_path = folder.with_suffix(".7z")

        # Skip if the .7z archive already exists
        if archive_path.exists():
            print(f"[SKIP] Archive already exists: {archive_path.name}")
            skipped += 1
            continue

        # 7z syntax: 7z a -mx=9 "output.7z" "folder_name"
        # Running from parent directory preserves clean root paths inside the archive
        cmd = [
            seven_zip_bin,
            "a",
            f"-mx={mx}",  # Compression level (0=none, 5=normal, 9=ultra)
            archive_path.name,
            folder.name,
        ]

        if dry_run:
            print(f"[DRY RUN] Would create '{archive_path.name}' from '{folder.name}'")
            if delete_after:
                print(f"[DRY RUN] Would delete original folder: '{folder.name}'")
            processed += 1
            continue

        print(f"[COMPRESSING] {folder.name} -> {archive_path.name}...")
        try:
            subprocess.run(
                cmd,
                cwd=target_dir,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            print(f"[SUCCESS] Created {archive_path.name}")
            processed += 1

            if delete_after:
                shutil.rmtree(folder)
                print(f"[DELETED] Removed source folder: {folder.name}")

        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to compress '{folder.name}':\n{e.stderr}", file=sys.stderr)

    print("\n" + "=" * 40)
    mode = "Dry Run Summary" if dry_run else "Execution Summary"
    print(f"{mode}: {processed} queued/processed, {skipped} skipped.")


def main():
    parser = argparse.ArgumentParser(
        description="Compress immediate subdirectories to .7z if not already compressed."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default="./results",
        help="Path to the parent folder containing subdirectories (default: current directory)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show actions that would be taken without creating archives",
    )
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="Delete the original subfolder after successful compression",
    )
    parser.add_argument(
        "-mx",
        type=int,
        default=9,
        choices=range(0, 10),
        metavar="0-9",
        help="Compression level from 0 (store) to 9 (ultra, default)",
    )

    args = parser.parse_args()
    target_path = Path(args.directory).resolve()

    compress_subfolders(
        target_dir=target_path,
        dry_run=args.dry_run,
        delete_after=args.delete_source,
        mx=args.mx,
    )


if __name__ == "__main__":
    main()