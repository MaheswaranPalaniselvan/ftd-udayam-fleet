#!/usr/bin/env python3
"""
gstin_bridge.py
===============
GSTIN (Goods and Services Tax Identification Number) Bridge & Validator.

Format:
  [2 digits: State Code] + [10 chars: PAN] + [1 char: Entity Code] + [1 char: 'Z'] + [1 char: Checksum]
  Example: 33AABCT1332L1Z4
"""

import sys
import sqlite3
from pathlib import Path

# Character map for Luhn mod-36 checksum
CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CHAR_MAP = {c: i for i, c in enumerate(CHARS)}

STATE_CODES = {
    "JAMMU AND KASHMIR": "01",
    "HIMACHAL PRADESH": "02",
    "PUNJAB": "03",
    "CHANDIGARH": "04",
    "UTTARAKHAND": "05",
    "HARYANA": "06",
    "DELHI": "07",
    "RAJASTHAN": "08",
    "UTTAR PRADESH": "09",
    "BIHAR": "10",
    "SIKKIM": "11",
    "ARUNACHAL PRADESH": "12",
    "NAGALAND": "13",
    "MANIPUR": "14",
    "MIZORAM": "15",
    "TRIPURA": "16",
    "MEGHALAYA": "17",
    "ASSAM": "18",
    "WEST BENGAL": "19",
    "JHARKHAND": "20",
    "ODISHA": "21",
    "CHHATTISGARH": "22",
    "MADHYA PRADESH": "23",
    "GUJARAT": "24",
    "DAMAN AND DIU": "25",
    "DADRA AND NAGAR HAVELI": "26",
    "MAHARASHTRA": "27",
    "ANDHRA PRADESH": "28",  # Or 37 post-bifurcation
    "KARNATAKA": "29",
    "GOA": "30",
    "LAKSHADWEEP": "31",
    "KERALA": "32",
    "TAMIL NADU": "33",
    "PUDUCHERRY": "34",
    "ANDAMAN AND NICOBAR ISLANDS": "35",
    "TELANGANA": "36",
    "LADAKH": "38",
}


def calculate_gstin_checksum(first_14: str) -> str:
    """Calculate the 15th checksum character using Luhn Mod-36."""
    first_14 = first_14.upper()
    total = 0
    for i, c in enumerate(first_14):
        val = CHAR_MAP[c]
        factor = 2 if (i % 2 != 0) else 1
        product = val * factor
        quotient = product // 36
        remainder = product % 36
        total += quotient + remainder

    check_code = (36 - (total % 36)) % 36
    return CHARS[check_code]


def validate_gstin(gstin: str) -> bool:
    """Validates length, format, and checksum of a GSTIN."""
    gstin = gstin.strip().upper()
    if len(gstin) != 15:
        return False
    if gstin[13] != "Z":
        return False
    if not (gstin[:2].isdigit() and gstin[2:7].isalpha() and gstin[7:11].isdigit() and gstin[11].isalpha()):
        return False
    expected_check = calculate_gstin_checksum(gstin[:14])
    return gstin[14] == expected_check


def derive_gstin(state_code: str, pan: str, entity_number: int = 1) -> str:
    """Derives valid 15-character GSTIN from State Code and PAN."""
    st = str(state_code).zfill(2)
    pan = pan.strip().upper()
    entity = str(entity_number)
    base = f"{st}{pan}{entity}Z"
    chk = calculate_gstin_checksum(base)
    return f"{base}{chk}"


if __name__ == "__main__":
    test_gst = "33AABCT1332L1Z4"
    print(f"Testing GSTIN validation for {test_gst}: {validate_gstin(test_gst)}")
    
    # Example derivation
    derived = derive_gstin("33", "AABCT1332L", 1)
    print(f"Derived GSTIN for PAN AABCT1332L in Tamil Nadu (33): {derived}")
    print(f"Validation: {validate_gstin(derived)}")
