"""
MCA CDM (Corporate Data Management Portal) CSV Extraction Suite
================================================================
Asynchronous, Pipeline-Ready Extraction Assistant for Ministry of Corporate Affairs CDM Portal.

Features:
  - Non-blocking pipeline: As soon as CAPTCHA is filled and submitted,
    immediately advances to the next report while downloads generate in background.
  - Context-level background download listener routes CSVs to canonical directories.
  - Auto-selects 100% of multiselect checkboxes (including all 814+ Dynamic CSR filters).
  - Highlights CAPTCHA in glowing cyan and gives it direct keyboard focus.
  - Automatically handles tabs, sub-tabs, and financial year switching.
"""

import os
import sys
import time
import argparse
import functools
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright

print = functools.partial(print, flush=True)

BASE_OUTPUT_DIR = Path("data/mca_cdm")
COMPANY_DIR = BASE_OUTPUT_DIR / "company_master"
CSR_DIR = BASE_OUTPUT_DIR / "csr_data"
GDP_DIR = BASE_OUTPUT_DIR / "gdp_calculation"

for d in (COMPANY_DIR, CSR_DIR, GDP_DIR):
    d.mkdir(parents=True, exist_ok=True)

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
        
        # Save download
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
        print(f"🚀 Queued '{label}' for background download! (Pending active exports: {self.pending_count})")

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
    def __init__(self, page, download_mgr: BackgroundDownloadManager):
        self.page = page
        self.mgr = download_mgr
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
                        <div style="font-weight: 700; font-size: 16px; color: #00d2ff;">⚡ Fast MCA CDM Assistant — ${{JSON.stringify({title})}}</div>
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

    def wait_for_submission(self, form_label: str, timeout_sec=180) -> bool:
        """
        Non-blocking workflow:
        Waits for the user to submit the form/CAPTCHA. Once submitted and accepted,
        immediately returns True so the caller can advance to the next tab while
        the download continues in the background!
        """
        self.last_submitted_endpoint = None
        print(f"\n👉 [{form_label}]")
        print(f"   ⌨️  Please enter the 6-character CAPTCHA in the glowing cyan box and click Export (or press Enter).")
        print(f"   ⚡ As soon as submitted, we will immediately jump to the next form!")

        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            # Check if an export network request was fired
            if self.last_submitted_endpoint is not None:
                # Wait 1.5 seconds to ensure server accepts submission without instant client validation error
                self.page.wait_for_timeout(1500)

                # Check if there is an active error message on screen
                error_msg = self.page.evaluate("""() => {
                    let msgs = [
                        document.querySelector('#download-message'),
                        document.querySelector('#download-message-llp'),
                        document.querySelector('#download-message-foreign'),
                        document.querySelector('#download-message-ia'),
                        document.querySelector('#download-message-state'),
                        document.querySelector('#download-message-district'),
                        document.querySelector('#download-message-psu'),
                        document.querySelector('#download-message-devsec'),
                        document.querySelector('#download-message-sub-devsec'),
                        document.querySelector('#downloadStatus.alert-danger')
                    ];
                    for (let m of msgs) {
                        if (m && m.offsetParent !== null) {
                            let txt = (m.innerText || '').trim();
                            if (txt && (txt.toLowerCase().includes('captcha') || txt.toLowerCase().includes('error') || txt.toLowerCase().includes('failed') || txt.toLowerCase().includes('invalid'))) {
                                return txt;
                            }
                        }
                    }
                    return null;
                }""")

                if error_msg:
                    print(f"   ⚠️ Server notice: {error_msg}. Please re-enter the CAPTCHA.")
                    self.update_badge("INVALID CAPTCHA - TRY AGAIN", "#dc3545", "#fff")
                    self.last_submitted_endpoint = None
                    start_time = time.time()
                    continue

                # Submission accepted! Increment pending count and advance immediately!
                self.update_badge("SUBMITTED! MOVING TO NEXT...", "#17a2b8", "#fff")
                self.mgr.increment_pending(form_label)
                self.page.wait_for_timeout(800)
                return True

            # If user clicked GDP download directly
            try:
                gdp_link = self.page.query_selector("#downloadLinks a.btn")
                if gdp_link and gdp_link.is_visible():
                    gdp_link.click()
                    self.mgr.increment_pending(form_label)
                    return True
            except Exception:
                pass

            self.page.wait_for_timeout(400)

        print(f"   ⚠️ Timed out waiting for user input on {form_label}.")
        return False

    # =========================================================================
    # 1. Company Master Details
    # =========================================================================
    def extract_company_master(self):
        print("\n" + "=" * 65)
        print("🏢 [1/3] EXTRACTING COMPANY MASTER DETAILS")
        print("    URL: https://mcacdm.nic.in/company-master-details")
        print("=" * 65)

        self.page.goto("https://mcacdm.nic.in/company-master-details", wait_until="domcontentloaded", timeout=45000)
        self.page.wait_for_timeout(2000)

        # Tab 1: Company Master Details
        self.page.click("#v-pills-home-tab")
        self.page.wait_for_timeout(500)
        self.show_banner("Company Master Details", "Auto-selected all 36 States & 23 Classifications. Enter CAPTCHA & submit.")
        checked = self.page.evaluate("""() => {
            let cbs = document.querySelectorAll("#exportForm input[type='checkbox']");
            cbs.forEach(cb => cb.checked = true);
            return cbs.length;
        }""")
        print(f"   Selected all {checked} states and classifications automatically.")
        self.highlight_captcha("#exportForm", "input[name='captcha_input']")
        self.wait_for_submission("Company Master Details")

        # Tab 2: LLP Master Details (Switch immediately!)
        self.page.click("#llp-home-tab")
        self.page.wait_for_timeout(1000)
        self.show_banner("LLP Master Details", "Auto-selected all States & Classifications. Enter CAPTCHA & submit.")
        checked = self.page.evaluate("""() => {
            let cbs = document.querySelectorAll("#exportFormLLP input[type='checkbox']");
            cbs.forEach(cb => cb.checked = true);
            return cbs.length;
        }""")
        print(f"   Selected all {checked} LLP parameters automatically.")
        self.highlight_captcha("#exportFormLLP", "input[name='captcha_input_llp']")
        self.wait_for_submission("LLP Master Details")

        # Tab 3: Foreign Company Details
        self.page.click("#foreign-home-tab")
        self.page.wait_for_timeout(1000)
        self.show_banner("Foreign Company Master Details", "Enter CAPTCHA & submit.")
        self.highlight_captcha("#exportFormForeign", "input[name='captcha_input_foreign']")
        self.wait_for_submission("Foreign Company Details")

    # =========================================================================
    # 2. CSR Data
    # =========================================================================
    def extract_csr_data(self):
        print("\n" + "=" * 65)
        print("🤝 [2/3] EXTRACTING CSR DATA (Corporate Social Responsibility)")
        print("    URL: https://mcacdm.nic.in/csr-data")
        print("=" * 65)

        self.page.goto("https://mcacdm.nic.in/csr-data", wait_until="domcontentloaded", timeout=45000)
        self.page.wait_for_timeout(2000)

        # 1. Dynamic CSR Report (814 parameters)
        self.page.click("#v-pills-home-tab")
        self.page.wait_for_timeout(800)
        self.show_banner("Dynamic CSR Data", "Auto-selected all 814+ parameters (Years, States, Districts, Sectors).")
        checked = self.page.evaluate("""() => {
            let cbs = document.querySelectorAll("#exportForm input[type='checkbox']");
            cbs.forEach(cb => cb.checked = true);
            return cbs.length;
        }""")
        print(f"   Selected all {checked} filter checkboxes automatically.")
        self.highlight_captcha("#exportForm", "input[name='captcha_input']")
        self.wait_for_submission("Dynamic CSR Report (814 parameters)")

        # 2. Implementing Agency Master
        self.page.click("#ia-master")
        self.page.wait_for_timeout(800)
        self.show_banner("Implementing Agency Master", "Enter CAPTCHA & submit.")
        self.highlight_captcha("#exportFormia", "input[name='captcha_input']")
        self.wait_for_submission("Implementing Agency Master")

        # 3-7: CSR MIS Sub-tabs
        csr_mis_tabs = [
            {"name": "State-wise CSR Summary", "tab_id": "#home-tab", "form": "#exportFormState"},
            {"name": "District-wise CSR Summary", "tab_id": "#district-tab", "form": "#exportFormDistrict"},
            {"name": "PSU-wise CSR Summary", "tab_id": "#profile-tab", "form": "#exportFormpsu"},
            {"name": "Development Sector-wise CSR", "tab_id": "#contact-tab", "form": "#exportFormdevsec"},
            {"name": "Sub-Development Sector-wise CSR", "tab_id": "#subcontact-tab", "form": "#exportFormsubdevsec"},
        ]

        for tab in csr_mis_tabs:
            self.page.click("#v-pills-messages-tab")
            self.page.wait_for_timeout(400)
            self.page.click(tab["tab_id"])
            self.page.wait_for_timeout(800)
            self.show_banner(tab['name'], "Enter CAPTCHA & submit.")
            self.highlight_captcha(tab["form"], f"{tab['form']} input[name='captcha_input']")
            self.wait_for_submission(tab['name'])

    # =========================================================================
    # 3. GDP Calculation Data
    # =========================================================================
    def extract_gdp_calculation(self, years=None):
        print("\n" + "=" * 65)
        print("📈 [3/3] EXTRACTING GDP CALCULATION FINANCIAL STATEMENTS")
        print("    URL: https://mcacdm.nic.in/gdp_dashboard.php")
        print("=" * 65)

        self.page.goto("https://mcacdm.nic.in/gdp_dashboard.php", wait_until="domcontentloaded", timeout=45000)
        self.page.wait_for_timeout(2000)

        primary_tables = [
            {"title": "XBRL Balance Sheet", "selector": "a[data-tbl='t_api_gdp_xbrl_bs_current_previous']"},
            {"title": "XBRL Profit & Loss", "selector": "a[data-tbl='t_api_gdp_xbrl_pl_current_previous']"},
            {"title": "INDAS Balance Sheet", "selector": "a[data-tbl='t_api_gdp_indas_bs_current_previous']"},
            {"title": "INDAS Profit & Loss", "selector": "a[data-tbl='t_api_gdp_indas_pl_current_previous']"},
            {"title": "Non-XBRL AOC-4 (BS/PL)", "selector": "a[data-tbl='t_api_gdp_nonxbrl_aoc4_bs_pl_current_previous']"},
            {"title": "NBFC Balance Sheet", "selector": "a[data-tbl='t_api_gdp_nbfc_bs_current_previous']"},
        ]

        available_years = self.page.evaluate("""() => {
            let select = document.getElementById('financial_year');
            if (!select) return [];
            return Array.from(select.options).filter(o => o.value).map(o => ({val: o.value, text: o.text}));
        }""")

        target_years = available_years[:2] if not years else [y for y in available_years if y['val'] in years or y['text'] in years]
        print(f"Target Financial Years: {[y['text'] for y in target_years]}")

        for tbl in primary_tables:
            try:
                self.page.click(tbl['selector'])
                self.page.wait_for_timeout(600)
            except Exception:
                pass

            for yr in target_years:
                self.show_banner(f"GDP: {tbl['title']} ({yr['text']})", f"Selected {yr['text']}. Enter CAPTCHA & click DOWNLOAD CSV.")
                self.page.select_option("#financial_year", yr['val'])
                self.page.wait_for_timeout(400)

                self.highlight_captcha("#exportForm", "#captcha_input_foreign")
                self.wait_for_submission(f"GDP {tbl['title']} ({yr['text']})")

def main():
    parser = argparse.ArgumentParser(description="MCA CDM Portal Bulk CSV Data Extraction Assistant")
    parser.add_argument("--all", action="store_true", default=False, help="Extract all 3 sections")
    parser.add_argument("--company", action="store_true", default=False, help="Extract Company Master Details")
    parser.add_argument("--csr", action="store_true", default=False, help="Extract CSR Data")
    parser.add_argument("--gdp", action="store_true", default=False, help="Extract GDP Calculation Statements")
    parser.add_argument("--gdp-all-years", action="store_true", default=False, help="Extract all available financial years for GDP")
    args = parser.parse_args()

    if not (args.company or args.csr or args.gdp):
        args.all = True

    print("=" * 65)
    print("   MCA CDM (Corporate Data Management Portal) CSV Extraction Suite   ")
    print("   [Fast Pipeline Mode: Background Downloads Enabled]                ")
    print("=" * 65)
    print(f"📁 Output Base: {BASE_OUTPUT_DIR.resolve()}\n")

    download_mgr = BackgroundDownloadManager()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(viewport=None, accept_downloads=True)
        
        # Attach context-wide download listener
        context.on("download", download_mgr.on_download)

        page = context.new_page()
        extractor = MCACDMExtractor(page, download_mgr)

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
            print(f"Total files captured: {len(download_mgr.completed)}")
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
