"""
FlawlessTech Data - Windows Laptop Direct SSH & Fleet Orchestration Utility
Connects to ELCOT@192.168.0.12 via Paramiko, installs SSH keys for passwordless
access, synchronizes workspace files directly, and manages headless scraper runs.
"""

import os
import sys
import argparse
from pathlib import Path

try:
    import paramiko
except ImportError:
    print("Paramiko not installed. Run via: uv run --with paramiko python scripts/laptop_direct.py")
    sys.exit(1)

LAPTOP_HOST = "192.168.0.12"
LAPTOP_USER = "ELCOT"
LAPTOP_DEFAULT_PASS = "4810"
LAPTOP_PORT = 22
REMOTE_WORK_DIR = "C:/Users/ELCOT/udayam"

WINDOWS_PRIV_KEY = Path.home() / ".ssh" / "id_rsa"
WINDOWS_PUB_KEY = Path.home() / ".ssh" / "id_rsa.pub"


def sftp_mkdir_p(sftp: paramiko.SFTPClient, remote_directory: str):
    """Recursively creates remote directories via SFTP."""
    clean = remote_directory.replace("\\", "/").rstrip("/")
    parts = clean.split("/")
    if len(parts) <= 1:
        return
    current = parts[0]
    for part in parts[1:]:
        if not part:
            continue
        current += "/" + part
        try:
            sftp.stat(current)
        except IOError:
            try:
                sftp.mkdir(current)
            except IOError:
                pass


def sync_files_to_laptop(client: paramiko.SSHClient):
    """Directly synchronizes project files to the laptop via SFTP."""
    sftp = client.open_sftp()
    sftp_mkdir_p(sftp, REMOTE_WORK_DIR)

    # Collect core files needed for running the worker
    sync_list = [
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        ".env",
        "extract_list.py",
        "deploy/setup_machine.ps1",
        "scripts/audit_laptop_extracts.py",
    ]

    for p in Path("client").rglob("*.py"):
        # Skip heavy build/testing dirs
        rel_str = str(p).replace("\\", "/")
        if "build/" in rel_str or "tests/" in rel_str:
            continue
        sync_list.append(rel_str)

    print(f"📦 Synchronizing {len(sync_list)} workspace files to {REMOTE_WORK_DIR}...")
    for rel in sync_list:
        local_f = Path(rel)
        if not local_f.is_file():
            continue

        remote_f = f"{REMOTE_WORK_DIR}/{rel.replace(os.sep, '/')}"
        remote_dir = "/".join(remote_f.split("/")[:-1])
        sftp_mkdir_p(sftp, remote_dir)

        print(f"   -> Uploading {rel} -> {remote_f}")
        sftp.put(str(local_f), remote_f)

    sftp.close()
    print("✅ All files synced successfully!")


def get_ssh_client(password: str = None) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"🔌 Connecting to {LAPTOP_USER}@{LAPTOP_HOST}:{LAPTOP_PORT}...")

    # 1. Try SSH Key first
    if WINDOWS_PRIV_KEY.is_file():
        try:
            client.connect(
                hostname=LAPTOP_HOST,
                port=LAPTOP_PORT,
                username=LAPTOP_USER,
                key_filename=str(WINDOWS_PRIV_KEY),
                timeout=8,
                allow_agent=True,
                look_for_keys=True
            )
            print("✅ Connected successfully using SSH Key!")
            return client
        except Exception:
            pass

    # 2. Fallback to password
    pwd = password or LAPTOP_DEFAULT_PASS
    client.connect(
        hostname=LAPTOP_HOST,
        port=LAPTOP_PORT,
        username=LAPTOP_USER,
        password=pwd,
        timeout=8,
        allow_agent=False,
        look_for_keys=False
    )
    print("✅ Connected successfully using Password!")
    return client


def setup_ssh_keys(client: paramiko.SSHClient):
    """Installs local Windows public key into the laptop's authorized_keys."""
    if not WINDOWS_PUB_KEY.is_file():
        print(f"❌ Public key not found at {WINDOWS_PUB_KEY}")
        return

    with open(WINDOWS_PUB_KEY, "r") as f:
        pub_key_content = f.read().strip()

    print("🔑 Installing SSH public key on Windows laptop...")

    # PowerShell command to configure authorized_keys
    cmd = f"""powershell -Command "
        $userSsh = \\\"$env:USERPROFILE\\.ssh\\\";
        if (-not (Test-Path $userSsh)) {{ New-Item -ItemType Directory -Path $userSsh -Force }};
        Add-Content -Path \\\"$userSsh\\authorized_keys\\\" -Value '{pub_key_content}' -Force;
        
        $adminKeys = \\\"C:\\ProgramData\\ssh\\administrators_authorized_keys\\\";
        if (Test-Path \\\"C:\\ProgramData\\ssh\\\") {{
            Add-Content -Path $adminKeys -Value '{pub_key_content}' -Force;
            icacls $adminKeys /inheritance:r /grant \\\"Administrators:F\\\" /grant \\\"SYSTEM:F\\\" | Out-Null;
        }}
        Write-Output 'KEY_INSTALLED';
    " """

    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()

    if "KEY_INSTALLED" in out:
        print("✅ Passwordless SSH authorized_keys successfully configured!")
    else:
        print(f"⚠️ Setup output: {out}\nErrors: {err}")


def run_remote_command(client: paramiko.SSHClient, command: str, powershell: bool = True):
    """Executes a command on the remote Windows laptop and streams output."""
    if powershell:
        # Wrap safely so cmd.exe doesn't intercept pipes or quotes
        encoded_cmd = command.strip()
        full_cmd = f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{encoded_cmd}"'
    else:
        full_cmd = command

    print(f"\n💻 Executing: {command}")
    stdin, stdout, stderr = client.exec_command(full_cmd)

    for line in iter(stdout.readline, ""):
        print(line, end="")

    err = stderr.read().decode()
    if err.strip():
        print(f"❌ Error: {err.strip()}")


def show_laptop_status(client: paramiko.SSHClient):
    """Fetches and displays complete health and worker telemetry from the laptop."""
    print("📊 Querying laptop health, power, and scraper status...\n")

    # 1. System & Battery Info
    ps_sys = """
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = Get-CimInstance Win32_Processor
    $bat = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
    $procs = Get-Process python -ErrorAction SilentlyContinue

    Write-Host "💻 Machine Name   : $env:COMPUTERNAME ($($os.Caption))" -ForegroundColor Cyan
    Write-Host "⚡ CPU Model      : $($cpu.Name) ($($cpu.NumberOfCores) Cores / $($cpu.NumberOfLogicalProcessors) Threads)" -ForegroundColor Cyan
    
    $freeRamMb = [math]::Round($os.FreePhysicalMemory / 1024, 1)
    $totRamMb = [math]::Round($os.TotalVisibleMemorySize / 1024, 1)
    Write-Host "🧠 RAM Usage      : $($totRamMb - $freeRamMb) MB / $totRamMb MB (Free: $freeRamMb MB)" -ForegroundColor Cyan

    if ($bat) {
        $batStatus = switch ($bat.BatteryStatus) { 1 {'Discharging'} 2 {'AC Connected / Charging'} 3 {'Fully Charged'} Default {'AC Connected'} }
        Write-Host "🔋 Battery Health : $($bat.EstimatedChargeRemaining)% ($batStatus)" -ForegroundColor Green
    } else {
        Write-Host "🔋 Battery        : Desktop / No battery detected" -ForegroundColor Gray
    }

    Write-Host ""
    if ($procs) {
        Write-Host "🏃 Active Python Worker Daemons ($($procs.Count) running):" -ForegroundColor Green
        $procs | Select-Object Id, ProcessName, @{Name="CPU(s)";Expression={[math]::Round($_.CPU, 1)}}, @{Name="RAM(MB)";Expression={[math]::Round($_.WorkingSet64 / 1MB, 1)}} | Format-Table -AutoSize | Out-String | Write-Host
    } else {
        Write-Host "💤 No active scraper processes currently running." -ForegroundColor Yellow
    }
    """
    run_remote_command(client, ps_sys)


def start_detached_daemon(client: paramiko.SSHClient, machine: str, concurrency: int, state: str = "", district: str = ""):
    """Launches the scraper as a detached background process on the remote Windows laptop."""
    extra = []
    if state:
        extra.append(f"--state {state}")
    if district:
        extra.append(f"--district {district}")
    extra_str = " ".join(extra)

    ps_launch = f"Start-Process powershell.exe -WorkingDirectory 'C:\\Users\\ELCOT\\udayam' -WindowStyle Hidden -ArgumentList '-NoProfile -Command uv run python client/app.py --cli --machine {machine} --concurrency {concurrency} --no-auto-update {extra_str}'"

    print(f"🚀 Starting background daemon on laptop: {machine} (Concurrency: {concurrency})...")
    run_remote_command(client, ps_launch)
    print("✅ Background daemon launched detached! It will run continuously even if SSH disconnects.")


def stop_worker_daemon(client: paramiko.SSHClient):
    """Terminates any running python scraper processes on the laptop."""
    ps_kill = """
    $procs = Get-Process python -ErrorAction SilentlyContinue;
    if ($procs) {
        $procs | Stop-Process -Force;
        Write-Host "🛑 Stopped $($procs.Count) Python worker process(es)." -ForegroundColor Red;
    } else {
        Write-Host "ℹ️ No running Python processes found." -ForegroundColor Yellow;
    }
    """
    run_remote_command(client, ps_kill)


def main():
    parser = argparse.ArgumentParser(description="Laptop Direct SSH & Fleet Orchestration")
    parser.add_argument("--status", action="store_true", help="Display laptop health, battery, and worker status")
    parser.add_argument("--setup-keys", action="store_true", help="Install passwordless SSH keys")
    parser.add_argument("--sync", action="store_true", help="Synchronize workspace files to laptop")
    parser.add_argument("--setup-env", action="store_true", help="Run uv sync and install Chromium on laptop")
    parser.add_argument("--daemon", action="store_true", help="Start scraper as an independent background daemon")
    parser.add_argument("--kill", action="store_true", help="Stop running scraper processes on laptop")
    parser.add_argument("--worker", action="store_true", help="Launch foreground fleet worker on laptop")
    parser.add_argument("--machine", type=str, default="Laptop-Ryzen-ELCOT", help="Worker machine identifier")
    parser.add_argument("--concurrency", type=int, default=3, help="Browser scraping concurrency (default: 3)")
    parser.add_argument("--state", type=str, default="", help="Optional preferred state filter (e.g. TN, KL)")
    parser.add_argument("--district", type=str, default="", help="Optional specific district code (e.g. TN-02)")
    parser.add_argument("--cmd", nargs="+", help="Execute custom PowerShell command on laptop")
    args = parser.parse_args()

    try:
        client = get_ssh_client()
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return

    try:
        if args.setup_keys:
            setup_ssh_keys(client)

        if args.sync:
            sync_files_to_laptop(client)

        if args.setup_env:
            run_remote_command(client, f"cd {REMOTE_WORK_DIR}; uv sync; uv run playwright install chromium")

        if args.kill:
            stop_worker_daemon(client)

        if args.daemon:
            start_detached_daemon(client, args.machine, args.concurrency, args.state, args.district)

        if args.worker:
            extra_flags = []
            if args.state:
                extra_flags.append(f"--state {args.state}")
            if args.district:
                extra_flags.append(f"--district {args.district}")
            flags_str = " ".join(extra_flags)

            worker_cmd = (
                f"cd {REMOTE_WORK_DIR}; "
                f"uv run python client/app.py --cli "
                f"--machine \"{args.machine}\" "
                f"--concurrency {args.concurrency} "
                f"--no-auto-update {flags_str}"
            )
            run_remote_command(client, worker_cmd)

        if args.status or (not args.setup_keys and not args.sync and not args.setup_env and not args.daemon and not args.kill and not args.worker and not args.cmd):
            show_laptop_status(client)

        if args.cmd:
            run_remote_command(client, " ".join(args.cmd))

    finally:
        client.close()


if __name__ == "__main__":
    main()

