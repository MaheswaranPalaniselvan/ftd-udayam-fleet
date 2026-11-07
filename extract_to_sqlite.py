import os
import sqlite3
import json
import csv
from bs4 import BeautifulSoup
import re

RESULTS_DIR = "results"
FAILED_DIR = "failed"
DB_PATH = os.path.join("github-pages", "udyam_data.sqlite")

def extract_text(soup, element_id):
    el = soup.find(id=element_id)
    return el.text.strip() if el else ""

def extract_table_data(soup, header_text):
    # Find the header element, then find the next table
    header_el = soup.find(lambda tag: tag.name in ["b", "h3", "h4"] and header_text in tag.text)
    if not header_el:
        return []
    
    table = header_el.find_next("table")
    if not table:
        return []
        
    rows = table.find_all("tr")
    if len(rows) < 2:
        return []
        
    headers = [th.text.strip() for th in rows[0].find_all(["th", "td"])]
    
    data = []
    for row in rows[1:]:
        cols = [td.text.strip() for td in row.find_all("td")]
        if len(cols) == len(headers):
            data.append(dict(zip(headers, cols)))
    return data

def parse_html(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')
        
    record = {
        "udyam_reg_no": extract_text(soup, "ctl00_ContentPlaceHolder1_lbludyamregNo"),
        "enterprise_name": extract_text(soup, "ctl00_ContentPlaceHolder1_lblEnterpriseName"),
        "organisation_type": extract_text(soup, "ctl00_ContentPlaceHolder1_lblOrganisationType"),
        "major_activity": extract_text(soup, "ctl00_ContentPlaceHolder1_lblServices") or extract_text(soup, "ctl00_ContentPlaceHolder1_lblManufacturing"),
        "gender": extract_text(soup, "ctl00_ContentPlaceHolder1_lblGender"),
        "social_category": extract_text(soup, "ctl00_ContentPlaceHolder1_lblsocialcat"),
        "date_of_incorporation": extract_text(soup, "ctl00_ContentPlaceHolder1_lbldateofincorporation"),
        "date_of_commencement": extract_text(soup, "ctl00_ContentPlaceHolder1_lbldateofcommencement"),
        "flat": extract_text(soup, "ctl00_ContentPlaceHolder1_lblflats"),
        "building": extract_text(soup, "ctl00_ContentPlaceHolder1_lblBuilding"),
        "village": extract_text(soup, "ctl00_ContentPlaceHolder1_lblVillage"),
        "block": extract_text(soup, "ctl00_ContentPlaceHolder1_lblBlock"),
        "road": extract_text(soup, "ctl00_ContentPlaceHolder1_lblRoad"),
        "city": extract_text(soup, "ctl00_ContentPlaceHolder1_lblCity"),
        "state": extract_text(soup, "ctl00_ContentPlaceHolder1_lblState"),
        "district": extract_text(soup, "ctl00_ContentPlaceHolder1_lblDistrict"),
        "pin": extract_text(soup, "ctl00_ContentPlaceHolder1_lblPin"),
        "mobile": extract_text(soup, "ctl00_ContentPlaceHolder1_lblMobile"),
        "email": extract_text(soup, "ctl00_ContentPlaceHolder1_lblEmail"),
    }
    
    classification_data = extract_table_data(soup, "Enterprise Type")
    record["classification_details"] = json.dumps(classification_data) if classification_data else "[]"
    
    nic_data = extract_table_data(soup, "National Industry Classification")
    record["nic_codes"] = json.dumps(nic_data) if nic_data else "[]"
    
    return record

def process_results():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Track the tables we've created
    created_tables = set()
    
    # Process successes
    for state_folder in os.listdir(RESULTS_DIR):
        folder_path = os.path.join(RESULTS_DIR, state_folder)
        if not os.path.isdir(folder_path):
            continue
            
        # Clean table name (e.g., DL-01 -> DL_01)
        table_name = state_folder.replace("-", "_")
            
        print(f"Processing folder {state_folder} into table {table_name}...")
        
        # Create table if not exists
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                udyam_reg_no TEXT PRIMARY KEY,
                enterprise_name TEXT,
                organisation_type TEXT,
                major_activity TEXT,
                gender TEXT,
                social_category TEXT,
                date_of_incorporation TEXT,
                date_of_commencement TEXT,
                flat TEXT,
                building TEXT,
                village TEXT,
                block TEXT,
                road TEXT,
                city TEXT,
                state TEXT,
                district TEXT,
                pin TEXT,
                mobile TEXT,
                email TEXT,
                classification_details TEXT,
                nic_codes TEXT
            )
        """)
        created_tables.add(table_name)
        
        count = 0
        for file in os.listdir(folder_path):
            if file.endswith(".html"):
                filepath = os.path.join(folder_path, file)
                try:
                    record = parse_html(filepath)
                    
                    columns = ', '.join(record.keys())
                    placeholders = ', '.join(['?'] * len(record))
                    query = f"INSERT OR REPLACE INTO {table_name} ({columns}) VALUES ({placeholders})"
                    
                    cursor.execute(query, tuple(record.values()))
                    count += 1
                except Exception as e:
                    print(f"Error parsing {file}: {e}")
                    
        print(f"Inserted {count} records into {table_name}")
        conn.commit()
        
    # Process failures
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS failures (
            state_district TEXT,
            udyam_number TEXT PRIMARY KEY,
            status TEXT,
            time_taken_s REAL
        )
    """)
    
    if os.path.exists(FAILED_DIR):
        fail_count = 0
        for state_folder in os.listdir(FAILED_DIR):
            folder_path = os.path.join(FAILED_DIR, state_folder)
            if not os.path.isdir(folder_path):
                continue
                
            for file in os.listdir(folder_path):
                if file.startswith("failed_") and file.endswith(".csv"):
                    filepath = os.path.join(folder_path, file)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            reader = csv.reader(f)
                            header = next(reader, None)
                            for row in reader:
                                if row and len(row) >= 3:
                                    udyam_no = row[0]
                                    status = row[1]
                                    time_taken = row[2]
                                    
                                    cursor.execute("""
                                        INSERT OR REPLACE INTO failures 
                                        (state_district, udyam_number, status, time_taken_s)
                                        VALUES (?, ?, ?, ?)
                                    """, (state_folder, udyam_no, status, time_taken))
                                    fail_count += 1
                    except Exception as e:
                        print(f"Error parsing {file}: {e}")
        print(f"Inserted {fail_count} failure records.")
        conn.commit()

    conn.close()
    print("Database generation complete.")

if __name__ == "__main__":
    process_results()
