# Central Coordinator & Google Sheet Setup Guide

This guide explains how to connect your **[UDAYAM extract - Google Sheets](https://docs.google.com/spreadsheets/d/1dwWvxENHxF5Lxz9BLCzwXR_rL09CuD9jU8FvDEAVN-E/edit?gid=104828484#gid=104828484)** to the distributed fleet orchestrator in under 2 minutes.

---

## Step 1: Deploy Google Apps Script Web App

1. Open your Google Sheet: [UDAYAM extract](https://docs.google.com/spreadsheets/d/1dwWvxENHxF5Lxz9BLCzwXR_rL09CuD9jU8FvDEAVN-E/edit?gid=104828484#gid=104828484).
2. In the top menu, click **Extensions** $\to$ **Apps Script**.
3. Replace any existing code in the editor with the entire content of [`orchestrator/Code.gs`](file:///c:/python_works/udayam/orchestrator/Code.gs).
4. *(Optional)* Configure Telegram credentials:
   - At the top of `Code.gs`, enter your `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, or set them under **Project Settings** $\to$ **Script Properties**.
5. In the top right, click **Deploy** $\to$ **New deployment**.
   - **Select type**: Click the gear icon $\to$ **Web app**.
   - **Description**: `Udayam Fleet Coordinator v1`
   - **Execute as**: `Me (your email)`
   - **Who has access**: `Anyone` *(Crucial: allows worker computers to send updates without requiring Google sign-in or API keys)*.
6. Click **Deploy**. Authorize the permissions when prompted.
7. Copy the generated **Web App URL** (looks like `https://script.google.com/macros/s/.../exec`).

---

## Adding the FlawlessTech Data Logo to Your Google Sheet

The official high-resolution logo from [flawlesstechdata.com](https://flawlesstechdata.com/) is:
`https://flawlesstechdata.com/wp-content/uploads/2024/10/FLawless.png`

You can add it in either of two ways:

### Option 1: In-Cell Formula (Instant)
In your Google Sheet, select an empty cell at the top (e.g. cell `N1` or insert a new header row) and enter:
```excel
=IMAGE("https://flawlesstechdata.com/wp-content/uploads/2024/10/FLawless.png", 1)
```
*(Option `1` scales the logo neatly to fit within the cell boundaries)*.

### Option 2: Automated Floating Header (Via Apps Script)
In the Apps Script editor where you pasted `Code.gs`:
1. Select the function dropdown at the top: choose **`addFlawlessLogo`**.
2. Click **Run**.
3. It will automatically place a floating 240×54 px FlawlessTech Data logo over column `J1` / `N1`.

---

## Step 2: Set Up Scheduled Telegram Fleet Reports

To receive consolidated fleet updates every 30 or 60 minutes across all active computers:
1. In the Apps Script editor, click the **Triggers** icon (clock icon on the left sidebar).
2. Click **+ Add Trigger** (bottom right).
3. Set the following:
   - **Choose which function to run**: `sendTelegramFleetReport`
   - **Select event source**: `Time-driven`
   - **Select type of time based trigger**: `Minutes timer` $\to$ `Every 30 minutes` (or `Hour timer` $\to$ `Every hour`).
4. Click **Save**.

---

## Step 3: Sync Existing .7z Archives to Google Sheet

We already scanned all 98 districts in your `results/` folder into `sync_report.csv`.
To push these completed districts into your Google Sheet:

```bash
uv run sync_existing_archives.py --web-app-url "<YOUR_WEB_APP_URL>"
```

The script will instantly match each district row, fill `Last Record`, `Last Recorded Date`, `Total Records Extracted`, `Total Failed Records`, and mark them as `Completed`.

---

## Step 4: Running on Worker Computers

### Option A: 1-Click Desktop GUI
1. On any computer, run `run_worker.bat` (or launch `UdayamScraper.exe`).
2. Paste the **Web App URL** once (or keep it in `.env` as `GOOGLE_APPS_SCRIPT_URL=<YOUR_WEB_APP_URL>`).
3. Set the machine name (auto-detected e.g. `Carbon-X`, `ELCOT-01`, `Dell-PC`).
4. Click **▶ Start Auto-Extract**.
5. The machine will automatically:
   - Claim the next pending district.
   - Resume from the last known record.
   - Stream updates to the Google Sheet every 50 records.
   - Compress the completed district into `.7z` and upload it to Google Drive.
   - Claim the next district in an infinite loop until all work is done.

### Option B: Headless Background CLI
For running quietly in the background on any machine:
```bash
uv run python client/app.py --cli --machine "Dell-PC" --state "TN"
```

---

## Step 5: Custom Udyam List Extractor & CSV Exporter GUI

If you have a specific list of Udyam registration numbers and want to extract all structured details into a clean CSV:

1. Double-click [`run_extractor.bat`](file:///c:/python_works/udayam/run_extractor.bat) (or run `uv run python client/gui/extractor_gui.py`).
2. **Input Numbers**:
   - Paste numbers into the text box (comma, space, or newline separated), OR
   - Click **📂 Load from File** to upload a `.txt` or `.csv` file.
3. **Choose Options**:
   - Select output CSV location (defaults to `udyam_extracted_data.csv`).
   - Check/uncheck *Fetch live from Udyam Portal if not found locally*.
4. Click **▶ Extract & Export to CSV**.
5. Once complete, click **📊 Open Exported CSV** to view the structured results in Excel!
