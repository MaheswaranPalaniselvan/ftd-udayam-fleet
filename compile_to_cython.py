"""
Automated Cython compilation pipeline.
Compiles proprietary Python modules into native C machine-code binaries (.so on Linux),
then cleans up all original .py source files and intermediate C files.
"""

import os
import shutil
import sys
from pathlib import Path

# Proprietary source files to compile into binary machine code
TARGET_FILES = [
    "client/core/archiver.py",
    "client/core/coordinator.py",
    "client/core/district_manager.py",
    "client/core/gsheet_sync.py",
    "client/core/ocr.py",
    "client/core/parser.py",
    "client/core/scraper.py",
    "xlsx_to_html.py",
    "extract_list.py",
    "scraper.py",
    "sync_existing_archives.py",
]


def compile_modules():
    project_root = Path(__file__).parent.resolve()
    os.chdir(project_root)

    print("==========================================================")
    print("   FlawlessTech Data - Cython Native Machine-Code Builder ")
    print("==========================================================")
    print(f"Working Directory: {project_root}")
    print(f"Target Modules:    {len(TARGET_FILES)} files")
    print()

    # Filter to files that actually exist
    existing_targets = []
    for rel_path in TARGET_FILES:
        p = project_root / rel_path
        if p.exists():
            existing_targets.append(rel_path.replace("\\", "/"))
        else:
            print(f"[WARN] File not found, skipping: {rel_path}")

    if not existing_targets:
        print("[ERROR] No target files found to compile.")
        sys.exit(1)

    print(f"[1/4] Cythonizing {len(existing_targets)} Python modules...")
    from setuptools import setup
    from Cython.Build import cythonize

    # Force inplace build
    sys.argv = [sys.argv[0], "build_ext", "--inplace"]

    ext_modules = cythonize(
        existing_targets,
        compiler_directives={
            "language_level": "3",
            "always_allow_keywords": True,
            "binding": True,
        },
        quiet=False,
    )

    print("\n[2/4] Compiling C source to native shared libraries (.so / .pyd)...")
    setup(ext_modules=ext_modules)

    print("\n[3/4] Verifying compiled binary output...")
    compiled_count = 0
    for rel_path in existing_targets:
        stem = Path(rel_path).stem
        parent_dir = project_root / Path(rel_path).parent

        # Search for .so (Linux) or .pyd (Windows)
        binaries = list(parent_dir.glob(f"{stem}.*.so")) + list(parent_dir.glob(f"{stem}.*.pyd"))
        if binaries:
            for b in binaries:
                print(f"      [OK] Compiled binary: {b.relative_to(project_root)} ({b.stat().st_size:,} bytes)")
                compiled_count += 1
        else:
            print(f"      [WARN] No binary found for {rel_path}")

    print(f"\n[4/4] Stripping original Python source files & intermediate C code...")
    # Delete original .py files that were compiled
    for rel_path in existing_targets:
        p = project_root / rel_path
        if p.exists():
            p.unlink()
            print(f"      [DELETED SOURCE] {rel_path}")

    # Ensure client/core/__init__.py exists (empty) so package imports resolve cleanly
    core_init = project_root / "client" / "core" / "__init__.py"
    if not core_init.exists():
        core_init.touch()
        print("      [CREATED] client/core/__init__.py")

    client_init = project_root / "client" / "__init__.py"
    if not client_init.exists():
        client_init.touch()
        print("      [CREATED] client/__init__.py")

    # Clean intermediate .c and build folders
    for c_file in project_root.rglob("*.c"):
        try:
            c_file.unlink()
        except Exception:
            pass

    build_dir = project_root / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)

    print("\n==========================================================")
    print(f"[SUCCESS] Native C compilation complete! ({compiled_count} binaries created)")
    print("All proprietary Python source files have been removed.")
    print("==========================================================")


if __name__ == "__main__":
    compile_modules()

