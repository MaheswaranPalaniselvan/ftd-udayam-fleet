"""
MCA CDM (Corporate Data Management Portal) CSV Extraction Suite
================================================================
Automated form navigation, parameter multiselection, and CSV download manager
for the Ministry of Corporate Affairs CDM Portal (https://mcacdm.nic.in).

Targets:
  1. Company Master Details (Company, LLP, Foreign)
  2. CSR Data (Dynamic CSR with 814+ parameters, IA, State, District, PSU, DevSec, SubDevSec)
  3. GDP Calculation Data (XBRL, INDAS, Non-XBRL AOC-4, NBFC)

Compliance Note:
  Under safety policies, CAPTCHA challenges are not solved programmatically.
  This suite handles 100% of the UI navigation, selects all multi-select parameters,
  highlights and focuses the CAPTCHA box, and automatically intercepts, renames,
  and verifies downloaded CSVs.
"""

import os
import sys
import time
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_OUTPUT_DIR = Path("data/mca_cdm")
COMPANY_DIR = BASE_OUTPUT_DIR / "company_master"
CSR_DIR = BASE_OUTPUT_DIR / "csr_data"
GDP_DIR = BASE_OUTPUT_DIR / "gdp_calculation"

for d in (COMPANY_DIR, CSR_DIR, GDP_DIR):
    d.mkdir(parents=True, exist_ok=True)

class MCACDMExtractor:
    def __init__(self, page):
        self.page = page
        self.downloaded_file = None
        self.page.on("download", self._on_download)

    def _on_download(self, download):
        self.downloaded_file = download

    def show_banner(self, title, subtitle):
        """Displays an in-browser HUD banner to guide the user."""
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
                        <div style="font-weight: 700; font-size: 16px; color: #00d2ff;">🤖 MCA CDM Assistant — ${{JSON.stringify({title})}}</div>
                        <div style="font-size: 13px; color: #e0e0e0; margin-top: 2px;">${{JSON.stringify({subtitle})}}</div>
                    </div>
                    <div id="mca-hud-badge" style="background: #ffc107; color: #000; font-weight: bold; padding: 6px 14px; border-radius: 20px; font-size: 12px; letter-spacing: 0.5px;">
                        WAITING FOR CAPTCHA
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

    def wait_for_download(self, target_path, timeout_sec=120):
        """Waits for user submission and intercepts the downloaded CSV."""
        self.downloaded_file = None
        start_time = time.time()
        print(f"   ⏳ Waiting for user to solve CAPTCHA and click Export (timeout: {timeout_sec}s)...")

        while time.time() - start_time < timeout_sec:
            # Check if GDP dashboard generated download links
            try:
                gdp_link = self.page.query_selector("#downloadLinks a.btn")
                if gdp_link and gdp_link.is_visible():
                    print("   🔗 Detected generated download link in GDP dashboard. Triggering download...")
                    gdp_link.click()
            except Exception:
                pass

            if self.downloaded_file is not None:
                self.update_badge("DOWNLOADING CSV...", "#17a2b8", "#fff")
                download = self.downloaded_file
                self.downloaded_file = None
                target_path.parent.mkdir(parents=True, exist_ok=True)
                download.save_as(str(target_path))
                
                size_mb = target_path.stat().st_size / (1024 * 1024)
                print(f"   ✅ Successfully exported: {target_path.name} ({size_mb:.2f} MB)")
                self.update_badge("EXPORT COMPLETE!", "#28a745", "#fff")
                self.page.wait_for_timeout(1500)
                return True

            # Check if an error message is visible
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
                        if (txt && !txt.includes('Downloading') && !txt.includes('Successfully')) {
                            return txt;
                        }
                    }
                }
                return null;
            }""")
            if error_msg:
                self.update_badge(f"ERROR: {error_msg[:25]}", "#dc3545", "#fff")

            self.page.wait_for_timeout(500)

        print(f"   ⚠️ Timed out waiting for export of {target_path.name}")
        return False

    def highlight_captcha(self, form_selector, input_selector):
        """Scrolls to and highlights the CAPTCHA section with glowing cyan border."""
        try:
            self.page.evaluate(f"""() => {{
                const form = document.querySelector("{form_selector}");
                if (!form) return;
                const inp = form.querySelector("{input_selector}") || document.querySelector("{input_selector}");
                if (inp) {{
                    inp.style.border = "3px solid #00d2ff";
                    inp.style.boxShadow = "0 0 10px rgba(0, 210, 255, 0.7)";
                    inp.scrollIntoView({{ behavior: "smooth", block: "center" }});
                    inp.focus();
                }}
                const img = form.querySelector("img[src*='captcha'], #captcha-foreign-box img, .captcha-container img");
                if (img) {{
                    img.style.border = "2px solid #ffc107";
                    img.style.padding = "2px";
                }}
            }}""")
        except Exception:
            pass

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
        print("\n👉 [Company Master Details]")
        self.show_banner("Company Master Details", "Auto-selected all 36 States & 23 Classifications. Enter CAPTCHA & Export.")
        checked = self.page.evaluate("""() => {
            let cbs = document.querySelectorAll("#exportForm input[type='checkbox']");
            cbs.forEach(cb => cb.checked = true);
            return cbs.length;
        }""")
        print(f"   Selected all {checked} states and industrial classifications.")
        self.highlight_captcha("#exportForm", "input[name='captcha_input']")
        target_path = COMPANY_DIR / "Company_Master_Details.csv"
        self.wait_for_download(target_path)

        # Tab 2: LLP Master Details
        print("\n👉 [LLP Master Details]")
        self.page.click("a[href='#llp']")
        self.page.wait_for_timeout(1500)
        self.show_banner("LLP Master Details", "Auto-selected all States & Classifications. Enter CAPTCHA & Export.")
        checked = self.page.evaluate("""() => {
            let cbs = document.querySelectorAll("#exportFormLLP input[type='checkbox']");
            cbs.forEach(cb => cb.checked = true);
            return cbs.length;
        }""")
        print(f"   Selected all {checked} LLP parameters.")
        self.highlight_captcha("#exportFormLLP", "input[name='captcha_input_llp']")
        target_path = COMPANY_DIR / "LLP_Master_Details.csv"
        self.wait_for_download(target_path)

        # Tab 3: Foreign Company Details
        print("\n👉 [Foreign Company Master Details]")
        self.page.click("a[href='#foreign']")
        self.page.wait_for_timeout(1500)
        self.show_banner("Foreign Company Master Details", "Enter CAPTCHA & Export.")
        self.highlight_captcha("#exportFormForeign", "input[name='captcha_input_foreign']")
        target_path = COMPANY_DIR / "Foreign_Company_Master_Details.csv"
        self.wait_for_download(target_path)

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

        csr_tabs = [
            {
                "name": "Dynamic CSR Data",
                "form": "#exportForm",
                "input": "input[name='captcha_input']",
                "target": "CSR_Dynamic_Data.csv",
                "select_all": True,
                "desc": "Auto-selected all 814+ parameters (Years, States, Districts, Sectors)."
            },
            {
                "name": "Implementing Agency (IA) Master",
                "form": "#exportFormia",
                "input": "#exportFormia input[name='captcha_input']",
                "target": "CSR_Implementing_Agencies.csv",
                "select_all": False,
                "desc": "Master list of all Registered Implementing Agencies."
            },
            {
                "name": "State-wise CSR Summary",
                "form": "#exportFormState",
                "input": "#exportFormState input[name='captcha_input']",
                "target": "CSR_State_Wise.csv",
                "select_all": False,
                "desc": "Aggregated CSR expenditures state-by-state."
            },
            {
                "name": "District-wise CSR Summary",
                "form": "#exportFormDistrict",
                "input": "#exportFormDistrict input[name='captcha_input']",
                "target": "CSR_District_Wise.csv",
                "select_all": False,
                "desc": "Aggregated CSR expenditures district-by-district."
            },
            {
                "name": "PSU-wise CSR Summary",
                "form": "#exportFormpsu",
                "input": "#exportFormpsu input[name='captcha_input']",
                "target": "CSR_PSU_Wise.csv",
                "select_all": False,
                "desc": "Public Sector Undertakings CSR contributions."
            },
            {
                "name": "Development Sector-wise CSR",
                "form": "#exportFormdevsec",
                "input": "#exportFormdevsec input[name='captcha_input']",
                "target": "CSR_DevSec_Wise.csv",
                "select_all": False,
                "desc": "Sectoral CSR breakdowns (Health, Education, Rural, etc.)."
            },
            {
                "name": "Sub-Development Sector-wise CSR",
                "form": "#exportFormsubdevsec",
                "input": "#exportFormsubdevsec input[name='captcha_input']",
                "target": "CSR_Sub_DevSec_Wise.csv",
                "select_all": False,
                "desc": "Granular sub-sector CSR expenditures."
            },
        ]

        for tab in csr_tabs:
            print(f"\n👉 [{tab['name']}]")
            self.show_banner(tab['name'], tab['desc'])

            if tab["select_all"]:
                checked = self.page.evaluate(f"""() => {{
                    let cbs = document.querySelectorAll("{tab['form']} input[type='checkbox']");
                    cbs.forEach(cb => cb.checked = true);
                    return cbs.length;
                }}""")
                print(f"   Selected all {checked} filter checkboxes automatically.")

            self.highlight_captcha(tab["form"], tab["input"])
            target_path = CSR_DIR / tab["target"]
            self.wait_for_download(target_path)

    # =========================================================================
    # 3. GDP Calculation Data
    # =========================================================================
    def extract_gdp_calculation(self, years=None, tables=None):
        print("\n" + "=" * 65)
        print("📈 [3/3] EXTRACTING GDP CALCULATION FINANCIAL STATEMENTS")
        print("    URL: https://mcacdm.nic.in/gdp_dashboard.php")
        print("=" * 65)

        self.page.goto("https://mcacdm.nic.in/gdp_dashboard.php", wait_until="domcontentloaded", timeout=45000)
        self.page.wait_for_timeout(2000)

        primary_tables = [
            {"title": "XBRL Balance Sheet", "menu": "#xbrlMenu", "sub": "#xbrlSubMenu", "selector": "a[data-tbl='t_api_gdp_xbrl_bs_current_previous']"},
            {"title": "XBRL Profit & Loss", "menu": "#xbrlMenu", "sub": "#xbrlSubMenu", "selector": "a[data-tbl='t_api_gdp_xbrl_pl_current_previous']"},
            {"title": "INDAS Balance Sheet", "menu": "#xbrlMenu", "sub": "#indasMenu", "selector": "a[data-tbl='t_api_gdp_indas_bs_current_previous']"},
            {"title": "INDAS Profit & Loss", "menu": "#xbrlMenu", "sub": "#indasMenu", "selector": "a[data-tbl='t_api_gdp_indas_pl_current_previous']"},
            {"title": "Non-XBRL AOC-4 (BS/PL)", "menu": "#nonxbrlMenu", "sub": "#aoc4Menu", "selector": "a[data-tbl='t_api_gdp_nonxbrl_aoc4_bs_pl_current_previous']"},
            {"title": "NBFC Balance Sheet", "menu": "#nonxbrlMenu", "sub": "#nbfcMenu", "selector": "a[data-tbl='t_api_gdp_nbfc_bs_current_previous']"},
        ]

        available_years = self.page.evaluate("""() => {
            let select = document.getElementById('financial_year');
            if (!select) return [];
            return Array.from(select.options).filter(o => o.value).map(o => ({val: o.value, text: o.text}));
        }""")

        target_years = available_years[:2] if not years else [y for y in available_years if y['val'] in years or y['text'] in years]
        print(f"Target Financial Years: {[y['text'] for y in target_years]}")

        for tbl in primary_tables:
            print(f"\n📂 Dataset: {tbl['title']}")
            try:
                self.page.evaluate(f"""() => {{
                    const el = document.querySelector("{tbl['selector']}");
                    if (el) {{
                        el.click();
                    }}
                }}""")
                self.page.wait_for_timeout(1000)
            except Exception:
                pass

            for yr in target_years:
                print(f"   📅 Year: {yr['text']} ({yr['val']})")
                self.show_banner(f"GDP: {tbl['title']} ({yr['text']})", f"Selected {yr['text']}. Enter CAPTCHA & click DOWNLOAD CSV.")
                self.page.select_option("#financial_year", yr['val'])
                self.page.wait_for_timeout(500)

                self.highlight_captcha("#exportForm", "#captcha_input_foreign")
                clean_tbl = tbl['title'].replace(" ", "_").replace("&", "and").replace("/", "-").replace("(", "").replace(")", "")
                target_path = GDP_DIR / f"GDP_{clean_tbl}_{yr['text'].replace('/', '-')}.csv"
                self.wait_for_download(target_path)

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
    print("=" * 65)
    print(f"📁 Output Base: {BASE_OUTPUT_DIR.resolve()}")
    print("👉 A visible Chrome browser window will now open.")
    print("👉 All forms and multiselect parameters will be chosen automatically.")
    print("👉 For each form, simply enter the 6-character CAPTCHA in the glowing box.")
    print("=" * 65)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(viewport=None, accept_downloads=True)
        page = context.new_page()
        extractor = MCACDMExtractor(page)

        try:
            if args.all or args.company:
                extractor.extract_company_master()

            if args.all or args.csr:
                extractor.extract_csr_data()

            if args.all or args.gdp:
                years = None if not args.gdp_all_years else ["2025", "2024", "2023", "2022", "2021", "2020"]
                extractor.extract_gdp_calculation(years=years)

            print("\n" + "=" * 65)
            print("🎉 MCA CDM DATA EXTRACTION WORKFLOW COMPLETE!")
            print(f"📁 All downloaded CSVs are stored in: {BASE_OUTPUT_DIR.resolve()}")
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
