/**
 * Udyam Distributed Extraction Coordinator - Google Apps Script
 * Attached directly to [UDAYAM extract - Google Sheets]
 * 
 * Features:
 * - Atomic district task leasing (LockService) so multiple computers never duplicate work.
 * - Live progress tracking & cell updates (Last Record, Date, Extracted, Failed).
 * - Consolidated fleet Telegram reports every 30/60 minutes & offline alerts.
 * - Automated Google Drive archive upload ingestion.
 * - Bulk sync endpoint for existing .7z archives.
 */

// CONFIGURATION: Set your Telegram Bot credentials here or via Script Properties
const TELEGRAM_BOT_TOKEN = PropertiesService.getScriptProperties().getProperty("TELEGRAM_BOT_TOKEN") || "YOUR_BOT_TOKEN_HERE";
const TELEGRAM_CHAT_ID = PropertiesService.getScriptProperties().getProperty("TELEGRAM_CHAT_ID") || "YOUR_CHAT_ID_HERE";
const LOGO_URL = "https://flawlesstechdata.com/wp-content/uploads/2024/10/FLawless.png";
const ARCHIVE_FOLDER_NAME = "Udyam_Archives";
const LEASE_TIMEOUT_MINUTES = 15;

const CANONICAL_STATE_CODES = {
  "Andaman and Nicobar Islands": "AN",
  "Andhra Pradesh": "AP",
  "Arunachal Pradesh": "AR",
  "Assam": "AS",
  "Bihar": "BR",
  "Chandigarh": "CH",
  "Chhattisgarh": "CG",
  "Dadra and Nagar Haveli and Daman and Diu": "DD",
  "Delhi": "DL",
  "Goa": "GA",
  "Gujarat": "GJ",
  "Haryana": "HR",
  "Himachal Pradesh": "HP",
  "Jammu and Kashmir": "JK",
  "Jharkhand": "JH",
  "Karnataka": "KA",
  "Kerala": "KL",
  "Ladakh": "LA",
  "Lakshadweep": "LD",
  "Madhya Pradesh": "MP",
  "Maharashtra": "MH",
  "Manipur": "MN",
  "Meghalaya": "ML",
  "Mizoram": "MZ",
  "Nagaland": "NL",
  "Odisha": "OR",
  "Puducherry": "PY",
  "Punjab": "PB",
  "Rajasthan": "RJ",
  "Sikkim": "SK",
  "Tamil Nadu": "TN",
  "Telangana": "TS",
  "Tripura": "TR",
  "Uttar Pradesh": "UP",
  "Uttarakhand": "UK",
  "West Bengal": "WB"
};

/**
 * Adds the FlawlessTech Data organization logo to the top of the Google Sheet.
 * Can be run manually from Apps Script editor menu or during setup.
 */
function addFlawlessLogo() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getActiveSheet();
  try {
    // Insert floating image over the top-right columns
    const image = sheet.insertImage(LOGO_URL, 10, 1);
    image.setWidth(240);
    image.setHeight(54);
    Logger.log("Logo successfully inserted.");
  } catch (err) {
    Logger.log("Could not insert floating image, setting formula: " + err);
    sheet.getRange("N1").setFormula(`=IMAGE("${LOGO_URL}", 1)`);
  }
}

/**
 * Get fleet summary and active worker state
 */
function getFleetStatus() {
  const ctx = getSheetContext();
  const data = ctx.data;
  const col = ctx.colMap;
  const now = new Date();

  let activeWorkers = [];
  let totalExtractedFleet = 0;
  let completedCount = 0;
  let totalDistricts = 0;

  for (let r = 1; r < data.length; r++) {
    const row = data[r];
    const level = (row[col["Level"]] || "").toString().trim();
    if (level === "District") totalDistricts++;

    const status = (row[col["Status"]] || "").toString().trim();
    const claimedBy = (row[col["Claimed By"]] || "").toString().trim();
    const distCode = (row[col["State Code"]] || "").toString().trim();
    const lastRecord = (row[col["Last Record"]] || "").toString().trim();
    const lastPingStr = row[col["Last Ping"]];
    const speed = row[col["Speed (rec/min)"]] || 0;
    const extracted = parseInt(row[col["Total Records Extracted"]] || 0, 10);

    totalExtractedFleet += extracted;
    if (status === "Completed") completedCount++;

    if (status === "In Progress" && claimedBy) {
      let isStalled = false;
      let minutesAgo = 999;
      if (lastPingStr) {
        minutesAgo = Math.round((now.getTime() - new Date(lastPingStr).getTime()) / (60 * 1000));
        if (minutesAgo > LEASE_TIMEOUT_MINUTES) {
          isStalled = true;
        }
      }
      activeWorkers.push({
        machine: claimedBy,
        district: distCode,
        lastRecord: lastRecord,
        speed: speed,
        stalled: isStalled,
        minutesAgo: minutesAgo
      });
    }
  }

  return {
    status: "ok",
    total_districts: totalDistricts,
    districts_completed: completedCount,
    total_extracted: totalExtractedFleet,
    active_workers: activeWorkers
  };
}

/**
 * Handle HTTP GET Requests (e.g. claim_task, fleet_status)
 */
function doGet(e) {
  const params = e.parameter || {};
  const action = params.action;

  try {
    if (action === "claim_task") {
      return jsonResponse(handleClaimTask(params.machine, params.preferred_state, params.preferred_district));
    } else if (action === "fleet_status") {
      return jsonResponse(getFleetStatus());
    } else if (action === "check_file") {
      return jsonResponse(handleCheckFileExists(params.filename));
    } else if (action === "list_archives") {
      return jsonResponse(handleListArchives());
    } else if (action === "ping") {
      return jsonResponse({ status: "ok", time: new Date().toISOString() });
    } else {
      return jsonResponse({ error: "Invalid GET action: " + action }, 400);
    }
  } catch (err) {
    return jsonResponse({ error: err.toString() }, 500);
  }
}

/**
 * Handle HTTP POST Requests (e.g. heartbeat, complete_task, bulk_sync_status, upload_archive)
 */
function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    lock.waitLock(30000); // Wait up to 30s for atomic access
  } catch (err) {
    return jsonResponse({ error: "Could not obtain lock, server busy." }, 503);
  }

  try {
    let payload = {};
    if (e.postData && e.postData.contents) {
      try {
        payload = JSON.parse(e.postData.contents);
      } catch (ex) {
        payload = e.parameter || {};
      }
    } else {
      payload = e.parameter || {};
    }

    const action = payload.action;

    if (action === "heartbeat") {
      return jsonResponse(handleHeartbeat(payload));
    } else if (action === "complete_task") {
      return jsonResponse(handleCompleteTask(payload));
    } else if (action === "bulk_sync_status") {
      return jsonResponse(handleBulkSyncStatus(payload.districts));
    } else if (action === "upload_archive") {
      return jsonResponse(handleUploadArchive(payload));
    } else if (action === "check_file") {
      return jsonResponse(handleCheckFileExists(payload.filename));
    } else if (action === "list_archives") {
      return jsonResponse(handleListArchives());
    } else {
      return jsonResponse({ error: "Invalid POST action: " + action }, 400);
    }
  } catch (err) {
    return jsonResponse({ error: err.toString() }, 500);
  } finally {
    lock.releaseLock();
  }
}

// ==========================================
// TASK ALLOCATION & COORDINATION
// ==========================================

function getSheetContext() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getActiveSheet();
  const data = sheet.getDataRange().getValues();
  const headers = data[0];

  // Column map
  const colMap = {};
  for (let c = 0; c < headers.length; c++) {
    colMap[headers[c].toString().trim()] = c;
  }

  // Ensure necessary tracking columns exist
  let modified = false;
  const extraCols = ["Status", "Claimed By", "Last Ping", "Speed (rec/min)"];
  for (const colName of extraCols) {
    if (colMap[colName] === undefined) {
      const newColIdx = headers.length;
      sheet.getRange(1, newColIdx + 1).setValue(colName);
      headers.push(colName);
      colMap[colName] = newColIdx;
      modified = true;
    }
  }

  return { ss, sheet, data, headers, colMap };
}

/**
 * Determines whether a district's latest registration date (or last audit ping) is current.
 * Threshold: Within 4 calendar days (96 hours).
 */
function isDateLatest(rawDate, rawPing) {
  const now = new Date();
  const FOUR_DAYS_MS = 4 * 24 * 60 * 60 * 1000;

  // 1. If worker recently completed/verified this district within 4 days, treat as fresh
  if (rawPing) {
    const pingDate = (rawPing instanceof Date) ? rawPing : new Date(rawPing);
    if (!isNaN(pingDate.getTime())) {
      if ((now.getTime() - pingDate.getTime()) < FOUR_DAYS_MS) {
        return true;
      }
    }
  }

  // 2. Parse registration date
  if (!rawDate) return false;
  let d = null;
  if (rawDate instanceof Date) {
    d = rawDate;
  } else {
    const cleaned = rawDate.toString().trim().replace(/Sept/gi, "Sep");
    const dmyMatch = cleaned.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
    if (dmyMatch) {
      d = new Date(Date.UTC(parseInt(dmyMatch[3], 10), parseInt(dmyMatch[2], 10) - 1, parseInt(dmyMatch[1], 10)));
    } else {
      d = new Date(cleaned);
    }
  }

  if (!d || isNaN(d.getTime())) return false;

  const diffMs = now.getTime() - d.getTime();
  return diffMs <= FOUR_DAYS_MS;
}

function handleClaimTask(machine, preferredState, preferredDistrict) {
  if (!machine) machine = "Worker-" + Math.floor(Math.random() * 1000);

  const ctx = getSheetContext();
  const sheet = ctx.sheet;
  const data = ctx.data;
  const col = ctx.colMap;

  const now = new Date();
  let assignedRow = -1;
  let assignedDistrict = "";
  let stateCode = "";
  let lastRecord = "";
  let lastDor = "";
  let prevExtracted = 0;
  let assignedStatus = "";

  function isRowLeased(claimedBy, status, lastPingStr) {
    if (claimedBy && claimedBy !== machine && status === "In Progress") {
      if (lastPingStr) {
        const lastPing = (lastPingStr instanceof Date) ? lastPingStr : new Date(lastPingStr);
        if (!isNaN(lastPing.getTime())) {
          const minutesSince = (now.getTime() - lastPing.getTime()) / (60 * 1000);
          return (minutesSince < LEASE_TIMEOUT_MINUTES);
        }
      }
      return true;
    }
    return false;
  }

  function rowMatchesFilter(distCode, statePrefix, stateName) {
    if (preferredDistrict) {
      return distCode.toUpperCase() === preferredDistrict.toUpperCase();
    }
    if (preferredState) {
      const ps = preferredState.toUpperCase();
      return (
        distCode.toUpperCase().startsWith(ps + "-") ||
        statePrefix.toUpperCase() === ps ||
        stateName.toUpperCase() === ps ||
        distCode.toUpperCase() === ps
      );
    }
    return true;
  }

  // PASS 1: Search for pending / uncompleted districts (Status !== "Completed")
  for (let r = 1; r < data.length; r++) {
    const row = data[r];
    const level = (row[col["Level"]] || "").toString().trim();
    if (level !== "District") continue;

    const status = (row[col["Status"]] || "").toString().trim();
    if (status === "Completed") continue;

    let distCode = (row[col["State Code"]] || "").toString().trim();
    const stateName = (row[col["State/UT"]] || "").toString().trim();
    const claimedBy = (row[col["Claimed By"]] || "").toString().trim();
    const lastPingStr = row[col["Last Ping"]];

    const statePrefix = CANONICAL_STATE_CODES[stateName] || (distCode.indexOf("-") !== -1 ? distCode.split("-")[0] : distCode);

    // If district code has no hyphen (e.g. only "HP" or blank), check state match and auto-index
    if (!distCode.includes("-")) {
      if (!rowMatchesFilter(distCode, statePrefix, stateName)) continue;
      distCode = statePrefix + "-01";
      sheet.getRange(r + 1, col["State Code"] + 1).setValue(distCode);
    }

    if (isRowLeased(claimedBy, status, lastPingStr)) continue;

    if (rowMatchesFilter(distCode, statePrefix, stateName)) {
      assignedRow = r + 1;
      assignedDistrict = distCode;
      stateCode = stateName;
      lastRecord = (row[col["Last Record"]] || "").toString().trim();
      lastDor = (row[col["Last Recorded Date"]] || "").toString().trim();
      const rawExt = (row[col["Total Records Extracted"]] || 0).toString().replace(/,/g, "");
      prevExtracted = parseInt(rawExt, 10) || 0;
      assignedStatus = status;
      break;
    }
  }

  // PASS 2: If no pending districts found, search for Completed districts whose Date of Registration is STALE (!isDateLatest)
  if (assignedRow === -1) {
    for (let r = 1; r < data.length; r++) {
      const row = data[r];
      const level = (row[col["Level"]] || "").toString().trim();
      if (level !== "District") continue;

      const status = (row[col["Status"]] || "").toString().trim();
      if (status !== "Completed") continue;

      const rawDor = row[col["Last Recorded Date"]];
      const rawPing = row[col["Last Ping"]];

      if (isDateLatest(rawDor, rawPing)) continue;

      let distCode = (row[col["State Code"]] || "").toString().trim();
      const stateName = (row[col["State/UT"]] || "").toString().trim();
      const claimedBy = (row[col["Claimed By"]] || "").toString().trim();
      const statePrefix = CANONICAL_STATE_CODES[stateName] || (distCode.indexOf("-") !== -1 ? distCode.split("-")[0] : distCode);

      if (!distCode.includes("-")) {
        if (!rowMatchesFilter(distCode, statePrefix, stateName)) continue;
        distCode = statePrefix + "-01";
        sheet.getRange(r + 1, col["State Code"] + 1).setValue(distCode);
      }

      if (isRowLeased(claimedBy, status, rawPing)) continue;

      if (rowMatchesFilter(distCode, statePrefix, stateName)) {
        assignedRow = r + 1;
        assignedDistrict = distCode;
        stateCode = stateName;
        lastRecord = (row[col["Last Record"]] || "").toString().trim();
        lastDor = (row[col["Last Recorded Date"]] || "").toString().trim();
        const rawExt = (row[col["Total Records Extracted"]] || 0).toString().replace(/,/g, "");
        prevExtracted = parseInt(rawExt, 10) || 0;
        assignedStatus = status;
        break;
      }
    }
  }

  if (assignedRow === -1) {
    return { success: false, message: "No available districts matching criteria." };
  }

  // Calculate resume start number
  let startNum = 1;
  const isCompletedResume = (assignedStatus === "Completed");
  if (lastRecord) {
    const cleaned = lastRecord.toString().replace(/,/g, "").trim();
    const mHyphen = cleaned.match(/-(\d+)$/);
    if (mHyphen) {
      const parsed = parseInt(mHyphen[1], 10);
      startNum = isCompletedResume ? (parsed + 1) : Math.max(1, parsed - 10);
    } else {
      const mNum = cleaned.match(/\d+/);
      if (mNum) {
        const parsed = parseInt(mNum[0], 10);
        startNum = isCompletedResume ? (parsed + 1) : Math.max(1, parsed - 10);
      }
    }
  }

  // Update sheet: mark as claimed
  sheet.getRange(assignedRow, col["Status"] + 1).setValue("In Progress");
  sheet.getRange(assignedRow, col["Claimed By"] + 1).setValue(machine);
  sheet.getRange(assignedRow, col["Last Ping"] + 1).setValue(now.toISOString());

  if (isCompletedResume) {
    sendTelegramAlert(`🔄 <b>Incremental Refresh Claimed</b>\n💻 <b>Machine:</b> ${machine}\n📍 <b>District:</b> ${assignedDistrict}\n📅 <b>Stale DOR:</b> ${lastDor || 'N/A'}\n🔢 <b>Resuming from:</b> #${startNum}\n📊 <b>Prev Extracted:</b> ${prevExtracted.toLocaleString()}`);
  } else {
    sendTelegramAlert(`🚜 <b>Task Claimed</b>\n💻 <b>Machine:</b> ${machine}\n📍 <b>District:</b> ${assignedDistrict}\n🔢 <b>Resuming at:</b> #${startNum}`);
  }

  return {
    success: true,
    district_code: assignedDistrict,
    start_num: startNum,
    last_record: lastRecord,
    last_dor: lastDor,
    prev_extracted: prevExtracted,
    limit: 500000
  };
}

function canonicalizeUdyamNumber(val, distCode) {
  if (!val) return "";
  const s = val.toString().trim();
  if (!s || s === "None" || s === "-" || s === "0" || s === "null") return "";
  if (s.toUpperCase().startsWith("UDYAM-")) {
    const m = s.match(/^(UDYAM-[A-Z]{2}-\d{2}-)(\d+)$/i);
    if (m) {
      return m[1].toUpperCase() + String(parseInt(m[2], 10)).padStart(7, "0");
    }
    return s.toUpperCase();
  }
  const mCode = s.match(/^([A-Z]{2}-\d{2}-)(\d+)$/i);
  if (mCode) {
    return "UDYAM-" + mCode[1].toUpperCase() + String(parseInt(mCode[2], 10)).padStart(7, "0");
  }
  const cleaned = s.replace(/,/g, "").split(".")[0].trim();
  const digits = cleaned.replace(/\D/g, "");
  if (digits && parseInt(digits, 10) > 0) {
    const seq = parseInt(digits, 10);
    const code = (distCode || "").toString().trim().toUpperCase();
    if (code.indexOf("-") !== -1) {
      return `UDYAM-${code}-${String(seq).padStart(7, "0")}`;
    } else if (code) {
      return `UDYAM-${code}-01-${String(seq).padStart(7, "0")}`;
    }
  }
  return s;
}

function handleHeartbeat(payload) {
  const machine = payload.machine || "Unknown";
  const distCode = payload.district_code;
  const currentRecord = canonicalizeUdyamNumber(payload.current_record || "", distCode);
  const currentDor = payload.current_dor || "";
  const totalExtracted = payload.total_extracted || 0;
  const totalFailed = payload.total_failed || 0;
  const speed = payload.speed_rpm || 0;

  const ctx = getSheetContext();
  const sheet = ctx.sheet;
  const data = ctx.data;
  const col = ctx.colMap;

  for (let r = 1; r < data.length; r++) {
    const code = (data[r][col["State Code"]] || "").toString().trim();
    if (code.toUpperCase() === distCode.toUpperCase()) {
      const rowIdx = r + 1;
      if (currentRecord) sheet.getRange(rowIdx, col["Last Record"] + 1).setValue(currentRecord);
      if (currentDor) sheet.getRange(rowIdx, col["Last Recorded Date"] + 1).setValue(currentDor);
      if (totalExtracted) sheet.getRange(rowIdx, col["Total Records Extracted"] + 1).setValue(totalExtracted);
      if (totalFailed) sheet.getRange(rowIdx, col["Total Failed Records"] + 1).setValue(totalFailed);
      sheet.getRange(rowIdx, col["Last Ping"] + 1).setValue(new Date().toISOString());
      sheet.getRange(rowIdx, col["Claimed By"] + 1).setValue(machine);
      sheet.getRange(rowIdx, col["Status"] + 1).setValue("In Progress");
      if (col["Speed (rec/min)"] !== undefined) {
        sheet.getRange(rowIdx, col["Speed (rec/min)"] + 1).setValue(speed);
      }
      return { success: true };
    }
  }

  return { success: false, message: "District not found in sheet: " + distCode };
}

function handleCompleteTask(payload) {
  const machine = payload.machine || "Unknown";
  const distCode = payload.district_code;
  const totalExtracted = payload.total_extracted || 0;
  const totalFailed = payload.total_failed || 0;
  const lastRecord = canonicalizeUdyamNumber(payload.final_record || "", distCode);
  const lastDor = payload.final_dor || "";

  const ctx = getSheetContext();
  const sheet = ctx.sheet;
  const data = ctx.data;
  const col = ctx.colMap;

  for (let r = 1; r < data.length; r++) {
    const code = (data[r][col["State Code"]] || "").toString().trim();
    if (code.toUpperCase() === distCode.toUpperCase()) {
      const rowIdx = r + 1;
      sheet.getRange(rowIdx, col["Status"] + 1).setValue("Completed");
      sheet.getRange(rowIdx, col["Claimed By"] + 1).setValue(machine);
      sheet.getRange(rowIdx, col["Last Ping"] + 1).setValue(new Date().toISOString());
      if (lastRecord) sheet.getRange(rowIdx, col["Last Record"] + 1).setValue(lastRecord);
      if (lastDor) sheet.getRange(rowIdx, col["Last Recorded Date"] + 1).setValue(lastDor);
      if (totalExtracted) sheet.getRange(rowIdx, col["Total Records Extracted"] + 1).setValue(totalExtracted);
      if (totalFailed) sheet.getRange(rowIdx, col["Total Failed Records"] + 1).setValue(totalFailed);

      sendTelegramAlert(`🏁 <b>District Completed!</b>\n💻 <b>Machine:</b> ${machine}\n🏛 <b>District:</b> ${distCode}\n✅ <b>Extracted:</b> ${totalExtracted.toLocaleString()}\n❌ <b>Failed:</b> ${totalFailed.toLocaleString()}\n📅 <b>Latest DOR:</b> ${lastDor}`);
      return { success: true };
    }
  }

  return { success: false, message: "District not found: " + distCode };
}

function handleBulkSyncStatus(districtsMap) {
  if (!districtsMap) return { success: false, message: "No districts provided" };

  const ctx = getSheetContext();
  const sheet = ctx.sheet;
  const data = ctx.data;
  const col = ctx.colMap;

  let updatedCount = 0;

  for (let r = 1; r < data.length; r++) {
    const code = (data[r][col["State Code"]] || "").toString().trim().toUpperCase();
    if (districtsMap[code]) {
      const info = districtsMap[code];
      const rowIdx = r + 1;

      if (info.last_record) sheet.getRange(rowIdx, col["Last Record"] + 1).setValue(info.last_record);
      if (info.last_recorded_date) sheet.getRange(rowIdx, col["Last Recorded Date"] + 1).setValue(info.last_recorded_date);
      if (info.total_extracted !== undefined) sheet.getRange(rowIdx, col["Total Records Extracted"] + 1).setValue(info.total_extracted);
      if (info.total_failed !== undefined) sheet.getRange(rowIdx, col["Total Failed Records"] + 1).setValue(info.total_failed);

      sheet.getRange(rowIdx, col["Status"] + 1).setValue("Completed");
      sheet.getRange(rowIdx, col["Claimed By"] + 1).setValue("Archived / Synced");
      sheet.getRange(rowIdx, col["Last Ping"] + 1).setValue(new Date().toISOString());

      updatedCount++;
    }
  }

  return { success: true, updated_count: updatedCount };
}

// ==========================================
// GOOGLE DRIVE ARCHIVE INGESTION
// ==========================================

function handleCheckFileExists(filename) {
  if (!filename) {
    return { success: false, exists: false, message: "Missing filename parameter" };
  }
  const folders = DriveApp.getFoldersByName(ARCHIVE_FOLDER_NAME);
  if (!folders.hasNext()) {
    return { success: true, exists: false, filename: filename };
  }
  const folder = folders.next();
  const files = folder.getFilesByName(filename);
  if (files.hasNext()) {
    const f = files.next();
    return { 
      success: true, 
      exists: true, 
      filename: filename, 
      file_id: f.getId(), 
      url: f.getUrl(), 
      size: f.getSize() 
    };
  }
  return { success: true, exists: false, filename: filename };
}

function handleListArchives() {
  const folders = DriveApp.getFoldersByName(ARCHIVE_FOLDER_NAME);
  if (!folders.hasNext()) {
    return { success: true, files: [] };
  }
  const folder = folders.next();
  const files = folder.getFiles();
  const fileList = [];
  while (files.hasNext()) {
    const f = files.next();
    fileList.push({ name: f.getName(), id: f.getId(), size: f.getSize() });
  }
  return { success: true, files: fileList };
}

function handleUploadArchive(payload) {
  const filename = payload.filename;
  const base64Data = payload.data;

  if (!filename || !base64Data) {
    return { success: false, message: "Missing filename or data" };
  }

  // Locate or create archive folder
  const folders = DriveApp.getFoldersByName(ARCHIVE_FOLDER_NAME);
  let folder;
  if (folders.hasNext()) {
    folder = folders.next();
  } else {
    folder = DriveApp.createFolder(ARCHIVE_FOLDER_NAME);
  }

  // Check if file already exists with same name to avoid duplicates
  const existingFiles = folder.getFilesByName(filename);
  if (existingFiles.hasNext()) {
    const existingFile = existingFiles.next();
    return { 
      success: true, 
      already_exists: true, 
      file_id: existingFile.getId(), 
      url: existingFile.getUrl(),
      message: "File already exists in Google Drive"
    };
  }

  const bytes = Utilities.base64Decode(base64Data);
  const blob = Utilities.newBlob(bytes, "application/x-7z-compressed", filename);
  const file = folder.createFile(blob);

  return { success: true, file_id: file.getId(), url: file.getUrl() };
}

// ==========================================
// TELEGRAM NOTIFICATIONS & FLEET REPORT
// ==========================================

function sendTelegramAlert(htmlText) {
  if (!TELEGRAM_BOT_TOKEN || TELEGRAM_BOT_TOKEN === "YOUR_BOT_TOKEN_HERE") return;
  const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`;
  const payload = {
    chat_id: TELEGRAM_CHAT_ID,
    text: htmlText,
    parse_mode: "HTML"
  };
  try {
    UrlFetchApp.fetch(url, {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
  } catch (err) {
    Logger.log("Telegram error: " + err);
  }
}

/**
 * Scheduled Trigger: Run every 30 or 60 minutes
 */
function sendTelegramFleetReport() {
  const ctx = getSheetContext();
  const data = ctx.data;
  const col = ctx.colMap;
  const now = new Date();

  let activeWorkers = [];
  let totalExtractedFleet = 0;
  let completedCount = 0;

  for (let r = 1; r < data.length; r++) {
    const row = data[r];
    const status = (row[col["Status"]] || "").toString().trim();
    const claimedBy = (row[col["Claimed By"]] || "").toString().trim();
    const distCode = (row[col["State Code"]] || "").toString().trim();
    const lastRecord = (row[col["Last Record"]] || "").toString().trim();
    const lastPingStr = row[col["Last Ping"]];
    const speed = row[col["Speed (rec/min)"]] || 0;
    const extracted = parseInt(row[col["Total Records Extracted"]] || 0, 10);

    totalExtractedFleet += extracted;
    if (status === "Completed") completedCount++;

    if (status === "In Progress" && claimedBy) {
      let isStalled = false;
      let minutesAgo = 999;
      if (lastPingStr) {
        minutesAgo = Math.round((now.getTime() - new Date(lastPingStr).getTime()) / (60 * 1000));
        if (minutesAgo > LEASE_TIMEOUT_MINUTES) {
          isStalled = true;
        }
      }

      activeWorkers.push({
        machine: claimedBy,
        district: distCode,
        lastRecord: lastRecord,
        speed: speed,
        stalled: isStalled,
        minutesAgo: minutesAgo
      });
    }
  }

  if (activeWorkers.length === 0) return;

  let msg = `🏢 <b>FLAWLESSTECH DATA | Udyam Fleet Status</b>\n⚡ <i>Active Workers: ${activeWorkers.length}</i>\n━━━━━━━━━━━━━━━━━━━━\n`;
  for (const w of activeWorkers) {
    const icon = w.stalled ? "⚠️ (Stalled)" : "✅";
    msg += `💻 <b>${w.machine}</b>: ${w.district} [${w.speed} rec/m] ${icon}\n   ↳ <i>${w.lastRecord}</i>\n`;
  }
  msg += `━━━━━━━━━━━━━━━━━━━━\n📈 <b>Total Records:</b> ${totalExtractedFleet.toLocaleString()}\n🏁 <b>Districts Completed:</b> ${completedCount}`;

  sendTelegramAlert(msg);
}

function jsonResponse(obj, statusCode = 200) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * One-click utility function:
 * Automatically populates Column B ("State Code") for ALL 785 districts across all 36 States/UTs.
 * Run directly from Google Sheets Apps Script editor menu:
 * Select "autoIndexAllDistricts" and click "Run".
 */
function autoIndexAllDistricts() {
  const ctx = getSheetContext();
  const sheet = ctx.sheet;
  const data = ctx.data;
  const col = ctx.colMap;

  // Group district rows by state
  const byState = {};
  for (let r = 1; r < data.length; r++) {
    const row = data[r];
    const level = (row[col["Level"]] || "").toString().trim();
    const stateName = (row[col["State/UT"]] || "").toString().trim();
    const code = (row[col["State Code"]] || "").toString().trim();
    const distName = (row[col["Location Name"]] || row[col["District Name"]] || "").toString().trim();

    if (level === "District" && stateName) {
      if (!byState[stateName]) byState[stateName] = [];
      byState[stateName].push({ rowIdx: r + 1, code: code, name: distName });
    }
  }

  let totalUpdated = 0;
  for (const [stateName, distList] of Object.entries(byState)) {
    const prefix = CANONICAL_STATE_CODES[stateName] || "XX";
    const hasHyphens = distList.some(d => d.code && d.code.indexOf("-") !== -1);

    if (!hasHyphens) {
      // Sort alphabetically by district name
      distList.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
      distList.forEach((d, idx) => {
        const numStr = idx + 1 < 10 ? "0" + (idx + 1) : "" + (idx + 1);
        const newCode = prefix + "-" + numStr;
        sheet.getRange(d.rowIdx, col["State Code"] + 1).setValue(newCode);
        totalUpdated++;
      });
    }
  }

  Logger.log("Successfully auto-indexed " + totalUpdated + " districts across Google Sheet.");
  return { success: true, updated_districts: totalUpdated };
}

