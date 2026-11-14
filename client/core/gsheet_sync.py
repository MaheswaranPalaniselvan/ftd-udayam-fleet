"""
Google Sheets Fleet Statistics & District Coverage Sync Engine.
Fetches, aggregates, and caches fleet coverage data from:
1. Google Sheets: [UDAYAM extract]
2. Local sync_report.csv and results archives
Provides state-level and district-level hierarchical drill-down statistics.
"""

import csv
import io
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import httpx
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

DEFAULT_GSHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1dwWvxENHxF5Lxz9BLCzwXR_rL09CuD9jU8FvDEAVN-E/export?format=csv&gid=104828484"
CACHE_FILE_PATH = Path("gsheet_cache.json")


def clean_number(val: object = None) -> int:
    """Extracts integer value from string or number, ignoring commas and symbols."""
    if val is None:
        return 0
    cleaned = re.sub(r"[^\d]", "", str(val))
    return int(cleaned) if cleaned else 0


def fetch_gsheet_raw_csv(url: str, timeout: float = 12.0) -> Optional[str]:
    """Fetches CSV content from Google Sheet export URL."""
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        if resp.status_code == 200 and len(resp.text) > 100:
            return resp.text
    except Exception as e:
        logging.warning(f"Could not fetch Google Sheet CSV: {e}")
    return None


def load_local_sync_report(workspace_dir: Path = Path(".")) -> dict[str, dict]:
    """Reads sync_report.csv into a dictionary keyed by district code."""
    sync_csv = workspace_dir / "sync_report.csv"
    report = {}
    if sync_csv.exists():
        try:
            with open(sync_csv, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    code = row.get("District Code", "").strip().upper()
                    if code:
                        report[code] = {
                            "district_code": code,
                            "last_record": row.get("Last Record", "").strip(),
                            "last_dor": row.get("Last Recorded Date", "").strip(),
                            "extracted": clean_number(row.get("Total Extracted", 0)),
                            "dereg_unreg": clean_number(row.get("Deregistered/Unregistered", row.get("Dereg/Unreg", 0))),
                            "failed": clean_number(row.get("Total Failed", 0)),
                            "is_archive": row.get("Is Archive", "").strip().lower() == "true",
                            "source": "Local sync_report.csv"
                        }
        except Exception:
            pass
    return report


def get_cached_or_local_statistics(workspace_dir: Path = Path(".")) -> dict:
    """
    Returns statistics synchronously and immediately (< 0.05s) from gsheet_cache.json if present,
    or generates an initial state structure from local sync_report.csv and local archives.
    Guarantees instantaneous UI rendering when opening the Coverage Dialog.
    """
    cache_path = workspace_dir / CACHE_FILE_PATH
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                if "states" in cached_data and cached_data["states"]:
                    cached_data["summary"]["source"] = "Cached GSheet (Instant)"
                    return cached_data
        except Exception:
            pass

    # Fallback to local sync report
    local_report = load_local_sync_report(workspace_dir)
    states_dict = {}
    total_districts = 0
    covered_districts = 0
    fleet_extracted = 0
    fleet_failed = 0

    for code, item in local_report.items():
        state_prefix = code.split("-")[0] if "-" in code else code
        if state_prefix not in states_dict:
            states_dict[state_prefix] = {
                "code": state_prefix,
                "name": state_prefix,
                "districts": [],
                "total_extracted": 0,
                "total_dereg_unreg": 0,
                "total_failed": 0,
                "districts_total": 0,
                "districts_covered": 0,
                "latest_dor": ""
            }
        is_covered = bool(item["last_record"] and not item["last_record"].endswith("-0000000"))
        total_districts += 1
        if is_covered:
            covered_districts += 1
        dist_item = {
            "district_code": code,
            "district_name": f"District {code}",
            "state_code": state_prefix,
            "state_name": state_prefix,
            "last_record": item["last_record"],
            "last_dor": item["last_dor"],
            "extracted": item["extracted"],
            "dereg_unreg": item.get("dereg_unreg", 0),
            "failed": item["failed"],
            "is_covered": is_covered,
            "status": "Completed" if is_covered else "Pending",
            "source": item.get("source", "Local Archive")
        }
        states_dict[state_prefix]["districts"].append(dist_item)
        states_dict[state_prefix]["districts_total"] += 1
        if is_covered:
            states_dict[state_prefix]["districts_covered"] += 1
        states_dict[state_prefix]["total_extracted"] += item["extracted"]
        states_dict[state_prefix]["total_dereg_unreg"] += item.get("dereg_unreg", 0)
        states_dict[state_prefix]["total_failed"] += item["failed"]
        fleet_extracted += item["extracted"]
        fleet_failed += item["failed"]
        if item["last_dor"] and not states_dict[state_prefix]["latest_dor"]:
            states_dict[state_prefix]["latest_dor"] = item["last_dor"]

    states_covered_count = sum(1 for s in states_dict.values() if s["districts_covered"] > 0)
    for st_code, st_data in states_dict.items():
        tot = st_data["districts_total"]
        cov = st_data["districts_covered"]
        st_data["coverage_pct"] = round((cov / tot) * 100, 1) if tot > 0 else 0.0
        st_data["status"] = "Completed" if (cov == tot and tot > 0) else ("In Progress" if cov > 0 else "Pending")
        st_data["districts"].sort(key=lambda d: d["district_code"])

    overall_pct = round((covered_districts / total_districts) * 100, 1) if total_districts > 0 else 0.0
    return {
        "summary": {
            "total_states": len(states_dict),
            "states_covered": states_covered_count,
            "total_districts": total_districts,
            "districts_covered": covered_districts,
            "coverage_pct": overall_pct,
            "total_extracted": fleet_extracted,
            "total_failed": fleet_failed,
            "last_sync_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "Local Sync Report",
            "gsheet_url": DEFAULT_GSHEET_CSV_URL
        },
        "states": states_dict
    }


def fetch_gsheet_statistics(
    gsheet_url: str = None,
    merge_local: bool = True,
    workspace_dir: Path = Path("."),
    timeout: float = 12.0
) -> dict:
    """
    Fetches full State & District statistics from Google Sheet, caching locally
    and merging with local archives for 100% complete coverage metrics.
    """
    target_url = gsheet_url or os.getenv("GOOGLE_SHEET_CSV_URL") or DEFAULT_GSHEET_CSV_URL
    raw_csv = fetch_gsheet_raw_csv(target_url, timeout=timeout)
    source_name = "Live Google Sheet"

    cache_path = workspace_dir / CACHE_FILE_PATH

    # If fetch failed, fallback to local cache
    if not raw_csv and cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                cached_data["summary"]["source"] = "Cached GSheet (Offline Fallback)"
                return cached_data
        except Exception:
            pass

    local_report = load_local_sync_report(workspace_dir) if merge_local else {}

    states_dict = {}
    total_districts_count = 0
    covered_districts_count = 0
    fleet_total_extracted = 0
    fleet_total_failed = 0

    if raw_csv:
        reader = csv.DictReader(io.StringIO(raw_csv))
        rows = list(reader)

        for r in rows:
            lvl = r.get("Level", "").strip()
            st_code = r.get("State Code", "").strip().upper()
            st_name = r.get("State/UT", "").strip()
            loc_name = r.get("Location_Name", "").strip()
            last_rec = r.get("Last Record", "").strip()
            last_dor = r.get("Last Recorded Date", "").strip()
            ext_val = clean_number(r.get("Total Records Extracted", 0))
            fail_val = clean_number(r.get("Total Failed Records", 0))

            if not st_code:
                continue

            if lvl == "State":
                if st_code not in states_dict:
                    states_dict[st_code] = {
                        "code": st_code,
                        "name": st_name or loc_name or st_code,
                        "districts": [],
                        "total_extracted": 0,
                        "total_failed": 0,
                        "districts_total": 0,
                        "districts_covered": 0,
                        "latest_dor": ""
                    }
                else:
                    if not states_dict[st_code]["name"]:
                        states_dict[st_code]["name"] = st_name or loc_name

            elif lvl == "District":
                total_districts_count += 1
                state_prefix = st_code.split("-")[0] if "-" in st_code else st_code

                if state_prefix not in states_dict:
                    states_dict[state_prefix] = {
                        "code": state_prefix,
                        "name": st_name or state_prefix,
                        "districts": [],
                        "total_extracted": 0,
                        "total_failed": 0,
                        "districts_total": 0,
                        "districts_covered": 0,
                        "latest_dor": ""
                    }

                dist_source = "GSheet"
                # If local sync report has richer data or newer last record, merge it
                if merge_local and st_code in local_report:
                    loc_d = local_report[st_code]
                    if not last_rec and loc_d["last_record"]:
                        last_rec = loc_d["last_record"]
                        last_dor = loc_d["last_dor"] or last_dor
                        ext_val = max(ext_val, loc_d["extracted"])
                        fail_val = max(fail_val, loc_d["failed"])
                        dist_source = "Local Archive (Synced)"
                    elif loc_d["last_record"]:
                        # Compare sequence numbers
                        m_sheet = re.search(r"-(\d+)$", last_rec)
                        m_loc = re.search(r"-(\d+)$", loc_d["last_record"])
                        if m_sheet and m_loc and int(m_loc.group(1)) > int(m_sheet.group(1)):
                            last_rec = loc_d["last_record"]
                            last_dor = loc_d["last_dor"] or last_dor
                            ext_val = max(ext_val, loc_d["extracted"])
                            fail_val = max(fail_val, loc_d["failed"])
                            dist_source = "Local Archive (Newer)"

                is_covered = bool(last_rec and not last_rec.endswith("-0000000"))
                if is_covered:
                    covered_districts_count += 1

                dist_item = {
                    "district_code": st_code,
                    "district_name": loc_name or st_code,
                    "state_code": state_prefix,
                    "state_name": st_name or states_dict[state_prefix]["name"],
                    "last_record": last_rec,
                    "last_dor": last_dor,
                    "extracted": ext_val,
                    "failed": fail_val,
                    "is_covered": is_covered,
                    "status": "Completed" if is_covered else "Pending",
                    "source": dist_source
                }

                states_dict[state_prefix]["districts"].append(dist_item)
                states_dict[state_prefix]["districts_total"] += 1
                if is_covered:
                    states_dict[state_prefix]["districts_covered"] += 1

                states_dict[state_prefix]["total_extracted"] += ext_val
                states_dict[state_prefix]["total_failed"] += fail_val
                fleet_total_extracted += ext_val
                fleet_total_failed += fail_val

                if last_dor and not states_dict[state_prefix]["latest_dor"]:
                    states_dict[state_prefix]["latest_dor"] = last_dor

    # Also incorporate any local districts in sync_report not in GSheet rows
    if merge_local and local_report:
        existing_codes = {d["district_code"] for s in states_dict.values() for d in s["districts"]}
        for code, item in local_report.items():
            if code not in existing_codes and re.match(r"^[A-Z]{2}-\d{2}$", code):
                state_prefix = code.split("-")[0]
                if state_prefix not in states_dict:
                    states_dict[state_prefix] = {
                        "code": state_prefix,
                        "name": state_prefix,
                        "districts": [],
                        "total_extracted": 0,
                        "total_failed": 0,
                        "districts_total": 0,
                        "districts_covered": 0,
                        "latest_dor": ""
                    }
                total_districts_count += 1
                covered_districts_count += 1
                dist_item = {
                    "district_code": code,
                    "district_name": f"District {code}",
                    "state_code": state_prefix,
                    "state_name": states_dict[state_prefix]["name"],
                    "last_record": item["last_record"],
                    "last_dor": item["last_dor"],
                    "extracted": item["extracted"],
                    "failed": item["failed"],
                    "is_covered": True,
                    "status": "Completed",
                    "source": "Local Archive"
                }
                states_dict[state_prefix]["districts"].append(dist_item)
                states_dict[state_prefix]["districts_total"] += 1
                states_dict[state_prefix]["districts_covered"] += 1
                states_dict[state_prefix]["total_extracted"] += item["extracted"]
                states_dict[state_prefix]["total_failed"] += item["failed"]
                fleet_total_extracted += item["extracted"]
                fleet_total_failed += item["failed"]

    # Calculate state coverage metrics
    states_covered_count = 0
    for st_code, st_data in states_dict.items():
        tot = st_data["districts_total"]
        cov = st_data["districts_covered"]
        st_data["coverage_pct"] = round((cov / tot) * 100, 1) if tot > 0 else 0.0

        if cov > 0:
            states_covered_count += 1

        if cov == tot and tot > 0:
            st_data["status"] = "Completed"
        elif cov > 0:
            st_data["status"] = "In Progress"
        else:
            st_data["status"] = "Pending"

        # Sort districts by district code
        st_data["districts"].sort(key=lambda d: d["district_code"])

    overall_pct = round((covered_districts_count / total_districts_count) * 100, 1) if total_districts_count > 0 else 0.0

    payload = {
        "summary": {
            "total_states": len(states_dict),
            "states_covered": states_covered_count,
            "total_districts": total_districts_count,
            "districts_covered": covered_districts_count,
            "coverage_pct": overall_pct,
            "total_extracted": fleet_total_extracted,
            "total_failed": fleet_total_failed,
            "last_sync_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source_name,
            "gsheet_url": target_url
        },
        "states": states_dict
    }

    # Save to local cache
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    return payload


def export_coverage_stats_to_excel(stats_data: dict, out_path: Path):
    """
    Exports state & district coverage statistics into an Excel workbook (.xlsx)
    with two beautifully formatted sheets: State Summary and District Drilldown.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()

    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    data_font = Font(name="Segoe UI", size=10)
    data_font_bold = Font(name="Segoe UI", size=10, bold=True)
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    thin_border = Border(
        left=Side(style="thin", color="D0D7DE"),
        right=Side(style="thin", color="D0D7DE"),
        top=Side(style="thin", color="D0D7DE"),
        bottom=Side(style="thin", color="D0D7DE")
    )
    alt_fill = PatternFill(start_color="F6F8FA", end_color="F6F8FA", fill_type="solid")
    green_fill = PatternFill(start_color="E6FFED", end_color="E6FFED", fill_type="solid")
    yellow_fill = PatternFill(start_color="FFFBEB", end_color="FFFBEB", fill_type="solid")

    # Sheet 1: State Summary
    ws1 = wb.active
    ws1.title = "State Coverage Summary"
    ws1.views.sheetView[0].showGridLines = True

    headers1 = [
        "State Code", "State / UT Name", "Status", "Districts Covered", "Total Districts",
        "Coverage %", "Total Records Extracted", "Total Failed Records", "Latest Registration Date"
    ]
    ws1.row_dimensions[1].height = 28
    for col_idx, h in enumerate(headers1, start=1):
        c = ws1.cell(row=1, column=col_idx, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = header_align
        c.border = thin_border

    states = stats_data.get("states", {})
    row_idx = 2
    for code, s in sorted(states.items()):
        ws1.row_dimensions[row_idx].height = 20
        use_alt = (row_idx % 2 == 1)
        row_vals = [
            code,
            s.get("name", code),
            s.get("status", "Pending"),
            s.get("districts_covered", 0),
            s.get("districts_total", 0),
            f"{s.get('coverage_pct', 0)}%",
            f"{s.get('total_extracted', 0):,}",
            f"{s.get('total_failed', 0):,}",
            s.get("latest_dor", "")
        ]

        for col_idx, val in enumerate(row_vals, start=1):
            cell = ws1.cell(row=row_idx, column=col_idx, value=val)
            cell.font = data_font_bold if col_idx == 1 else data_font
            cell.border = thin_border
            if use_alt:
                cell.fill = alt_fill

            if col_idx in [1, 3, 4, 5, 6, 9]:
                cell.alignment = align_center
            elif col_idx in [7, 8]:
                cell.alignment = align_right
            else:
                cell.alignment = align_left

            # Highlight status
            if col_idx == 3:
                if val == "Completed":
                    cell.fill = green_fill
                elif val == "In Progress":
                    cell.fill = yellow_fill

        row_idx += 1

    for col in ws1.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = max(max_len + 4, 14)

    ws1.freeze_panes = "A2"
    ws1.auto_filter.ref = ws1.dimensions

    # Sheet 2: District Drilldown
    ws2 = wb.create_sheet(title="District Drilldown")
    ws2.views.sheetView[0].showGridLines = True

    headers2 = [
        "State Code", "State Name", "District Code", "District Name", "Status",
        "Last Extracted Udyam Number", "Last Registered Date", "Extracted Records",
        "Failed Records", "Data Source"
    ]
    ws2.row_dimensions[1].height = 28
    for col_idx, h in enumerate(headers2, start=1):
        c = ws2.cell(row=1, column=col_idx, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = header_align
        c.border = thin_border

    row_idx = 2
    for code, s in sorted(states.items()):
        for d in s.get("districts", []):
            ws2.row_dimensions[row_idx].height = 20
            use_alt = (row_idx % 2 == 1)
            row_vals = [
                d.get("state_code", ""),
                d.get("state_name", ""),
                d.get("district_code", ""),
                d.get("district_name", ""),
                d.get("status", "Pending"),
                d.get("last_record", ""),
                d.get("last_dor", ""),
                f"{d.get('extracted', 0):,}",
                f"{d.get('failed', 0):,}",
                d.get("source", "GSheet")
            ]

            for col_idx, val in enumerate(row_vals, start=1):
                cell = ws2.cell(row=row_idx, column=col_idx, value=val)
                cell.font = data_font_bold if col_idx in [1, 3] else data_font
                cell.border = thin_border
                if use_alt:
                    cell.fill = alt_fill

                if col_idx in [1, 3, 5, 7]:
                    cell.alignment = align_center
                elif col_idx in [8, 9]:
                    cell.alignment = align_right
                else:
                    cell.alignment = align_left

                if col_idx == 5:
                    if val == "Completed":
                        cell.fill = green_fill
                    elif val == "Pending":
                        cell.fill = alt_fill

            row_idx += 1

    for col in ws2.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = max(max_len + 4, 14)

    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = ws2.dimensions

    wb.save(out_path)
    wb.close()
