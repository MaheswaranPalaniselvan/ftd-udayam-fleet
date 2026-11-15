"""
FlawlessTech Data - Universal District Indexer.
Assigns canonical 2-digit Udayam district codes (e.g. HP-01, KL-01, AP-01)
across all 785 district rows in the Universe spreadsheet.
"""

import csv
from pathlib import Path
import openpyxl

CANONICAL_PREFIX = {
    'Andaman and Nicobar Islands': 'AN',
    'Andhra Pradesh': 'AP',
    'Arunachal Pradesh': 'AR',
    'Assam': 'AS',
    'Bihar': 'BR',
    'Chandigarh': 'CH',
    'Chhattisgarh': 'CG',
    'Dadra and Nagar Haveli and Daman and Diu': 'DD',
    'Delhi': 'DL',
    'Goa': 'GA',
    'Gujarat': 'GJ',
    'Haryana': 'HR',
    'Himachal Pradesh': 'HP',
    'Jammu and Kashmir': 'JK',
    'Jharkhand': 'JH',
    'Karnataka': 'KA',
    'Kerala': 'KL',
    'Ladakh': 'LA',
    'Lakshadweep': 'LD',
    'Madhya Pradesh': 'MP',
    'Maharashtra': 'MH',
    'Manipur': 'MN',
    'Meghalaya': 'ML',
    'Mizoram': 'MZ',
    'Nagaland': 'NL',
    'Odisha': 'OR',
    'Puducherry': 'PY',
    'Punjab': 'PB',
    'Rajasthan': 'RJ',
    'Sikkim': 'SK',
    'Tamil Nadu': 'TN',
    'Telangana': 'TS',
    'Tripura': 'TR',
    'Uttar Pradesh': 'UP',
    'Uttarakhand': 'UK',
    'West Bengal': 'WB',
}


def index_universe_workbook(
    src_xlsx: Path = Path("public/udayam_latest.xlsx"),
    out_xlsx: Path = Path("public/udayam_all_districts_indexed.xlsx"),
    out_csv: Path = Path("public/column_B_all_districts.csv")
):
    if not src_xlsx.exists():
        src_xlsx = Path("live_udayam_extract.xlsx")
    
    wb = openpyxl.load_workbook(src_xlsx, data_only=False)
    ws = wb["Universe"]

    # Gather districts by state
    by_state = {}
    row_meta = {}

    for r in range(2, ws.max_row + 1):
        level = str(ws.cell(r, 1).value or "").strip()
        code = str(ws.cell(r, 2).value or "").strip()
        state = str(ws.cell(r, 3).value or "").strip()
        dist = str(ws.cell(r, 4).value or "").strip()
        
        row_meta[r] = {
            "level": level,
            "orig_code": code,
            "state": state,
            "district": dist
        }

        if level == "District" and state:
            by_state.setdefault(state, []).append((r, code, dist))

    # Determine assignments
    assignments = {} # row -> new_code

    for state, dlist in by_state.items():
        prefix = CANONICAL_PREFIX.get(state, "XX")
        # Check if state already has verified hyphenated codes (e.g. TN, AN, AR)
        has_hyphens = any("-" in c for _, c, _ in dlist)
        
        if has_hyphens:
            for r, code, dist in dlist:
                assignments[r] = code
        else:
            # Sort alphabetically by district name (case-insensitive)
            sorted_dists = sorted(dlist, key=lambda x: x[2].lower())
            for idx, (r, code, dist) in enumerate(sorted_dists, start=1):
                assignments[r] = f"{prefix}-{idx:02d}"

    # Apply assignments to workbook
    csv_rows = [["Row", "Level", "State/UT", "District Name", "Original Code", "Assigned District Code"]]
    col_b_only_rows = []

    for r in range(2, ws.max_row + 1):
        meta = row_meta.get(r, {})
        level = meta.get("level", "")
        state = meta.get("state", "")
        dist = meta.get("district", "")
        orig_code = meta.get("orig_code", "")

        if level == "District":
            new_code = assignments.get(r, orig_code)
            ws.cell(r, 2).value = new_code
            csv_rows.append([r, level, state, dist, orig_code, new_code])
            col_b_only_rows.append(new_code)
        elif level == "State":
            state_code = CANONICAL_PREFIX.get(state, orig_code or "")
            ws.cell(r, 2).value = state_code
            csv_rows.append([r, level, state, dist or state, orig_code, state_code])
            col_b_only_rows.append(state_code)
        else:
            csv_rows.append([r, level, state, dist, orig_code, orig_code])
            col_b_only_rows.append(orig_code)

    # Save outputs
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_xlsx)
    
    # Also update public/udayam_latest.xlsx in place
    wb.save(src_xlsx)

    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(csv_rows)

    # Also save a plain text file containing just Column B values (Row 2 onwards) for direct copy-paste into Google Sheets
    col_b_txt = out_csv.with_name("column_B_values_for_gsheet_paste.txt")
    with open(col_b_txt, "w", encoding="utf-8") as f:
        for val in col_b_only_rows:
            f.write(f"{val}\n")

    print(f"[OK] Successfully indexed {len(assignments)} districts across {len(by_state)} states.")
    print(f"     Updated workbook: {src_xlsx}")
    print(f"     Indexed copy:     {out_xlsx}")
    print(f"     Full CSV mapping: {out_csv}")
    print(f"     Column B TXT:     {col_b_txt}")


if __name__ == "__main__":
    index_universe_workbook()

