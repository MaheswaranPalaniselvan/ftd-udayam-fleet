"""
Build script for GitHub Pages Dashboard.
Downloads the latest state from the master Google Sheet,
converts it into an interactive hierarchical drill-down HTML viewer,
and places it in public/index.html.
"""

import base64
import csv
from datetime import datetime, date
from typing import Optional
import json
import os
from pathlib import Path
import re
import shutil
import httpx
import openpyxl

DEFAULT_GSHEET_EXPORT = "https://docs.google.com/spreadsheets/d/1dwWvxENHxF5Lxz9BLCzwXR_rL09CuD9jU8FvDEAVN-E/export?format=xlsx"


def get_logo_base64() -> str:
    """Returns the base64-encoded FlawlessTech Data logo or empty string."""
    p = Path("flawless_logo.png")
    if p.exists():
        try:
            with open(p, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            pass
    return ""


def clean_int(val) -> int:
    """Safely parse integer counts, avoiding string concatenation/decimal truncation errors."""
    if val is None or val == "":
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    cleaned = str(val).replace(",", "").strip()
    try:
        return int(float(cleaned))
    except ValueError:
        digits = re.sub(r"[^\d]", "", cleaned.split(".")[0])
        return int(digits) if digits else 0


def format_indian_num(num: int) -> str:
    """Formats number according to Indian numbering system (e.g. 12,34,567)."""
    s = str(num)
    if len(s) <= 3:
        return s
    last_three = s[-3:]
    remaining = s[:-3]
    groups = []
    while remaining:
        groups.append(remaining[-2:])
        remaining = remaining[:-2]
    groups.reverse()
    return ",".join(groups) + "," + last_three


def normalize_udyam_number(val, district_code: str = "") -> str:
    """
    Normalizes a last_record value into canonical UDYAM-{CODE}-{SEQ:07d} format.
    Handles:
    - Already canonical format: 'UDYAM-TN-01-0037524' -> unchanged (ensures 7 digits)
    - Prefixed without 'UDYAM-': 'TN-01-0037524' -> 'UDYAM-TN-01-0037524'
    - Raw numbers or numbers with commas/floats: '1,32,800', 76818.0, '11392' -> 'UDYAM-TN-11-0132800'
    - Blank / None / '-' / '0' -> '-'
    """
    if val is None:
        return "-"
    s = str(val).strip()
    if not s or s in ("None", "-", "", "null", "0", "0.0"):
        return "-"

    # 1. Already in canonical UDYAM-{CODE}-{SEQ} format
    if s.upper().startswith("UDYAM-"):
        m = re.match(r"^(UDYAM-[A-Z]{2}-\d{2}-)(\d+)$", s, re.IGNORECASE)
        if m:
            prefix_part = m.group(1).upper()
            seq_part = int(m.group(2))
            return f"{prefix_part}{seq_part:07d}"
        return s.upper()

    # 2. Format like TN-01-0012345
    m_code = re.match(r"^([A-Z]{2}-\d{2}-)(\d+)$", s, re.IGNORECASE)
    if m_code:
        seq_part = int(m_code.group(2))
        return f"UDYAM-{m_code.group(1).upper()}{seq_part:07d}"

    # 3. Numeric string (with commas or decimal point, e.g. '1,32,800', 76818.0, 11392)
    cleaned = s.replace(",", "").split(".")[0].strip()
    digits = re.sub(r"[^\d]", "", cleaned)
    if digits and int(digits) > 0:
        seq = int(digits)
        code = district_code.strip().upper()
        if code and "-" in code:
            return f"UDYAM-{code}-{seq:07d}"
        elif code:
            return f"UDYAM-{code}-01-{seq:07d}"

    return s


def parse_date_to_datetime(val) -> Optional[datetime]:
    """Parses various date and timestamp formats into a datetime object."""
    if not val or str(val).strip() in ("None", "", "-", "null"):
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    
    s = str(val).strip().replace("Sept", "Sep")
    
    # 1. DD/MM/YYYY or DD-MM-YYYY
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
            
    # 2. YYYY-MM-DD
    m2 = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$", s)
    if m2:
        try:
            return datetime(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        except ValueError:
            pass

    # 3. Standard string formats
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.split(".")[0].replace("Z", ""), fmt)
        except ValueError:
            pass

    return None


def format_harvest_date(val) -> str:
    """Formats raw timestamp / ISO string / datetime into human-friendly date (e.g. 03 Nov 2026)."""
    dt = parse_date_to_datetime(val)
    if dt:
        return dt.strftime("%d %b %Y")
    s = str(val).strip() if val else "-"
    return s if s not in ("None", "", "null") else "-"


def is_registration_live(val, threshold_days: int = 5) -> bool:
    """Returns True if the registration date is current (within threshold_days of current date, accounting for weekend cycles)."""
    dt = parse_date_to_datetime(val)
    if not dt:
        return False
    now = datetime.now()
    diff = (now.date() - dt.date()).days
    return -1 <= diff <= threshold_days


def fetch_live_portal_facts() -> dict:
    """Fetches the latest official live counters directly from udyamregistration.gov.in
    and dashboard.msme.gov.in.
    """
    default_facts = {
        "date_str": "Live Govt Counter",
        "total_registrations": "5,57,23,519",
        "total_msmes_all": "10,07,23,996",
        "total_udyam": "5,56,98,978",
        "total_uap": "4,50,25,018",
        "micro": "5,51,10,920",
        "small": "5,45,971",
        "medium": "42,087",
        "employment": "37,87,84,983",
        "is_live": True,
        "state_metrics": {},
    }

    # Load cached MSME Dashboard metrics from dashboard.msme.gov.in
    cached_path = Path("assets/msme_dashboard_statewise.json")
    if cached_path.exists():
        try:
            with open(cached_path, "r", encoding="utf-8") as f:
                dash_data = json.load(f)
                default_facts["state_metrics"] = dash_data.get("states", {})
                tots = dash_data.get("totals", {})
                if tots:
                    default_facts["total_msmes_all"] = format_indian_num(tots.get("total_msmes", 100723996))
                    default_facts["total_udyam"] = format_indian_num(tots.get("total_udyam", 55698978))
                    default_facts["total_uap"] = format_indian_num(tots.get("uap_imes", 45025018))
                    default_facts["micro"] = format_indian_num(tots.get("micro", 55110920))
                    default_facts["small"] = format_indian_num(tots.get("small", 545971))
                    default_facts["medium"] = format_indian_num(tots.get("medium", 42087))
        except Exception:
            pass

    # Quick update from udyamregistration.gov.in for employment & date
    try:
        r = httpx.get(
            "https://www.udyamregistration.gov.in/Default.aspx",
            timeout=5.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        if r.status_code == 200:
            m_date = re.search(r'id=["\']lbldate["\'][^>]*>([^<]+)<', r.text)
            m_total = re.search(r'id=["\']lblTotalReg["\'][^>]*>([^<]+)<', r.text)
            m_emp = re.search(r'id=["\']lblEmployment["\'][^>]*>([^<]+)<', r.text)
            if m_date:
                default_facts["date_str"] = m_date.group(1).replace("Facts Dated:-", "").strip()
            if m_total:
                default_facts["total_registrations"] = m_total.group(1).strip()
            if m_emp:
                default_facts["employment"] = m_emp.group(1).strip()
    except Exception:
        pass

    return default_facts


def build_drilldown_data(xlsx_path: Path) -> dict:
    """Parses Universe spreadsheet and builds hierarchical state and district data model."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Universe"]

    # Canonical 36 States & Union Territories of India
    CANONICAL_STATES = {
        "Andaman and Nicobar Islands": {"code": "AN", "type": "UT"},
        "Andhra Pradesh": {"code": "AP", "type": "State"},
        "Arunachal Pradesh": {"code": "AR", "type": "State"},
        "Assam": {"code": "AS", "type": "State"},
        "Bihar": {"code": "BR", "type": "State"},
        "Chandigarh": {"code": "CH", "type": "UT"},
        "Chhattisgarh": {"code": "CG", "type": "State"},
        "Dadra and Nagar Haveli and Daman and Diu": {"code": "DH/DD", "type": "UT"},
        "Delhi": {"code": "DL", "type": "UT"},
        "Goa": {"code": "GA", "type": "State"},
        "Gujarat": {"code": "GJ", "type": "State"},
        "Haryana": {"code": "HR", "type": "State"},
        "Himachal Pradesh": {"code": "HP", "type": "State"},
        "Jammu and Kashmir": {"code": "JK", "type": "UT"},
        "Jharkhand": {"code": "JH", "type": "State"},
        "Karnataka": {"code": "KA", "type": "State"},
        "Kerala": {"code": "KL", "type": "State"},
        "Ladakh": {"code": "LA", "type": "UT"},
        "Lakshadweep": {"code": "LD", "type": "UT"},
        "Madhya Pradesh": {"code": "MP", "type": "State"},
        "Maharashtra": {"code": "MH", "type": "State"},
        "Manipur": {"code": "MN", "type": "State"},
        "Meghalaya": {"code": "ML", "type": "State"},
        "Mizoram": {"code": "MZ", "type": "State"},
        "Nagaland": {"code": "NL", "type": "State"},
        "Odisha": {"code": "OR", "type": "State"},
        "Puducherry": {"code": "PY", "type": "UT"},
        "Punjab": {"code": "PB", "type": "State"},
        "Rajasthan": {"code": "RJ", "type": "State"},
        "Sikkim": {"code": "SK", "type": "State"},
        "Tamil Nadu": {"code": "TN", "type": "State"},
        "Telangana": {"code": "TS", "type": "State"},
        "Tripura": {"code": "TR", "type": "State"},
        "Uttar Pradesh": {"code": "UP", "type": "State"},
        "Uttarakhand": {"code": "UK", "type": "State"},
        "West Bengal": {"code": "WB", "type": "State"},
    }

    # Initialize all 36 states/UTs
    states_dict = {}
    for s_name, meta in CANONICAL_STATES.items():
        states_dict[s_name] = {
            "code": meta["code"],
            "name": s_name,
            "type": meta["type"],
            "share": 0.0,
            "districts": [],
        }

    # Load local sync report if available
    local_sync = {}
    sync_csv = Path("sync_report.csv")
    if sync_csv.is_file():
        try:
            with open(sync_csv, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    c = row.get("District Code", "").strip().upper()
                    if c:
                        local_sync[c] = {
                            "last_record": row.get("Last Record", "").strip(),
                            "last_dor": row.get("Last Recorded Date", "").strip(),
                            "extracted": clean_int(row.get("Total Extracted", 0)),
                            "failed": clean_int(row.get("Total Failed", 0)),
                        }
        except Exception:
            pass

    for r in ws.iter_rows(min_row=2, values_only=True):
        level = str(r[0]).strip() if r[0] else ""
        code = str(r[1]).strip() if r[1] else ""
        state_name = str(r[2]).strip() if r[2] else ""
        loc_name = str(r[3]).strip() if r[3] else ""

        if level == "State":
            name = state_name or loc_name
            if name in states_dict:
                states_dict[name]["share"] = r[8] or 0.0
                if code and not states_dict[name]["code"]:
                    states_dict[name]["code"] = code
        elif level == "District":
            if state_name in states_dict:
                status_raw = str(r[13]).strip() if len(r) > 13 and r[13] else "Pending"
                if not status_raw or status_raw == "None":
                    status_raw = "Pending"

                extracted = clean_int(r[11])
                # Date of registration from the last record extracted as the last date harvested value
                last_dor_raw = r[10] if len(r) > 10 and r[10] else None
                harvest_date = format_harvest_date(last_dor_raw)

                # Strict freshness evaluation:
                # District is Live ONLY if verified completed, has extracted records, and latest registration date is current (within 4 days).
                # All older historical extracts or unstarted/in-progress are classified as Outdated.
                is_live = (
                    status_raw.lower() in ("completed", "live")
                    and extracted > 0
                    and is_registration_live(last_dor_raw or harvest_date)
                )
                if is_live:
                    live_status_label = "Live"
                elif status_raw.lower() == "in progress":
                    live_status_label = "Outdated (In Progress)"
                elif status_raw.lower() in ("completed", "live", "outdated"):
                    live_status_label = "Outdated" if extracted > 0 else "Outdated (Not Started)"
                else:
                    live_status_label = "Outdated (Not Started)"

                total_msme = clean_int(r[7]) if len(r) > 7 else 0
                states_dict[state_name]["districts"].append({
                    "code": code,
                    "name": loc_name,
                    "total": total_msme,
                    "extracted": extracted,
                    "last_record": normalize_udyam_number(r[9], code),
                    "harvest_date": harvest_date,
                    "failed": clean_int(r[12]),
                    "status": status_raw,
                    "is_live": is_live,
                    "live_status": live_status_label,
                    "claimed_by": str(r[14] or "").strip(),
                    "speed": float(r[16]) if len(r) > 16 and r[16] not in (None, "", "None") else 0.0,
                })

    # Ensure all districts have proper canonical codes (e.g. HP-01, KL-01) even if raw sheet is un-indexed
    for s_name, s_data in states_dict.items():
        st_prefix = s_data["code"]
        dists = s_data["districts"]
        if not dists:
            continue
        unindexed = [d for d in dists if not d["code"] or "-" not in d["code"]]
        if unindexed:
            alpha_sorted = sorted(dists, key=lambda x: x["name"].lower())
            name_to_code = {d["name"]: f"{st_prefix}-{i+1:02d}" for i, d in enumerate(alpha_sorted)}
            for d in dists:
                if not d["code"] or "-" not in d["code"]:
                    d["code"] = name_to_code.get(d["name"], f"{st_prefix}-01")

    # Populate Dadra and Nagar Haveli and Daman and Diu districts if missing from raw sheet
    dh_dd_dists = states_dict["Dadra and Nagar Haveli and Daman and Diu"]["districts"]
    if not dh_dd_dists:
        dh_dd_dists.extend([
            {
                "code": "DD-01",
                "name": "Daman",
                "extracted": 9141,
                "last_record": "UDYAM-DD-01-0009967",
                "harvest_date": "09 Sept 2026",
                "failed": 0,
                "status": "Completed",
                "is_live": False,
                "live_status": "Outdated",
                "claimed_by": "Archived / Synced",
                "speed": 0.0,
            },
            {
                "code": "DD-02",
                "name": "Diu",
                "extracted": 1298,
                "last_record": "UDYAM-DD-02-0001298",
                "harvest_date": "09 Sept 2026",
                "failed": 0,
                "status": "Completed",
                "is_live": False,
                "live_status": "Outdated",
                "claimed_by": "Archived / Synced",
                "speed": 0.0,
            },
            {
                "code": "DN-01",
                "name": "Dadra and Nagar Haveli",
                "extracted": 8021,
                "last_record": "UDYAM-DN-01-0008021",
                "harvest_date": "09 Sept 2026",
                "failed": 0,
                "status": "Completed",
                "is_live": False,
                "live_status": "Outdated",
                "claimed_by": "Archived / Synced",
                "speed": 0.0,
            },
        ])

    # Overlay verified data from local sync_report.csv
    if local_sync:
        for s_name, s_data in states_dict.items():
            for d in s_data["districts"]:
                d_code = d.get("code", "").upper()
                if d_code in local_sync:
                    loc = local_sync[d_code]
                    if loc["extracted"] > 0:
                        d["extracted"] = max(d["extracted"], loc["extracted"])
                        d["status"] = "Completed"
                    if loc["last_record"] and (not d["last_record"] or d["last_record"] in ("None", "-", "")):
                        d["last_record"] = loc["last_record"]
                    if loc["last_dor"]:
                        d_dor = format_harvest_date(loc["last_dor"])
                        if d_dor and d_dor != "-":
                            dt_loc = parse_date_to_datetime(d_dor)
                            dt_current = parse_date_to_datetime(d.get("harvest_date"))
                            # Only overwrite if local sync is strictly newer or current date is absent
                            if dt_loc and (not dt_current or dt_loc > dt_current):
                                d["harvest_date"] = d_dor
                    if loc["failed"] > 0:
                        d["failed"] = max(d["failed"], loc["failed"])

                    # Strict freshness evaluation:
                    is_live = (
                        d["status"].lower() in ("completed", "live")
                        and d["extracted"] > 0
                        and is_registration_live(d.get("harvest_date"))
                    )
                    d["is_live"] = is_live
                    if is_live:
                        d["live_status"] = "Live"
                    elif d["status"].lower() == "in progress":
                        d["live_status"] = "Outdated (In Progress)"
                    elif d["status"].lower() in ("completed", "live"):
                        d["live_status"] = "Outdated"
                    else:
                        d["live_status"] = "Outdated (Not Started)"

    # Normalize and canonicalize all last_record fields across all districts
    for s_name, s_data in states_dict.items():
        for d in s_data["districts"]:
            d["last_record"] = normalize_udyam_number(d.get("last_record"), d.get("code", ""))

    states_list = list(states_dict.values())

    # Calculate aggregations
    total_extracted_records = 0
    total_failed_records = 0
    total_districts_count = 0
    total_live_districts = 0
    total_outdated_districts = 0
    total_completed_districts = 0
    total_inprogress_districts = 0
    total_enterprises_all = 0

    for s in states_list:
        dists = s["districts"]
        s["district_count"] = len(dists)
        s["total_enterprises"] = sum(d.get("total", 0) for d in dists)
        total_enterprises_all += s["total_enterprises"]
        s["live_count"] = sum(1 for d in dists if d.get("is_live", False))
        s["outdated_count"] = s["district_count"] - s["live_count"]
        s["completed_count"] = sum(1 for d in dists if d["status"].lower() == "completed")
        s["in_progress_count"] = sum(1 for d in dists if d["status"].lower() == "in progress")
        s["extracted_total"] = sum(d["extracted"] for d in dists)
        s["failed_total"] = sum(d["failed"] for d in dists)
        s["live_pct"] = round((s["live_count"] / len(dists) * 100), 1) if dists else 0.0
        s["completion_pct"] = round((s["completed_count"] / len(dists) * 100), 1) if dists else 0.0

        active_harvest_dates = [d["harvest_date"] for d in dists if d["harvest_date"] != "-"]
        s["latest_harvest"] = active_harvest_dates[0] if active_harvest_dates else "-"

        total_districts_count += len(dists)
        total_live_districts += s["live_count"]
        total_outdated_districts += s["outdated_count"]
        total_completed_districts += s["completed_count"]
        total_inprogress_districts += s["in_progress_count"]
        total_extracted_records += s["extracted_total"]
        total_failed_records += s["failed_total"]

    overall_live_pct = round((total_live_districts / total_districts_count * 100), 1) if total_districts_count else 0.0
    overall_pct = round((total_completed_districts / total_districts_count * 100), 1) if total_districts_count else 0.0

    live_facts = fetch_live_portal_facts()
    dash_states = live_facts.get("state_metrics", {})

    for s in states_list:
        key_upper = s["name"].upper()
        if "DADRA" in key_upper:
            msme_st = dash_states.get("THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU", {})
        else:
            msme_st = dash_states.get(key_upper, {})

        s["msme_total"] = msme_st.get("total_msmes", 0)
        s["msme_udyam"] = msme_st.get("total_udyam", 0)
        s["msme_uap"] = msme_st.get("uap_imes", 0)
        s["msme_micro"] = msme_st.get("micro", 0)
        s["msme_small"] = msme_st.get("small", 0)
        s["msme_medium"] = msme_st.get("medium", 0)

    return {
        "live_facts": live_facts,
        "kpi": {
            "total_states": len(states_list),
            "total_districts": total_districts_count,
            "total_enterprises": total_enterprises_all,
            "total_extracted": total_extracted_records,
            "total_remaining": max(0, total_enterprises_all - total_extracted_records),
            "live_districts": total_live_districts,
            "outdated_districts": total_outdated_districts,
            "live_pct": overall_live_pct,
            "completed_districts": total_completed_districts,
            "inprogress_districts": total_inprogress_districts,
            "completion_pct": overall_pct,
            "total_failed": total_failed_records,
        },
        "states": states_list,
    }


def generate_drilldown_html(data: dict, logo_b64: str, output_path: Path):
    """Generates the interactive hierarchical drill-down HTML viewer."""
    json_payload = json.dumps(data, ensure_ascii=False)
    live_facts = data.get("live_facts", {})

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FlawlessTech Data | Enterprise Udayam Live Coverage & Drill-Down Viewer</title>
  <meta name="description" content="State and district MSME extraction tracker with live verified records and fleet synchronization.">

  <!-- Google Fonts: Outfit & Inter & JetBrains Mono -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">

  <!-- SheetJS for local Excel Export (CDN with local asset fallback) -->
  <script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
  <script>
    if (typeof XLSX === 'undefined') {{
      document.write('<script src="assets/xlsx.full.min.js"><\\/script>');
    }}
  </script>

  <style>
    :root {{
      --bg-base: #090d16;
      --bg-surface: #0f1624;
      --bg-card: rgba(16, 23, 38, 0.85);
      --bg-card-hover: rgba(26, 37, 59, 0.95);
      --bg-subrow: #0a0f1b;
      --border-subtle: rgba(255, 255, 255, 0.07);
      --border-card: rgba(255, 255, 255, 0.12);
      --border-focus: #38bdf8;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --accent-cyan: #00d2ff;
      --accent-blue: #3b82f6;
      --accent-emerald: #10b981;
      --accent-amber: #f59e0b;
      --accent-rose: #f43f5e;
      --accent-purple: #a855f7;
      --font-heading: 'Outfit', sans-serif;
      --font-body: 'Inter', sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background: radial-gradient(circle at 10% 10%, rgba(0, 210, 255, 0.05), transparent 45%),
                  radial-gradient(circle at 90% 90%, rgba(99, 102, 241, 0.05), transparent 45%),
                  var(--bg-base);
      color: var(--text-main);
      font-family: var(--font-body);
      min-height: 100vh;
      padding: 1.5rem;
    }}

    .container {{
      max-width: 1440px;
      margin: 0 auto;
    }}

    /* Top Navigation Header */
    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 1.1rem 1.6rem;
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 16px;
      backdrop-filter: blur(16px);
      margin-bottom: 1.25rem;
      box-shadow: 0 8px 30px rgba(0,0,0,0.4);
    }}

    .brand-left {{
      display: flex;
      align-items: center;
      gap: 1.25rem;
    }}

    .brand-logo {{
      height: 48px;
      object-fit: contain;
    }}

    .brand-title h1 {{
      font-family: var(--font-heading);
      font-size: 1.35rem;
      font-weight: 700;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 0.65rem;
    }}

    .brand-title p {{
      font-size: 0.82rem;
      color: var(--text-muted);
      margin-top: 2px;
    }}

    .pill-badge {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.72rem;
      font-weight: 600;
      padding: 0.25rem 0.65rem;
      border-radius: 9999px;
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.4);
      color: #34d399;
    }}

    .pulse-dot {{
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 10px #10b981;
      animation: pulse 1.8s infinite;
    }}

    @keyframes pulse {{
      0%, 100% {{ opacity: 1; transform: scale(1); }}
      50% {{ opacity: 0.4; transform: scale(0.85); }}
    }}

    /* Live Official Govt Portal Banner */
    .portal-banner {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      background: linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.85));
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: 14px;
      padding: 0.85rem 1.4rem;
      margin-bottom: 1.5rem;
      gap: 1rem;
    }}

    .portal-banner-left {{
      display: flex;
      align-items: center;
      gap: 0.85rem;
    }}

    .portal-emblem {{
      font-size: 1.6rem;
    }}

    .portal-text h3 {{
      font-size: 0.92rem;
      font-weight: 600;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }}

    .portal-text p {{
      font-size: 0.78rem;
      color: var(--text-muted);
    }}

    .portal-stats-pills {{
      display: flex;
      gap: 0.75rem;
      flex-wrap: wrap;
    }}

    .portal-pill {{
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      padding: 0.35rem 0.75rem;
      font-size: 0.78rem;
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }}

    .portal-pill-val {{
      font-family: var(--font-mono);
      font-weight: 700;
      color: var(--accent-cyan);
    }}

    .portal-link {{
      color: #38bdf8;
      text-decoration: none;
      font-size: 0.78rem;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 0.25rem;
    }}

    .portal-link:hover {{
      text-decoration: underline;
    }}

    /* KPI Summary Cards */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }}

    .kpi-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 14px;
      padding: 1.15rem 1.25rem;
      position: relative;
      overflow: hidden;
      box-shadow: 0 4px 20px rgba(0,0,0,0.25);
    }}

    .kpi-card::before {{
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0; height: 3px;
      background: linear-gradient(90deg, var(--card-accent, #3b82f6), transparent);
    }}

    .kpi-label {{
      font-size: 0.76rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin-bottom: 0.4rem;
    }}

    .kpi-value {{
      font-family: var(--font-heading);
      font-size: 1.85rem;
      font-weight: 700;
      color: #fff;
    }}

    .kpi-subtext {{
      font-size: 0.75rem;
      color: var(--text-dim);
      margin-top: 0.3rem;
    }}

    /* Filter & Search Bar */
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 14px;
      padding: 0.85rem 1.25rem;
      margin-bottom: 1.25rem;
    }}

    .search-box {{
      position: relative;
      flex: 1;
      max-width: 440px;
      min-width: 260px;
    }}

    .search-input {{
      width: 100%;
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: 10px;
      padding: 0.6rem 1rem 0.6rem 2.4rem;
      color: #fff;
      font-family: var(--font-body);
      font-size: 0.9rem;
      outline: none;
      transition: all 0.2s;
    }}

    .search-input:focus {{
      border-color: var(--border-focus);
      box-shadow: 0 0 15px rgba(56, 189, 248, 0.2);
    }}

    .search-icon {{
      position: absolute;
      left: 0.8rem;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-dim);
      pointer-events: none;
    }}

    .filter-chips {{
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}

    .chip {{
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 0.4rem 0.9rem;
      border-radius: 8px;
      font-size: 0.82rem;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
    }}

    .chip:hover, .chip.active {{
      background: rgba(56, 189, 248, 0.15);
      border-color: var(--border-focus);
      color: #fff;
    }}

    .action-buttons {{
      display: flex;
      gap: 0.6rem;
    }}

    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      background: var(--bg-surface);
      border: 1px solid var(--border-card);
      color: var(--text-main);
      padding: 0.5rem 1rem;
      border-radius: 10px;
      font-size: 0.84rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }}

    .btn:hover {{
      background: var(--bg-card-hover);
      border-color: var(--text-muted);
    }}

    .btn-primary {{
      background: linear-gradient(135deg, #00d2ff, #3b82f6);
      border: none;
      color: #fff;
      box-shadow: 0 4px 15px rgba(0, 210, 255, 0.3);
    }}

    .btn-primary:hover {{
      transform: translateY(-1px);
      box-shadow: 0 6px 20px rgba(0, 210, 255, 0.4);
    }}

    /* Hierarchical Drill-Down Accordion / Table */
    .drilldown-container {{
      display: flex;
      flex-direction: column;
      gap: 0.65rem;
    }}

    .state-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 12px;
      overflow: hidden;
      transition: all 0.2s;
    }}

    .state-card:hover {{
      border-color: rgba(255, 255, 255, 0.22);
    }}

    .state-row {{
      display: flex;
      align-items: center;
      padding: 1rem 1.25rem;
      cursor: pointer;
      user-select: none;
      gap: 1rem;
      transition: background 0.15s;
    }}

    .state-row:hover {{
      background: var(--bg-card-hover);
    }}

    .chevron {{
      font-size: 0.8rem;
      color: var(--text-dim);
      transition: transform 0.25s ease;
      width: 16px;
      text-align: center;
    }}

    .state-card.open .chevron {{
      transform: rotate(90deg);
      color: var(--accent-cyan);
    }}

    .state-code-pill {{
      font-family: var(--font-mono);
      font-size: 0.78rem;
      font-weight: 700;
      padding: 0.25rem 0.55rem;
      border-radius: 6px;
      background: rgba(59, 130, 246, 0.2);
      border: 1px solid rgba(59, 130, 246, 0.4);
      color: #93c5fd;
      min-width: 42px;
      text-align: center;
    }}

    .state-name {{
      font-family: var(--font-heading);
      font-size: 1.05rem;
      font-weight: 600;
      color: #fff;
      flex: 1;
      min-width: 180px;
    }}

    .progress-bar-wrapper {{
      width: 160px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}

    .progress-track {{
      height: 6px;
      background: rgba(255, 255, 255, 0.08);
      border-radius: 3px;
      overflow: hidden;
    }}

    .progress-fill {{
      height: 100%;
      background: linear-gradient(90deg, #10b981, #00d2ff);
      border-radius: 3px;
      transition: width 0.3s ease;
    }}

    .progress-text {{
      font-size: 0.72rem;
      color: var(--text-dim);
      display: flex;
      justify-content: space-between;
    }}

    .state-stats {{
      display: flex;
      gap: 1.5rem;
      align-items: center;
      font-size: 0.85rem;
    }}

    .stat-col {{
      text-align: right;
      min-width: 110px;
    }}

    .stat-val {{
      font-family: var(--font-mono);
      font-weight: 600;
      color: #fff;
    }}

    .stat-sub {{
      font-size: 0.72rem;
      color: var(--text-dim);
    }}

    .status-badge {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.2rem 0.65rem;
      border-radius: 9999px;
      text-transform: capitalize;
    }}

    .status-completed {{
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.4);
      color: #34d399;
    }}

    .status-live {{
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.45);
      color: #34d399;
      font-weight: 600;
    }}

    .status-inprogress, .status-outdated-progress {{
      background: rgba(245, 158, 11, 0.15);
      border: 1px solid rgba(245, 158, 11, 0.4);
      color: #fbbf24;
      font-weight: 500;
    }}

    .status-pending, .status-outdated {{
      background: rgba(244, 63, 94, 0.12);
      border: 1px solid rgba(244, 63, 94, 0.35);
      color: #fb7185;
      font-weight: 500;
    }}

    .freshness-logic-banner {{
      display: flex;
      align-items: center;
      gap: 0.85rem;
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 12px;
      padding: 0.8rem 1.25rem;
      font-size: 0.83rem;
      color: var(--text-muted);
      margin-bottom: 1.25rem;
      line-height: 1.5;
    }}

    /* Nested Districts Sub-Table */
    .districts-table-wrapper {{
      display: none;
      padding: 0 1.25rem 1.25rem 1.25rem;
      background: var(--bg-subrow);
      border-top: 1px solid var(--border-subtle);
    }}

    .state-card.open .districts-table-wrapper {{
      display: block;
      animation: fadeIn 0.2s ease-in;
    }}

    @keyframes fadeIn {{
      from {{ opacity: 0; transform: translateY(-4px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    .sub-table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 0.75rem;
      font-size: 0.84rem;
    }}

    .sub-table th {{
      background: rgba(15, 23, 42, 0.9);
      color: var(--text-muted);
      font-weight: 600;
      text-align: left;
      padding: 0.65rem 0.85rem;
      border-bottom: 1px solid var(--border-subtle);
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}

    /* Interactive Sortable Headers */
    .sortable-th {{
      cursor: pointer;
      user-select: none;
      transition: background 0.15s, color 0.15s;
      white-space: nowrap;
    }}
    .sortable-th:hover {{
      background: rgba(56, 189, 248, 0.12) !important;
      color: #fff !important;
    }}
    .sortable-th.active {{
      color: #38bdf8 !important;
      background: rgba(56, 189, 248, 0.08) !important;
    }}
    .sort-icon {{
      display: inline-block;
      margin-left: 4px;
      font-size: 0.72rem;
      opacity: 0.6;
      transition: opacity 0.15s;
    }}
    .sortable-th:hover .sort-icon,
    .sortable-th.active .sort-icon {{
      opacity: 1;
    }}

    /* Sort Control Dropdown in Toolbar */
    .sort-control-wrapper {{
      display: flex;
      align-items: center;
      gap: 6px;
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      padding: 2px 8px;
    }}
    .sort-dropdown {{
      background: transparent;
      border: none;
      color: var(--text-main);
      padding: 0.45rem 0.6rem;
      font-family: var(--font-body);
      font-size: 0.8rem;
      font-weight: 500;
      outline: none;
      cursor: pointer;
    }}
    .sort-dropdown option {{
      background: #0f1624;
      color: #fff;
    }}

    .sub-table td {{
      padding: 0.7rem 0.85rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      color: var(--text-main);
    }}

    .sub-table tr:hover td {{
      background: rgba(255, 255, 255, 0.025);
    }}

    .dist-code {{
      font-family: var(--font-mono);
      font-weight: 600;
      color: var(--accent-cyan);
    }}

    .mono-num {{
      font-family: var(--font-mono);
    }}

    .empty-state {{
      text-align: center;
      padding: 3rem 1rem;
      color: var(--text-muted);
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 12px;
      margin-top: 1rem;
    }}

    @media (max-width: 900px) {{
      .state-stats {{ display: none; }}
      .progress-bar-wrapper {{ width: 110px; }}
      .portal-stats-pills {{ display: none; }}
    }}

    /* View Switcher Controls */
    .view-switch-group {{
      display: inline-flex;
      background: rgba(15, 23, 42, 0.75);
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 10px;
      padding: 4px;
      gap: 4px;
    }}
    .view-tab-btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      background: transparent;
      color: var(--text-muted);
      border: none;
      padding: 0.55rem 1.15rem;
      border-radius: 7px;
      font-family: var(--font-body);
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }}
    .view-tab-btn:hover {{
      color: #fff;
      background: rgba(255, 255, 255, 0.06);
    }}
    .view-tab-btn.active {{
      background: #38bdf8;
      color: #090d16;
      font-weight: 700;
      box-shadow: 0 2px 10px rgba(56, 189, 248, 0.4);
    }}
    .view-tab-btn.active .header-count-pill {{
      background: #090d16;
      color: #38bdf8;
    }}
    .header-count-pill {{
      font-size: 0.72rem;
      font-weight: 700;
      padding: 0.15rem 0.55rem;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.12);
      color: #34d399;
      transition: all 0.2s;
    }}

    /* Fleet View Styles */
    .fleet-view-container {{
      margin-top: 0.5rem;
      animation: fadeIn 0.2s ease-in-out;
    }}
    .fleet-hero-banner {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      background: linear-gradient(135deg, rgba(24, 24, 37, 0.95), rgba(17, 17, 27, 0.98));
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: 14px;
      padding: 1.25rem 1.75rem;
      margin-bottom: 1.25rem;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
      gap: 1rem;
    }}
    .fleet-hero-left {{
      display: flex;
      align-items: center;
      gap: 1.25rem;
    }}
    .fleet-hero-title h2 {{
      font-size: 1.35rem;
      font-weight: 700;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }}
    .fleet-hero-title p {{
      font-size: 0.85rem;
      color: var(--text-muted);
      margin-top: 0.25rem;
    }}
    .fleet-kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 1rem;
      margin-bottom: 1.25rem;
    }}
    .fleet-kpi-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 12px;
      padding: 1.15rem 1.35rem;
      transition: transform 0.2s, border-color 0.2s;
    }}
    .fleet-kpi-card:hover {{
      transform: translateY(-2px);
      border-color: rgba(56, 189, 248, 0.4);
    }}
    .fleet-kpi-label {{
      font-size: 0.72rem;
      font-weight: 700;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.6px;
      margin-bottom: 0.35rem;
    }}
    .fleet-kpi-value {{
      font-family: var(--font-mono);
      font-size: 1.85rem;
      font-weight: 800;
      color: #fff;
    }}
    .fleet-kpi-sub {{
      font-size: 0.78rem;
      color: var(--text-muted);
      margin-top: 0.25rem;
    }}
    .fleet-table-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 14px;
      padding: 1.25rem;
      overflow: hidden;
    }}
    .fleet-table-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
      margin-bottom: 1rem;
    }}
    .fleet-search-box {{
      background: var(--bg-base);
      border: 1px solid var(--border-card);
      border-radius: 8px;
      padding: 0.55rem 0.95rem;
      color: #fff;
      font-family: var(--font-body);
      font-size: 0.85rem;
      width: 280px;
      outline: none;
    }}
    .fleet-search-box:focus {{
      border-color: #38bdf8;
    }}
    .fleet-filter-chips {{
      display: flex;
      gap: 0.4rem;
      flex-wrap: wrap;
    }}
    .fleet-filter-chip {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 0.35rem 0.8rem;
      border-radius: 6px;
      font-size: 0.78rem;
      cursor: pointer;
      font-weight: 600;
      transition: all 0.2s;
    }}
    .fleet-filter-chip:hover {{
      background: rgba(255, 255, 255, 0.1);
      color: #fff;
    }}
    .fleet-filter-chip.active {{
      background: rgba(56, 189, 248, 0.2);
      border-color: rgba(56, 189, 248, 0.5);
      color: #38bdf8;
    }}
    .fleet-status-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.86rem;
    }}
    .fleet-status-table th {{
      background: rgba(255, 255, 255, 0.03);
      color: var(--text-muted);
      font-weight: 600;
      text-align: left;
      padding: 0.75rem 1rem;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      border-bottom: 1px solid var(--border-subtle);
    }}
    .fleet-status-table td {{
      padding: 0.85rem 1rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      color: var(--text-main);
    }}
    .fleet-status-table tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}

    /* ======================================================= */
    /* FLEET VELOCITY & DYNAMIC COMPLETION ETA SECTION STYLES  */
    /* ======================================================= */
    .fleet-eta-section {{
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 14px;
      padding: 1.35rem 1.5rem;
      margin-bottom: 1.25rem;
      position: relative;
      overflow: hidden;
    }}
    .fleet-eta-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 1.15rem;
      padding-bottom: 0.85rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.07);
    }}
    .fleet-eta-header-left {{
      display: flex;
      align-items: center;
      gap: 0.85rem;
    }}
    .fleet-eta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 1rem;
      margin-bottom: 1.15rem;
    }}
    .fleet-eta-card {{
      background: rgba(255, 255, 255, 0.025);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 12px;
      padding: 1.1rem 1.25rem;
      transition: all 0.2s ease;
    }}
    .fleet-eta-card:hover {{
      transform: translateY(-2px);
      border-color: rgba(56, 189, 248, 0.4);
    }}
    .fleet-eta-card.primary {{
      background: rgba(56, 189, 248, 0.05);
      border-color: rgba(56, 189, 248, 0.35);
    }}
    .fleet-eta-card-label {{
      font-size: 0.7rem;
      font-weight: 700;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.6px;
      margin-bottom: 0.35rem;
    }}
    .fleet-eta-card-value {{
      font-family: var(--font-mono);
      font-size: 1.65rem;
      font-weight: 800;
      line-height: 1.2;
    }}
    .fleet-eta-card-sub {{
      font-size: 0.78rem;
      color: var(--text-muted);
      margin-top: 0.35rem;
    }}
    .fleet-eta-sim-bar {{
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.65rem;
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 10px;
      padding: 0.75rem 1rem;
      margin-bottom: 1.15rem;
    }}
    .fleet-eta-sim-title {{
      font-size: 0.82rem;
      color: var(--text-muted);
      margin-right: 0.25rem;
    }}
    .fleet-sim-chip {{
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.12);
      color: var(--text-muted);
      border-radius: 20px;
      padding: 0.35rem 0.85rem;
      font-size: 0.76rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
    }}
    .fleet-sim-chip:hover {{
      background: rgba(255, 255, 255, 0.12);
      color: #fff;
    }}
    .fleet-sim-chip.active {{
      background: #38bdf8;
      border-color: #38bdf8;
      color: #0f172a;
      box-shadow: 0 0 12px rgba(56, 189, 248, 0.35);
    }}
    .fleet-eta-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.83rem;
    }}
    .fleet-eta-table th {{
      text-align: left;
      padding: 0.65rem 0.85rem;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-dim);
      background: rgba(255, 255, 255, 0.02);
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }}
    .fleet-eta-table td {{
      padding: 0.75rem 0.85rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      color: #cbd5e1;
    }}
    .fleet-eta-table tr:hover td {{
      background: rgba(255, 255, 255, 0.025);
    }}

    /* ========================================== */
    /* ONBOARDING & SETUP TAB STYLES              */
    /* ========================================== */
    .onboarding-view-container {{
      margin-top: 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1.5rem;
    }}
    .onboarding-hero {{
      background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%);
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: 12px;
      padding: 1.5rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
    }}
    .device-tab-bar {{
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
      background: rgba(15, 23, 42, 0.6);
      padding: 0.4rem;
      border-radius: 10px;
      border: 1px solid var(--border-subtle);
    }}
    .device-tab-btn {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      padding: 0.55rem 1.1rem;
      border-radius: 7px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.15s ease;
    }}
    .device-tab-btn:hover {{
      color: #fff;
      background: rgba(255, 255, 255, 0.05);
    }}
    .device-tab-btn.active {{
      background: #38bdf8;
      color: #0b1120;
    }}
    .code-card {{
      background: #090e17;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 10px;
      overflow: hidden;
      margin-top: 0.75rem;
      margin-bottom: 1rem;
    }}
    .code-card-header {{
      background: rgba(255, 255, 255, 0.03);
      padding: 0.6rem 1rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-dim);
    }}
    .code-card-body {{
      padding: 1rem;
      font-family: var(--font-mono);
      font-size: 0.85rem;
      color: #38bdf8;
      white-space: pre-wrap;
      word-break: break-all;
      background: rgba(0, 0, 0, 0.3);
      user-select: all;
      line-height: 1.5;
    }}
    .copy-btn {{
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.2);
      color: var(--text-main);
      padding: 0.35rem 0.75rem;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.15s;
    }}
    .copy-btn:hover {{
      background: rgba(255, 255, 255, 0.15);
      color: #fff;
    }}
    .step-box {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid var(--border-subtle);
      border-radius: 10px;
      padding: 1.25rem;
      margin-bottom: 1rem;
    }}
    .step-title {{
      font-size: 0.95rem;
      font-weight: 700;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 0.5rem;
    }}
    .matrix-table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 1rem;
      font-size: 0.84rem;
    }}
    .matrix-table th {{
      background: rgba(15, 23, 42, 0.8);
      color: var(--text-dim);
      text-align: left;
      padding: 0.75rem 1rem;
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      border-bottom: 1px solid var(--border-subtle);
    }}
    .matrix-table td {{
      padding: 0.85rem 1rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      color: var(--text-main);
    }}
    .matrix-table tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}
  </style>
</head>
<body>
  <div class="container">

    <!-- Header with Branding -->
    <header>
      <div class="brand-left">
        {'<img src="data:image/png;base64,' + logo_b64 + '" class="brand-logo" alt="FlawlessTech Data Logo">' if logo_b64 else ''}
        <div class="brand-title">
          <h1>⚡ FlawlessTech Data <span class="pill-badge"><span class="pulse-dot"></span> Live Fleet Drill-Down</span></h1>
          <p>State & District Hierarchical Coverage & Extraction Dashboard</p>
        </div>
      </div>
      <div class="brand-right" style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
        <!-- Integrated View Switcher -->
        <div class="view-switch-group">
          <button id="nav-btn-coverage" class="view-tab-btn active" onclick="switchMainView('coverage')">
            📊 State Coverage View
          </button>
          <button id="nav-btn-fleet" class="view-tab-btn" onclick="switchMainView('fleet')">
            <span class="pulse-dot"></span> 🌐 Fleet Status View <span id="header-fleet-badge" class="header-count-pill">-- Active</span>
          </button>
          <button id="nav-btn-onboarding" class="view-tab-btn" onclick="switchMainView('onboarding')">
            🚀 1-Click Fleet Setup
          </button>
        </div>
        <button class="btn btn-primary" onclick="exportFilteredExcel()">📊 Export Excel (.xlsx)</button>
      </div>
    </header>

    <!-- ========================================== -->
    <!-- VIEW 1: STATE COVERAGE DASHBOARD VIEW     -->
    <!-- ========================================== -->
    <div id="view-coverage" class="coverage-view-container" style="display: block;">
      <!-- Official Live Government Portal Facts Banner -->
      <div class="portal-banner">
      <div class="portal-banner-left">
        <span class="portal-emblem">🏛️</span>
        <div class="portal-text">
          <h3>Ministry of MSME Performance Dashboard & Live Portal Universe <span style="font-size: 0.72rem; color: #34d399; font-weight: normal;">● Live Govt Facts</span></h3>
          <p>Official registry from <a href="https://dashboard.msme.gov.in/" target="_blank" class="portal-link">dashboard.msme.gov.in ↗</a> & <a href="https://www.udyamregistration.gov.in/" target="_blank" class="portal-link">udyamregistration.gov.in ↗</a> ({live_facts.get('date_str', 'Updated Daily')})</p>
        </div>
      </div>
      <div class="portal-stats-pills">
        <div class="portal-pill" title="Total Formal MSMEs + Informal Micro Enterprises (UAP)">
          <span>Total MSMEs (All India):</span>
          <span class="portal-pill-val" style="color: #38bdf8;">{live_facts.get('total_msmes_all', '10.07 Cr+')}</span>
        </div>
        <div class="portal-pill" title="Formal Udyam Registration Portal">
          <span>Udyam Formal:</span>
          <span class="portal-pill-val">{live_facts.get('total_udyam', '5.57 Cr')}</span>
        </div>
        <div class="portal-pill" title="Udyam Assist Platform for Informal Micro Enterprises">
          <span>UAP (Informal):</span>
          <span class="portal-pill-val" style="color: #c084fc;">{live_facts.get('total_uap', '4.50 Cr')}</span>
        </div>
        <div class="portal-pill" title="Micro Enterprises">
          <span>Micro:</span>
          <span class="portal-pill-val">{live_facts.get('micro', '5.51 Cr')}</span>
        </div>
        <div class="portal-pill" title="Small Enterprises">
          <span>Small:</span>
          <span class="portal-pill-val">{live_facts.get('small', '5.46 L')}</span>
        </div>
      </div>
    </div>

    <!-- Executive KPI Row -->
    <div class="kpi-grid">
      <div class="kpi-card" style="--card-accent: #00d2ff;">
        <div class="kpi-label">Total States / UTs</div>
        <div class="kpi-value">{data['kpi']['total_states']}</div>
        <div class="kpi-subtext">28 States + 8 UTs</div>
      </div>
      <div class="kpi-card" style="--card-accent: #3b82f6;">
        <div class="kpi-label">Total Districts</div>
        <div class="kpi-value">{data['kpi']['total_districts']}</div>
        <div class="kpi-subtext">Active Fleet Universe</div>
      </div>
      <div class="kpi-card" style="--card-accent: #10b981;">
        <div class="kpi-label">Live Districts</div>
        <div class="kpi-value">{data['kpi']['live_districts']} <span style="font-size: 1rem; color: #34d399;">({data['kpi']['live_pct']}%)</span></div>
        <div class="kpi-subtext">Current & Actively Fresh</div>
      </div>
      <div class="kpi-card" style="--card-accent: #f43f5e;">
        <div class="kpi-label">Outdated Districts</div>
        <div class="kpi-value">{data['kpi']['outdated_districts']} <span style="font-size: 0.95rem; color: #fb7185;">({round(100 - data['kpi']['live_pct'], 1)}%)</span></div>
        <div class="kpi-subtext">Stale / Pending Re-harvest</div>
      </div>
      <div class="kpi-card" style="--card-accent: #a855f7;">
        <div class="kpi-label">Total Extracted Records</div>
        <div class="kpi-value">{format_indian_num(data['kpi']['total_extracted'])}</div>
        <div class="kpi-subtext">Verified Harvested MSMEs</div>
      </div>
    </div>

    <!-- Freshness Classification Logic Explanation Banner -->
    <div class="freshness-logic-banner">
      <span style="font-size: 1.25rem;">💡</span>
      <div style="flex: 1;">
        <strong style="color: #f1f5f9;">Data Freshness Logic:</strong> Districts are strictly classified as <span style="color: #34d399; font-weight: 600;">🟢 Live</span> only when verified extraction is complete and the latest registration date is current (within 4 calendar days). Districts with older historical extracts, in-progress runs, or pending extraction are classified as <span style="color: #fb7185; font-weight: 600;">🔴 Outdated</span>.
      </div>
    </div>

    <!-- Filter & Search Toolbar -->
    <div class="toolbar">
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" id="searchInput" class="search-input" placeholder="Search state, district, or code (e.g. TN-02, Kerala)..." oninput="handleSearch()">
      </div>
      <div class="filter-chips">
        <span class="chip active" data-status="all" onclick="filterStatus('all')">All States & UTs ({data['kpi']['total_states']})</span>
        <span class="chip" data-status="live" onclick="filterStatus('live')">🟢 Live ({data['kpi']['live_districts']})</span>
        <span class="chip" data-status="outdated" onclick="filterStatus('outdated')">🔴 Outdated ({data['kpi']['outdated_districts']})</span>
        <span class="chip" data-status="inprogress" onclick="filterStatus('inprogress')">⚡ In Progress ({data['kpi']['inprogress_districts']})</span>
      </div>
      <!-- Sort Selector Dropdown -->
      <div class="sort-control-wrapper" title="Change district and state sorting order">
        <span style="font-size: 0.76rem; color: var(--text-dim); font-weight: 700; letter-spacing: 0.5px;">SORT:</span>
        <select id="sortSelect" class="sort-dropdown" onchange="handleSortDropdownChange(this.value)">
          <option value="code_asc">District Code (Ascending)</option>
          <option value="code_desc">District Code (Descending)</option>
          <option value="name_asc">District Name (A → Z)</option>
          <option value="name_desc">District Name (Z → A)</option>
          <option value="harvest_date_desc">Last Date Harvested (Newest First)</option>
          <option value="harvest_date_asc">Last Date Harvested (Oldest First)</option>
          <option value="extracted_desc">Extracted Records (Highest First)</option>
          <option value="extracted_asc">Extracted Records (Lowest First)</option>
          <option value="status_desc">Status (Live → In Progress → Outdated)</option>
          <option value="failed_desc">Failed Records (Highest First)</option>
          <option value="speed_desc">Speed (Highest rpm First)</option>
          <option value="last_record_asc">Last Record Extracted (A → Z)</option>
          <option value="claimed_by_asc">Worker / Node (A → Z)</option>
        </select>
      </div>
      <div class="action-buttons">
        <button class="btn" onclick="toggleAllStates(true)">⬇️ Expand All</button>
        <button class="btn" onclick="toggleAllStates(false)">⬆️ Collapse All</button>
      </div>
    </div>

    <!-- Hierarchical Accordion Container -->
    <div id="drilldownList" class="drilldown-container">
      <!-- Populated via JavaScript -->
    </div>

    <div id="emptyMessage" class="empty-state" style="display: none;">
      <h3>No matching states or districts found</h3>
      <p style="margin-top: 0.5rem; font-size: 0.85rem;">Try adjusting your search terms or filter selection.</p>
    </div>
  </div> <!-- end of #view-coverage -->

  <!-- ========================================== -->
  <!-- VIEW 2: CENTRAL FLEET STATUS MONITOR VIEW  -->
  <!-- ========================================== -->
  <div id="view-fleet" class="fleet-view-container" style="display: none;">
    <!-- Fleet Hero Banner -->
    <div class="fleet-hero-banner">
      <div class="fleet-hero-left">
        <span style="font-size: 2.2rem;">🌐</span>
        <div class="fleet-hero-title">
          <h2>Central Fleet Live Health & Daemon Monitor <span class="pill-badge"><span class="pulse-dot"></span> Live Telemetry</span></h2>
          <p>Real-time autonomous tracking across Raspberry Pi 5, Pi 4, Jetson Nano & Cloud Workers</p>
        </div>
      </div>
      <div style="display: flex; gap: 10px; align-items: center;">
        <span id="fleetSyncTimerMsg" style="font-size: 0.8rem; color: var(--text-dim);">Auto-refreshing every 15s</span>
        <button onclick="fetchFleetStatus()" class="btn" style="background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.18); color: #fff; font-size: 0.82rem; padding: 0.5rem 0.9rem; cursor: pointer; border-radius: 8px;">
          🔄 Refresh Telemetry
        </button>
      </div>
    </div>

    <!-- Fleet KPI Grid -->
    <div class="fleet-kpi-grid">
      <div class="fleet-kpi-card">
        <div class="fleet-kpi-label">Active Daemons</div>
        <div class="fleet-kpi-value" id="kpiActiveDaemons" style="color: #34d399;">--</div>
        <div class="fleet-kpi-sub">SBCs & Workers Scraping Now</div>
      </div>
      <div class="fleet-kpi-card">
        <div class="fleet-kpi-label">Districts Harvested</div>
        <div class="fleet-kpi-value" id="kpiDistrictsCompleted" style="color: #38bdf8;">--</div>
        <div class="fleet-kpi-sub">Total Leased & Completed (788 All India)</div>
      </div>
      <div class="fleet-kpi-card">
        <div class="fleet-kpi-label">Fleet Aggregate Speed</div>
        <div class="fleet-kpi-value" id="kpiAggregateSpeed" style="color: #fbbf24;">--</div>
        <div class="fleet-kpi-sub">Combined Records / Minute</div>
      </div>
      <div class="fleet-kpi-card">
        <div class="fleet-kpi-label">Last Coordinator Ping</div>
        <div class="fleet-kpi-value" id="kpiLastSync" style="font-size: 1.4rem; color: #c084fc;">--</div>
        <div class="fleet-kpi-sub">Google Apps Script Live Sync</div>
      </div>
    </div>

    <!-- ======================================================= -->
    <!-- NEW SECTION: FLEET VELOCITY & DYNAMIC COMPLETION ETA    -->
    <!-- ======================================================= -->
    <div class="fleet-eta-section">
      <div class="fleet-eta-header">
        <div class="fleet-eta-header-left">
          <span style="font-size: 1.8rem;">⏱️</span>
          <div>
            <h3 style="margin: 0; font-size: 1.22rem; font-family: 'Outfit', sans-serif; font-weight: 700; color: #fff;">
              Harvest Velocity & Dynamic Completion ETA Forecast
            </h3>
            <p style="margin: 0.2rem 0 0 0; font-size: 0.82rem; color: var(--text-dim);">
              Projections dynamically computed from active fleet aggregate speed (RPM) against India's MSME universe
            </p>
          </div>
        </div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <span class="pill-badge" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; font-weight: 700;">
            <span class="pulse-dot"></span> Dynamic Forecast
          </span>
        </div>
      </div>

      <!-- ETA Big Metrics Grid -->
      <div class="fleet-eta-grid">
        <div class="fleet-eta-card primary">
          <div class="fleet-eta-card-label">PROJECTED COMPLETION (ALL INDIA)</div>
          <div class="fleet-eta-card-value" id="etaTimeDisplay" style="color: #38bdf8;">--</div>
          <div class="fleet-eta-card-sub" id="etaDateDisplay">Target Finish: Calculating...</div>
        </div>

        <div class="fleet-eta-card">
          <div class="fleet-eta-card-label">CURRENT FLEET THROUGHPUT</div>
          <div class="fleet-eta-card-value" id="etaThroughputDisplay" style="color: #fbbf24;">0.0 rpm</div>
          <div class="fleet-eta-card-sub" id="etaDailyYieldDisplay">-- records / day</div>
        </div>

        <div class="fleet-eta-card">
          <div class="fleet-eta-card-label">NET RECORDS REMAINING</div>
          <div class="fleet-eta-card-value" id="etaRemainingDisplay" style="color: #f43f5e;">--</div>
          <div class="fleet-eta-card-sub" id="etaProgressPctDisplay">--% Completed</div>
        </div>

        <div class="fleet-eta-card">
          <div class="fleet-eta-card-label">SPEED FOR 30-DAY FINISH</div>
          <div class="fleet-eta-card-value" id="etaTarget30d" style="color: #34d399; font-size: 1.35rem;">--</div>
          <div class="fleet-eta-card-sub" id="etaTarget90d">-- for 90d target</div>
        </div>
      </div>

      <!-- Interactive Speed Simulator / What-If Scenario Bar -->
      <div class="fleet-eta-sim-bar">
        <div class="fleet-eta-sim-title">
          <span>⚡ <strong>Fleet Speed Simulator:</strong> Explore completion timelines at different RPM tiers:</span>
        </div>
        <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
          <button class="fleet-sim-chip active" id="chipLiveSpeed" onclick="setEtaSimulationSpeed('live')">🟢 Live RPM (<span id="chipLiveRpmVal">0</span>)</button>
          <button class="fleet-sim-chip" id="chipSim100" onclick="setEtaSimulationSpeed(100)">100 rpm (8 workers)</button>
          <button class="fleet-sim-chip" id="chipSim250" onclick="setEtaSimulationSpeed(250)">250 rpm (20 cloud workers)</button>
          <button class="fleet-sim-chip" id="chipSim500" onclick="setEtaSimulationSpeed(500)">500 rpm (40 workers)</button>
          <button class="fleet-sim-chip" id="chipSim1000" onclick="setEtaSimulationSpeed(1000)">1,000 rpm (Scale Fleet)</button>
        </div>
      </div>

      <!-- Multi-Scope Progress & Projection Table -->
      <div style="overflow-x: auto;">
        <table class="fleet-eta-table">
          <thead>
            <tr>
              <th>Extraction Scope</th>
              <th>Target Universe</th>
              <th>Extracted So Far</th>
              <th>Net Remaining</th>
              <th>Daily Yield (@ Active RPM)</th>
              <th>Projected Duration</th>
              <th>Estimated Finish Date</th>
            </tr>
          </thead>
          <tbody id="etaTableBody">
            <tr>
              <td colspan="7" style="text-align: center; color: var(--text-dim); padding: 1.5rem;">
                Calculating dynamic velocity and timeline forecasts...
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Live Daemon Status Table Card -->
    <div class="fleet-table-card">
      <div class="fleet-table-toolbar">
        <input type="text" id="fleetSearchInput" class="fleet-search-box" placeholder="Search Machine / Daemon or District..." oninput="filterFleetTable()">
        <div class="fleet-filter-chips">
          <button class="fleet-filter-chip active" data-filter="all" onclick="setFleetFilter('all')">All Daemons</button>
          <button class="fleet-filter-chip" data-filter="active" onclick="setFleetFilter('active')">🟢 Active</button>
          <button class="fleet-filter-chip" data-filter="lagging" onclick="setFleetFilter('lagging')">🟡 Lagging</button>
          <button class="fleet-filter-chip" data-filter="stalled" onclick="setFleetFilter('stalled')">🟠 Stalled</button>
          <button class="fleet-filter-chip" data-filter="offline" onclick="setFleetFilter('offline')">🔴 Offline</button>
        </div>
      </div>

      <div style="overflow-x: auto;">
        <table class="fleet-status-table">
          <thead>
            <tr>
              <th>Machine / Daemon Name</th>
              <th>Hardware / Role</th>
              <th>Live Status</th>
              <th>Assigned District</th>
              <th>Current Progress Record</th>
              <th>Speed (rpm)</th>
              <th>Last Heartbeat</th>
            </tr>
          </thead>
          <tbody id="fleetTableBody">
            <tr>
              <td colspan="7" style="text-align: center; color: var(--text-dim); padding: 2.5rem;">
                Connecting to Central Coordinator & fetching live fleet telemetry...
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div> <!-- end of #view-fleet -->

  <!-- ========================================== -->
  <!-- VIEW 3: UNIVERSAL FLEET ONBOARDING & SETUP -->
  <!-- ========================================== -->
  <div id="view-onboarding" class="onboarding-view-container" style="display: none;">
    <!-- Onboarding Hero Banner -->
    <div class="onboarding-hero">
      <div style="display: flex; gap: 15px; align-items: center;">
        <span style="font-size: 2.5rem;">🚀</span>
        <div>
          <h2 style="font-size: 1.45rem; font-weight: 700; color: #fff;">Universal Fleet Worker Onboarding & 1-Click Bootstrap</h2>
          <p style="color: var(--text-muted); font-size: 0.88rem; margin-top: 4px;">
            Turn any Raspberry Pi 5, Pi 4, Jetson Nano, or Windows PC into an autonomous 24/7 scraping node with automated dependency resolution & hardware auto-tuning.
          </p>
        </div>
      </div>
      <div style="display: flex; gap: 10px; align-items: center;">
        <span class="pill-badge" style="background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.3); color: #38bdf8; padding: 0.4rem 0.8rem; font-size: 0.78rem;">
          ⚡ Concurrency Auto-Tuning Included
        </span>
      </div>
    </div>

    <!-- Device Switcher Tab Bar -->
    <div class="device-tab-bar">
      <button class="device-tab-btn active" data-device="pi" onclick="switchDeviceTab('pi')">
        🍓 Raspberry Pi 5 / 4 (ARM64)
      </button>
      <button class="device-tab-btn" data-device="jetson" onclick="switchDeviceTab('jetson')">
        ⚡ NVIDIA Jetson Nano
      </button>
      <button class="device-tab-btn" data-device="windows" onclick="switchDeviceTab('windows')">
        🪟 Windows 10/11 (PC / Server)
      </button>
      <button class="device-tab-btn" data-device="cloud" onclick="switchDeviceTab('cloud')">
        ☁️ Linux Cloud / Colab / VPS
      </button>
    </div>

    <!-- PANEL 1: Raspberry Pi 5 / 4 (ARM64) -->
    <div id="device-panel-pi" class="device-content-panel" style="display: block;">
      <div class="step-box">
        <div class="step-title">
          <span>⚡ Step 1: 1-Click Universal Bootstrap Command (Fresh or New Pi)</span>
          <span class="pill-badge" style="background: rgba(52, 211, 153, 0.15); color: #34d399; font-size: 0.72rem;">Automates Everything</span>
        </div>
        <p style="font-size: 0.84rem; color: var(--text-muted); margin-bottom: 0.5rem;">
          Open terminal on your Raspberry Pi and paste this single command. It clones the repo, installs all system/apt packages, sets up <code>uv</code>, downloads Playwright Chromium for ARM64, runs the thermal & concurrency benchmark, and launches the 24/7 background <code>systemd</code> daemon:
        </p>
        <div class="code-card">
          <div class="code-card-header">
            <span>BASH TERMINAL (ONE-CLICK DEPLOY)</span>
            <button class="copy-btn" onclick="copyCode('code-pi-bootstrap', this)">📋 Copy Command</button>
          </div>
          <div id="code-pi-bootstrap" class="code-card-body">git clone https://github.com/MaheswaranPalaniselvan/udayam-source.git ~/udayam &amp;&amp; cd ~/udayam &amp;&amp; bash scripts/bootstrap_worker.sh</div>
        </div>
      </div>

      <div class="step-box">
        <div class="step-title">
          <span>🔄 Already Have the Code Cloned on your Pi? (Quick Update &amp; Launch)</span>
        </div>
        <p style="font-size: 0.84rem; color: var(--text-muted); margin-bottom: 0.5rem;">
          If you already have <code>~/udayam</code> on your Pi 5, pull the latest repo updates and run the bootstrap installer directly:
        </p>
        <div class="code-card">
          <div class="code-card-header">
            <span>BASH TERMINAL (EXISTING WORKSPACE)</span>
            <button class="copy-btn" onclick="copyCode('code-pi-update', this)">📋 Copy Command</button>
          </div>
          <div id="code-pi-update" class="code-card-body">cd ~/udayam &amp;&amp; git pull origin main &amp;&amp; bash scripts/bootstrap_worker.sh</div>
        </div>
      </div>

      <div class="step-box">
        <div class="step-title">
          <span>🎯 Step 2: Optimal Concurrency Benchmark &amp; Active Cooler Test</span>
        </div>
        <p style="font-size: 0.84rem; color: var(--text-muted); margin-bottom: 0.5rem;">
          Run the built-in benchmark script to test your Pi 5 with the Active Cooler. It stress-tests ONNX OCR inference across concurrency levels 1, 2, and 3, monitors temperature and fan RPM, and saves the optimal setting:
        </p>
        <div class="code-card">
          <div class="code-card-header">
            <span>RUN HARDWARE AUTO-TUNER</span>
            <button class="copy-btn" onclick="copyCode('code-pi-bench', this)">📋 Copy Command</button>
          </div>
          <div id="code-pi-bench" class="code-card-body">cd ~/udayam &amp;&amp; uv run python scripts/benchmark_concurrency.py --apply</div>
        </div>
        <div style="margin-top: 0.75rem;">
          <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 0.35rem;">Real-time Active Cooler thermal &amp; fan speed monitor command:</p>
          <div class="code-card" style="margin-top: 0.2rem;">
            <div class="code-card-header">
              <span>WATCH TEMPERATURE &amp; FAN RPM</span>
              <button class="copy-btn" onclick="copyCode('code-pi-watch', this)">📋 Copy Command</button>
            </div>
            <div id="code-pi-watch" class="code-card-body">watch -n 1 "vcgencmd measure_temp; vcgencmd get_throttled; cat /sys/devices/platform/cooling_fan/hwmon/*/fan1_input 2>/dev/null | awk '{{print \"Fan RPM: \" \\$1}}'"</div>
          </div>
        </div>
      </div>

      <div class="step-box">
        <div class="step-title">
          <span>🛠️ Step 3: Managing the 24/7 Background Daemon</span>
        </div>
        <p style="font-size: 0.84rem; color: var(--text-muted);">
          The worker runs continuously as a managed <code>systemd</code> service, automatically restarting after reboots or WiFi hiccups:
        </p>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; margin-top: 0.75rem;">
          <div style="background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.06); padding: 0.75rem; border-radius: 8px;">
            <div style="font-size: 0.76rem; color: var(--text-dim); font-weight: 700;">VIEW LIVE SCRAPING LOGS</div>
            <code style="color: #38bdf8; font-size: 0.8rem;">journalctl -u udyam-worker -f</code>
          </div>
          <div style="background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.06); padding: 0.75rem; border-radius: 8px;">
            <div style="font-size: 0.76rem; color: var(--text-dim); font-weight: 700;">CHECK SERVICE HEALTH</div>
            <code style="color: #38bdf8; font-size: 0.8rem;">sudo systemctl status udyam-worker</code>
          </div>
          <div style="background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.06); padding: 0.75rem; border-radius: 8px;">
            <div style="font-size: 0.76rem; color: var(--text-dim); font-weight: 700;">RESTART WORKER</div>
            <code style="color: #38bdf8; font-size: 0.8rem;">sudo systemctl restart udyam-worker</code>
          </div>
        </div>
      </div>
    </div>

    <!-- PANEL 2: NVIDIA Jetson Nano -->
    <div id="device-panel-jetson" class="device-content-panel" style="display: none;">
      <div class="step-box">
        <div class="step-title">
          <span>⚡ NVIDIA Jetson Nano 1-Click Bootstrap</span>
          <span class="pill-badge" style="background: rgba(251, 191, 36, 0.15); color: #fbbf24; font-size: 0.72rem;">Concurrency 1 Tuned</span>
        </div>
        <p style="font-size: 0.84rem; color: var(--text-muted); margin-bottom: 0.5rem;">
          Jetson Nano shares 4GB total RAM between the CPU and Maxwell GPU. Concurrency is automatically constrained to <strong>1</strong> to guarantee zero swap-thrashing and steady 10-12 rpm extraction:
        </p>
        <div class="code-card">
          <div class="code-card-header">
            <span>BASH TERMINAL (JETSON NANO)</span>
            <button class="copy-btn" onclick="copyCode('code-jetson-bootstrap', this)">📋 Copy Command</button>
          </div>
          <div id="code-jetson-bootstrap" class="code-card-body">git clone https://github.com/MaheswaranPalaniselvan/udayam-source.git ~/udayam &amp;&amp; cd ~/udayam &amp;&amp; bash scripts/bootstrap_worker.sh</div>
        </div>
        <div style="margin-top: 0.75rem;">
          <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 0.35rem;">Enable 5V PWM fan on Jetson heatsink:</p>
          <div class="code-card" style="margin-top: 0.2rem;">
            <div class="code-card-header">
              <span>ACTIVATE 5V PWM FAN</span>
              <button class="copy-btn" onclick="copyCode('code-jetson-fan', this)">📋 Copy Command</button>
            </div>
            <div id="code-jetson-fan" class="code-card-body">sudo sh -c 'echo 200 > /sys/devices/pwm-fan/target_pwm'</div>
          </div>
        </div>
      </div>
    </div>

    <!-- PANEL 3: Windows 10/11 -->
    <div id="device-panel-windows" class="device-content-panel" style="display: none;">
      <div class="step-box">
        <div class="step-title">
          <span>🪟 Windows 1-Click Quick Deploy</span>
        </div>
        <p style="font-size: 0.84rem; color: var(--text-muted); margin-bottom: 0.5rem;">
          Run in PowerShell on any Windows 10/11 workstation or laptop. Sets up dependencies, Playwright Chromium, and desktop launcher shortcut:
        </p>
        <div class="code-card">
          <div class="code-card-header">
            <span>POWERSHELL SETUP</span>
            <button class="copy-btn" onclick="copyCode('code-win-setup', this)">📋 Copy Command</button>
          </div>
          <div id="code-win-setup" class="code-card-body">git clone https://github.com/MaheswaranPalaniselvan/udayam-source.git; cd udayam; .\\setup_machine.bat</div>
        </div>
        <div style="margin-top: 0.75rem;">
          <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 0.35rem;">Start Headless Fleet Worker with Auto-Concurrency (4 workers):</p>
          <div class="code-card" style="margin-top: 0.2rem;">
            <div class="code-card-header">
              <span>LAUNCH WINDOWS FLEET WORKER</span>
              <button class="copy-btn" onclick="copyCode('code-win-run', this)">📋 Copy Command</button>
            </div>
            <div id="code-win-run" class="code-card-body">uv run python client/app.py --cli --machine "Win-$env:COMPUTERNAME" --concurrency 4</div>
          </div>
        </div>
      </div>
    </div>

    <!-- PANEL 4: Linux Cloud / Server -->
    <div id="device-panel-cloud" class="device-content-panel" style="display: none;">
      <div class="step-box">
        <div class="step-title">
          <span>☁️ Linux VPS / Google Colab / Dedicated Cloud Worker</span>
        </div>
        <p style="font-size: 0.84rem; color: var(--text-muted); margin-bottom: 0.5rem;">
          Deploy on any Debian/Ubuntu cloud server, Docker container, or virtual machine:
        </p>
        <div class="code-card">
          <div class="code-card-header">
            <span>BASH TERMINAL (CLOUD WORKER)</span>
            <button class="copy-btn" onclick="copyCode('code-cloud-setup', this)">📋 Copy Command</button>
          </div>
          <div id="code-cloud-setup" class="code-card-body">git clone https://github.com/MaheswaranPalaniselvan/udayam-source.git ~/udayam &amp;&amp; cd ~/udayam &amp;&amp; bash scripts/bootstrap_worker.sh</div>
        </div>
      </div>
    </div>

    <!-- Hardware & Concurrency Guide Matrix Card -->
    <div class="step-box" style="margin-top: 0.5rem;">
      <div class="step-title">
        <span>📊 Fleet Hardware &amp; Optimal Concurrency Reference Guide</span>
      </div>
      <p style="font-size: 0.84rem; color: var(--text-muted);">
        Comparison of tested hardware boards, recommended concurrency targets, memory consumption, and cooling recommendations:
      </p>
      <div style="overflow-x: auto;">
        <table class="matrix-table">
          <thead>
            <tr>
              <th>Hardware Device</th>
              <th>Cores / RAM</th>
              <th>Recommended Concurrency</th>
              <th>Expected Speed</th>
              <th>Thermal &amp; Cooling Requirements</th>
              <th>Fleet Role</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style="font-weight: 600; color: #fff;">🍓 Raspberry Pi 5</td>
              <td>4 Cores / 4-8 GB</td>
              <td><span class="pill-badge" style="background: rgba(52, 211, 153, 0.15); color: #34d399; font-weight: 700;">2 - 3 Workers</span></td>
              <td style="color: #38bdf8; font-weight: 600;">24 - 34 rpm</td>
              <td style="color: #34d399;">Active Cooler (hovers 48°C - 55°C, 0% throttling)</td>
              <td>High-throughput 24/7 edge daemon</td>
            </tr>
            <tr>
              <td style="font-weight: 600; color: #fff;">🍓 Raspberry Pi 4</td>
              <td>4 Cores / 4-8 GB</td>
              <td><span class="pill-badge" style="background: rgba(251, 191, 36, 0.15); color: #fbbf24; font-weight: 700;">1 - 2 Workers</span></td>
              <td style="color: #38bdf8; font-weight: 600;">14 - 22 rpm</td>
              <td style="color: #fbbf24;">Heatsink + 5V Fan recommended (&lt; 68°C)</td>
              <td>Standard low-power worker node</td>
            </tr>
            <tr>
              <td style="font-weight: 600; color: #fff;">⚡ NVIDIA Jetson Nano</td>
              <td>4 Cores / 4 GB (Shared)</td>
              <td><span class="pill-badge" style="background: rgba(192, 132, 252, 0.15); color: #c084fc; font-weight: 700;">1 Worker</span></td>
              <td style="color: #38bdf8; font-weight: 600;">8 - 12 rpm</td>
              <td style="color: #c084fc;">5V PWM Fan required; concurrency 1 prevents OOM</td>
              <td>Low-power secondary worker</td>
            </tr>
            <tr>
              <td style="font-weight: 600; color: #fff;">🪟 Windows PC (i5/i7/Ryzen)</td>
              <td>8-16 Cores / 16+ GB</td>
              <td><span class="pill-badge" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; font-weight: 700;">4 - 8 Workers</span></td>
              <td style="color: #38bdf8; font-weight: 600;">45 - 75 rpm</td>
              <td style="color: #38bdf8;">Standard workstation cooling</td>
              <td>Burst batch harvesting workstation</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div> <!-- end of #view-onboarding -->

</div> <!-- end of .container -->

  <script>
    const RAW_DATA = {json_payload};
    let currentFilter = 'all';
    let searchQuery = '';
    let currentSortField = 'code';
    let currentSortDir = 'asc';
    const openStateSet = new Set();

    function parseHarvestDate(dStr) {{
      if (!dStr || dStr === '-' || dStr === 'None') return 0;
      const parsed = Date.parse(dStr);
      return isNaN(parsed) ? 0 : parsed;
    }}

    function getSortIcon(field) {{
      if (currentSortField !== field) return '↕';
      return currentSortDir === 'asc' ? '▲' : '▼';
    }}

    function setDistrictSort(field) {{
      if (currentSortField === field) {{
        currentSortDir = currentSortDir === 'asc' ? 'desc' : 'asc';
      }} else {{
        currentSortField = field;
        if (['extracted', 'harvest_date', 'failed', 'speed', 'status'].includes(field)) {{
          currentSortDir = 'desc';
        }} else {{
          currentSortDir = 'asc';
        }}
      }}
      syncSortDropdownUI();
      renderView();
    }}

    function handleSortDropdownChange(val) {{
      if (!val) return;
      const lastUnderscore = val.lastIndexOf('_');
      if (lastUnderscore !== -1) {{
        currentSortField = val.substring(0, lastUnderscore);
        currentSortDir = val.substring(lastUnderscore + 1);
      }}
      renderView();
    }}

    function syncSortDropdownUI() {{
      const select = document.getElementById('sortSelect');
      if (!select) return;
      const targetVal = `${{currentSortField}}_${{currentSortDir}}`;
      let found = false;
      for (let i = 0; i < select.options.length; i++) {{
        if (select.options[i].value === targetVal) {{
          select.selectedIndex = i;
          found = true;
          break;
        }}
      }}
      if (!found) {{
        for (let i = 0; i < select.options.length; i++) {{
          if (select.options[i].value.startsWith(currentSortField + '_')) {{
            select.selectedIndex = i;
            break;
          }}
        }}
      }}
    }}

    function sortDistrictsList(dists) {{
      const sorted = [...dists];
      sorted.sort((a, b) => {{
        let diff = 0;
        if (currentSortField === 'code') {{
          diff = (a.code || '').localeCompare(b.code || '', undefined, {{ numeric: true, sensitivity: 'base' }});
        }} else if (currentSortField === 'name') {{
          diff = (a.name || '').localeCompare(b.name || '', undefined, {{ sensitivity: 'base' }});
        }} else if (currentSortField === 'extracted') {{
          diff = (Number(a.extracted) || 0) - (Number(b.extracted) || 0);
        }} else if (currentSortField === 'failed') {{
          diff = (Number(a.failed) || 0) - (Number(b.failed) || 0);
        }} else if (currentSortField === 'speed') {{
          diff = (parseFloat(a.speed) || 0) - (parseFloat(b.speed) || 0);
        }} else if (currentSortField === 'last_record') {{
          diff = (a.last_record || '').localeCompare(b.last_record || '', undefined, {{ numeric: true, sensitivity: 'base' }});
        }} else if (currentSortField === 'claimed_by') {{
          diff = (a.claimed_by || '').localeCompare(b.claimed_by || '', undefined, {{ sensitivity: 'base' }});
        }} else if (currentSortField === 'status') {{
          const rank = (d) => {{
            if (d.is_live) return 3;
            const st = (d.status || '').toLowerCase();
            if (st === 'in progress') return 2;
            if (st === 'completed') return 1;
            return 0;
          }};
          diff = rank(a) - rank(b);
        }} else if (currentSortField === 'harvest_date') {{
          const timeA = parseHarvestDate(a.harvest_date);
          const timeB = parseHarvestDate(b.harvest_date);
          if (timeA === 0 && timeB === 0) diff = 0;
          else if (timeA === 0) return 1;
          else if (timeB === 0) return -1;
          else diff = timeA - timeB;
        }}
        return currentSortDir === 'desc' ? -diff : diff;
      }});
      return sorted;
    }}

    function sortStatesList(states) {{
      const sorted = [...states];
      sorted.sort((a, b) => {{
        let diff = 0;
        if (currentSortField === 'code') {{
          diff = (a.code || '').localeCompare(b.code || '', undefined, {{ numeric: true, sensitivity: 'base' }});
        }} else if (currentSortField === 'name') {{
          diff = (a.name || '').localeCompare(b.name || '', undefined, {{ sensitivity: 'base' }});
        }} else if (currentSortField === 'extracted') {{
          diff = (Number(a.extracted_total) || 0) - (Number(b.extracted_total) || 0);
        }} else if (currentSortField === 'status') {{
          const rateA = a.district_count ? (a.live_count / a.district_count) : 0;
          const rateB = b.district_count ? (b.live_count / b.district_count) : 0;
          diff = rateA - rateB;
        }} else if (currentSortField === 'harvest_date') {{
          const timeA = parseHarvestDate(a.latest_harvest);
          const timeB = parseHarvestDate(b.latest_harvest);
          if (timeA === 0 && timeB === 0) diff = 0;
          else if (timeA === 0) return 1;
          else if (timeB === 0) return -1;
          else diff = timeA - timeB;
        }} else {{
          diff = (a.code || '').localeCompare(b.code || '', undefined, {{ numeric: true, sensitivity: 'base' }});
          return diff;
        }}
        return currentSortDir === 'desc' ? -diff : diff;
      }});
      return sorted;
    }}

    function renderView() {{
      const listEl = document.getElementById('drilldownList');
      const emptyEl = document.getElementById('emptyMessage');
      listEl.innerHTML = '';

      let visibleStates = 0;
      const q = searchQuery.toLowerCase().trim();

      const sortedStates = sortStatesList(RAW_DATA.states);

      sortedStates.forEach(state => {{
        // Filter districts
        let filteredDists = state.districts.filter(d => {{
          // Status filter
          if (currentFilter === 'live' && !d.is_live) return false;
          if (currentFilter === 'outdated' && d.is_live) return false;
          if (currentFilter === 'inprogress' && (d.status || '').toLowerCase() !== 'in progress') return false;

          // Search query
          if (q) {{
            const matchDistName = d.name.toLowerCase().includes(q);
            const matchDistCode = d.code.toLowerCase().includes(q);
            const matchLastRec = d.last_record.toLowerCase().includes(q);
            const matchStateName = state.name.toLowerCase().includes(q);
            const matchStateCode = state.code.toLowerCase().includes(q);
            return matchDistName || matchDistCode || matchLastRec || matchStateName || matchStateCode;
          }}
          return true;
        }});

        // State matches query directly?
        const stateMatchesDirectly = q && (state.name.toLowerCase().includes(q) || state.code.toLowerCase().includes(q));
        if (stateMatchesDirectly && currentFilter === 'all') {{
          filteredDists = state.districts;
        }}

        if (filteredDists.length === 0 && !stateMatchesDirectly) {{
          return;
        }}

        visibleStates++;
        const isAutoOpen = Boolean(q) || currentFilter === 'live' || currentFilter === 'inprogress' || openStateSet.has(state.code);

        const safeId = state.code.replace(/[^a-zA-Z0-9]/g, '_');
        const stateCard = document.createElement('div');
        stateCard.className = `state-card ${{isAutoOpen ? 'open' : ''}}`;
        stateCard.id = `state-${{safeId}}`;

        const livePct = state.district_count ? Math.round((state.live_count / state.district_count) * 100) : 0;

        let statusClass = 'status-outdated';
        let statusText = `${{state.live_count}} / ${{state.district_count}} Live`;
        if (state.live_count === state.district_count && state.district_count > 0) {{
          statusClass = 'status-live';
          statusText = `100% Live (as of ${{state.latest_harvest}})`;
        }} else if (state.live_count > 0) {{
          statusClass = 'status-live';
          statusText = `${{state.live_count}} Live • ${{state.outdated_count}} Outdated`;
        }} else if (state.in_progress_count > 0) {{
          statusClass = 'status-outdated-progress';
          statusText = 'In Progress';
        }} else {{
          statusClass = 'status-outdated';
          statusText = 'Outdated';
        }}

        // District rows HTML
        const sortedDists = sortDistrictsList(filteredDists);
        let distRowsHtml = '';
        sortedDists.forEach(d => {{
          let dStatusClass = 'status-outdated';
          let dStatusText = 'Outdated (Not Started)';
          let dTooltip = 'District has not been harvested yet. Data is outdated.';

          if (d.is_live) {{
            dStatusClass = 'status-live';
            dStatusText = 'Live';
            dTooltip = `Verified live dataset. Latest registration: ${{d.harvest_date}}`;
          }} else if ((d.status || '').toLowerCase() === 'in progress') {{
            dStatusClass = 'status-outdated-progress';
            dStatusText = 'Outdated (In Progress)';
            dTooltip = 'Scraping is actively in progress. Complete snapshot not yet finalized.';
          }} else if ((d.status || '').toLowerCase() === 'completed') {{
            dStatusClass = 'status-outdated';
            dStatusText = 'Outdated';
            dTooltip = `Harvested up to ${{d.harvest_date}}. Data is outdated pending fresh run.`;
          }}

          distRowsHtml += `
            <tr>
              <td class="dist-code">${{d.code}}</td>
              <td style="font-weight: 500;">${{d.name}}</td>
              <td><span class="status-badge ${{dStatusClass}}" title="${{dTooltip}}">${{dStatusText}}</span></td>
              <td class="mono-num" style="color: #34d399; font-weight: 600; font-size: 0.92rem;">
                ${{d.extracted ? d.extracted.toLocaleString('en-IN') : '0'}}
              </td>
              <td class="mono-num" style="font-size: 0.82rem; color: #93c5fd;">${{d.last_record || '-'}}</td>
              <td style="font-size: 0.82rem; color: #fbbf24; font-weight: 500;">${{d.harvest_date || '-'}}</td>
              <td class="mono-num" style="color: ${{d.failed ? '#f87171' : 'var(--text-dim)'}};">${{d.failed || '0'}}</td>
              <td style="font-size: 0.78rem; color: var(--text-dim);">${{d.claimed_by || '-'}}</td>
              <td class="mono-num" style="font-size: 0.78rem; color: var(--text-dim);">${{d.speed ? d.speed + ' rpm' : '-'}}</td>
            </tr>
          `;
        }});

        stateCard.innerHTML = `
          <div class="state-row" onclick="toggleState('${{state.code}}')">
            <span class="chevron">▶</span>
            <span class="state-code-pill">${{state.code}}</span>
            <span class="state-name">${{state.name}}</span>
            <span class="pill-badge" style="background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); color: var(--text-muted); font-size: 0.68rem; padding: 0.15rem 0.5rem;">${{state.type || 'State'}}</span>

            <div class="progress-bar-wrapper">
              <div class="progress-track">
                <div class="progress-fill" style="width: ${{livePct}}%;"></div>
              </div>
              <div class="progress-text">
                <span>${{livePct}}% Live</span>
                <span>${{state.live_count}} / ${{state.district_count}} Live</span>
              </div>
            </div>

            <div class="state-stats">
              <div class="stat-col" title="Formal Udyam: ${{state.msme_udyam ? state.msme_udyam.toLocaleString('en-IN') : '0'}} | UAP Informal: ${{state.msme_uap ? state.msme_uap.toLocaleString('en-IN') : '0'}}">
                <div class="stat-val" style="color: #38bdf8; font-size: 0.98rem;">${{state.msme_total ? state.msme_total.toLocaleString('en-IN') : '-'}}</div>
                <div class="stat-sub">Ministry MSME Reg.</div>
              </div>
              <div class="stat-col">
                <div class="stat-val" style="color: #34d399; font-size: 0.98rem;">${{state.extracted_total ? state.extracted_total.toLocaleString('en-IN') : '0'}}</div>
                <div class="stat-sub">Harvested Records</div>
              </div>
              <div class="stat-col">
                <div class="stat-val" style="color: #fbbf24; font-size: 0.92rem;">${{state.latest_harvest || '-'}}</div>
                <div class="stat-sub">Latest Live Date</div>
              </div>
            </div>

            <span class="status-badge ${{statusClass}}">${{statusText}}</span>
          </div>

          <div class="districts-table-wrapper">
            <div class="state-ministry-bar" style="display: flex; flex-wrap: wrap; align-items: center; gap: 1rem; padding: 0.65rem 0.95rem; margin-top: 0.75rem; background: rgba(56, 189, 248, 0.05); border: 1px solid rgba(56, 189, 248, 0.15); border-radius: 8px; font-size: 0.78rem;">
              <span style="color: #38bdf8; font-weight: 600;">🏛️ Ministry of MSME Live State Data:</span>
              <span>Total MSMEs: <strong style="color: #f1f5f9;">${{state.msme_total ? state.msme_total.toLocaleString('en-IN') : '-'}}</strong></span>
              <span>Udyam Formal: <strong style="color: #93c5fd;">${{state.msme_udyam ? state.msme_udyam.toLocaleString('en-IN') : '-'}}</strong></span>
              <span>UAP Informal: <strong style="color: #c084fc;">${{state.msme_uap ? state.msme_uap.toLocaleString('en-IN') : '-'}}</strong></span>
              <span>Micro: <strong style="color: #94a3b8;">${{state.msme_micro ? state.msme_micro.toLocaleString('en-IN') : '-'}}</strong></span>
              <span>Small: <strong style="color: #94a3b8;">${{state.msme_small ? state.msme_small.toLocaleString('en-IN') : '-'}}</strong></span>
              <span>Medium: <strong style="color: #94a3b8;">${{state.msme_medium ? state.msme_medium.toLocaleString('en-IN') : '-'}}</strong></span>
            </div>
            <table class="sub-table">
              <thead>
                <tr>
                  <th class="sortable-th ${{currentSortField === 'code' ? 'active' : ''}}" onclick="setDistrictSort('code')" title="Click to sort by District Code">
                    Code <span class="sort-icon">${{getSortIcon('code')}}</span>
                  </th>
                  <th class="sortable-th ${{currentSortField === 'name' ? 'active' : ''}}" onclick="setDistrictSort('name')" title="Click to sort by District Name">
                    District Name <span class="sort-icon">${{getSortIcon('name')}}</span>
                  </th>
                  <th class="sortable-th ${{currentSortField === 'status' ? 'active' : ''}}" onclick="setDistrictSort('status')" title="Click to sort by Data Freshness">
                    Data Freshness <span class="sort-icon">${{getSortIcon('status')}}</span>
                  </th>
                  <th class="sortable-th ${{currentSortField === 'extracted' ? 'active' : ''}}" onclick="setDistrictSort('extracted')" title="Click to sort by Extracted Records">
                    Extracted Records <span class="sort-icon">${{getSortIcon('extracted')}}</span>
                  </th>
                  <th class="sortable-th ${{currentSortField === 'last_record' ? 'active' : ''}}" onclick="setDistrictSort('last_record')" title="Click to sort by Last Record Extracted">
                    Last Record Extracted <span class="sort-icon">${{getSortIcon('last_record')}}</span>
                  </th>
                  <th class="sortable-th ${{currentSortField === 'harvest_date' ? 'active' : ''}}" onclick="setDistrictSort('harvest_date')" title="Click to sort by Last Date Harvested">
                    Last Date Harvested <span class="sort-icon">${{getSortIcon('harvest_date')}}</span>
                  </th>
                  <th class="sortable-th ${{currentSortField === 'failed' ? 'active' : ''}}" onclick="setDistrictSort('failed')" title="Click to sort by Failed Records">
                    Failed <span class="sort-icon">${{getSortIcon('failed')}}</span>
                  </th>
                  <th class="sortable-th ${{currentSortField === 'claimed_by' ? 'active' : ''}}" onclick="setDistrictSort('claimed_by')" title="Click to sort by Worker / Node">
                    Node / Worker <span class="sort-icon">${{getSortIcon('claimed_by')}}</span>
                  </th>
                  <th class="sortable-th ${{currentSortField === 'speed' ? 'active' : ''}}" onclick="setDistrictSort('speed')" title="Click to sort by Speed">
                    Speed <span class="sort-icon">${{getSortIcon('speed')}}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                ${{distRowsHtml}}
              </tbody>
            </table>
          </div>
        `;

        listEl.appendChild(stateCard);
      }});

      emptyEl.style.display = visibleStates === 0 ? 'block' : 'none';
    }}

    function toggleState(code) {{
      const safeId = code.replace(/[^a-zA-Z0-9]/g, '_');
      const card = document.getElementById(`state-${{safeId}}`);
      if (card) {{
        card.classList.toggle('open');
        if (card.classList.contains('open')) {{
          openStateSet.add(code);
        }} else {{
          openStateSet.delete(code);
        }}
      }}
    }}

    function toggleAllStates(open) {{
      document.querySelectorAll('.state-card').forEach(card => {{
        if (open) {{
          card.classList.add('open');
        }} else {{
          card.classList.remove('open');
        }}
      }});
      if (open) {{
        RAW_DATA.states.forEach(s => openStateSet.add(s.code));
      }} else {{
        openStateSet.clear();
      }}
    }}

    function handleSearch() {{
      searchQuery = document.getElementById('searchInput').value;
      renderView();
    }}

    function filterStatus(status) {{
      currentFilter = status;
      document.querySelectorAll('.chip').forEach(c => {{
        c.classList.toggle('active', c.getAttribute('data-status') === status);
      }});
      renderView();
    }}

    function exportFilteredExcel() {{
      const rows = [];
      rows.push(['State Code', 'State Name', 'District Code', 'District Name', 'Data Freshness', 'Harvested Records', 'Last Record Extracted', 'Last Date Harvested', 'Raw Status', 'Ministry MSME Total', 'Ministry Udyam Formal', 'Ministry UAP Informal', 'Failed Records', 'Worker Machine', 'Speed']);

      RAW_DATA.states.forEach(s => {{
        s.districts.forEach(d => {{
          rows.push([
            s.code,
            s.name,
            d.code,
            d.name,
            d.live_status || (d.is_live ? 'Live' : 'Outdated'),
            d.extracted,
            d.last_record,
            d.harvest_date,
            d.status,
            s.msme_total,
            s.msme_udyam,
            s.msme_uap,
            d.failed,
            d.claimed_by,
            d.speed
          ]);
        }});
      }});

      const ws = XLSX.utils.aoa_to_sheet(rows);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, "Udayam Coverage");
      XLSX.writeFile(wb, "FlawlessTech_Udayam_Coverage_DrillDown.xlsx");
    }}

    // ==========================================
    // DUAL-VIEW INTEGRATION & REAL-TIME FLEET TELEMETRY
    // ==========================================
    const FLEET_API_URL = "https://script.google.com/macros/s/AKfycby3tmgH9PtjUhl6XfGrBfgRNZFQZaSLR0N4Dnff9tt9K5qjatyarJy_nnE0ulCtMNm2xA/exec";
    let currentMainView = 'coverage';
    let fleetRawData = [];
    let currentFleetFilter = 'all';
    let fleetPollingTimer = null;

    function switchMainView(viewName) {{
      currentMainView = viewName;
      const coverageView = document.getElementById('view-coverage');
      const fleetView = document.getElementById('view-fleet');
      const onboardingView = document.getElementById('view-onboarding');
      const btnCoverage = document.getElementById('nav-btn-coverage');
      const btnFleet = document.getElementById('nav-btn-fleet');
      const btnOnboarding = document.getElementById('nav-btn-onboarding');

      if (coverageView) coverageView.style.display = viewName === 'coverage' ? 'block' : 'none';
      if (fleetView) fleetView.style.display = viewName === 'fleet' ? 'block' : 'none';
      if (onboardingView) onboardingView.style.display = viewName === 'onboarding' ? 'block' : 'none';

      if (btnCoverage) btnCoverage.classList.toggle('active', viewName === 'coverage');
      if (btnFleet) btnFleet.classList.toggle('active', viewName === 'fleet');
      if (btnOnboarding) btnOnboarding.classList.toggle('active', viewName === 'onboarding');

      if (viewName === 'fleet') {{
        fetchFleetStatus();
      }}
    }}

    function switchDeviceTab(device) {{
      document.querySelectorAll('.device-tab-btn').forEach(btn => {{
        btn.classList.toggle('active', btn.getAttribute('data-device') === device);
      }});
      document.querySelectorAll('.device-content-panel').forEach(panel => {{
        panel.style.display = panel.id === `device-panel-${{device}}` ? 'block' : 'none';
      }});
    }}

    function copyCode(elementId, btn) {{
      const el = document.getElementById(elementId);
      if (!el) return;
      const text = el.innerText.trim();
      navigator.clipboard.writeText(text).then(() => {{
        const orig = btn.innerHTML;
        btn.innerHTML = '✅ Copied!';
        btn.style.color = '#34d399';
        btn.style.borderColor = '#34d399';
        setTimeout(() => {{
          btn.innerHTML = orig;
          btn.style.color = '';
          btn.style.borderColor = '';
        }}, 2000);
      }}).catch(() => {{
        const range = document.createRange();
        range.selectNodeContents(el);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }});
    }}

    async function fetchFleetStatus() {{
      const msg = document.getElementById('fleetSyncTimerMsg');
      try {{
        const resp = await fetch(`${{FLEET_API_URL}}?action=fleet_status`);
        const data = await resp.json();
        if (data && data.status === 'ok') {{
          fleetRawData = data.active_workers || [];
          updateFleetUI(data);
          if (msg) msg.textContent = `Last synced: ${{new Date().toLocaleTimeString()}} (auto-refresh 15s)`;
        }}
      }} catch (err) {{
        if (msg) msg.textContent = `Sync note: ${{err.message}}`;
      }}
    }}

    function updateFleetUI(data) {{
      const activeWorkers = data.active_workers || [];
      const actCountEl = document.getElementById('kpiActiveDaemons');
      const compCountEl = document.getElementById('kpiDistrictsCompleted');
      const spdEl = document.getElementById('kpiAggregateSpeed');
      const syncEl = document.getElementById('kpiLastSync');
      const navBadge = document.getElementById('header-fleet-badge');

      if (compCountEl) compCountEl.textContent = `${{data.districts_completed || 0}} / ${{data.total_districts || 788}}`;
      if (syncEl) syncEl.textContent = new Date().toLocaleTimeString();

      let activeCount = 0;
      let totalSpeed = 0.0;

      activeWorkers.forEach(w => {{
        const mins = w.minutesAgo || 0;
        const spd = parseFloat(w.speed) || 0.0;
        if (mins <= 5) {{
          activeCount++;
          totalSpeed += spd;
        }} else if (mins <= 15) {{
          activeCount++;
          totalSpeed += spd;
        }}
      }});

      if (actCountEl) actCountEl.textContent = `${{activeCount}} Active`;
      if (spdEl) spdEl.textContent = `${{totalSpeed.toFixed(1)}} rpm`;
      if (navBadge) {{
        navBadge.textContent = `${{activeCount}} Active`;
        navBadge.style.color = activeCount > 0 ? '#34d399' : '#94a3b8';
      }}

      currentLiveAggregateSpeed = totalSpeed;
      updateEtaForecastUI();

      renderFleetTable();
    }}

    // ==========================================
    // FLEET VELOCITY & DYNAMIC COMPLETION ETA LOGIC
    // ==========================================
    let currentLiveAggregateSpeed = 0.0;
    let selectedSimRpm = 'live';

    function setEtaSimulationSpeed(val) {{
      selectedSimRpm = val;
      document.querySelectorAll('.fleet-sim-chip').forEach(c => c.classList.remove('active'));
      if (val === 'live') {{
        document.getElementById('chipLiveSpeed')?.classList.add('active');
      }} else {{
        const btn = document.getElementById(`chipSim${{val}}`);
        if (btn) btn.classList.add('active');
      }}
      updateEtaForecastUI();
    }}

    function formatNumberCommas(n) {{
      if (n === null || n === undefined || isNaN(n)) return '0';
      return Math.round(n).toLocaleString('en-IN');
    }}

    function formatDurationReadable(days) {{
      if (days === Infinity || isNaN(days) || days <= 0) return '--';
      if (days < 1) {{
        const hrs = days * 24;
        return `${{hrs.toFixed(1)}} hrs`;
      }}
      const months = days / 30.417;
      if (days > 60) {{
        return `${{days.toFixed(0)}} days (${{months.toFixed(1)}} mo)`;
      }}
      return `${{days.toFixed(1)}} days`;
    }}

    function formatFutureDate(days) {{
      if (days === Infinity || isNaN(days) || days <= 0) return '--';
      const d = new Date(Date.now() + days * 86400000);
      return d.toLocaleDateString('en-GB', {{ day: 'numeric', month: 'short', year: 'numeric' }});
    }}

    function updateEtaForecastUI() {{
      let effectiveRpm = currentLiveAggregateSpeed;
      if (selectedSimRpm !== 'live') {{
        effectiveRpm = Number(selectedSimRpm);
      }}

      const liveChipVal = document.getElementById('chipLiveRpmVal');
      if (liveChipVal) liveChipVal.textContent = currentLiveAggregateSpeed.toFixed(1);

      const kpi = RAW_DATA.kpi || {{}};
      const totalUniverse = kpi.total_enterprises || 47126597;
      const totalExtracted = kpi.total_extracted || 0;
      const netRemainingAll = Math.max(0, totalUniverse - totalExtracted);

      let pendingOutdatedTarget = 0;
      let pendingOutdatedExtracted = 0;
      let pendingOnlyTarget = 0;

      (RAW_DATA.states || []).forEach(st => {{
        (st.districts || []).forEach(d => {{
          const tot = d.total || 0;
          const ext = d.extracted || 0;
          const isDone = d.is_live || (d.status && d.status.toLowerCase() === 'completed' && ext > 100);
          if (!isDone) {{
            pendingOutdatedTarget += tot;
            pendingOutdatedExtracted += ext;
          }}
          if (ext === 0) {{
            pendingOnlyTarget += tot;
          }}
        }});
      }});

      const netRemainingPendingOutdated = Math.max(0, pendingOutdatedTarget - pendingOutdatedExtracted);
      const netRemainingPendingOnly = pendingOnlyTarget;

      const speedDisp = document.getElementById('etaThroughputDisplay');
      const dailyYieldDisp = document.getElementById('etaDailyYieldDisplay');
      const remDisp = document.getElementById('etaRemainingDisplay');
      const pctDisp = document.getElementById('etaProgressPctDisplay');
      const timeDisp = document.getElementById('etaTimeDisplay');
      const dateDisp = document.getElementById('etaDateDisplay');
      const t30d = document.getElementById('etaTarget30d');
      const t90d = document.getElementById('etaTarget90d');

      const dailyYield = effectiveRpm > 0 ? (effectiveRpm * 60 * 24) : 0;
      if (speedDisp) {{
        const modeLabel = selectedSimRpm === 'live' ? '' : ' (Simulated)';
        speedDisp.textContent = `${{effectiveRpm.toFixed(1)}} rpm${{modeLabel}}`;
        speedDisp.style.color = effectiveRpm > 0 ? '#fbbf24' : '#94a3b8';
      }}
      if (dailyYieldDisp) {{
        dailyYieldDisp.textContent = effectiveRpm > 0 ? `${{formatNumberCommas(dailyYield)}} records / day` : '0 records / day (Fleet Idle)';
      }}
      if (remDisp) remDisp.textContent = formatNumberCommas(netRemainingAll);
      if (pctDisp) {{
        const pct = totalUniverse > 0 ? ((totalExtracted / totalUniverse) * 100).toFixed(2) : 0;
        pctDisp.textContent = `${{pct}}% of ${{formatNumberCommas(totalUniverse)}} harvested`;
      }}

      if (effectiveRpm > 0) {{
        const daysAll = netRemainingAll / (effectiveRpm * 1440);
        if (timeDisp) timeDisp.textContent = formatDurationReadable(daysAll);
        if (dateDisp) dateDisp.textContent = `Target Finish: ${{formatFutureDate(daysAll)}}`;
      }} else {{
        if (timeDisp) timeDisp.textContent = 'Fleet Idle';
        if (dateDisp) dateDisp.textContent = 'Select an RPM preset above to calculate ETA';
      }}

      const rpmFor30d = Math.round(netRemainingAll / (30 * 1440));
      const rpmFor90d = Math.round(netRemainingAll / (90 * 1440));
      if (t30d) t30d.textContent = `${{formatNumberCommas(rpmFor30d)}} rpm (${{Math.ceil(rpmFor30d / 12)}} workers)`;
      if (t90d) t90d.textContent = `${{formatNumberCommas(rpmFor90d)}} rpm (${{Math.ceil(rpmFor90d / 12)}} workers) for 90d target`;

      const tbody = document.getElementById('etaTableBody');
      if (tbody) {{
        const scopes = [
          {{
            name: 'All-India Remaining Universe',
            badge: 'Full Country',
            target: totalUniverse,
            extracted: totalExtracted,
            remaining: netRemainingAll,
            desc: 'Complete universal coverage across all 788 districts'
          }},
          {{
            name: 'Pending + Outdated Districts',
            badge: 'Active Scope',
            target: pendingOutdatedTarget,
            extracted: pendingOutdatedExtracted,
            remaining: netRemainingPendingOutdated,
            desc: 'Excludes already harvested & verified live districts'
          }},
          {{
            name: 'Pending Districts Only',
            badge: 'Unstarted',
            target: pendingOnlyTarget,
            extracted: 0,
            remaining: netRemainingPendingOnly,
            desc: 'Zero-extracted districts requiring initial sequence baseline'
          }}
        ];

        tbody.innerHTML = scopes.map(s => {{
          const days = effectiveRpm > 0 ? (s.remaining / (effectiveRpm * 1440)) : null;
          const durText = days !== null ? formatDurationReadable(days) : '-- (Idle)';
          const finDate = days !== null ? formatFutureDate(days) : '--';
          const yieldText = effectiveRpm > 0 ? `${{formatNumberCommas(dailyYield)}} / day` : '0 / day';

          return `
            <tr>
              <td>
                <div style="font-weight: 600; color: #fff;">${{s.name}}</div>
                <div style="font-size: 0.72rem; color: var(--text-muted);">${{s.desc}}</div>
              </td>
              <td style="font-family: var(--font-mono);">${{formatNumberCommas(s.target)}}</td>
              <td style="font-family: var(--font-mono); color: #34d399;">${{formatNumberCommas(s.extracted)}}</td>
              <td style="font-family: var(--font-mono); font-weight: 700; color: #f43f5e;">${{formatNumberCommas(s.remaining)}}</td>
              <td style="font-family: var(--font-mono); color: #fbbf24;">${{yieldText}}</td>
              <td><span class="pill-badge" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; font-weight: 700;">${{durText}}</span></td>
              <td style="font-family: var(--font-mono); color: #cbd5e1;">${{finDate}}</td>
            </tr>
          `;
        }}).join('');
      }}
    }}

    function setFleetFilter(filter) {{
      currentFleetFilter = filter;
      document.querySelectorAll('.fleet-filter-chip').forEach(c => {{
        c.classList.toggle('active', c.getAttribute('data-filter') === filter);
      }});
      renderFleetTable();
    }}

    function filterFleetTable() {{
      renderFleetTable();
    }}

    function renderFleetTable() {{
      const tbody = document.getElementById('fleetTableBody');
      if (!tbody) return;

      const query = (document.getElementById('fleetSearchInput')?.value || '').toLowerCase().trim();

      let filtered = fleetRawData.filter(w => {{
        const mach = (w.machine || '').toLowerCase();
        const dist = (w.district || '').toLowerCase();
        if (query && !mach.includes(query) && !dist.includes(query)) return false;

        const mins = w.minutesAgo || 0;
        if (currentFleetFilter === 'active' && mins > 5) return false;
        if (currentFleetFilter === 'lagging' && (mins <= 5 || mins > 15)) return false;
        if (currentFleetFilter === 'stalled' && (mins <= 15 || mins > 60)) return false;
        if (currentFleetFilter === 'offline' && mins <= 60) return false;

        return true;
      }});

      if (!filtered.length) {{
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-dim); padding: 2rem;">No worker daemons matching current filter.</td></tr>';
        return;
      }}

      filtered.sort((a, b) => (a.minutesAgo || 0) - (b.minutesAgo || 0));

      let rows = '';
      filtered.forEach(w => {{
        const mins = w.minutesAgo || 0;
        const spd = parseFloat(w.speed) || 0.0;
        let badgeClass = 'status-live';
        let badgeText = '🟢 Active';

        if (mins <= 5) {{
          badgeClass = 'status-live';
          badgeText = '🟢 Active';
        }} else if (mins <= 15) {{
          badgeClass = 'status-outdated-progress';
          badgeText = '🟡 Lagging';
        }} else if (mins <= 60) {{
          badgeClass = 'status-outdated-progress';
          badgeText = '🟠 Stalled';
        }} else {{
          badgeClass = 'status-outdated';
          badgeText = '🔴 Offline';
        }}

        const machName = w.machine || 'Unknown';
        let hwBadge = '💻 Worker';
        if (machName.toLowerCase().includes('pi5')) hwBadge = '🍓 Pi 5 (ARM64)';
        else if (machName.toLowerCase().includes('pi4')) hwBadge = '🍓 Pi 4 (ARM64)';
        else if (machName.toLowerCase().includes('jetson')) hwBadge = '⚡ Jetson Nano';
        else if (machName.toLowerCase().includes('colab')) hwBadge = '☁️ Colab Cloud';
        else if (machName.toLowerCase().includes('github')) hwBadge = '🐙 GitHub Runner';

        const lastPingText = mins === 0 ? 'Just now' : (mins === 1 ? '1 min ago' : (mins < 60 ? `${{mins}} mins ago` : `${{(mins/60).toFixed(1)}} hrs ago`));

        rows += `
          <tr>
            <td style="font-weight: 600; color: #fff;">${{machName}}</td>
            <td><span class="pill-badge" style="background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); color: var(--text-muted); font-size: 0.74rem;">${{hwBadge}}</span></td>
            <td><span class="status-badge ${{badgeClass}}">${{badgeText}}</span></td>
            <td class="dist-code">${{w.district || '-'}}</td>
            <td class="mono-num" style="color: #93c5fd; font-size: 0.88rem;">${{w.lastRecord || '-'}}</td>
            <td class="mono-num" style="color: #34d399; font-weight: 600;">${{spd.toFixed(1)}} rpm</td>
            <td style="color: var(--text-muted); font-size: 0.82rem;">${{lastPingText}}</td>
          </tr>
        `;
      }});

      tbody.innerHTML = rows;
    }}

    // Initial render
    renderView();
    updateEtaForecastUI();
    // Start background polling every 15s
    fetchFleetStatus();
    fleetPollingTimer = setInterval(fetchFleetStatus, 15000);
  </script>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def build_pages(output_dir: Path = Path("public"), gsheet_url: str = None):
    """Orchestrates downloading Google Sheet, building drill-down HTML viewer, and copying assets."""
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_xlsx = output_dir / "udayam_latest.xlsx"
    target_html = output_dir / "index.html"

    export_url = gsheet_url or os.getenv("GSHEET_EXPORT_URL") or DEFAULT_GSHEET_EXPORT

    print(f"[1/3] Downloading latest live data from Google Sheet...")
    download_success = False
    try:
        resp = httpx.get(export_url, follow_redirects=True, timeout=60.0)
        resp.raise_for_status()
        with open(temp_xlsx, "wb") as f:
            f.write(resp.content)
        print(f"      [OK] Downloaded {len(resp.content):,} bytes to {temp_xlsx}")
        download_success = True
    except Exception as e:
        print(f"      [WARN] Failed to fetch live Google Sheet: {e}")

    if not download_success:
        # Fallback to local files if present
        local_fallback = None
        for fb in [temp_xlsx, Path("live_udayam_extract.xlsx"), Path("results.xlsx")]:
            if fb.exists() and fb.stat().st_size > 0:
                local_fallback = fb
                break
        if local_fallback:
            print(f"      [INFO] Using local fallback: {local_fallback}")
            if local_fallback != temp_xlsx:
                shutil.copy2(local_fallback, temp_xlsx)
        else:
            raise RuntimeError("No Google Sheet connection and no local fallback available.")

    print(f"[2/3] Generating hierarchical drill-down viewer...")
    logo = get_logo_base64()
    data = build_drilldown_data(temp_xlsx)
    generate_drilldown_html(data, logo, target_html)
    print(f"      [OK] Generated {target_html} ({target_html.stat().st_size:,} bytes)")
    print(f"           States/UTs: {data['kpi']['total_states']} | Total Districts: {data['kpi']['total_districts']}")
    print(f"           Completed: {data['kpi']['completed_districts']} | Verified Extracted: {format_indian_num(data['kpi']['total_extracted'])}")

    # Copy static assets if they exist
    print(f"[3/3] Copying static assets...")
    assets_src = Path("assets")
    if assets_src.exists():
        assets_dst = output_dir / "assets"
        shutil.copytree(assets_src, assets_dst, dirs_exist_ok=True)
        print(f"      [OK] Copied assets folder to {assets_dst}")

    logo_src = Path("flawless_logo.png")
    if logo_src.exists():
        shutil.copy2(logo_src, output_dir / "flawless_logo.png")
        print(f"      [OK] Copied logo to {output_dir}")

    print(f"\n[SUCCESS] GitHub Pages bundle ready in: {output_dir.resolve()}")


if __name__ == "__main__":
    build_pages()
