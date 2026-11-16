"""
FlawlessTech Data - Raspberry Pi 4B Direct SSH & Fleet Orchestrator
Connects to mahesp93@192.168.0.50 via Paramiko, installs SSH keys for passwordless
access, synchronizes workspace files, and manages the scraper daemon.
"""

import os
import sys
import argparse
from pathlib import Path

try:
    import paramiko
except ImportError:
    print("Paramiko not installed. Run via: uv run python scripts/pi4_direct.py")
    sys.exit(1)

PI4_HOST = "192.168.0.50"
PI4_USER = "mahesp93"
PI4_PORT = 22
PI4_DIR = "/home/mahesp93/udayam"
DEFAULT_PASSWORD = "this2shall9@55"

SSH_DIR = Path.home() / ".ssh"


def get_ssh_client(password: str = DEFAULT_PASSWORD) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"🔌 Connecting to {PI4_USER}@{PI4_HOST}:{PI4_PORT}...")

    # Try SSH Keys first
    for key_name in ["id_ed25519", "id_rsa"]:
        priv_key = SSH_DIR / key_name
        if priv_key.is_file():
            try:
                client.connect(
                    hostname=PI4_HOST,
                    port=PI4_PORT,
                    username=PI4_USER,
                    key_filename=str(priv_key),
                    timeout=8,
                    allow_agent=True,
                    look_for_keys=True
                )
                print(f"✅ Connected successfully using SSH Key ({key_name})!")
                return client
            except Exception:
                pass

    if password:
        client.connect(
            hostname=PI4_HOST,
            port=PI4_PORT,
            username=PI4_USER,
            password=password,
            timeout=10,
            allow_agent=False,
            look_for_keys=False
        )
        print("✅ Connected successfully using Password!")
        return client

    raise RuntimeError("Could not connect: SSH Key failed and no password provided.")


def install_public_key(client: paramiko.SSHClient):
    """Installs local SSH public key onto Pi 4B for permanent passwordless access."""
    for key_name in ["id_ed25519.pub", "id_rsa.pub"]:
        pub_key = SSH_DIR / key_name
        if pub_key.is_file():
            pub_key_str = pub_key.read_text().strip()
            cmd = (
                f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys; "
                f"(grep -F '{pub_key_str}' ~/.ssh/authorized_keys 2>/dev/null) || echo '{pub_key_str}' >> ~/.ssh/authorized_keys"
            )
            stdin, stdout, stderr = client.exec_command(cmd)
            stdout.channel.recv_exit_status()
            print(f"🔑 Installed local {key_name} on Pi 4B authorized_keys.")


def sftp_mkdir_p(sftp, remote_dir):
    dirs = remote_dir.strip("/").split("/")
    current = ""
    for d in dirs:
        current += "/" + d
        try:
            sftp.stat(current)
        except IOError:
            try:
                sftp.mkdir(current)
            except IOError:
                pass


def sync_files_to_pi(client: paramiko.SSHClient):
    """SFTP sync core scraper files to Pi 4B."""
    print(f"📦 Synchronizing workspace files to {PI4_HOST}:{PI4_DIR}...")
    sftp = client.open_sftp()
    sftp_mkdir_p(sftp, PI4_DIR)

    files_to_sync = [
        "deploy/setup_raspberry_pi.sh",
        "deploy/run_pi_worker.sh",
        "deploy/setup_pi_daemon.sh",
        "client/app.py",
        "client/core/scraper.py",
        "client/core/coordinator.py",
        "client/core/district_manager.py",
        "client/core/districts_universe.json",
        "client/core/ocr.py",
        "client/core/parser.py",
        "client/core/archiver.py",
        "extract_list.py",
        "zip_results.py",
        "pyproject.toml",
        ".env"
    ]

    for rel_path in files_to_sync:
        local_p = Path(rel_path)
        if not local_p.is_file():
            continue
        remote_p = f"{PI4_DIR}/{rel_path}"
        remote_dir = "/".join(remote_p.split("/")[:-1])
        sftp_mkdir_p(sftp, remote_dir)
        sftp.put(str(local_p), remote_p)

    sftp.close()
    print("✅ Files synced directly via SFTP!")


def run_remote_command(client: paramiko.SSHClient, command: str, sudo_password: str = None) -> int:
    print(f"\n🚀 Running on Pi 4B: {command}")
    print("-" * 65)

    stdin, stdout, stderr = client.exec_command(command, get_pty=True)
    if sudo_password:
        stdin.write(f"{sudo_password}\n")
        stdin.flush()

    for line in iter(stdout.readline, ""):
        print(line, end="")

    exit_status = stdout.channel.recv_exit_status()
    print("-" * 65)
    print(f"🏁 Remote command exited with code {exit_status}\n")
    return exit_status


def show_pi_status(client: paramiko.SSHClient):
    """Displays health, temperature, memory, disk, and scraper daemon status."""
    status_cmd = (
        "echo '=== RASPBERRY PI 4B SYSTEM STATUS ==='; "
        "hostname; "
        "uptime; "
        "vcgencmd measure_temp 2>/dev/null || echo 'Temp: N/A'; "
        "free -h; "
        "df -h /; "
        "echo '--- Running Scraper Processes ---'; "
        "ps aux | grep -E 'python.*client/app' | grep -v grep || echo 'None running'; "
        "echo '--- Recent Scraper Log (Tail 15) ---'; "
        "tail -n 15 /home/mahesp93/udayam/daemon.log 2>/dev/null || tail -n 15 /home/mahesp93/udayam/worker.log 2>/dev/null || echo 'No daemon.log found'"
    )
    run_remote_command(client, status_cmd)


def setup_pi_daemon(client: paramiko.SSHClient, state: str = "AP", district: str = None, concurrency: int = 1):
    """Starts the scraper as an immortal background daemon via nohup and crontab."""
    print(f"⚙️ Starting background scraper daemon on Pi 4B (State: {state}, Concurrency: {concurrency})...")
    
    # Check if virtualenv exists
    check_venv = (
        "cd /home/mahesp93/udayam && "
        "if [ ! -d '.venv' ]; then "
        "  curl -LsSf https://astral.sh/uv/install.sh | sh; "
        "  ~/.local/bin/uv sync; "
        "  ~/.local/bin/uv run patchright install chromium; "
        "fi"
    )
    run_remote_command(client, check_venv)

    dist_flag = f"--district {district}" if district else ""
    state_flag = f"--state {state}" if state and not district else ""

    start_cmd = (
        f"cd {PI4_DIR}; "
        f"pkill -9 -f 'client/app.py' 2>/dev/null || true; "
        f"sleep 1; "
        f"nohup ~/.local/bin/uv run python client/app.py --cli --machine 'Pi4B-mahesp93' --concurrency {concurrency} {state_flag} {dist_flag} --no-auto-update > daemon.log 2>&1 & "
        f"sleep 2; "
        f"echo '✅ Scraper daemon launched in background!'; "
        f"ps aux | grep -E 'python.*client/app' | grep -v grep"
    )
    run_remote_command(client, start_cmd)


def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi 4B Direct SSH & Fleet Orchestrator")
    parser.add_argument("--password", type=str, default=DEFAULT_PASSWORD, help="SSH password")
    parser.add_argument("--status", action="store_true", help="Check Pi 4B health and worker status")
    parser.add_argument("--sync", action="store_true", help="Sync workspace files to Pi 4B")
    parser.add_argument("--daemon", action="store_true", help="Start background scraper daemon")
    parser.add_argument("--state", type=str, default="AP", help="Target state filter (default: AP)")
    parser.add_argument("--district", type=str, default=None, help="Specific target district code")
    parser.add_argument("--concurrency", type=int, default=1, help="Scraper concurrency (default: 1)")
    parser.add_argument("--stop", action="store_true", help="Stop running scraper processes")
    parser.add_argument("--logs", action="store_true", help="Tail scraper daemon.log")
    parser.add_argument("--cmd", nargs=argparse.REMAINDER, help="Execute custom shell command")
    args = parser.parse_args()

    client = get_ssh_client(args.password)
    try:
        install_public_key(client)

        if args.status or (not any([args.sync, args.daemon, args.stop, args.logs, args.cmd])):
            show_pi_status(client)

        if args.sync:
            sync_files_to_pi(client)

        if args.daemon:
            sync_files_to_pi(client)
            setup_pi_daemon(client, state=args.state, district=args.district, concurrency=args.concurrency)

        if args.stop:
            run_remote_command(client, "pkill -9 -f 'client/app.py' 2>/dev/null || true; echo 'Stopped Pi 4B scraper.'")

        if args.logs:
            run_remote_command(client, "tail -n 40 /home/mahesp93/udayam/daemon.log 2>/dev/null || tail -n 40 /home/mahesp93/udayam/worker.log 2>/dev/null")

        if args.cmd:
            run_remote_command(client, " ".join(args.cmd))
    finally:
        client.close()

if __name__ == "__main__":
    main()
