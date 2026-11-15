"""
MCA CDM (Corporate Data Management Portal) CSV Extraction Suite
================================================================
Fast, Idempotent Pipeline Extraction Assistant for Ministry of Corporate Affairs CDM Portal.

Key Features:
  1. Idempotent Daily Cache:
     - Checks if a report was already downloaded today (> 0 bytes, modified today).
     - Skips already-downloaded reports so on any given day, each file is only downloaded once.
     - Use --force to override and re-download.
  2. Confirmed Generation Pipeline:
     - Waits specifically for "Generating file, please wait..." (or "Downloading Report..." / "Preparing export...")
       to appear before moving on to the next form.
     - Does NOT block waiting for the entire file download to finish; generation continues in the background!
  3. Automatic Multiselect & Focus:
     - Auto-selects 100% of multiselect checkboxes (including all 814+ Dynamic CSR filters).
     - Highlights the CAPTCHA image and input box in glowing cyan and sets keyboard focus.
  4. Context-Wide Download Listener:
     - Intercepts completed CSV downloads across all tabs in the background and saves them
       to canonical directories.
"""

import os
import sys
import time
import argparse
import functools
import threading
from datetime import datetime, date
from pathlib import Path
from playwright.sync_api import sync_playwright

print = functools.partial(print, flush=True)

BASE_OUTPUT_DIR = Path("data/mca_cdm")
COMPANY_DIR = BASE_OUTPUT_DIR / "company_master"
CSR_DIR = BASE_OUTPUT_DIR / "csr_data"
GDP_DIR = BASE_OUTPUT_DIR / "gdp_calculation"

for d in (COMPANY_DIR, CSR_DIR, GDP_DIR):
    d.mkdir(parents=True, exist_ok=True)

def is_already_downloaded_today(target_path: Path, force: bool = False) -> bool:
    """Checks if the target file already exists and was downloaded today (> 0 bytes)."""
    if force:
        return False
    if not target_path.exists():
        return False
    stat = target_path.stat()
    if stat.st_size == 0:
        return False
    mod_date = datetime.fromtimestamp(stat.st_mtime).date()
    today = date.today()
    return mod_date == today

def route_download(suggested_name: str) -> Path:
    """Routes an incoming download to its canonical folder and filename."""
    lower = suggested_name.lower()
    if "foreign" in lower:
        return COMPANY_DIR / "Foreign_Company_Master_Details.csv"
    elif "llp" in lower:
        return COMPANY_DIR / "LLP_Master_Details.csv"
    elif "master" in lower or "company" in lower:
        return COMPANY_DIR / "Company_Master_Details.csv"
    elif "ia" in lower:
        return CSR_DIR / "CSR_Implementing_Agencies.csv"
    elif "state" in lower:
        return CSR_DIR / "CSR_State_Wise.csv"
    elif "district" in lower:
        return CSR_DIR / "CSR_District_Wise.csv"
    elif "psu" in lower:
        return CSR_DIR / "CSR_PSU_Wise.csv"
    elif "sub" in lower:
        return CSR_DIR / "CSR_Sub_DevSec_Wise.csv"
    elif "devsec" in lower:
        return CSR_DIR / "CSR_DevSec_Wise.csv"
    elif "csr" in lower:
        return CSR_DIR / "CSR_Dynamic_Data.csv"
    elif any(k in lower for k in ["gdp", "xbrl", "indas", "aoc", "nbfc"]):
        return GDP_DIR / suggested_name
    else:
        return BASE_OUTPUT_DIR / suggested_name

class BackgroundDownloadManager:
    def __init__(self):
        self.pending_count = 0
        self.completed = []
        self.lock = threading.Lock()

    def on_download(self, download):
        suggested = download.suggested_filename
        target = route_download(suggested)
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"\n📥 [Background Download Started] Intercepting: {suggested}")
        
        # Save download to disk
        download.save_as(str(target))
        size_mb = target.stat().st_size / (1024 * 1024)
        print(f"✅ [Background Download Complete] Saved: {target.name} ({size_mb:.2f} MB)")
        with self.lock:
            self.completed.append(target.name)
            if self.pending_count > 0:
                self.pending_count -= 1

    def increment_pending(self, label):
        with self.lock:
            self.pending_count += 1
        print(f"🚀 Queued '{label}' for background download! (Active in-flight exports: {self.pending_count})")

    def wait_for_all_downloads(self, timeout_sec=300):
        if self.pending_count == 0:
            print("\n🎉 All background downloads are already completed!")
            return
        print(f"\n⏳ Waiting for remaining {self.pending_count} background downloads to finish generating (timeout: {timeout_sec}s)...")
        start = time.time()
        while self.pending_count > 0 and (time.time() - start < timeout_sec):
            time.sleep(1)
        if self.pending_count == 0:
            print("🎉 All background downloads successfully captured and saved!")
        else:
            print(f"⚠️ Timed out waiting for {self.pending_count} background exports.")

class MCACDMExtractor:
    def __init__(self, page, download_mgr: BackgroundDownloadManager, force: bool = False):
        self.page = page
        self.mgr = download_mgr
        self.force = force
        self.last_submitted_endpoint = None
        self.page.on("request", self._on_request)

    def _on_request(self, request):
        url = request.url
        if "export" in url and (".php" in url or "cdm" in url):
            self.last_submitted_endpoint = url

    def show_banner(self, title, subtitle):
        """Displays in-browser top HUD banner."""
        try:
            self.page.evaluate(f"""() => {{
                let banner = document.getElementById('mca-hud-banner');
                if (!banner) {{
                    banner = document.createElement('div');
                    banner.id = 'mca-hud-banner';
                    banner.style.position = 'fixed';
                    banner.style.top = '0';
                    banner.style.left = '0';
                    banner.style.right = '0';
                    banner.style.zIndex = '9999999';
                    banner.style.background = 'linear-gradient(90deg, #0d3b66, #001e3d)';
                    banner.style.color = '#ffffff';
                    banner.style.padding = '12px 24px';
                    banner.style.boxShadow = '0 4px 15px rgba(0,0,0,0.4)';
                    banner.style.fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
                    banner.style.fontSize = '14px';
                    banner.style.display = 'flex';
                    banner.style.justifyContent = 'space-between';
                    banner.style.alignItems = 'center';
                    document.body.prepend(banner);
                }}
                banner.innerHTML = `
                    <div>
                        <div style="font-weight: 700; font-size: 16px; color: #00d2ff;">⚡ MCA CDM Assistant — ${{JSON.stringify({title})}}</div>
                        <div style="font-size: 13px; color: #e0e0e0; margin-top: 2px;">${{JSON.stringify({subtitle})}}</div>
                    </div>
                    <div id="mca-hud-badge" style="background: #ffc107; color: #000; font-weight: bold; padding: 6px 14px; border-radius: 20px; font-size: 12px; letter-spacing: 0.5px;">
                        ENTER CAPTCHA & SUBMIT
                    </div>
                `;
            }}""")
        except Exception:
            pass

    def update_badge(self, text, color="#28a745", text_color="#fff"):
        try:
            self.page.evaluate(f"""() => {{
                let badge = document.getElementById('mca-hud-badge');
                if (badge) {{
                    badge.innerText = "{text}";
                    badge.style.background = "{color}";
                    badge.style.color = "{text_color}";
                }}
            }}""")
        except Exception:
            pass

    def highlight_captcha(self, form_selector, input_selector):
        """Highlights the CAPTCHA section and automatically sets focus."""
        try:
            self.page.evaluate(f"""() => {{
                const form = document.querySelector("{form_selector}");
                if (!form) return;
                const inp = form.querySelector("{input_selector}") || document.querySelector("{input_selector}");
                if (inp) {{
                    inp.style.border = "3px solid #00d2ff";
                    inp.style.boxShadow = "0 0 14px rgba(0, 210, 255, 0.9)";
                    inp.style.fontSize = "16px";
                    inp.scrollIntoView({{ behavior: "smooth", block: "center" }});
                    inp.focus();
                }}
                const img = form.querySelector("img[src*='captcha'], #captcha-foreign-box img, .captcha-container img");
                if (img) {{
                    img.style.border = "2px solid #ffc107";
                    img.style.padding = "2px";
                    img.style.borderRadius = "4px";
                }}
            }}""")
        except Exception:
            pass

    def wait_for_generation_start(self, form_label: str, target_path: Path, timeout_sec=180) -> bool:
        """
        Waits specifically for 'Generating file, please wait...' or 'Preparing CSV...'
        to appear before moving on to the next form.
        """
        self.last_submitted_endpoint = None
        print(f"\n👉 [{form_label}]")
        print(f"   ⌨️  Please enter the 6-character CAPTCHA in the glowing cyan box and click Export (or press Enter).")
        print(f"   ⏳ Waiting for 'Generating file, please wait...' or 'Preparing CSV...' before moving on...")

        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            # Check generation status in the DOM
            status_info = self.page.evaluate("""() => {
                const checkText = (el) => {
                    if (!el) return null;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return null;
                    return (el.innerText || el.textContent || '').trim();
                };

                // Check GDP specific loader button first
                const csvLoader = document.getElementById('csvBtnLoader');
                if (csvLoader) {
                    const style = window.getComputedStyle(csvLoader);
                    if (style.display !== 'none' && style.visibility !== 'hidden') {
                        return { status: 'generating', message: 'Preparing CSV...' };
                    }
                }

                const msgs = [
                    document.querySelector('#csvBtnLoader'),
                    document.querySelector('#downloadStatus'),
                    document.querySelector('#download-message'),
                    document.querySelector('#download-message-llp'),
                    document.querySelector('#download-message-foreign'),
                    document.querySelector('#download-message-ia'),
                    document.querySelector('#download-message-state'),
                    document.querySelector('#download-message-district'),
                    document.querySelector('#download-message-psu'),
                    document.querySelector('#download-message-devsec'),
                    document.querySelector('#download-message-sub-devsec'),
                    document.querySelector('.alert-info')
                ];

                for (const el of msgs) {
                    const txt = checkText(el);
                    if (txt) {
                        const lower = txt.toLowerCase();
                        if (lower.includes('preparing csv') || lower.includes('generating file') || lower.includes('downloading report') || lower.includes('preparing export')) {
                            return { status: 'generating', message: txt };
                        }
                        if (lower.includes('invalid') || lower.includes('error') || lower.includes('please enter captcha') || lower.includes('failed')) {
                            return { status: 'error', message: txt };
                        }
                    }
                }

                // Check button disabled state during AJAX
                const activeBtn = document.querySelector('button[type="submit"]:disabled, #csvDownloadBtn.disabled');
                if (activeBtn) {
                    return { status: 'generating', message: 'Preparing CSV / Export in progress...' };
                }

                return null;
            }""")

            if status_info:
                if status_info['status'] == 'generating':
                    print(f"   ⏳ [Confirmed Generation] '{status_info['message']}' detected!")
                    self.update_badge("GENERATING IN BACKGROUND — ADVANCING...", "#17a2b8", "#fff")
                    self.mgr.increment_pending(form_label)
                    # Brief pause so the message is visible and browser state is stable
                    self.page.wait_for_timeout(1000)
                    return True
                elif status_info['status'] == 'error':
                    print(f"   ⚠️ Server notice: {status_info['message']}. Please re-enter the CAPTCHA.")
                    self.update_badge(f"NOTICE: {status_info['message'][:25]}", "#dc3545", "#fff")
                    self.last_submitted_endpoint = None
                    start_time = time.time()

            # GDP dashboard download links check
            try:
                gdp_link = self.page.query_selector("#downloadLinks a.btn")
                if gdp_link and gdp_link.is_visible():
                    print("   🔗 Detected generated file link in GDP dashboard. Triggering download...")
                    gdp_link.click()
                    self.mgr.increment_pending(form_label)
                    return True
            except Exception:
                pass

            self.page.wait_for_timeout(400)

        print(f"   ⚠️ Timed out waiting for generation start on {form_label}.")
        return False

    # =========================================================================
    # 1. Company Master Details
    # =========================================================================
    def extract_company_master(self):
        print("\n" + "=" * 65)
        print("🏢 [1/3] EXTRACTING COMPANY MASTER DETAILS")
        print("    URL: https://mcacdm.nic.in/company-master-details")
        print("=" * 65)

        reports = [
            {
                "label": "Company Master Details",
                "tab_id": "#v-pills-home-tab",
                "form": "#exportForm",
                "input": "input[name='captcha_input']",
                "target": COMPANY_DIR / "Company_Master_Details.csv",
                "select_all": True,
                "desc": "Auto-selected all 36 States & 23 Classifications."
            },
            {
                "label": "LLP Master Details",
                "tab_id": "#llp-home-tab",
                "form": "#exportFormLLP",
                "input": "input[name='captcha_input_llp']",
                "target": COMPANY_DIR / "LLP_Master_Details.csv",
                "select_all": True,
                "desc": "Auto-selected all States & Classifications for LLPs."
            },
            {
                "label": "Foreign Company Master Details",
                "tab_id": "#foreign-home-tab",
                "form": "#exportFormForeign",
                "input": "input[name='captcha_input_foreign']",
                "target": COMPANY_DIR / "Foreign_Company_Master_Details.csv",
                "select_all": False,
                "desc": "Foreign Companies Registered in India."
            },
        ]

        # Check if all reports in this section are already downloaded today
        pending_reports = [r for r in reports if not is_already_downloaded_today(r["target"], self.force)]
        if not pending_reports:
            print("⏩ [Already Downloaded Today] All Company Master files are already up-to-date for today! Skipping section.")
            for r in reports:
                size_mb = r["target"].stat().st_size / (1024 * 1024)
                print(f"   ✓ {r['target'].name} ({size_mb:.2f} MB)")
            return

        self.page.goto("https://mcacdm.nic.in/company-master-details", wait_until="domcontentloaded", timeout=45000)
        self.page.wait_for_timeout(2000)

        for r in reports:
            if is_already_downloaded_today(r["target"], self.force):
                size_mb = r["target"].stat().st_size / (1024 * 1024)
                print(f"\n⏩ [Skipped - Already Downloaded Today] {r['target'].name} ({size_mb:.2f} MB)")
                continue

            self.page.click(r["tab_id"])
            self.page.wait_for_timeout(800)
            self.show_banner(r["label"], r["desc"])

            if r["select_all"]:
                checked = self.page.evaluate(f"""() => {{
                    let cbs = document.querySelectorAll("{r['form']} input[type='checkbox']");
                    cbs.forEach(cb => cb.checked = true);
                    return cbs.length;
                }}""")
                print(f"   Selected all {checked} filter checkboxes automatically.")

            self.highlight_captcha(r["form"], r["input"])
            self.wait_for_generation_start(r["label"], r["target"])

    # =========================================================================
    # 2. CSR Data
    # =========================================================================
    def extract_csr_data(self):
        print("\n" + "=" * 65)
        print("🤝 [2/3] EXTRACTING CSR DATA (Corporate Social Responsibility)")
        print("    URL: https://mcacdm.nic.in/csr-data")
        print("=" * 65)

        csr_reports = [
            {
                "label": "Dynamic CSR Report",
                "tab_id": "#v-pills-home-tab",
                "parent_tab": None,
                "form": "#exportForm",
                "input": "input[name='captcha_input']",
                "target": CSR_DIR / "CSR_Dynamic_Data.csv",
                "select_all": True,
                "desc": "Auto-selected all 814+ parameters (Years, States, Districts, Sectors)."
            },
            {
                "label": "Implementing Agency (IA) Master",
                "tab_id": "#ia-master",
                "parent_tab": None,
                "form": "#exportFormia",
                "input": "#exportFormia input[name='captcha_input']",
                "target": CSR_DIR / "CSR_Implementing_Agencies.csv",
                "select_all": False,
                "desc": "Master list of all Registered Implementing Agencies."
            },
            {
                "label": "State-wise CSR Summary",
                "tab_id": "#home-tab",
                "parent_tab": "#v-pills-messages-tab",
                "form": "#exportFormState",
                "input": "#exportFormState input[name='captcha_input']",
                "target": CSR_DIR / "CSR_State_Wise.csv",
                "select_all": False,
                "desc": "Aggregated CSR expenditures state-by-state."
            },
            {
                "label": "District-wise CSR Summary",
                "tab_id": "#district-tab",
                "parent_tab": "#v-pills-messages-tab",
                "form": "#exportFormDistrict",
                "input": "#exportFormDistrict input[name='captcha_input']",
                "target": CSR_DIR / "CSR_District_Wise.csv",
                "select_all": False,
                "desc": "Aggregated CSR expenditures district-by-district."
            },
            {
                "label": "PSU-wise CSR Summary",
                "tab_id": "#profile-tab",
                "parent_tab": "#v-pills-messages-tab",
                "form": "#exportFormpsu",
                "input": "#exportFormpsu input[name='captcha_input']",
                "target": CSR_DIR / "CSR_PSU_Wise.csv",
                "select_all": False,
                "desc": "Public Sector Undertakings CSR contributions."
            },
            {
                "label": "Development Sector-wise CSR",
                "tab_id": "#contact-tab",
                "parent_tab": "#v-pills-messages-tab",
                "form": "#exportFormdevsec",
                "input": "#exportFormdevsec input[name='captcha_input']",
                "target": CSR_DIR / "CSR_DevSec_Wise.csv",
                "select_all": False,
                "desc": "Sectoral CSR breakdowns."
            },
            {
                "label": "Sub-Development Sector-wise CSR",
                "tab_id": "#subcontact-tab",
                "parent_tab": "#v-pills-messages-tab",
                "form": "#exportFormsubdevsec",
                "input": "#exportFormsubdevsec input[name='captcha_input']",
                "target": CSR_DIR / "CSR_Sub_DevSec_Wise.csv",
                "select_all": False,
                "desc": "Granular sub-sector CSR expenditures."
            },
        ]

        # Check if all reports in this section are already downloaded today
        pending_reports = [r for r in csr_reports if not is_already_downloaded_today(r["target"], self.force)]
        if not pending_reports:
            print("⏩ [Already Downloaded Today] All CSR Data files are already up-to-date for today! Skipping section.")
            for r in csr_reports:
                size_mb = r["target"].stat().st_size / (1024 * 1024)
                print(f"   ✓ {r['target'].name} ({size_mb:.2f} MB)")
            return

        self.page.goto("https://mcacdm.nic.in/csr-data", wait_until="domcontentloaded", timeout=45000)
        self.page.wait_for_timeout(2000)

        for r in csr_reports:
            if is_already_downloaded_today(r["target"], self.force):
                size_mb = r["target"].stat().st_size / (1024 * 1024)
                print(f"\n⏩ [Skipped - Already Downloaded Today] {r['target'].name} ({size_mb:.2f} MB)")
                continue

            if r["parent_tab"]:
                self.page.click(r["parent_tab"])
                self.page.wait_for_timeout(400)

            self.page.click(r["tab_id"])
            self.page.wait_for_timeout(800)
            self.show_banner(r["label"], r["desc"])

            if r["select_all"]:
                checked = self.page.evaluate(f"""() => {{
                    let cbs = document.querySelectorAll("{r['form']} input[type='checkbox']");
                    cbs.forEach(cb => cb.checked = true);
                    return cbs.length;
                }}""")
                print(f"   Selected all {checked} filter checkboxes automatically.")

            self.highlight_captcha(r["form"], r["input"])
            self.wait_for_generation_start(r["label"], r["target"])

    # =========================================================================
    # 3. GDP Calculation Data
    # =========================================================================
    def extract_gdp_calculation(self, years=None):
        print("\n" + "=" * 65)
        print("📈 [3/3] EXTRACTING GDP CALCULATION FINANCIAL STATEMENTS")
        print("    URL: https://mcacdm.nic.in/gdp_dashboard.php")
        print("=" * 65)

        primary_tables = [
            {"title": "XBRL Balance Sheet", "selector": "a[data-tbl='t_api_gdp_xbrl_bs_current_previous']"},
            {"title": "XBRL Profit & Loss", "selector": "a[data-tbl='t_api_gdp_xbrl_pl_current_previous']"},
            {"title": "INDAS Balance Sheet", "selector": "a[data-tbl='t_api_gdp_indas_bs_current_previous']"},
            {"title": "INDAS Profit & Loss", "selector": "a[data-tbl='t_api_gdp_indas_pl_current_previous']"},
            {"title": "Non-XBRL AOC-4 (BS/PL)", "selector": "a[data-tbl='t_api_gdp_nonxbrl_aoc4_bs_pl_current_previous']"},
            {"title": "NBFC Balance Sheet", "selector": "a[data-tbl='t_api_gdp_nbfc_bs_current_previous']"},
        ]

        self.page.goto("https://mcacdm.nic.in/gdp_dashboard.php", wait_until="domcontentloaded", timeout=45000)
        self.page.wait_for_timeout(2000)

        available_years = self.page.evaluate("""() => {
            let select = document.getElementById('financial_year');
            if (!select) return [];
            return Array.from(select.options).filter(o => o.value).map(o => ({val: o.value, text: o.text}));
        }""")

        target_years = available_years[:2] if not years else [y for y in available_years if y['val'] in years or y['text'] in years]
        print(f"Target Financial Years: {[y['text'] for y in target_years]}")

        for tbl in primary_tables:
            clean_tbl = tbl['title'].replace(" ", "_").replace("&", "and").replace("/", "-").replace("(", "").replace(")", "")
            
            for yr in target_years:
                target_path = GDP_DIR / f"GDP_{clean_tbl}_{yr['text'].replace('/', '-')}.csv"
                if is_already_downloaded_today(target_path, self.force):
                    size_mb = target_path.stat().st_size / (1024 * 1024)
                    print(f"\n⏩ [Skipped - Already Downloaded Today] {target_path.name} ({size_mb:.2f} MB)")
                    continue

                try:
                    self.page.click(tbl['selector'])
                    self.page.wait_for_timeout(600)
                except Exception:
                    pass

                self.show_banner(f"GDP: {tbl['title']} ({yr['text']})", f"Selected {yr['text']}. Enter CAPTCHA & click DOWNLOAD CSV.")
                self.page.select_option("#financial_year", yr['val'])
                self.page.wait_for_timeout(400)

                self.highlight_captcha("#exportForm", "#captcha_input_foreign")
                self.wait_for_generation_start(f"GDP {tbl['title']} ({yr['text']})", target_path)

def main():
    parser = argparse.ArgumentParser(description="MCA CDM Portal Bulk CSV Data Extraction Assistant")
    parser.add_argument("--all", action="store_true", default=False, help="Extract all 3 sections")
    parser.add_argument("--company", action="store_true", default=False, help="Extract Company Master Details")
    parser.add_argument("--csr", action="store_true", default=False, help="Extract CSR Data")
    parser.add_argument("--gdp", action="store_true", default=False, help="Extract GDP Calculation Statements")
    parser.add_argument("--gdp-all-years", action="store_true", default=False, help="Extract all available financial years for GDP")
    parser.add_argument("--force", action="store_true", default=False, help="Force re-download even if downloaded today")
    args = parser.parse_args()

    if not (args.company or args.csr or args.gdp):
        args.all = True

    today_str = date.today().isoformat()
    print("=" * 65)
    print("   MCA CDM (Corporate Data Management Portal) CSV Extraction Suite   ")
    print(f"   Date: {today_str} | Idempotency Check: Active (1 download/day)    ")
    print("=" * 65)
    print(f"📁 Output Base: {BASE_OUTPUT_DIR.resolve()}\n")

    download_mgr = BackgroundDownloadManager()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(viewport=None, accept_downloads=True)
        
        # Attach context-wide download listener
        context.on("download", download_mgr.on_download)

        page = context.new_page()
        extractor = MCACDMExtractor(page, download_mgr, force=args.force)

        try:
            if args.all or args.company:
                extractor.extract_company_master()

            if args.all or args.csr:
                extractor.extract_csr_data()

            if args.all or args.gdp:
                years = None if not args.gdp_all_years else ["2025", "2024", "2023", "2022", "2021", "2020"]
                extractor.extract_gdp_calculation(years=years)

            # Wait for any in-flight background downloads to complete before exiting
            download_mgr.wait_for_all_downloads(timeout_sec=300)

            print("\n" + "=" * 65)
            print("🎉 MCA CDM DATA EXTRACTION WORKFLOW COMPLETE!")
            print(f"📁 All downloaded CSVs saved in: {BASE_OUTPUT_DIR.resolve()}")
            print(f"Total files captured in this session: {len(download_mgr.completed)}")
            print("=" * 65)
        except Exception as e:
            print(f"\n❌ Error during extraction workflow: {e}")
            import traceback
            traceback.print_exc()
        finally:
            page.wait_for_timeout(3000)
            context.close()
            browser.close()

if __name__ == "__main__":
    main()
