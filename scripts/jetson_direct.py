"""
FlawlessTech Data - Jetson Direct SSH & SFTP Sync Utility
Connects to mahesp93@jetson-nano via Paramiko, installs SSH keys for passwordless
access, synchronizes workspace files directly (bypassing git), and runs setup commands.
"""

import os
import sys
import argparse
from pathlib import Path

try:
    import paramiko
except ImportError:
    print("Paramiko not installed. Run via: uv run --with paramiko python scripts/jetson_direct.py")
    sys.exit(1)

JETSON_HOST = "jetson-nano"
JETSON_USER = "mahesp93"
JETSON_PORT = 22
JETSON_DIR = "/home/mahesp93/udayam"

WINDOWS_PRIV_KEY = Path.home() / ".ssh" / "id_rsa"
WINDOWS_PUB_KEY = Path.home() / ".ssh" / "id_rsa.pub"


def get_ssh_client(password: str = None) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"🔌 Connecting to {JETSON_USER}@{JETSON_HOST}:{JETSON_PORT}...")

    # Try SSH Key first
    if WINDOWS_PRIV_KEY.is_file():
        try:
            client.connect(
                hostname=JETSON_HOST,
                port=JETSON_PORT,
                username=JETSON_USER,
                key_filename=str(WINDOWS_PRIV_KEY),
                timeout=10,
                allow_agent=True,
                look_for_keys=True
            )
            print("✅ Connected successfully using SSH Key!")
            return client
        except Exception:
            pass

    if password:
        client.connect(
            hostname=JETSON_HOST,
            port=JETSON_PORT,
            username=JETSON_USER,
            password=password,
            timeout=10,
            allow_agent=False,
            look_for_keys=False
        )
        print("✅ Connected successfully using Password!")
        return client

    raise RuntimeError("Could not connect: SSH Key failed and no password provided.")


def install_public_key(client: paramiko.SSHClient):
    """Installs local SSH key onto Jetson Nano for permanent passwordless access."""
    if not WINDOWS_PUB_KEY.is_file():
        print("⚠️ Windows public key ~/.ssh/id_rsa.pub not found, skipping key install.")
        return
    pub_key_str = WINDOWS_PUB_KEY.read_text().strip()
    cmd = f"""mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qF "{pub_key_str}" ~/.ssh/authorized_keys 2>/dev/null || echo "{pub_key_str}" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"""
    stdin, stdout, stderr = client.exec_command(cmd)
    stdout.channel.recv_exit_status()
    print("🔑 Local SSH public key successfully installed into ~/.ssh/authorized_keys on Jetson Nano!")


def patch_jetson_patchright_cli(client: paramiko.SSHClient):
    """Installs Node 16 shims into patchright driver on Jetson Nano."""
    sftp = client.open_sftp()
    local_cli = Path("deploy/jetson_patchright_cli.js")
    remote_cli = "/home/mahesp93/udayam/.venv/lib/python3.13/site-packages/patchright/driver/package/cli.js"
    if local_cli.is_file():
        try:
            sftp.put(str(local_cli), remote_cli)
            sftp.chmod(remote_cli, 0o755)
            print("✅ Uploaded Node 16 compatible cli.js via SFTP")
        except Exception as e:
            print(f"⚠️ Could not upload cli.js: {e}")
    sftp.close()

    # Lower minimumMajorNodeVersion from 20 to 16 in coreBundle.js
    patch_bundles_cmd = (
        "sed -i 's/minimumMajorNodeVersion = 20/minimumMajorNodeVersion = 16/g' "
        "/home/mahesp93/udayam/.venv/lib/python3.13/site-packages/patchright/driver/package/lib/coreBundle.js "
        "/home/mahesp93/udayam/.venv/lib/python3.13/site-packages/patchright/driver/package/lib/bootstrap.js 2>/dev/null || true"
    )
    client.exec_command(patch_bundles_cmd)
    print("✅ Lowered Node minimumMajorNodeVersion check to 16 in core bundles")


def sync_files_to_jetson(client: paramiko.SSHClient):
    """Syncs modified files directly to ~/udayam on Jetson Nano via SFTP."""
    sftp = client.open_sftp()
    
    files_to_sync = [
        "deploy/setup_jetson_nano.sh",
        "deploy/run_pi_worker.sh",
        "deploy/start_jetson_daemon.sh",
        "client/app.py",
        "client/core/scraper.py",
        "client/core/coordinator.py",
        "extract_list.py",
    ]
    
    print(f"📦 Direct syncing {len(files_to_sync)} files to {JETSON_DIR}...")
    for rel_path in files_to_sync:
        local_p = Path(rel_path)
        if not local_p.is_file():
            continue
        remote_p = f"{JETSON_DIR}/{rel_path.replace(os.sep, '/')}"
        
        # Ensure remote parent directory exists
        remote_parent = "/".join(remote_p.split("/")[:-1])
        try:
            sftp.stat(remote_parent)
        except IOError:
            client.exec_command(f"mkdir -p '{remote_parent}'")
            
        print(f"   -> Uploading {rel_path} -> {remote_p}")
        sftp.put(str(local_p), remote_p)
        # Ensure executable permission for bash scripts
        if rel_path.endswith(".sh"):
            sftp.chmod(remote_p, 0o755)
            
    sftp.close()
    print("✅ Files synced directly via SFTP!")


def run_remote_command(client: paramiko.SSHClient, command: str, sudo_password: str = None):
    # Ensure user's local bin & node are always in PATH for non-login SSH sessions
    env_prefix = 'export PATH="$HOME/.local/bin:$HOME/.local/node-v16/bin:$PATH"; '
    full_cmd = env_prefix + command

    print(f"\n🚀 Running on Jetson Nano: {command}")
    print("---------------------------------------------------------------------")
    if sudo_password:
        full_cmd = f"echo '{sudo_password}' | sudo -S bash -c '{full_cmd}'"
    stdin, stdout, stderr = client.exec_command(full_cmd, get_pty=True)
    
    for line in iter(stdout.readline, ""):
        print(line, end="")
        sys.stdout.flush()
        
    exit_status = stdout.channel.recv_exit_status()
    print("---------------------------------------------------------------------")
    print(f"🏁 Remote command exited with code {exit_status}\n")
    return exit_status


def setup_systemd_daemon(client: paramiko.SSHClient):
    """Starts the scraper as an immortal background daemon (no uv run, auto-restart loop, auto-boot via cron)."""
    print("⚙️ Deploying background scraper daemon on Jetson Nano...")
    setup_cmd = (
        "chmod +x /home/mahesp93/udayam/deploy/start_jetson_daemon.sh; "
        "pkill -9 -f 'uv run' 2>/dev/null || true; "
        "pkill -9 -f 'client/app.py' 2>/dev/null || true; "
        "pkill -9 -f 'start_jetson_daemon.sh' 2>/dev/null || true; "
        "sleep 1; "
        "nohup /home/mahesp93/udayam/deploy/start_jetson_daemon.sh > /dev/null 2>&1 & "
        "sleep 2; "
        "(crontab -l 2>/dev/null | grep -F 'start_jetson_daemon.sh') || "
        "(crontab -l 2>/dev/null; echo '@reboot /home/mahesp93/udayam/deploy/start_jetson_daemon.sh > /dev/null 2>&1 &') | crontab -; "
        "echo '✅ Scraper daemon launched in background! crontab @reboot registered.'; "
        "ps aux | grep -E 'python.*client/app' | grep -v grep || echo 'Checking daemon startup...'"
    )
    run_remote_command(client, setup_cmd)


def stop_jetson_daemon(client: paramiko.SSHClient):
    """Stops the daemon and terminates any running scraper processes."""
    print("🛑 Stopping Jetson Nano scraper...")
    stop_cmd = (
        "pkill -9 -f 'start_jetson_daemon.sh' 2>/dev/null || true; "
        "pkill -9 -f 'client/app.py' 2>/dev/null || true; "
        "pkill -9 -f 'uv run' 2>/dev/null || true; "
        "echo 'Stopped all scraper processes on Jetson Nano.'"
    )
    run_remote_command(client, stop_cmd)


def show_jetson_status(client: paramiko.SSHClient):
    """Displays health, uptime, memory, and scraper daemon status."""
    status_cmd = (
        "echo '=== JETSON NANO STATUS ==='; "
        "uptime; "
        "echo '--- Running Scraper Processes ---'; "
        "ps aux | grep -E 'start_jetson_daemon|python.*client/app' | grep -v grep || echo 'None running'; "
        "echo '--- Recent Daemon Log (Tail 15) ---'; "
        "tail -n 15 /home/mahesp93/udayam/daemon.log 2>/dev/null || echo 'No daemon.log found'"
    )
    run_remote_command(client, status_cmd)


def main():
    parser = argparse.ArgumentParser(description="Direct SSH connection to Jetson Nano")
    parser.add_argument("--password", type=str, default=None, help="Password for mahesp93@jetson-nano")
    parser.add_argument("--daemon", action="store_true", help="Install and start background systemd daemon (no uv run)")
    parser.add_argument("--status", action="store_true", help="Check Jetson worker service status and logs")
    parser.add_argument("--stop", action="store_true", help="Stop Jetson worker daemon")
    parser.add_argument("--logs", action="store_true", help="Tail daemon.log")
    parser.add_argument("--setup", action="store_true", help="Run deploy/setup_jetson_nano.sh")
    parser.add_argument("--cmd", nargs=argparse.REMAINDER, help="Specific command to run on Jetson Nano")
    args = parser.parse_args()

    client = get_ssh_client(args.password)
    try:
        install_public_key(client)
        sync_files_to_jetson(client)
        patch_jetson_patchright_cli(client)
        
        if args.daemon:
            setup_systemd_daemon(client)
        elif args.stop:
            stop_jetson_daemon(client)
        elif args.status:
            show_jetson_status(client)
        elif args.logs:
            run_remote_command(client, "tail -n 30 /home/mahesp93/udayam/daemon.log")
        elif args.setup:
            run_remote_command(client, f"bash {JETSON_DIR}/deploy/setup_jetson_nano.sh", sudo_password=args.password)
        elif args.cmd:
            cmd_str = " ".join(args.cmd) if isinstance(args.cmd, list) else args.cmd
            run_remote_command(client, cmd_str)
        else:
            show_jetson_status(client)
    finally:
        client.close()


if __name__ == "__main__":
    main()

