# Multi-Machine Setup & Deployment Guide
## FlawlessTech Data - Udayam HTML Extractor & Coverage Dashboard

This guide provides step-by-step instructions for deploying and running the **Udayam Extractor** on multiple machines (client PCs, fleet workers, or office computers).

---

## 🚀 Option 1: One-Click Fleet Setup (Recommended)
This is the fastest, cleanest, and most reliable method for modern Windows machines. It uses an automated bootstrap script that sets up an isolated Python environment and browser automation binaries without requiring manual software installation or admin rights.

### Step 1: Generate the Distribution Package
On your development machine, run:
```powershell
uv run python build_dist_package.py
```
This generates a lightweight zip file (~1.9 MB) in the `dist/` directory:
- `dist/UdayamExtractor_FleetPackage_YYYYMMDD_HHMM.zip`

### Step 2: Transfer to Target Machines
Copy the `.zip` file to target machines using:
- USB Flash Drive
- Google Drive / OneDrive
- Local Network Shared Folder

### Step 3: Extract and Run Setup
On each target Windows machine:
1. Right-click the `.zip` file and select **Extract All...** to a permanent location (e.g., `C:\UdayamExtractor` or `Desktop\UdayamExtractor`).
2. Double-click **`setup_machine.bat`**.
3. The setup script will automatically:
   - Check and download the high-speed `uv` package manager (takes ~3s, no admin rights required).
   - Create an isolated Python environment with all dependencies (`playwright`, `scrapling`, `ddddocr`, `openpyxl`, `httpx`).
   - Download the headless Chromium browser automation binaries.
   - Place a **`Udayam Extractor`** shortcut directly on the user's **Desktop**.
4. Double-click the **Udayam Extractor** desktop shortcut to launch!

---

## 📦 Option 2: Standalone Compiled Executable (PyInstaller)
Use this option if you want to deploy the application without exposing the Python source code to machine operators.

### Step 1: Build the Executable Folder
On your build machine, run:
```powershell
uv run python client/build/build_extractor_gui_exe.py
```
This will compile the Python code, assets, and dependencies into:
- `dist/UdayamExtractor/` containing `UdayamExtractor.exe`.

### Step 2: Install Playwright Browsers on the Target Machine
Because web scrapers use real browser binaries, run this one-time command on target machines:
```powershell
playwright install chromium
```

### Step 3: Launch
Simply double-click `UdayamExtractor.exe` inside `dist/UdayamExtractor/`.

---

## 💿 Option 3: Professional Windows Installer (.exe Setup via Inno Setup)
Use this option if you need a standard Windows setup wizard (`Setup.exe`) that installs to `AppData\Local` or `Program Files`, adds Start Menu entries, and creates an uninstaller in Windows Control Panel.

### Prerequisites:
1. Download and install **[Inno Setup](https://jrsoftware.org/isdl.php)** (free & open source).
2. Build the PyInstaller package using Option 2 above (`dist/UdayamExtractor`).

### Step 1: Compile the Installer
1. Right-click **`installer.iss`** in the project folder and select **Compile**.
   *(Or run via CLI: `"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss`)*
2. Inno Setup will compile everything into a single file:
   - `dist/installer/Udayam_Extractor_Setup_v1.0.exe`

### Step 2: Run Setup on Target Machine
1. Send `Udayam_Extractor_Setup_v1.0.exe` to the target machine.
2. The operator double-clicks the setup file, clicks **Next ➡️ Install ➡️ Finish**.
3. It creates Desktop icons, Start Menu shortcuts, and launches the app.

---

## 🔄 Updating Multiple Machines Later
When you update the code or add new features:
1. Run `uv run python build_dist_package.py` to create a new patch `.zip`.
2. Overwrite the files on the target machines (the existing virtual environment and downloaded browsers remain intact, so updates apply in seconds).

---

## 🍓 Raspberry Pi (ARM64 / aarch64) Deployment Guide
Raspberry Pis (Pi 4 & Pi 5) make cost-effective, low-power (~3-5W), always-on 24/7 worker nodes for scraping fleets.

### ⚠️ Prerequisite: 64-bit OS Required
Playwright and ONNX runtime (`ddddocr`) require a **64-bit operating system**.
Check your Pi's architecture via SSH:
```bash
uname -m
```
* If it outputs `aarch64` or `arm64`: **Supported**.
* If it outputs `armv7l` (32-bit): Flash **Raspberry Pi OS (64-bit)** or **Ubuntu Server (64-bit)** using Raspberry Pi Imager.

---

### Step 1: Copy Project to Raspberry Pi
Transfer the `UdayamExtractor_FleetPackage_*.zip` to your Pi (or clone via git):
```bash
scp dist/UdayamExtractor_FleetPackage_*.zip pi@<pi-ip-address>:~/
```
On the Pi:
```bash
unzip UdayamExtractor_FleetPackage_*.zip -d ~/udayam
cd ~/udayam
```

---

### Step 2: Run 1-Click Automated Pi Setup
Make the setup script executable and run it:
```bash
chmod +x setup_raspberry_pi.sh run_pi_worker.sh
./setup_raspberry_pi.sh
```
The script will automatically:
1. Verify 64-bit ARM architecture.
2. Install required Debian libraries (`libopenblas-dev`, `python3-tk`, `libnss3`, etc.).
3. Install standalone `uv` package manager for ARM64.
4. Synchronize all Python dependencies (`scrapling`, `playwright`, `ddddocr`, `openpyxl`).
5. Install Chromium browser binaries with ARM dependencies.

---

### Step 3: Run Extraction on the Pi

#### Interactive Launcher:
```bash
./run_pi_worker.sh
```
Prompts for:
1. Headless District Incremental (e.g. `TN-02`, 50 records)
2. Fleet Worker Mode (connects to central Google Sheet coordinator)
3. Re-checking failed records
4. Desktop GUI mode (if connected to monitor/VNC)

#### Direct Headless Commands:
* **Incremental District Extraction**:
  ```bash
  uv run python extract_list.py --district TN-02 --incremental --count 50 --concurrency 2 --output results.xlsx
  ```
* **Fleet Worker (claims tasks automatically)**:
  ```bash
  uv run python client/app.py --cli --machine "Pi-$(hostname)" --concurrency 2
  ```

---

### Step 4: Run as a 24/7 Background Service (Systemd)
To ensure the Pi automatically resumes scraping after reboots or power interruptions:
```bash
sudo cp udyam-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable udyam-worker
sudo systemctl start udyam-worker
```
Check live status and logs:
```bash
sudo systemctl status udyam-worker
journalctl -u udyam-worker -f
```
