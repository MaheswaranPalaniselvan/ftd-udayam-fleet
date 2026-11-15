#!/usr/bin/env python3
"""
din_resolver.py
===============
Director Identification Number (DIN) Registry & Cross-Referencing Engine.

Maps individual directors (8-digit DIN) to one or multiple registered companies (CINs),
tracking appointment dates, cessation dates, and designations.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("data/mca_master.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS directors (
    din TEXT PRIMARY KEY,
    director_name TEXT,
    pan TEXT,
    nationality TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS company_directors (
    cin TEXT,
    din TEXT,
    designation TEXT,
    date_of_appointment TEXT,
    date_of_cessation TEXT,
    is_active INTEGER DEFAULT 1,
    PRIMARY KEY (cin, din),
    FOREIGN KEY(cin) REFERENCES companies(cin),
    FOREIGN KEY(din) REFERENCES directors(din)
);

CREATE INDEX IF NOT EXISTS idx_dir_name ON directors(director_name);
CREATE INDEX IF NOT EXISTS idx_cd_din ON company_directors(din);
CREATE INDEX IF NOT EXISTS idx_cd_cin ON company_directors(cin);
"""


def init_din_tables():
    if not DB_PATH.exists():
        print(f"Error: {DB_PATH} not found.")
        return
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    print("DIN schema initialized in data/mca_master.db.")


def lookup_director_companies(din: str):
    """Find all companies where a director is or was appointed."""
    din = din.strip().zfill(8)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT cd.cin, c.company_name, cd.designation, cd.date_of_appointment, cd.is_active
        FROM company_directors cd
        LEFT JOIN companies c ON cd.cin = c.cin
        WHERE cd.din = ?
    """, (din,))
    results = cur.fetchall()
    conn.close()
    return results


if __name__ == "__main__":
    init_din_tables()

