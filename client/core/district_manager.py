"""
District Incremental Management & Failure Recovery Core Utilities.
Handles:
- Discovering all districts across archives, folders, and sync reports.
- Fast auto-detection of highest/last Udyam number for any district.
- Generating incremental batches of Udyam registration numbers.
- Extracting failed Udyam numbers from Excel/CSV result files.
- In-place updates and appends for Excel (.xlsx) and CSV datasets.
"""

import csv
import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Standard 28+ CSV Fields used across project
CSV_FIELDS = [
    "Udyam Number", "Enterprise Name", "Organisation Type", "Major Activity",
    "Gender", "Social Category", "Date of Incorporation", "Date of Commencement",
    "Date of Registration", "Enterprise Type", "Classification Date", "Unit Names",
    "Flat / Door / Block", "Premises / Building", "Village / Town", "Block",
    "Road / Street", "City", "State", "District", "Pin Code",
    "Mobile", "Email", "DIC", "MSME-DFO",
    "Primary NIC Code", "Primary NIC Activity", "All NIC Details", "Status"
]

ALL_STATE_CODES = [
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN",
    "GA", "GJ", "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD",
    "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "PB", "PY", "RJ",
    "SK", "TN", "TS", "UK", "UP", "WB"
]


def normalize_district_code(district_raw: str) -> str:
    """
    Normalizes user input into standard district format like 'TN-02' or 'KL-01'.
    Examples:
        'UDYAM-TN-02-0000001' -> 'TN-02'
        'UDYAM-TN-02' -> 'TN-02'
        'tn-2' -> 'TN-02'
        'TN02' -> 'TN-02'
    """
    if not district_raw:
        return "TN-02"

    cleaned = district_raw.strip().upper()
    cleaned = re.sub(r"^UDYAM-", "", cleaned)

    # Match state and 1-2 digits
    m = re.match(r"^([A-Z]{2})[-_ ]?(\d{1,2})", cleaned)
    if m:
        state, code = m.group(1), int(m.group(2))
        return f"{state}-{code:02d}"

    # If only digits provided, default to TN
    if cleaned.isdigit():
        return f"TN-{int(cleaned):02d}"

    return cleaned


def discover_all_districts(workspace_dir: Path = Path(".")) -> list[str]:
    """
    Discovers all known district codes in the workspace from sync_report.csv,
    results/ folder, failed/ folder, and downloaded_html/.
    """
    districts = set()

    # 1. Read from sync_report.csv
    sync_csv = workspace_dir / "sync_report.csv"
    if sync_csv.exists():
        try:
            with open(sync_csv, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    code = row.get("District Code", "").strip().upper()
                    if code and re.match(r"^[A-Z]{2}-\d{2}$", code):
                        districts.add(code)
        except Exception:
            pass

    # 2. Check results/ directory
    results_dir = workspace_dir / "results"
    if results_dir.exists():
        try:
            for item in results_dir.iterdir():
                m = re.match(r"^([A-Z]{2}-\d{2})", item.name.upper())
                if m:
                    districts.add(m.group(1))
        except Exception:
            pass

    # 3. Check failed/ directory
    failed_dir = workspace_dir / "failed"
    if failed_dir.exists():
        try:
            for item in failed_dir.iterdir():
                m = re.match(r"^([A-Z]{2}-\d{2})", item.name.upper())
                if m:
                    districts.add(m.group(1))
        except Exception:
            pass

    # 4. Check downloaded_html/
    html_dir = workspace_dir / "downloaded_html"
    if html_dir.exists():
        try:
            for h in html_dir.glob("UDYAM-*-*.html"):
                m = re.match(r"^UDYAM-([A-Z]{2}-\d{2})-", h.name.upper())
                if m:
                    districts.add(m.group(1))
        except Exception:
            pass

    # Fallback to sample districts if empty
    if not districts:
        districts.update(["TN-01", "TN-02", "TN-03", "KL-01", "AS-01", "MH-18"])

    return sorted(list(districts))


def get_districts_for_state(state_prefix: str, workspace_dir: Path = Path(".")) -> list[str]:
    """
    Returns the ordered list of all district codes for a given state prefix (e.g. 'TN' -> ['TN-01', ..., 'TN-38']).
    Sources from public/column_B_all_districts.csv if present.
    """
    st = state_prefix.strip().upper()
    csv_path = workspace_dir / "public" / "column_B_all_districts.csv"
    districts = []
    if csv_path.is_file():
        try:
            with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    if r.get("Level") == "District":
                        code = r.get("Assigned District Code", "").strip().upper()
                        if code.startswith(f"{st}-") and code not in districts:
                            districts.append(code)
        except Exception:
            pass
    if not districts:
        for i in range(1, 45):
            districts.append(f"{st}-{i:02d}")
    return districts


def discover_stale_or_unstarted_districts(workspace_dir: Path = Path(".")) -> list[dict]:
    """
    Returns an indexed list of districts across India, prioritizing unstarted
    and oldest-harvested districts for autonomous fleet worker distribution.
    """
    all_districts = []
    col_b = workspace_dir / "public" / "column_B_all_districts.csv"
    if col_b.is_file():
        try:
            with open(col_b, "r", encoding="utf-8", errors="replace") as f:
                for r in csv.DictReader(f):
                    if r.get("Level") == "District":
                        code = r.get("Assigned District Code", "").strip().upper()
                        name = r.get("District Name", "").strip()
                        state = r.get("State/UT", "").strip()
                        if "-" in code:
                            all_districts.append({
                                "code": code,
                                "name": name,
                                "state": state,
                                "dor": "None",
                                "extracted": 0
                            })
        except Exception:
            pass

    known = {}
    sync_csv = workspace_dir / "sync_report.csv"
    if sync_csv.is_file():
        try:
            with open(sync_csv, "r", encoding="utf-8", errors="replace") as f:
                for r in csv.DictReader(f):
                    c = r.get("District Code", "").strip().upper()
                    known[c] = {
                        "dor": r.get("Last Recorded Date", "").strip(),
                        "extracted": int(r.get("Total Extracted", 0) or 0)
                    }
        except Exception:
            pass

    for d in all_districts:
        c = d["code"]
        if c in known:
            d["dor"] = known[c]["dor"]
            d["extracted"] = known[c]["extracted"]

    return all_districts


def find_district_last_number(district: str, workspace_dir: Path = Path(".")) -> dict:
    """
    Finds the highest existing sequence number and last record for a given district.
    Scans in order:
      1. sync_report.csv (indexed sync cache)
      2. results/{district}/results_{district}.csv
      3. results.csv & results.xlsx
      4. downloaded_html/UDYAM-{district}-*.html
      5. failed/{district}/failed_{district}.csv
    """
    clean_dist = normalize_district_code(district)
    prefix = f"UDYAM-{clean_dist}"

    max_num = 0
    last_record_id = ""
    last_dor = ""
    source = ""

    # 1. Check sync_report.csv
    sync_csv = workspace_dir / "sync_report.csv"
    if sync_csv.exists():
        try:
            with open(sync_csv, "r", encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    if row.get("District Code", "").strip().upper() == clean_dist:
                        rec = row.get("Last Record", "").strip()
                        dor = row.get("Last Recorded Date", "").strip()
                        m = re.search(r"-(\d+)$", rec)
                        if m:
                            val = int(m.group(1))
                            if val > max_num:
                                max_num = val
                                last_record_id = rec
                                last_dor = dor
                                source = "sync_report.csv"
        except Exception:
            pass

    # 2. Check results/{district}/
    res_dir = workspace_dir / "results" / clean_dist
    if res_dir.is_dir():
        res_csv = res_dir / f"results_{clean_dist}.csv"
        if res_csv.exists():
            try:
                with open(res_csv, "r", encoding="utf-8", errors="replace") as f:
                    r = csv.reader(f)
                    next(r, None)
                    for row in r:
                        if row and row[0].startswith(prefix):
                            m = re.search(r"-(\d+)$", row[0].strip())
                            if m:
                                val = int(m.group(1))
                                if val > max_num:
                                    max_num = val
                                    last_record_id = row[0].strip()
                                    if len(row) > 3 and re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", row[3]):
                                        last_dor = row[3].strip()
                                    source = f"results/{clean_dist}"
            except Exception:
                pass

    # 2b. Check archives: results/{district}.7z, archives/{district}.7z, results/{district}.zip, archives/{district}.zip
    archive_candidates = [
        workspace_dir / "results" / f"{clean_dist}.7z",
        workspace_dir / "archives" / f"{clean_dist}.7z",
        workspace_dir / "results" / f"{clean_dist}.zip",
        workspace_dir / "archives" / f"{clean_dist}.zip",
    ]
    for arc in archive_candidates:
        if arc.is_file() and arc.stat().st_size > 0:
            csv_text = None
            if arc.suffix.lower() == ".zip":
                try:
                    with zipfile.ZipFile(arc, "r") as zf:
                        for name in zf.namelist():
                            if f"results_{clean_dist}.csv" in name or (name.endswith(".csv") and "results" in name.lower()):
                                csv_text = zf.read(name).decode("utf-8", errors="replace")
                                break
                except Exception:
                    pass
            elif arc.suffix.lower() == ".7z":
                seven_zip = shutil.which("7z")
                if not seven_zip:
                    for p in [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe", "/usr/bin/7z", "/usr/local/bin/7z"]:
                        if Path(p).is_file():
                            seven_zip = p
                            break
                if seven_zip:
                    try:
                        proc = subprocess.run([seven_zip, "e", str(arc), "-r", f"results_{clean_dist}.csv", "-so"], capture_output=True, text=True, errors="replace")
                        if proc.returncode == 0 and proc.stdout.strip():
                            csv_text = proc.stdout
                        else:
                            proc = subprocess.run([seven_zip, "e", str(arc), "-r", "results_*.csv", "-so"], capture_output=True, text=True, errors="replace")
                            if proc.returncode == 0 and proc.stdout.strip():
                                csv_text = proc.stdout
                    except Exception:
                        pass

            if csv_text:
                try:
                    reader = csv.reader(io.StringIO(csv_text))
                    header = next(reader, None)
                    dor_idx = -1
                    if header:
                        for i, col in enumerate(header):
                            c_lower = col.strip().lower()
                            if "date" in c_lower or "dor" in c_lower:
                                dor_idx = i
                                break
                    for row in reader:
                        if row and row[0].startswith(prefix):
                            m = re.search(r"-(\d+)$", row[0].strip())
                            if m:
                                val = int(m.group(1))
                                if val > max_num:
                                    max_num = val
                                    last_record_id = row[0].strip()
                                    if dor_idx != -1 and len(row) > dor_idx and re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", row[dor_idx]):
                                        last_dor = row[dor_idx].strip()
                                    elif len(row) > 3 and re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", row[3]):
                                        last_dor = row[3].strip()
                                    source = f"archive:{arc.name}"
                except Exception:
                    pass

    # 3. Check results.csv
    local_csv = workspace_dir / "results.csv"
    if local_csv.exists():
        try:
            with open(local_csv, "r", encoding="utf-8", errors="replace") as f:
                r = csv.reader(f)
                next(r, None)
                for row in r:
                    if row and row[0].startswith(prefix):
                        m = re.search(r"-(\d+)$", row[0].strip())
                        if m:
                            val = int(m.group(1))
                            if val > max_num:
                                max_num = val
                                last_record_id = row[0].strip()
                                source = "results.csv"
        except Exception:
            pass

    # 4. Check results.xlsx
    local_xlsx = workspace_dir / "results.xlsx"
    if local_xlsx.exists():
        try:
            wb = openpyxl.load_workbook(local_xlsx, read_only=True)
            ws = wb.active
            rows = ws.iter_rows(values_only=True)
            header = next(rows, None)
            if header and "Udyam Number" in header:
                idx = header.index("Udyam Number")
                ent_idx = header.index("Enterprise Name") if "Enterprise Name" in header else -1
                for r in rows:
                    if r and len(r) > idx and r[idx]:
                        # Skip if it is marked Failed
                        if ent_idx != -1 and len(r) > ent_idx and str(r[ent_idx] or "").startswith("Failed"):
                            continue
                        num_str = str(r[idx]).strip()
                        if num_str.startswith(prefix):
                            m = re.search(r"-(\d+)$", num_str)
                            if m:
                                val = int(m.group(1))
                                if 0 < val < 5000000 and val > max_num:
                                    max_num = val
                                    last_record_id = num_str
                                    source = "results.xlsx"
            wb.close()
        except Exception:
            pass

    # 5. Check downloaded_html/
    html_dir = workspace_dir / "downloaded_html"
    if html_dir.exists():
        try:
            for h in html_dir.glob(f"{prefix}-*.html"):
                m = re.search(r"-(\d+)\.html$", h.name)
                if m:
                    val = int(m.group(1))
                    if val > max_num:
                        max_num = val
                        last_record_id = h.stem
                        source = "downloaded_html"
        except Exception:
            pass

    # 6. Check failed/{district}/
    fail_dir = workspace_dir / "failed" / clean_dist
    if fail_dir.is_dir():
        fail_csv = fail_dir / f"failed_{clean_dist}.csv"
        if fail_csv.exists():
            try:
                with open(fail_csv, "r", encoding="utf-8", errors="replace") as f:
                    r = csv.reader(f)
                    next(r, None)
                    for row in r:
                        if row and row[0].startswith(prefix):
                            m = re.search(r"-(\d+)$", row[0].strip())
                            if m:
                                val = int(m.group(1))
                                if 0 < val < 5000000 and val > max_num:
                                    max_num = val
                                    last_record_id = row[0].strip()
                                    source = f"failed/{clean_dist}"
            except Exception:
                pass

    next_start = max_num + 1 if max_num > 0 else 1
    if not last_record_id:
        last_record_id = f"{prefix}-0000000"
        source = "New District (No prior records found)"

    return {
        "district": clean_dist,
        "max_number": max_num,
        "last_record": last_record_id,
        "last_dor": last_dor,
        "source": source,
        "next_start": next_start,
    }


def generate_district_udyam_numbers(district: str, start_num: int, count: int) -> list[str]:
    """Generates a contiguous sequence of Udyam registration numbers for a district."""
    clean_dist = normalize_district_code(district)
    start_num = max(1, start_num)
    count = max(1, count)
    return [f"UDYAM-{clean_dist}-{n:07d}" for n in range(start_num, start_num + count)]


def get_failed_udyam_numbers_from_file(file_path: Path) -> list[tuple[str, str]]:
    """
    Parses an Excel (.xlsx) or CSV file and extracts all Udyam numbers whose
    Status is not 'Success'.
    Returns list of tuples: [(udyam_number, failure_reason), ...]
    """
    if not file_path.exists():
        return []

    failed_list = []
    seen = set()

    suffix = file_path.suffix.lower()
    if suffix == ".xlsx":
        try:
            wb = openpyxl.load_workbook(file_path, read_only=True)
            ws = wb.active
            rows = ws.iter_rows(values_only=True)
            header = next(rows, None)
            if not header:
                return []

            # Detect column indices
            header_clean = [str(h).strip().lower() if h else "" for h in header]
            status_idx = -1
            num_idx = -1

            for idx, h in enumerate(header_clean):
                if h == "status":
                    status_idx = idx
                elif h in ["udyam number", "udyam_number", "number", "registration number"]:
                    num_idx = idx

            if num_idx == -1:
                num_idx = 0  # Fallback to column 0

            for r in rows:
                if not r or len(r) <= num_idx:
                    continue
                num_val = str(r[num_idx] or "").strip().upper()
                if not num_val or not num_val.startswith("UDYAM-"):
                    continue

                status_val = str(r[status_idx] or "").strip() if status_idx != -1 and len(r) > status_idx else ""
                # Any non-success status is considered failed
                if not status_val.lower().startswith("success"):
                    if num_val not in seen:
                        seen.add(num_val)
                        failed_list.append((num_val, status_val or "Failed (Not Extracted)"))
            wb.close()
        except Exception:
            pass

    elif suffix in [".csv", ".txt"]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return []

                header_clean = [str(h).strip().lower() for h in header]
                status_idx = -1
                num_idx = -1

                for idx, h in enumerate(header_clean):
                    if h == "status":
                        status_idx = idx
                    elif h in ["udyam number", "udyam_number", "number", "registration number"]:
                        num_idx = idx

                if num_idx == -1:
                    num_idx = 0

                for r in reader:
                    if not r or len(r) <= num_idx:
                        continue
                    num_val = str(r[num_idx]).strip().upper()
                    if not num_val or not num_val.startswith("UDYAM-"):
                        continue

                    status_val = str(r[status_idx]).strip() if status_idx != -1 and len(r) > status_idx else ""
                    if not status_val.lower().startswith("success"):
                        if num_val not in seen:
                            seen.add(num_val)
                            failed_list.append((num_val, status_val or "Failed"))
        except Exception:
            pass

    return failed_list


def save_or_update_records_file(
    file_path: Path,
    records: list[dict],
    update_in_place: bool = True
) -> tuple[int, int]:
    """
    Saves or updates records in an Excel workbook (.xlsx) or CSV file.
    If update_in_place is True:
      - Rows with matching Udyam Number are updated in-place (e.g. converting a Failed row to Success).
      - New Udyam Numbers are appended to the dataset.
    Returns: (updated_count, appended_count)
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = file_path.suffix.lower()

    if suffix == ".xlsx":
        from extract_list import export_records_to_excel

        if not file_path.exists() or not update_in_place:
            export_records_to_excel(records, file_path)
            return (0, len(records))

        # Update in-place
        wb = openpyxl.load_workbook(file_path)
        ws = wb.active

        # Extract headers from row 1
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        headers = [str(h).strip() if h is not None else f"Col_{i+1}" for i, h in enumerate(headers)]

        num_col_idx = 1
        for i, h in enumerate(headers, start=1):
            if h.lower() in ["udyam number", "number"]:
                num_col_idx = i
                break

        # Map existing numbers to their row indices
        row_map = {}
        for r in range(2, ws.max_row + 1):
            val = ws.cell(row=r, column=num_col_idx).value
            if val:
                row_map[str(val).strip().upper()] = r

        data_font = Font(name="Segoe UI", size=10)
        thin_border = Border(
            left=Side(style="thin", color="D0D7DE"),
            right=Side(style="thin", color="D0D7DE"),
            top=Side(style="thin", color="D0D7DE"),
            bottom=Side(style="thin", color="D0D7DE")
        )
        alt_fill = PatternFill(start_color="F6F8FA", end_color="F6F8FA", fill_type="solid")
        center_cols = {
            "Udyam Number", "Gender", "Social Category", "Date of Incorporation",
            "Date of Commencement", "Date of Registration", "Enterprise Type",
            "Classification Date", "Pin Code", "Mobile", "Status"
        }

        updated = 0
        appended = 0

        for rec in records:
            num = rec.get("Udyam Number", "").strip().upper()
            if not num:
                continue

            if num in row_map:
                row_idx = row_map[num]
                for col_idx, col_name in enumerate(headers, start=1):
                    if col_name in rec:
                        cell = ws.cell(row=row_idx, column=col_idx, value=rec[col_name])
                        cell.font = data_font
                        cell.border = thin_border
                        if col_name in center_cols:
                            cell.alignment = Alignment(horizontal="center", vertical="center")
                        else:
                            cell.alignment = Alignment(horizontal="left", vertical="center")
                updated += 1
            else:
                row_idx = ws.max_row + 1
                ws.row_dimensions[row_idx].height = 20
                use_alt = (row_idx % 2 == 1)

                for col_idx, col_name in enumerate(headers, start=1):
                    val = rec.get(col_name, "")
                    cell = ws.cell(row=row_idx, column=col_idx, value=val)
                    cell.font = data_font
                    cell.border = thin_border
                    if use_alt:
                        cell.fill = alt_fill
                    if col_name in center_cols:
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                    else:
                        cell.alignment = Alignment(horizontal="left", vertical="center")

                row_map[num] = row_idx
                appended += 1

        # Re-apply auto-filter reference
        ws.auto_filter.ref = ws.dimensions
        wb.save(file_path)
        wb.close()
        return (updated, appended)

    else:
        # CSV Handling
        existing_records = []
        if file_path.exists() and update_in_place:
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    r = csv.DictReader(f)
                    existing_records = list(r)
            except Exception:
                existing_records = []

        rec_map = {row.get("Udyam Number", "").strip().upper(): row for row in existing_records if row.get("Udyam Number")}
        updated = 0
        appended = 0

        for rec in records:
            num = rec.get("Udyam Number", "").strip().upper()
            if not num:
                continue
            if num in rec_map:
                rec_map[num].update(rec)
                updated += 1
            else:
                rec_map[num] = rec
                appended += 1

        all_final = list(rec_map.values())
        fieldnames = CSV_FIELDS
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_final)

        return (updated, appended)
