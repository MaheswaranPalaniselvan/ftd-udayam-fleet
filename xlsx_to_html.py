"""
FlawlessTech Data - Enterprise XLSX to HTML Converter & Interactive Viewer
Converts any Excel (.xlsx) file into an interactive, beautifully formatted web dashboard
with instant search, multi-column filtering, sorting, KPI metrics, enterprise dossier modal,
and client-side .xlsx download powered by SheetJS.
"""

import argparse
import base64
import json
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
import openpyxl


def get_logo_base64() -> str:
    """Returns the base64-encoded FlawlessTech Data logo or empty string."""
    logo_path = Path(__file__).parent / "flawless_logo.png"
    if logo_path.exists():
        try:
            with open(logo_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            pass
    return ""


def read_xlsx_to_dict(xlsx_path: Path) -> dict:
    """Reads all sheets from an .xlsx workbook into structured dictionaries."""
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Excel file not found: {xlsx_path}")

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    sheets_data = {}

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        headers = []
        for cell in ws[1]:
            val = cell.value
            headers.append(str(val).strip() if val is not None else f"Column_{len(headers)+1}")

        # Remove trailing empty headers
        while headers and headers[-1].startswith("Column_") and all(ws.cell(r, len(headers)).value is None for r in range(2, min(ws.max_row + 1, 15))):
            headers.pop()

        rows = []
        for row in ws.iter_rows(min_row=2, max_col=len(headers), values_only=True):
            if not any(v is not None and str(v).strip() != "" for v in row):
                continue
            row_dict = {}
            for i, h in enumerate(headers):
                val = row[i] if i < len(row) else ""
                if val is None:
                    row_dict[h] = ""
                elif isinstance(val, (datetime,)):
                    row_dict[h] = val.strftime("%d/%m/%Y")
                else:
                    row_dict[h] = str(val).strip()
            rows.append(row_dict)

        sheets_data[sheet_name] = {
            "headers": headers,
            "rows": rows,
            "total_rows": len(rows),
        }

    active_sheet = wb.active.title if wb.active else (wb.sheetnames[0] if wb.sheetnames else "")
    return {
        "filename": xlsx_path.name,
        "sheets": sheets_data,
        "active_sheet": active_sheet,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def generate_html_content(data_payload: dict, logo_b64: str) -> str:
    """Generates a self-contained, interactive HTML document with FlawlessTech Data branding."""
    json_data_str = json.dumps(data_payload, ensure_ascii=False)
    filename = data_payload.get("filename", "Dataset.xlsx")

    logo_src = f"data:image/png;base64,{logo_b64}" if logo_b64 else "https://flawlesstechdata.com/wp-content/uploads/2024/10/FLawless.png"

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FlawlessTech Data | Enterprise Data Viewer</title>
  <meta name="description" content="Interactive enterprise Excel viewer with search, filtering, and export by FlawlessTech Data.">
  
  <!-- Google Fonts: Outfit & Inter & JetBrains Mono -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  
  <!-- SheetJS for local Excel parsing and client-side XLSX generation -->
  <script src="assets/xlsx.full.min.js"></script>
  <script>
    if (typeof XLSX === 'undefined') {{
      document.write('<script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"><\\/script>');
    }}
  </script>

  <style>
    :root {{
      /* Dark Theme (Default) */
      --bg-base: #080c14;
      --bg-surface: #0f172a;
      --bg-card: rgba(17, 24, 39, 0.85);
      --bg-card-hover: rgba(30, 41, 59, 0.9);
      --bg-input: #0f172a;
      --bg-table-head: #111a2e;
      --bg-table-head-hover: #18243e;
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-card: rgba(255, 255, 255, 0.12);
      --border-focus: #38bdf8;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --accent-cyan: #00d2ff;
      --accent-blue: #3b82f6;
      --accent-indigo: #6366f1;
      --accent-emerald: #10b981;
      --accent-amber: #f59e0b;
      --accent-rose: #f43f5e;
      --accent-purple: #a855f7;
      --font-heading: 'Outfit', sans-serif;
      --font-body: 'Inter', sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
      --shadow-glow: 0 0 25px rgba(0, 210, 255, 0.15);
      --shadow-card: 0 10px 30px rgba(0, 0, 0, 0.35);
      --shadow-header: 0 4px 20px rgba(0, 0, 0, 0.4);
      --radius-sm: 8px;
      --radius-md: 12px;
      --radius-lg: 18px;
      --banner-bg: linear-gradient(135deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 41, 59, 0.85) 100%);
      --banner-title: #ffffff;
      --banner-tag-bg: rgba(255, 255, 255, 0.05);
      --banner-tag-border: rgba(255, 255, 255, 0.08);
      --banner-tag-color: #cbd5e1;
      --table-stripe: rgba(255, 255, 255, 0.015);
      --table-hover: rgba(0, 210, 255, 0.07);
      --table-td-border: rgba(255, 255, 255, 0.04);
      --table-td-text: #cbd5e1;
      --mono-color: #93c5fd;
      --btn-outline-bg: rgba(255, 255, 255, 0.05);
      --btn-outline-hover: rgba(255, 255, 255, 0.12);
      --btn-outline-text: #f1f5f9;
      --tab-bg: rgba(255, 255, 255, 0.04);
      --tab-text: #94a3b8;
      --modal-bg: #0f172a;
      --modal-header-bg: #111e38;
      --modal-box-bg: rgba(255, 255, 255, 0.02);
      --footer-bg: #090e1a;
      --radial-1: rgba(0, 210, 255, 0.07);
      --radial-2: rgba(99, 102, 241, 0.07);
      --radial-3: rgba(16, 185, 129, 0.05);
      --badge-success-bg: rgba(16, 185, 129, 0.15);
      --badge-success-text: #34d399;
      --badge-success-border: rgba(16, 185, 129, 0.35);
      --badge-failed-bg: rgba(244, 63, 94, 0.15);
      --badge-failed-text: #fb7185;
      --badge-failed-border: rgba(244, 63, 94, 0.35);
      --badge-micro-bg: rgba(168, 85, 247, 0.15);
      --badge-micro-text: #c084fc;
      --badge-micro-border: rgba(168, 85, 247, 0.35);
      --badge-small-bg: rgba(0, 210, 255, 0.15);
      --badge-small-text: #38bdf8;
      --badge-small-border: rgba(0, 210, 255, 0.35);
      --badge-medium-bg: rgba(59, 130, 246, 0.15);
      --badge-medium-text: #60a5fa;
      --badge-medium-border: rgba(59, 130, 246, 0.35);
      --badge-activity-bg: rgba(245, 158, 11, 0.15);
      --badge-activity-text: #fbbf24;
      --badge-activity-border: rgba(245, 158, 11, 0.3);
    }}

    [data-theme="light"] {{
      /* High-Contrast Corporate Light Theme */
      --bg-base: #f4f6fb;
      --bg-surface: #ffffff;
      --bg-card: #ffffff;
      --bg-card-hover: #f8fafc;
      --bg-input: #ffffff;
      --bg-table-head: #eef2f7;
      --bg-table-head-hover: #e2e8f0;
      --border-subtle: #e2e8f0;
      --border-card: #cbd5e1;
      --border-focus: #0284c7;
      --text-main: #0f172a;
      --text-muted: #475569;
      --text-dim: #64748b;
      --accent-cyan: #0284c7;
      --accent-blue: #2563eb;
      --accent-indigo: #4f46e5;
      --accent-emerald: #059669;
      --accent-amber: #d97706;
      --accent-rose: #e11d48;
      --accent-purple: #7e22ce;
      --shadow-glow: 0 0 20px rgba(2, 132, 199, 0.12);
      --shadow-card: 0 4px 16px rgba(15, 23, 42, 0.06);
      --shadow-header: 0 2px 10px rgba(15, 23, 42, 0.05);
      --banner-bg: linear-gradient(135deg, #ffffff 0%, #f1f5f9 100%);
      --banner-title: #0f172a;
      --banner-tag-bg: #f1f5f9;
      --banner-tag-border: #e2e8f0;
      --banner-tag-color: #334155;
      --table-stripe: #f8fafc;
      --table-hover: rgba(2, 132, 199, 0.08);
      --table-td-border: #f1f5f9;
      --table-td-text: #1e293b;
      --mono-color: #1e40af;
      --btn-outline-bg: #f8fafc;
      --btn-outline-hover: #f1f5f9;
      --btn-outline-text: #0f172a;
      --tab-bg: #f1f5f9;
      --tab-text: #475569;
      --modal-bg: #ffffff;
      --modal-header-bg: #f8fafc;
      --modal-box-bg: #f8fafc;
      --footer-bg: #ffffff;
      --radial-1: rgba(2, 132, 199, 0.04);
      --radial-2: rgba(79, 70, 229, 0.03);
      --radial-3: rgba(5, 150, 105, 0.03);
      --badge-success-bg: #ecfdf5;
      --badge-success-text: #047857;
      --badge-success-border: #a7f3d0;
      --badge-failed-bg: #fef2f2;
      --badge-failed-text: #b91c1c;
      --badge-failed-border: #fecaca;
      --badge-micro-bg: #f5f3ff;
      --badge-micro-text: #6d28d9;
      --badge-micro-border: #ddd6fe;
      --badge-small-bg: #f0f9ff;
      --badge-small-text: #0369a1;
      --badge-small-border: #bae6fd;
      --badge-medium-bg: #eff6ff;
      --badge-medium-text: #1d4ed8;
      --badge-medium-border: #bfdbfe;
      --badge-activity-bg: #fffbeb;
      --badge-activity-text: #b45309;
      --badge-activity-border: #fde68a;
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      background-color: var(--bg-base);
      color: var(--text-main);
      font-family: var(--font-body);
      line-height: 1.5;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      overflow-x: hidden;
      background-image: 
        radial-gradient(circle at 15% 10%, var(--radial-1) 0%, transparent 45%),
        radial-gradient(circle at 85% 20%, var(--radial-2) 0%, transparent 45%),
        radial-gradient(circle at 50% 85%, var(--radial-3) 0%, transparent 50%);
      background-attachment: fixed;
      transition: background-color 0.25s ease, color 0.25s ease;
    }}

    /* Top Navigation Banner */
    header.flawless-header {{
      background: var(--bg-surface);
      backdrop-filter: blur(18px);
      -webkit-backdrop-filter: blur(18px);
      border-bottom: 1px solid var(--border-subtle);
      position: sticky;
      top: 0;
      z-index: 100;
      padding: 12px 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      box-shadow: var(--shadow-header);
      transition: background-color 0.25s ease, border-color 0.25s ease;
    }}

    .brand-group {{
      display: flex;
      align-items: center;
      gap: 18px;
      text-decoration: none;
    }}

    .brand-logo-img {{
      height: 44px;
      max-width: 200px;
      object-fit: contain;
      filter: drop-shadow(0 2px 8px rgba(0,0,0,0.25));
    }}

    .brand-divider {{
      width: 1px;
      height: 32px;
      background: var(--border-subtle);
    }}

    .brand-titles h1 {{
      font-family: var(--font-heading);
      font-size: 1.15rem;
      font-weight: 700;
      color: var(--text-main);
      letter-spacing: -0.01em;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .brand-titles .tagline {{
      font-size: 0.78rem;
      color: var(--text-muted);
      font-weight: 400;
    }}

    .header-actions {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}

    /* Global Buttons */
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      font-family: var(--font-body);
      font-size: 0.86rem;
      font-weight: 600;
      padding: 8px 16px;
      border-radius: var(--radius-sm);
      border: 1px solid transparent;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      text-decoration: none;
      white-space: nowrap;
      user-select: none;
    }}

    .btn:active {{
      transform: scale(0.97);
    }}

    .btn-primary {{
      background: linear-gradient(135deg, #00d2ff 0%, #3a7bd5 100%);
      color: #040d1a;
      font-weight: 700;
      box-shadow: 0 4px 14px rgba(0, 210, 255, 0.35);
    }}

    .btn-primary:hover {{
      box-shadow: 0 6px 20px rgba(0, 210, 255, 0.5);
      filter: brightness(1.08);
      transform: translateY(-1px);
    }}

    .btn-outline {{
      background: var(--btn-outline-bg);
      color: var(--btn-outline-text);
      border-color: var(--border-subtle);
    }}

    .btn-outline:hover {{
      background: var(--btn-outline-hover);
      border-color: var(--border-card);
      color: var(--text-main);
    }}

    .theme-toggle-btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-weight: 600;
    }}

    .btn-success {{
      background: linear-gradient(135deg, #10b981 0%, #059669 100%);
      color: #ffffff;
      box-shadow: 0 4px 14px rgba(16, 185, 129, 0.3);
    }}

    .btn-success:hover {{
      box-shadow: 0 6px 18px rgba(16, 185, 129, 0.45);
      filter: brightness(1.08);
    }}

    .btn-sm {{
      padding: 5px 11px;
      font-size: 0.78rem;
    }}

    /* Main Container */
    main.app-container {{
      max-width: 1600px;
      width: 100%;
      margin: 0 auto;
      padding: 24px 28px 48px;
      flex: 1;
    }}

    /* Company Overview Card */
    .company-banner {{
      background: var(--banner-bg);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 22px 28px;
      margin-bottom: 24px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      position: relative;
      overflow: hidden;
      box-shadow: var(--shadow-card);
      transition: background 0.25s ease, border-color 0.25s ease;
    }}

    .company-banner::before {{
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      width: 4px;
      height: 100%;
      background: linear-gradient(180deg, var(--accent-cyan) 0%, var(--accent-indigo) 100%);
    }}

    .banner-text {{
      max-width: 820px;
    }}

    .banner-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      background: rgba(0, 210, 255, 0.12);
      color: var(--accent-cyan);
      border: 1px solid rgba(0, 210, 255, 0.3);
      padding: 4px 10px;
      border-radius: 999px;
      margin-bottom: 8px;
    }}

    .banner-title {{
      font-family: var(--font-heading);
      font-size: 1.4rem;
      font-weight: 700;
      color: var(--banner-title);
      margin-bottom: 6px;
    }}

    .banner-desc {{
      font-size: 0.88rem;
      color: var(--text-muted);
      line-height: 1.55;
    }}

    .banner-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}

    .tech-pill {{
      font-size: 0.75rem;
      background: var(--banner-tag-bg);
      border: 1px solid var(--banner-tag-border);
      color: var(--banner-tag-color);
      padding: 3px 10px;
      border-radius: 6px;
    }}

    .banner-links {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    /* KPI Summary Row */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}

    .kpi-card {{
      background: var(--bg-card);
      backdrop-filter: blur(12px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 16px 20px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      position: relative;
      transition: transform 0.2s ease, border-color 0.2s ease;
      box-shadow: var(--shadow-card);
    }}

    .kpi-card:hover {{
      transform: translateY(-2px);
      border-color: var(--border-card);
    }}

    .kpi-label {{
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .kpi-value {{
      font-family: var(--font-heading);
      font-size: 1.85rem;
      font-weight: 800;
      color: var(--text-main);
      line-height: 1.15;
    }}

    .kpi-subtext {{
      font-size: 0.74rem;
      color: var(--text-muted);
      margin-top: 2px;
    }}

    .kpi-card.cyan .kpi-value {{ color: var(--accent-cyan); }}
    .kpi-card.emerald .kpi-value {{ color: var(--accent-emerald); }}
    .kpi-card.purple .kpi-value {{ color: var(--accent-purple); }}
    .kpi-card.amber .kpi-value {{ color: var(--accent-amber); }}
    .kpi-card.blue .kpi-value {{ color: var(--accent-blue); }}

    /* Data Toolbar & Sheet Tabs */
    .controls-panel {{
      background: var(--bg-card);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 18px 22px;
      margin-bottom: 20px;
      box-shadow: var(--shadow-card);
    }}

    .toolbar-header {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--border-subtle);
    }}

    .sheet-tabs {{
      display: flex;
      align-items: center;
      gap: 8px;
      overflow-x: auto;
      max-width: 650px;
    }}

    .sheet-tab {{
      padding: 6px 14px;
      background: var(--tab-bg);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      color: var(--tab-text);
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
      white-space: nowrap;
    }}

    .sheet-tab.active {{
      background: rgba(0, 210, 255, 0.12);
      border-color: var(--accent-cyan);
      color: var(--accent-cyan);
      box-shadow: 0 0 12px rgba(0, 210, 255, 0.2);
    }}

    .action-button-group {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }}

    /* Search & Multi-Filters */
    .filter-grid {{
      display: grid;
      grid-template-columns: 2fr 1fr 1fr 1fr 1fr auto;
      gap: 12px;
      align-items: center;
    }}

    @media (max-width: 1200px) {{
      .filter-grid {{
        grid-template-columns: 1fr 1fr 1fr;
      }}
    }}

    @media (max-width: 768px) {{
      .filter-grid {{
        grid-template-columns: 1fr;
      }}
    }}

    .input-wrapper {{
      position: relative;
    }}

    .search-input, .select-filter {{
      width: 100%;
      background: var(--bg-input);
      border: 1px solid var(--border-subtle);
      color: var(--text-main);
      font-family: var(--font-body);
      font-size: 0.85rem;
      padding: 9px 14px;
      border-radius: var(--radius-sm);
      outline: none;
      transition: border-color 0.2s, box-shadow 0.2s;
    }}

    .search-input:focus, .select-filter:focus {{
      border-color: var(--accent-cyan);
      box-shadow: 0 0 0 3px rgba(0, 210, 255, 0.15);
    }}

    .select-filter option {{
      background: var(--bg-surface);
      color: var(--text-main);
    }}

    /* Data Table Card */
    .table-container {{
      background: var(--bg-card);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      overflow: hidden;
      box-shadow: var(--shadow-card);
      margin-bottom: 20px;
      position: relative;
    }}

    .table-wrapper {{
      width: 100%;
      overflow-x: auto;
      max-height: 680px;
    }}

    table.flawless-table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 0.82rem;
      text-align: left;
    }}

    thead th {{
      position: sticky;
      top: 0;
      background: var(--bg-table-head);
      color: var(--text-main);
      font-family: var(--font-heading);
      font-weight: 700;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 13px 16px;
      border-bottom: 2px solid var(--accent-cyan);
      white-space: nowrap;
      cursor: pointer;
      user-select: none;
      z-index: 10;
      transition: background 0.2s ease, color 0.2s ease;
    }}

    thead th:hover {{
      background: var(--bg-table-head-hover);
      color: var(--accent-cyan);
    }}

    thead th .sort-icon {{
      margin-left: 6px;
      font-size: 0.7rem;
      opacity: 0.5;
    }}

    thead th.sorted-asc .sort-icon {{
      opacity: 1;
      color: var(--accent-cyan);
    }}

    thead th.sorted-desc .sort-icon {{
      opacity: 1;
      color: var(--accent-cyan);
    }}

    tbody tr {{
      transition: background-color 0.15s ease;
      cursor: pointer;
    }}

    tbody tr:nth-child(even) {{
      background-color: var(--table-stripe);
    }}

    tbody tr:hover {{
      background-color: var(--table-hover) !important;
    }}

    tbody td {{
      padding: 11px 16px;
      border-bottom: 1px solid var(--table-td-border);
      color: var(--table-td-text);
      white-space: nowrap;
      max-width: 320px;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .mono-cell {{
      font-family: var(--font-mono);
      font-size: 0.8rem;
      color: var(--mono-color);
    }}

    /* Badges */
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.02em;
      white-space: nowrap;
    }}

    .badge-success {{
      background: var(--badge-success-bg);
      color: var(--badge-success-text);
      border: 1px solid var(--badge-success-border);
    }}

    .badge-failed {{
      background: var(--badge-failed-bg);
      color: var(--badge-failed-text);
      border: 1px solid var(--badge-failed-border);
    }}

    .badge-micro {{
      background: var(--badge-micro-bg);
      color: var(--badge-micro-text);
      border: 1px solid var(--badge-micro-border);
    }}

    .badge-small {{
      background: var(--badge-small-bg);
      color: var(--badge-small-text);
      border: 1px solid var(--badge-small-border);
    }}

    .badge-medium {{
      background: var(--badge-medium-bg);
      color: var(--badge-medium-text);
      border: 1px solid var(--badge-medium-border);
    }}

    .badge-activity {{
      background: var(--badge-activity-bg);
      color: var(--badge-activity-text);
      border: 1px solid var(--badge-activity-border);
    }}

    /* Pagination Footer */
    .table-footer {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 22px;
      background: var(--bg-surface);
      border-top: 1px solid var(--border-subtle);
    }}

    .page-info {{
      font-size: 0.82rem;
      color: var(--text-muted);
    }}

    .pagination-controls {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    .page-btn {{
      min-width: 32px;
      height: 32px;
      padding: 0 8px;
      background: var(--btn-outline-bg);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      color: var(--btn-outline-text);
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: all 0.2s ease;
    }}

    .page-btn:hover:not(:disabled) {{
      background: var(--btn-outline-hover);
      border-color: var(--border-card);
      color: var(--text-main);
    }}

    .page-btn.active {{
      background: var(--accent-cyan);
      color: #040d1a;
      font-weight: 700;
      border-color: var(--accent-cyan);
    }}

    .page-btn:disabled {{
      opacity: 0.35;
      cursor: not-allowed;
    }}

    /* Enterprise Dossier Modal */
    .modal-backdrop {{
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: rgba(4, 9, 20, 0.78);
      backdrop-filter: blur(8px);
      z-index: 1000;
      display: flex;
      align-items: center;
      justify-content: center;
      opacity: 0;
      visibility: hidden;
      transition: opacity 0.25s ease, visibility 0.25s ease;
      padding: 20px;
    }}

    .modal-backdrop.active {{
      opacity: 1;
      visibility: visible;
    }}

    .modal-box {{
      background: var(--modal-bg);
      border: 1px solid var(--border-card);
      border-radius: var(--radius-lg);
      width: 100%;
      max-width: 900px;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 25px 60px rgba(0, 0, 0, 0.4), var(--shadow-glow);
      transform: scale(0.95);
      transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
      overflow: hidden;
    }}

    .modal-backdrop.active .modal-box {{
      transform: scale(1);
    }}

    .modal-header {{
      padding: 18px 24px;
      background: var(--modal-header-bg);
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}

    .modal-title h2 {{
      font-family: var(--font-heading);
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--text-main);
    }}

    .modal-title .modal-subtitle {{
      font-family: var(--font-mono);
      font-size: 0.8rem;
      color: var(--accent-cyan);
    }}

    .modal-close {{
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 1.4rem;
      cursor: pointer;
      line-height: 1;
      transition: color 0.2s ease;
    }}

    .modal-close:hover {{
      color: var(--text-main);
    }}

    .modal-body {{
      padding: 24px;
      overflow-y: auto;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 20px;
      background: var(--modal-bg);
    }}

    .dossier-section-title {{
      font-family: var(--font-heading);
      font-size: 0.95rem;
      font-weight: 700;
      color: var(--accent-cyan);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 10px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .dossier-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
      background: var(--modal-box-bg);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 16px;
    }}

    .dossier-item {{
      display: flex;
      flex-direction: column;
      gap: 3px;
    }}

    .dossier-item-label {{
      font-size: 0.72rem;
      color: var(--text-dim);
      font-weight: 600;
      text-transform: uppercase;
    }}

    .dossier-item-value {{
      font-size: 0.88rem;
      color: var(--text-main);
      font-weight: 500;
      word-break: break-word;
    }}

    .dossier-full-box {{
      background: var(--modal-box-bg);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 14px 16px;
      font-size: 0.84rem;
      color: var(--text-main);
      line-height: 1.5;
    }}

    /* Footer */
    footer.flawless-footer {{
      background: var(--footer-bg);
      border-top: 1px solid var(--border-subtle);
      padding: 32px 28px;
      margin-top: auto;
      font-size: 0.82rem;
      color: var(--text-muted);
      transition: background 0.25s ease, border-color 0.25s ease;
    }}

    .footer-content {{
      max-width: 1600px;
      margin: 0 auto;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
    }}

    .footer-brand {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}

    .footer-links {{
      display: flex;
      gap: 18px;
    }}

    .footer-links a {{
      color: var(--text-muted);
      text-decoration: none;
      transition: color 0.2s;
    }}

    .footer-links a:hover {{
      color: var(--accent-cyan);
    }}
  </style>
</head>
<body>
  <!-- Inline Zero-Flash Theme Initialization -->
  <script>
    (function() {{
      try {{
        const savedTheme = localStorage.getItem('flawless_theme');
        if (savedTheme === 'light' || (!savedTheme && window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches)) {{
          document.documentElement.setAttribute('data-theme', 'light');
        }} else {{
          document.documentElement.setAttribute('data-theme', 'dark');
        }}
      }} catch (e) {{}}
    }})();
  </script>

  <!-- Header Navigation -->
  <header class="flawless-header">
    <a href="https://flawlesstechdata.com/" target="_blank" class="brand-group" title="Visit FlawlessTech Data">
      <img src="{logo_src}" alt="FlawlessTech Data Logo" class="brand-logo-img">
      <div class="brand-divider"></div>
      <div class="brand-titles">
        <h1>Enterprise Data Viewer</h1>
        <div class="tagline">FlawlessTech Data &bull; Empowering Your Business with Data-Driven Solutions</div>
      </div>
    </a>

    <div class="header-actions">
      <button class="btn btn-outline btn-sm theme-toggle-btn" id="btnThemeToggle" onclick="toggleTheme();" title="Toggle between Dark and Light Mode">
        <span id="themeIcon">☀️</span> <span id="themeLabel">Light Mode</span>
      </button>
      <button class="btn btn-outline btn-sm" id="btnCopyFailed" onclick="copyFailedNumbers();" title="Copy all failed Udyam numbers to clipboard for retry in the GUI">
        🔄 Copy Failed Numbers
      </button>
      <button class="btn btn-success btn-sm" id="btnDownloadXLSX" onclick="downloadCurrentDataXLSX();" title="Download the current table data directly as an Excel file">
        📥 Download as XLSX
      </button>
      <button class="btn btn-outline btn-sm" id="btnDownloadCSV" onclick="downloadCurrentDataCSV();" title="Download current records as CSV">
        📄 Export CSV
      </button>
    </div>
  </header>

  <!-- Main Container -->
  <main class="app-container">

    <!-- FlawlessTech Data Feature Banner -->
    <div class="company-banner">
      <div class="banner-text">
        <div class="banner-badge">🏢 FLAWLESSTECH DATA &bull; OFFICIAL CLIENT REPORT</div>
        <div class="banner-title" id="reportTitle">Udyam Registration Records & MSME Enterprise Directory</div>
        <p class="banner-desc">
          Automated web intelligence report extracted with distributed Playwright stealth crawlers, OCR verification, 
          and structured data pipelines. Designed, processed, and validated for <strong>FlawlessTech Data</strong>.
        </p>
        <div class="banner-tags">
          <span class="tech-pill">🌐 High-Scale Web Scraping</span>
          <span class="tech-pill">🎯 B2B Lead Intelligence</span>
          <span class="tech-pill">📊 Master Data Management</span>
          <span class="tech-pill">⚡ Real-time OCR Automation</span>
        </div>
      </div>

      <div class="banner-links">
        <a href="https://flawlesstechdata.com/contact/" target="_blank" class="btn btn-primary">
          Get in Touch &rarr;
        </a>
        <a href="https://flawlesstechdata.com/web-scraping/" target="_blank" class="btn btn-outline">
          Our Services
        </a>
      </div>
    </div>

    <!-- KPI Summary Row -->
    <div class="kpi-grid" id="kpiGrid">
      <div class="kpi-card cyan">
        <div class="kpi-label">Total Records</div>
        <div class="kpi-value" id="kpiTotal">0</div>
        <div class="kpi-subtext" id="kpiFileLabel">Verified Udyam Directory</div>
      </div>
      <div class="kpi-card emerald">
        <div class="kpi-label">Active / Success</div>
        <div class="kpi-value" id="kpiSuccess">0</div>
        <div class="kpi-subtext" id="kpiSuccessPct">100% verified</div>
      </div>
      <div class="kpi-card purple">
        <div class="kpi-label">Micro Units</div>
        <div class="kpi-value" id="kpiMicro">0</div>
        <div class="kpi-subtext">MSME Classification</div>
      </div>
      <div class="kpi-card cyan">
        <div class="kpi-label">Small Units</div>
        <div class="kpi-value" id="kpiSmall">0</div>
        <div class="kpi-subtext">MSME Classification</div>
      </div>
      <div class="kpi-card blue">
        <div class="kpi-label">Medium Units</div>
        <div class="kpi-value" id="kpiMedium">0</div>
        <div class="kpi-subtext">MSME Classification</div>
      </div>
      <div class="kpi-card amber">
        <div class="kpi-label">States Covered</div>
        <div class="kpi-value" id="kpiStates">0</div>
        <div class="kpi-subtext">Geographic Distribution</div>
      </div>
    </div>

    <!-- Controls & Multi-Filter Panel -->
    <div class="controls-panel">
      <div class="toolbar-header">
        <!-- Sheet Tabs (Multi-sheet support) -->
        <div class="sheet-tabs" id="sheetTabsContainer"></div>

        <div class="action-button-group">
          <span style="font-size: 0.8rem; color: var(--text-dim);" id="activeRecordCount">Showing 0 records</span>
          <button class="btn btn-outline btn-sm" onclick="resetAllFilters();" title="Clear all search & filter terms">
            🔄 Reset Filters
          </button>
        </div>
      </div>

      <!-- Real-Time Filter Toolbar -->
      <div class="filter-grid">
        <div class="input-wrapper">
          <input type="text" id="globalSearchInput" class="search-input" placeholder="🔍 Instant search enterprise name, Udyam number, city, PIN, email..." oninput="handleFilterChange();">
        </div>

        <select id="stateFilter" class="select-filter" onchange="handleFilterChange();">
          <option value="">All States</option>
        </select>

        <select id="typeFilter" class="select-filter" onchange="handleFilterChange();">
          <option value="">All Enterprise Types</option>
        </select>

        <select id="activityFilter" class="select-filter" onchange="handleFilterChange();">
          <option value="">All Activities</option>
        </select>

        <select id="statusFilter" class="select-filter" onchange="handleFilterChange();">
          <option value="">All Statuses</option>
        </select>

        <select id="pageSizeFilter" class="select-filter" style="min-width: 120px;" onchange="handlePageSizeChange();">
          <option value="15">15 per page</option>
          <option value="25" selected>25 per page</option>
          <option value="50">50 per page</option>
          <option value="100">100 per page</option>
          <option value="999999">Show All</option>
        </select>
      </div>
    </div>

    <!-- Interactive Data Table Card -->
    <div class="table-container">
      <div class="table-wrapper">
        <table class="flawless-table" id="dataTable">
          <thead id="tableHead"></thead>
          <tbody id="tableBody"></tbody>
        </table>
      </div>

      <!-- Table Pagination Footer -->
      <div class="table-footer">
        <div class="page-info" id="paginationInfo">Showing 0 of 0 entries</div>
        <div class="pagination-controls" id="paginationControls"></div>
      </div>
    </div>

  </main>

  <!-- Enterprise Dossier Slide-Over Modal -->
  <div class="modal-backdrop" id="dossierModal" onclick="if(event.target===this) closeDossier();">
    <div class="modal-box">
      <div class="modal-header">
        <div class="modal-title">
          <h2 id="modalEntName">Enterprise Details</h2>
          <div class="modal-subtitle" id="modalUdyamNum">UDYAM-XX-00-0000000</div>
        </div>
        <button class="modal-close" onclick="closeDossier();">&times;</button>
      </div>
      <div class="modal-body" id="modalBody">
        <!-- Rendered dynamically -->
      </div>
    </div>
  </div>

  <!-- Footer -->
  <footer class="flawless-footer">
    <div class="footer-content">
      <div class="footer-brand">
        <strong>FlawlessTech Data</strong>
        <span>Enterprise Data Extraction, Web Automation, & Lead Intelligence Solutions</span>
        <span>&copy; {datetime.now().year} FlawlessTech Data. All rights reserved.</span>
      </div>
      <div class="footer-links">
        <a href="https://flawlesstechdata.com/" target="_blank">Home</a>
        <a href="https://flawlesstechdata.com/web-scraping/" target="_blank">Web Scraping</a>
        <a href="https://flawlesstechdata.com/lead-generation/" target="_blank">Lead Generation</a>
        <a href="https://flawlesstechdata.com/contact/" target="_blank">Contact Support</a>
      </div>
    </div>
  </footer>

  <!-- Application Logic -->
  <script>
    // Embedded Initial Data
    let workbookData = {json_data_str};
    let currentSheetName = workbookData.active_sheet || Object.keys(workbookData.sheets)[0];
    let allRecords = [];
    let headers = [];
    let filteredRecords = [];
    let currentPage = 1;
    let pageSize = 25;
    let sortColumn = null;
    let sortAsc = true;

    // Initialize Page
    document.addEventListener('DOMContentLoaded', () => {{
      initTheme();
      initSheetTabs();
      loadSheetData(currentSheetName);
    }});

    // Theme Management (Dark & Light Mode)
    function initTheme() {{
      const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
      updateThemeUI(currentTheme);
    }}

    function toggleTheme() {{
      const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
      const newTheme = currentTheme === 'light' ? 'dark' : 'light';
      setTheme(newTheme);
    }}

    function setTheme(theme) {{
      document.documentElement.setAttribute('data-theme', theme);
      try {{
        localStorage.setItem('flawless_theme', theme);
      }} catch (e) {{
        console.warn('Could not save theme preference:', e);
      }}
      updateThemeUI(theme);
    }}

    function updateThemeUI(theme) {{
      const icon = document.getElementById('themeIcon');
      const label = document.getElementById('themeLabel');
      if (!icon || !label) return;
      if (theme === 'light') {{
        icon.textContent = '🌙';
        label.textContent = 'Dark Mode';
      }} else {{
        icon.textContent = '☀️';
        label.textContent = 'Light Mode';
      }}
    }}

    function initSheetTabs() {{
      const container = document.getElementById('sheetTabsContainer');
      container.innerHTML = '';
      const sheetNames = Object.keys(workbookData.sheets);

      sheetNames.forEach(sheetName => {{
        const btn = document.createElement('button');
        btn.className = `sheet-tab ${{sheetName === currentSheetName ? 'active' : ''}}`;
        btn.textContent = `📊 ${{sheetName}}`;
        btn.onclick = () => {{
          currentSheetName = sheetName;
          document.querySelectorAll('.sheet-tab').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          loadSheetData(sheetName);
        }};
        container.appendChild(btn);
      }});
    }}

    function loadSheetData(sheetName) {{
      const sheet = workbookData.sheets[sheetName];
      if (!sheet) return;

      headers = sheet.headers || [];
      allRecords = sheet.rows || [];
      filteredRecords = [...allRecords];
      currentPage = 1;

      populateFilterDropdowns();
      computeKPIMetrics();
      renderTableHeader();
      applyFilters();
    }}

    function populateFilterDropdowns() {{
      const stateSet = new Set();
      const typeSet = new Set();
      const activitySet = new Set();
      const statusSet = new Set();

      allRecords.forEach(r => {{
        if (r['State']) stateSet.add(r['State'].trim());
        if (r['Enterprise Type']) typeSet.add(r['Enterprise Type'].trim());
        if (r['Major Activity']) activitySet.add(r['Major Activity'].trim());
        if (r['Status']) statusSet.add(r['Status'].trim());
      }});

      populateSelect('stateFilter', stateSet, 'All States');
      populateSelect('typeFilter', typeSet, 'All Enterprise Types');
      populateSelect('activityFilter', activitySet, 'All Activities');
      populateSelect('statusFilter', statusSet, 'All Statuses');
    }}

    function populateSelect(elemId, setObj, placeholder) {{
      const sel = document.getElementById(elemId);
      sel.innerHTML = `<option value="">${{placeholder}}</option>`;
      Array.from(setObj).sort().forEach(val => {{
        if (val) {{
          const opt = document.createElement('option');
          opt.value = val;
          opt.textContent = val;
          sel.appendChild(opt);
        }}
      }});
    }}

    function computeKPIMetrics() {{
      const total = allRecords.length;
      document.getElementById('kpiTotal').textContent = total.toLocaleString();

      let successCount = 0;
      let microCount = 0;
      let smallCount = 0;
      let mediumCount = 0;
      const stateSet = new Set();

      allRecords.forEach(r => {{
        const st = (r['Status'] || '').toLowerCase();
        if (st.includes('success')) successCount++;

        const et = (r['Enterprise Type'] || '').toLowerCase();
        if (et.includes('micro')) microCount++;
        else if (et.includes('small')) smallCount++;
        else if (et.includes('medium')) mediumCount++;

        const stateVal = r['State'];
        if (stateVal && stateVal.trim()) stateSet.add(stateVal.trim().toUpperCase());
      }});

      document.getElementById('kpiSuccess').textContent = successCount.toLocaleString();
      const pct = total > 0 ? ((successCount / total) * 100).toFixed(1) : '100';
      document.getElementById('kpiSuccessPct').textContent = `${{pct}}% Success Rate`;

      document.getElementById('kpiMicro').textContent = microCount.toLocaleString();
      document.getElementById('kpiSmall').textContent = smallCount.toLocaleString();
      document.getElementById('kpiMedium').textContent = mediumCount.toLocaleString();
      document.getElementById('kpiStates').textContent = stateSet.size.toLocaleString();
    }}

    function renderTableHeader() {{
      const thead = document.getElementById('tableHead');
      thead.innerHTML = '';
      const tr = document.createElement('tr');

      // Actions column first
      const thAction = document.createElement('th');
      thAction.textContent = 'Action';
      thAction.style.width = '70px';
      tr.appendChild(thAction);

      headers.forEach(h => {{
        const th = document.createElement('th');
        th.innerHTML = `${{h}} <span class="sort-icon">▲▼</span>`;
        th.onclick = () => handleSort(h);
        if (sortColumn === h) {{
          th.classList.add(sortAsc ? 'sorted-asc' : 'sorted-desc');
        }}
        tr.appendChild(th);
      }});

      thead.appendChild(tr);
    }}

    function handleSort(column) {{
      if (sortColumn === column) {{
        sortAsc = !sortAsc;
      }} else {{
        sortColumn = column;
        sortAsc = true;
      }}
      renderTableHeader();

      filteredRecords.sort((a, b) => {{
        const valA = (a[column] || '').toString().toLowerCase();
        const valB = (b[column] || '').toString().toLowerCase();
        if (valA < valB) return sortAsc ? -1 : 1;
        if (valA > valB) return sortAsc ? 1 : -1;
        return 0;
      }});

      currentPage = 1;
      renderTableRows();
      renderPagination();
    }}

    function handleFilterChange() {{
      applyFilters();
    }}

    function handlePageSizeChange() {{
      pageSize = parseInt(document.getElementById('pageSizeFilter').value, 10);
      currentPage = 1;
      renderTableRows();
      renderPagination();
    }}

    function resetAllFilters() {{
      document.getElementById('globalSearchInput').value = '';
      document.getElementById('stateFilter').value = '';
      document.getElementById('typeFilter').value = '';
      document.getElementById('activityFilter').value = '';
      document.getElementById('statusFilter').value = '';
      applyFilters();
    }}

    function applyFilters() {{
      const query = (document.getElementById('globalSearchInput').value || '').toLowerCase().trim();
      const stateVal = document.getElementById('stateFilter').value;
      const typeVal = document.getElementById('typeFilter').value;
      const actVal = document.getElementById('activityFilter').value;
      const statusVal = document.getElementById('statusFilter').value;

      filteredRecords = allRecords.filter(r => {{
        if (stateVal && (r['State'] || '') !== stateVal) return false;
        if (typeVal && (r['Enterprise Type'] || '') !== typeVal) return false;
        if (actVal && (r['Major Activity'] || '') !== actVal) return false;
        if (statusVal && (r['Status'] || '') !== statusVal) return false;

        if (query) {{
          const match = Object.values(r).some(v => (v || '').toString().toLowerCase().includes(query));
          if (!match) return false;
        }}
        return true;
      }});

      document.getElementById('activeRecordCount').textContent = `Showing ${{filteredRecords.length.toLocaleString()}} of ${{allRecords.length.toLocaleString()}} records`;
      currentPage = 1;
      renderTableRows();
      renderPagination();
    }}

    function renderTableRows() {{
      const tbody = document.getElementById('tableBody');
      tbody.innerHTML = '';

      if (filteredRecords.length === 0) {{
        tbody.innerHTML = `<tr><td colspan="${{headers.length + 1}}" style="text-align: center; padding: 48px; color: var(--text-muted); font-size: 0.95rem;">
          🔍 No matching records found for the current search/filter criteria.
        </td></tr>`;
        return;
      }}

      const start = (currentPage - 1) * pageSize;
      const end = Math.min(start + pageSize, filteredRecords.length);
      const pageRows = filteredRecords.slice(start, end);

      pageRows.forEach(row => {{
        const tr = document.createElement('tr');
        tr.ondblclick = () => openDossier(row);

        // Action view button
        const tdAction = document.createElement('td');
        const viewBtn = document.createElement('button');
        viewBtn.className = 'btn btn-outline btn-sm';
        viewBtn.innerHTML = '🔍 View';
        viewBtn.onclick = (e) => {{
          e.stopPropagation();
          openDossier(row);
        }};
        tdAction.appendChild(viewBtn);
        tr.appendChild(tdAction);

        // Columns
        headers.forEach(h => {{
          const td = document.createElement('td');
          const val = row[h] || '';

          if (h === 'Status') {{
            if (val.toLowerCase().includes('success')) {{
              td.innerHTML = `<span class="badge badge-success">✓ ${{val}}</span>`;
            }} else {{
              td.innerHTML = `<span class="badge badge-failed">✕ ${{val || 'Not Found'}}</span>`;
            }}
          }} else if (h === 'Enterprise Type') {{
            const vLower = val.toLowerCase();
            if (vLower.includes('micro')) td.innerHTML = `<span class="badge badge-micro">${{val}}</span>`;
            else if (vLower.includes('small')) td.innerHTML = `<span class="badge badge-small">${{val}}</span>`;
            else if (vLower.includes('medium')) td.innerHTML = `<span class="badge badge-medium">${{val}}</span>`;
            else td.textContent = val;
          }} else if (h === 'Major Activity') {{
            td.innerHTML = `<span class="badge badge-activity">${{val}}</span>`;
          }} else if (h === 'Udyam Number' || h === 'Pin Code' || h.includes('Date')) {{
            td.className = 'mono-cell';
            td.textContent = val;
          }} else {{
            td.textContent = val;
            td.title = val;
          }}

          tr.appendChild(td);
        }});

        tbody.appendChild(tr);
      }});
    }}

    function renderPagination() {{
      const total = filteredRecords.length;
      const totalPages = Math.ceil(total / pageSize) || 1;
      const start = total === 0 ? 0 : (currentPage - 1) * pageSize + 1;
      const end = Math.min(currentPage * pageSize, total);

      document.getElementById('paginationInfo').textContent = `Showing ${{start.toLocaleString()}} to ${{end.toLocaleString()}} of ${{total.toLocaleString()}} entries`;

      const container = document.getElementById('paginationControls');
      container.innerHTML = '';

      const prevBtn = document.createElement('button');
      prevBtn.className = 'page-btn';
      prevBtn.innerHTML = '&larr;';
      prevBtn.disabled = currentPage === 1;
      prevBtn.onclick = () => {{ if (currentPage > 1) {{ currentPage--; renderTableRows(); renderPagination(); }} }};
      container.appendChild(prevBtn);

      const maxBtns = 5;
      let startPage = Math.max(1, currentPage - 2);
      let endPage = Math.min(totalPages, startPage + maxBtns - 1);
      if (endPage - startPage < maxBtns - 1) {{
        startPage = Math.max(1, endPage - maxBtns + 1);
      }}

      for (let p = startPage; p <= endPage; p++) {{
        const btn = document.createElement('button');
        btn.className = `page-btn ${{p === currentPage ? 'active' : ''}}`;
        btn.textContent = p;
        btn.onclick = () => {{ currentPage = p; renderTableRows(); renderPagination(); }};
        container.appendChild(btn);
      }}

      const nextBtn = document.createElement('button');
      nextBtn.className = 'page-btn';
      nextBtn.innerHTML = '&rarr;';
      nextBtn.disabled = currentPage >= totalPages;
      nextBtn.onclick = () => {{ if (currentPage < totalPages) {{ currentPage++; renderTableRows(); renderPagination(); }} }};
      container.appendChild(nextBtn);
    }}

    // Enterprise Dossier Modal
    function openDossier(row) {{
      document.getElementById('modalEntName').textContent = row['Enterprise Name'] || 'Enterprise Dossier';
      document.getElementById('modalUdyamNum').textContent = row['Udyam Number'] || '';

      const body = document.getElementById('modalBody');
      body.innerHTML = '';

      // Section 1: Basic Information
      const sec1 = createDossierSection('🏛️ Registration & Enterprise Information', [
        ['Udyam Number', row['Udyam Number']],
        ['Enterprise Name', row['Enterprise Name']],
        ['Organisation Type', row['Organisation Type']],
        ['Enterprise Type', row['Enterprise Type']],
        ['Major Activity', row['Major Activity']],
        ['Status', row['Status']],
        ['Gender', row['Gender']],
        ['Social Category', row['Social Category']],
        ['Date of Registration', row['Date of Registration']],
        ['Date of Incorporation', row['Date of Incorporation']],
        ['Date of Commencement', row['Date of Commencement']],
        ['Classification Date', row['Classification Date']],
      ]);
      body.appendChild(sec1);

      // Section 2: Address & Location
      const sec2 = createDossierSection('📍 Official Address & Plant Units', [
        ['Unit Names', row['Unit Names']],
        ['Flat / Door / Block', row['Flat / Door / Block']],
        ['Premises / Building', row['Premises / Building']],
        ['Village / Town', row['Village / Town']],
        ['Block', row['Block']],
        ['Road / Street', row['Road / Street']],
        ['City', row['City']],
        ['District', row['District']],
        ['State', row['State']],
        ['Pin Code', row['Pin Code']],
      ]);
      body.appendChild(sec2);

      // Section 3: Contact & Authorities
      const sec3 = createDossierSection('📞 Contact & Administration Authorities', [
        ['Mobile', row['Mobile']],
        ['Email', row['Email']],
        ['DIC (District Industries Centre)', row['DIC']],
        ['MSME-DFO', row['MSME-DFO']],
      ]);
      body.appendChild(sec3);

      // Section 4: National Industry Classification (NIC)
      const sec4 = document.createElement('div');
      sec4.innerHTML = `
        <div class="dossier-section-title">🏭 National Industry Classification (NIC) Activities</div>
        <div class="dossier-full-box">
          <div style="margin-bottom: 8px;"><strong>Primary NIC Code:</strong> ${{row['Primary NIC Code'] || 'N/A'}}</div>
          <div style="margin-bottom: 8px;"><strong>Primary NIC Activity:</strong> ${{row['Primary NIC Activity'] || 'N/A'}}</div>
          <div><strong>All Registered NIC Activities:</strong></div>
          <div style="margin-top: 6px; padding: 10px; background: rgba(0,0,0,0.25); border-radius: 6px; font-family: var(--font-mono); font-size: 0.78rem; line-height: 1.6;">
            ${{row['All NIC Details'] || 'None recorded'}}
          </div>
        </div>
      `;
      body.appendChild(sec4);

      document.getElementById('dossierModal').classList.add('active');
    }}

    function createDossierSection(title, items) {{
      const div = document.createElement('div');
      div.innerHTML = `<div class="dossier-section-title">${{title}}</div>`;
      const grid = document.createElement('div');
      grid.className = 'dossier-grid';

      items.forEach(([label, val]) => {{
        if (val !== undefined && val !== null && val.toString().trim() !== '') {{
          const item = document.createElement('div');
          item.className = 'dossier-item';
          item.innerHTML = `
            <div class="dossier-item-label">${{label}}</div>
            <div class="dossier-item-value">${{val}}</div>
          `;
          grid.appendChild(item);
        }}
      }});

      div.appendChild(grid);
      return div;
    }}

    function closeDossier() {{
      document.getElementById('dossierModal').classList.remove('active');
    }}

    // Client-side Export to XLSX via SheetJS
    function downloadCurrentDataXLSX() {{
      const dataToExport = filteredRecords.length > 0 ? filteredRecords : allRecords;
      if (dataToExport.length === 0) {{
        alert('No data available to export.');
        return;
      }}

      if (typeof XLSX === 'undefined') {{
        alert('SheetJS library is still loading. Please try again in a few moments.');
        return;
      }}

      const ws = XLSX.utils.json_to_sheet(dataToExport);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, currentSheetName || 'Udyam Data');

      const outName = 'results.xlsx';
      XLSX.writeFile(wb, outName);
    }}

    // Client-side Export to CSV
    function downloadCurrentDataCSV() {{
      const dataToExport = filteredRecords.length > 0 ? filteredRecords : allRecords;
      if (dataToExport.length === 0) return;

      const keys = headers;
      const csvLines = [keys.join(',')];

      dataToExport.forEach(row => {{
        const line = keys.map(k => {{
          let val = (row[k] || '').toString().replace(/"/g, '""');
          if (val.includes(',') || val.includes('\\n') || val.includes('"')) {{
            val = `"${{val}}"`;
          }}
          return val;
        }}).join(',');
        csvLines.push(line);
      }});

      const blob = new Blob([csvLines.join('\\r\\n')], {{ type: 'text/csv;charset=utf-8;' }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.setAttribute('href', url);
      link.setAttribute('download', 'results.csv');
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }}

    // Copy Failed Udyam Numbers to Clipboard
    function copyFailedNumbers() {{
      const failed = allRecords.filter(r => {{
        const st = (r['Status'] || '').toLowerCase();
        return st && !st.includes('success');
      }}).map(r => r['Udyam Number'] || r['Number']).filter(Boolean);

      if (failed.length === 0) {{
        alert('All records in this dataset are marked Success! No failed records found to copy.');
        return;
      }}

      const text = failed.join('\\n');
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(text).then(() => {{
          alert(`Copied ${{failed.length}} failed Udyam number(s) to clipboard!\\n\\nYou can now click '🔄 Load Failed Numbers' or paste them in the Udyam Extractor GUI to retry.`);
        }}).catch(() => {{
          prompt(`Copy ${{failed.length}} failed Udyam number(s):`, text);
        }});
      }} else {{
        prompt(`Copy ${{failed.length}} failed Udyam number(s):`, text);
      }}
    }}
  </script>
</body>
</html>
"""
    return html_template


def convert_xlsx_to_html(xlsx_path: Path, html_path: Path) -> Path:
    """Main conversion worker."""
    print(f"Reading Excel workbook: {xlsx_path.resolve()}...")
    data = read_xlsx_to_dict(xlsx_path)

    total_records = sum(len(s["rows"]) for s in data["sheets"].values())
    print(f"Loaded {len(data['sheets'])} sheet(s) with {total_records} total records.")

    logo_b64 = get_logo_base64()
    if logo_b64:
        print("Embedded FlawlessTech Data official logo (base64 offline encoded).")

    print(f"Generating formatted HTML viewer: {html_path.resolve()}...")
    html_content = generate_html_content(data, logo_b64)

    html_path.parent.mkdir(parents=True, exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[SUCCESS] Interactive HTML Viewer generated at: {html_path.resolve()}")
    return html_path


def main():
    parser = argparse.ArgumentParser(
        description="FlawlessTech Data - Convert XLSX to Interactive HTML Viewer & Downloader"
    )
    parser.add_argument(
        "-i", "--input",
        type=str,
        default="results.xlsx",
        help="Path to input .xlsx file (default: results.xlsx)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Path to output .html file (default: <input_stem>.html)"
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open generated HTML file in default web browser automatically"
    )

    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"[ERROR] Input Excel file not found: {input_path}")
        sys.exit(1)

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = input_path.with_suffix(".html")

    out_file = convert_xlsx_to_html(input_path, output_path)

    if args.open:
        print(f"Opening in browser: {out_file}...")
        webbrowser.open(out_file.as_uri())


if __name__ == "__main__":
    main()
