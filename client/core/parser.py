"""
Comprehensive Udyam HTML Parser & Local Archive Resolver.
Extracts all structured fields from Udyam registration certificates:
- Registration & Enterprise Details
- Address & Contact Info (Mobile, Email, Pin)
- Classification History (Micro/Small/Medium)
- Unit/Plant Location Details
- National Industry Classification (NIC) Codes & Activities
"""

import io
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from bs4 import BeautifulSoup


def _get_7z_binary() -> str | None:
    """Finds 7-Zip executable if available."""
    for bin_name in ("7z", "7za", "7zr"):
        found = shutil.which(bin_name)
        if found:
            return found
    common_paths = [
        Path(r"C:\Program Files\7-Zip\7z.exe"),
        Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
    ]
    for p in common_paths:
        if p.is_file():
            return str(p)
    return None


def extract_element_text(soup: BeautifulSoup, element_id: str) -> str:
    """Safely extracts stripped inner text from a DOM element by id."""
    el = soup.find(id=element_id)
    return el.text.strip() if el else ""


def extract_table_rows(soup: BeautifulSoup, header_keyword: str) -> list[list[str]]:
    """Finds a table preceded by a header containing header_keyword and returns rows of cells."""
    hdr = soup.find(lambda t: t.name in ["b", "h3", "h4", "th", "td", "div"] and header_keyword.lower() in t.text.lower())
    if not hdr:
        return []
    tbl = hdr.find_next("table")
    if not tbl:
        return []

    rows = tbl.find_all("tr")
    if len(rows) < 2:
        return []

    data = []
    for r in rows[1:]:
        cols = [td.text.strip() for td in r.find_all(["td", "th"])]
        if cols:
            data.append(cols)
    return data


def _clean(text: str) -> str:
    """Normalizes whitespace and removes unwanted multiline returns."""
    return re.sub(r"\s+", " ", text).strip() if text else ""


def parse_udyam_html(html_content: str) -> dict:
    """Parses full Udyam registration HTML document into a structured dictionary."""
    soup = BeautifulSoup(html_content, "html.parser")

    raw_activity = (
        extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblServices")
        or extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblManufacturing")
    )
    # Strip PSL notices like '[For availing benefits of Priority Sector Lending...]'
    cleaned_activity = re.sub(r"\[.*?\]", "", raw_activity).strip()

    record = {
        "Udyam Number": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lbludyamregNo")),
        "Enterprise Name": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblEnterpriseName")),
        "Organisation Type": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblOrganisationType")),
        "Major Activity": _clean(cleaned_activity or raw_activity),
        "Gender": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblGender")),
        "Social Category": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblsocialcat")),
        "Date of Incorporation": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lbldateofincorporation")),
        "Date of Commencement": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lbldateofcommencement")),
        "Date of Registration": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblACKNOWLEDGEMENT")),
        "Enterprise Type": "",
        "Classification Date": "",
        "Unit Names": "",
        "Flat / Door / Block": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblflats")),
        "Premises / Building": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblBuilding")),
        "Village / Town": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblVillage")),
        "Block": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblBlock")),
        "Road / Street": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblRoad")),
        "City": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblCity")),
        "State": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblState")),
        "District": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblDistrict")).replace(",Pin :", "").strip(),
        "Pin Code": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblPin")),
        "Mobile": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblMobile")),
        "Email": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblEmail")),
        "DIC": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblgmdic")),
        "MSME-DFO": _clean(extract_element_text(soup, "ctl00_ContentPlaceHolder1_lblMSMEDI")),
        "Primary NIC Code": "",
        "Primary NIC Activity": "",
        "All NIC Details": "",
    }

    # Fallback for Udyam Number if span is empty
    if not record["Udyam Number"]:
        m = re.search(r"UDYAM-[A-Z]{2}-\d{2}-\d{7}", html_content)
        if m:
            record["Udyam Number"] = m.group(0)

    # 1. Parse Enterprise Type Table (target leaf table only)
    for t in soup.find_all("table"):
        if len(t.find_all("table")) == 0:
            txt = t.get_text()
            if "Classification Year" in txt and "Enterprise Type" in txt:
                rows = t.find_all("tr")
                if len(rows) > 1:
                    cols = [_clean(c.get_text()) for c in rows[1].find_all(["td", "th"])]
                    if len(cols) >= 5:
                        record["Enterprise Type"] = cols[3]
                        record["Classification Date"] = cols[4]
                    elif len(cols) >= 4:
                        record["Enterprise Type"] = cols[2]
                        record["Classification Date"] = cols[3]
                break

    # 2. Parse Plant / Unit Details Table
    units = []
    plant_tbl = soup.find("table", id=lambda x: x and "gvPlant" in x)
    if not plant_tbl:
        for t in soup.find_all("table"):
            if len(t.find_all("table")) == 0 and "Unit Name" in t.get_text():
                plant_tbl = t
                break
    if plant_tbl:
        for r in plant_tbl.find_all("tr")[1:]:
            cols = [_clean(c.get_text()) for c in r.find_all(["td", "th"])]
            if len(cols) > 1 and cols[1]:
                units.append(cols[1])
    record["Unit Names"] = " | ".join(units)

    # 3. Parse NIC Code(s) Table
    nic_list = []
    for t in soup.find_all("table"):
        if len(t.find_all("table")) == 0 and "Nic 2 Digit" in t.get_text():
            rows = t.find_all("tr")
            for idx, r in enumerate(rows[1:]):
                cols = [_clean(c.get_text()) for c in r.find_all(["td", "th"])]
                if len(cols) >= 5:
                    nic_2, nic_4, nic_5, act = cols[1], cols[2], cols[3], cols[4]
                    if idx == 0:
                        record["Primary NIC Code"] = nic_5
                        record["Primary NIC Activity"] = f"{act} ({nic_2})"
                    nic_list.append(f"[{nic_5}] {act} - {nic_4}")
            break
    record["All NIC Details"] = " ; ".join(nic_list)

    return record


def find_html_content(udyam_number: str, results_dir: Path = Path("results")) -> str | None:
    """
    Locates HTML content for a given Udyam number:
    1. Checks uncompressed folder: results/{prefix}/{udyam_number}.html
    2. Checks .7z archive: results/{prefix}.7z (streams via 7z in ~50ms)
    """
    clean_num = udyam_number.strip().upper()
    m = re.match(r"^UDYAM-([A-Z]{2}-\d{2})-\d+", clean_num)
    if not m:
        # Fallback check across all results
        prefix = None
    else:
        prefix = m.group(1)

    # 1. Check uncompressed folder
    if prefix:
        local_file = results_dir / prefix / f"{clean_num}.html"
        if local_file.is_file():
            try:
                with open(local_file, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            except Exception:
                pass

    # 2. Check 7z archive
    seven_zip_bin = _get_7z_binary()
    if seven_zip_bin and prefix:
        archive_path = results_dir / f"{prefix}.7z"
        if archive_path.is_file():
            cmd = [seven_zip_bin, "e", str(archive_path), "-r", f"{clean_num}.html", "-so"]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace")
                if proc.stdout and "html" in proc.stdout.lower():
                    return proc.stdout
            except Exception:
                pass

    # 3. Fallback search across any folder in results_dir
    matches = list(results_dir.glob(f"**/{clean_num}.html"))
    if matches:
        try:
            with open(matches[0], "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            pass

    return None
