"""
Silent installer and configuration for TightVNC Server on the Windows laptop.
"""

import sys
import paramiko
from pathlib import Path

LAPTOP_HOST = "192.168.0.12"
LAPTOP_USER = "ELCOT"
PRIV_KEY = Path.home() / ".ssh" / "id_rsa"
VNC_PASS = "4810"

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {LAPTOP_USER}@{LAPTOP_HOST}...")
    client.connect(LAPTOP_HOST, port=22, username=LAPTOP_USER, key_filename=str(PRIV_KEY))

    # 1. Run msiexec
    msi_cmd = (
        'msiexec.exe /i C:\\Users\\ELCOT\\tightvnc-setup.msi /quiet /norestart '
        'ADDLOCAL=Server '
        'SET_USEVNCAUTH=1 VALUE_OF_USEVNCAUTH=1 '
        f'SET_PASSWORD=1 VALUE_OF_PASSWORD={VNC_PASS} '
        f'SET_CONTROLPASSWORD=1 VALUE_OF_CONTROLPASSWORD={VNC_PASS}'
    )
    print(f"1. Running MSI installer:\n   {msi_cmd}...")
    stdin, stdout, stderr = client.exec_command(msi_cmd)
    exit_code = stdout.channel.recv_exit_status()
    print(f"   Installer finished with exit code {exit_code}")

    # 2. Configure firewall & service in PowerShell
    ps_cfg = (
        "powershell -NoProfile -ExecutionPolicy Bypass -Command \""
        "New-NetFirewallRule -Name 'TightVNC-In-TCP-5900' -DisplayName 'TightVNC Server (TCP 5900)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 5900 -Profile Any -ErrorAction SilentlyContinue; "
        "Set-Service -Name tvnserver -StartupType Automatic -ErrorAction SilentlyContinue; "
        "Restart-Service -Name tvnserver -Force -ErrorAction SilentlyContinue; "
        "Start-Sleep -Seconds 2; "
        "Get-Service tvnserver | Select-Object Name, Status, StartType; "
        "Get-NetTCPConnection -LocalPort 5900 -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, State"
        "\""
    )
    print("2. Configuring firewall and starting tvnserver service...")
    stdin, stdout, stderr = client.exec_command(ps_cfg)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    print(out)
    if err:
        print("Errors:", err)

    client.close()

if __name__ == "__main__":
    main()

