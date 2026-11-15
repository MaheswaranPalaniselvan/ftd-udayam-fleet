#!/usr/bin/env python3
"""
build_mca_database.py
=====================
High-speed compilation of 3.68M+ Indian company records into SQLite (`data/mca_master.db`).
Uses bulk in-memory pragmas and post-insert indexing for maximum ingestion speed.
"""

import os
import sys
import csv
import glob
import time
import sqlite3
import argparse
from pathlib import Path

DATA_DIR = Path("data/mca_master_all_states")
DB_PATH = Path("data/mca_master.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS companies (
    cin TEXT PRIMARY KEY,
    company_name TEXT,
    roc_code TEXT,
    category TEXT,
    sub_category TEXT,
    class TEXT,
    authorized_capital REAL,
    paidup_capital REAL,
    registration_date TEXT,
    registered_address TEXT,
    listing_status TEXT,
    status TEXT,
    state TEXT,
    nic_code TEXT,
    industrial_classification TEXT,
    source_file TEXT
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_comp_name ON companies(company_name);
CREATE INDEX IF NOT EXISTS idx_comp_state ON companies(state);
CREATE INDEX IF NOT EXISTS idx_comp_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_comp_reg_date ON companies(registration_date);
"""


def init_db(conn: sqlite3.Connection):
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("PRAGMA journal_mode = MEMORY;")
    conn.execute("PRAGMA cache_size = -100000;")  # 100 MB cache
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def clean_val(val):
    if val is None:
        return ""
    v = str(val).strip()
    return v.replace("^", "")


def parse_float(val):
    if val is None:
        return 0.0
    try:
        clean = str(val).replace(",", "").strip()
        return float(clean) if clean else 0.0
    except (ValueError, TypeError):
        return 0.0


def ingest_csv(conn: sqlite3.Connection, fpath: Path):
    """Ingest standard CSV file into SQLite database with batch transactions."""
    fname = fpath.name
    cur = conn.cursor()
    batch = []
    batch_size = 25000
    rows_inserted = 0

    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return 0

        col_map = {col.strip().lower(): idx for idx, col in enumerate(header)}
        cin_idx = col_map.get("cin")
        name_idx = col_map.get("companyname")
        roc_idx = col_map.get("companyroccode")
        cat_idx = col_map.get("companycategory")
        subcat_idx = col_map.get("companysubcategory")
        class_idx = col_map.get("companyclass")
        auth_idx = col_map.get("authorizedcapital")
        paid_idx = col_map.get("paidupcapital")
        date_idx = col_map.get("companyregistrationdate_date") or col_map.get("date_of_registration")
        addr_idx = col_map.get("registered_office_address")
        list_idx = col_map.get("listingstatus")
        status_idx = col_map.get("companystatus")
        state_idx = col_map.get("companystatecode") or col_map.get("registered_state")
        nic_idx = col_map.get("nic_code") or col_map.get("principal_business_activity_code")
        ind_idx = col_map.get("companyindustrialclassification")

        if cin_idx is None:
            return 0

        for row in reader:
            if not row or len(row) <= cin_idx:
                continue
            cin = clean_val(row[cin_idx])
            if not cin or len(cin) < 10:
                continue

            record = (
                cin,
                clean_val(row[name_idx]) if name_idx is not None and name_idx < len(row) else "",
                clean_val(row[roc_idx]) if roc_idx is not None and roc_idx < len(row) else "",
                clean_val(row[cat_idx]) if cat_idx is not None and cat_idx < len(row) else "",
                clean_val(row[subcat_idx]) if subcat_idx is not None and subcat_idx < len(row) else "",
                clean_val(row[class_idx]) if class_idx is not None and class_idx < len(row) else "",
                parse_float(row[auth_idx]) if auth_idx is not None and auth_idx < len(row) else 0.0,
                parse_float(row[paid_idx]) if paid_idx is not None and paid_idx < len(row) else 0.0,
                clean_val(row[date_idx]) if date_idx is not None and date_idx < len(row) else "",
                clean_val(row[addr_idx]) if addr_idx is not None and addr_idx < len(row) else "",
                clean_val(row[list_idx]) if list_idx is not None and list_idx < len(row) else "",
                clean_val(row[status_idx]) if status_idx is not None and status_idx < len(row) else "",
                clean_val(row[state_idx]) if state_idx is not None and state_idx < len(row) else "",
                clean_val(row[nic_idx]) if nic_idx is not None and nic_idx < len(row) else "",
                clean_val(row[ind_idx]) if ind_idx is not None and ind_idx < len(row) else "",
                fname
            )
            batch.append(record)

            if len(batch) >= batch_size:
                cur.executemany("""
                    INSERT OR REPLACE INTO companies 
                    (cin, company_name, roc_code, category, sub_category, class,
                     authorized_capital, paidup_capital, registration_date, registered_address,
                     listing_status, status, state, nic_code, industrial_classification, source_file)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, batch)
                rows_inserted += len(batch)
                batch = []

        if batch:
            cur.executemany("""
                INSERT OR REPLACE INTO companies 
                (cin, company_name, roc_code, category, sub_category, class,
                 authorized_capital, paidup_capital, registration_date, registered_address,
                 listing_status, status, state, nic_code, industrial_classification, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            rows_inserted += len(batch)

    conn.commit()
    return rows_inserted


def ingest_xlsx(conn: sqlite3.Connection, fpath: Path):
    """Ingest XLSX file (e.g., Chattisgarh_2016.xlsx) into SQLite database."""
    import openpyxl
    fname = fpath.name
    cur = conn.cursor()
    wb = openpyxl.load_workbook(fpath, read_only=True)
    sheet = wb.active
    rows = sheet.iter_rows(values_only=True)
    header = next(rows, None)
    if not header:
        wb.close()
        return 0

    col_map = {str(col).strip().lower(): idx for idx, col in enumerate(header)}
    cin_idx = col_map.get("cin")
    name_idx = col_map.get("company_name") or col_map.get("companyname")
    class_idx = col_map.get("company_class")
    cat_idx = col_map.get("company_category")
    subcat_idx = col_map.get("company_subcat")
    status_idx = col_map.get("company_status")
    date_idx = col_map.get("date_of_registration")
    state_idx = col_map.get("registered_state")
    auth_idx = [col_map[k] for k in col_map if "authorized" in k]
    paid_idx = [col_map[k] for k in col_map if "paidup" in k or "paid_up" in k]
    auth_idx = auth_idx[0] if auth_idx else None
    paid_idx = paid_idx[0] if paid_idx else None
    nic_idx = col_map.get("principal_business_activity_code")
    addr_idx = col_map.get("registered_office_address")

    batch = []
    rows_inserted = 0
    for row in rows:
        if not row or cin_idx is None or len(row) <= cin_idx:
            continue
        cin = clean_val(row[cin_idx])
        if not cin or len(cin) < 10:
            continue

        record = (
            cin,
            clean_val(row[name_idx]) if name_idx is not None and name_idx < len(row) else "",
            "",
            clean_val(row[cat_idx]) if cat_idx is not None and cat_idx < len(row) else "",
            clean_val(row[subcat_idx]) if subcat_idx is not None and subcat_idx < len(row) else "",
            clean_val(row[class_idx]) if class_idx is not None and class_idx < len(row) else "",
            parse_float(row[auth_idx]) if auth_idx is not None and auth_idx < len(row) else 0.0,
            parse_float(row[paid_idx]) if paid_idx is not None and paid_idx < len(row) else 0.0,
            clean_val(row[date_idx]) if date_idx is not None and date_idx < len(row) else "",
            clean_val(row[addr_idx]) if addr_idx is not None and addr_idx < len(row) else "",
            "",
            clean_val(row[status_idx]) if status_idx is not None and status_idx < len(row) else "",
            clean_val(row[state_idx]) if state_idx is not None and state_idx < len(row) else "Chattisgarh",
            clean_val(row[nic_idx]) if nic_idx is not None and nic_idx < len(row) else "",
            "",
            fname
        )
        batch.append(record)
        if len(batch) >= 10000:
            cur.executemany("""
                INSERT OR REPLACE INTO companies 
                (cin, company_name, roc_code, category, sub_category, class,
                 authorized_capital, paidup_capital, registration_date, registered_address,
                 listing_status, status, state, nic_code, industrial_classification, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            rows_inserted += len(batch)
            batch = []

    if batch:
        cur.executemany("""
            INSERT OR REPLACE INTO companies 
            (cin, company_name, roc_code, category, sub_category, class,
             authorized_capital, paidup_capital, registration_date, registered_address,
             listing_status, status, state, nic_code, industrial_classification, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        rows_inserted += len(batch)

    conn.commit()
    wb.close()
    return rows_inserted


def build_database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    files = sorted([f for f in DATA_DIR.iterdir() if f.suffix in (".csv", ".xlsx") and not f.name.endswith(".tmp")])
    total_files = len(files)
    print("=" * 65)
    print(f" Ingesting {total_files} State Files into SQLite: {DB_PATH} ")
    print("=" * 65)
    t0 = time.time()
    grand_total = 0

    for idx, fpath in enumerate(files, 1):
        # Skip empty Chattisgarh.csv since Chattisgarh_2016.xlsx has the data
        if fpath.name == "Chattisgarh.csv":
            continue
        t_file = time.time()
        if fpath.name.endswith(".csv"):
            inserted = ingest_csv(conn, fpath)
        elif fpath.name.endswith(".xlsx"):
            inserted = ingest_xlsx(conn, fpath)
        else:
            continue
        grand_total += inserted
        print(f"[{idx:02d}/{total_files:02d}] {fpath.name:<30} -> {inserted:>8,} rows ({time.time() - t_file:.1f}s)")

    print("\nCreating performance indexes (CIN, Name, State, Status, Date)...")
    t_idx = time.time()
    conn.executescript(INDEX_SQL)
    conn.commit()
    print(f"Indexes created in {time.time() - t_idx:.1f}s")

    conn.close()
    dt = time.time() - t0
    db_size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print("=" * 65)
    print(f"Database build complete in {dt:.1f}s ({dt/60:.1f} min)")
    print(f"Total Companies Ingested : {grand_total:,}")
    print(f"Final SQLite Database Size : {db_size_mb:.2f} MB ({db_size_mb/1024:.2f} GB)")
    print("=" * 65)


def query_companies(term: str):
    if not DB_PATH.exists():
        print(f"Error: Database {DB_PATH} does not exist. Run with --build first.")
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT cin, company_name, state, status, class, authorized_capital, registration_date
        FROM companies
        WHERE cin LIKE ? OR company_name LIKE ?
        LIMIT 25
    """, (f"%{term}%", f"%{term}%"))
    results = cur.fetchall()
    conn.close()

    print(f"\n--- Search results for '{term}' (showing up to 25) ---")
    for r in results:
        print(f"CIN: {r[0]} | Name: {r[1]} | State: {r[2]} | Status: {r[3]} | Capital: Rs {r[5]:,.0f} | Date: {r[6]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MCA Company Database Ingestion and Query")
    parser.add_argument("--build", action="store_true", help="Build database from downloaded files")
    parser.add_argument("--search", type=str, help="Search for company by CIN or Name")
    args = parser.parse_args()

    if args.search:
        query_companies(args.search)
    else:
        build_database()
