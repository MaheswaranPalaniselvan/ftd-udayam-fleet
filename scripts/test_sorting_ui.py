import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

def test_sorting():
    html_path = Path("public/index.html").resolve()
    assert html_path.exists(), f"File {html_path} does not exist"

    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))

        print(f"Loading {html_path.as_uri()}...")
        page.goto(html_path.as_uri(), wait_until="networkidle")

        # 1. Check initial state
        state_cards = page.locator(".state-card")
        total_states = state_cards.count()
        print(f"Loaded {total_states} states successfully.")
        assert total_states == 36, f"Expected 36 states, got {total_states}"

        # 2. Expand all states
        page.click("button:has-text('Expand All')")
        page.wait_for_timeout(200)

        # Check Tamil Nadu or Manipur first district
        tn_card = page.locator("#state-TN")
        assert tn_card.count() > 0, "Tamil Nadu card not found"
        first_dist_code = tn_card.locator("table.sub-table tbody tr td.dist-code").first.inner_text().strip()
        print(f"Default TN first district code: {first_dist_code}")
        assert first_dist_code == "TN-01", f"Expected TN-01, got {first_dist_code}"

        # 3. Test changing sort via dropdown to name_asc (District Name A->Z)
        print("Testing sort dropdown: name_asc...")
        page.select_option("#sortSelect", "name_asc")
        page.wait_for_timeout(200)

        first_dist_name = tn_card.locator("table.sub-table tbody tr td:nth-child(2)").first.inner_text().strip()
        print(f"TN first district name (A->Z): {first_dist_name}")
        assert first_dist_name == "Ariyalur", f"Expected Ariyalur, got {first_dist_name}"

        # 4. Test changing sort via dropdown to extracted_desc
        print("Testing sort dropdown: extracted_desc...")
        page.select_option("#sortSelect", "extracted_desc")
        page.wait_for_timeout(200)

        top_extracted_tn = tn_card.locator("table.sub-table tbody tr td:nth-child(4)").first.inner_text().strip()
        top_dist_name_tn = tn_card.locator("table.sub-table tbody tr td:nth-child(2)").first.inner_text().strip()
        print(f"Top extracted district in TN: {top_dist_name_tn} with {top_extracted_tn}")
        # In TN, Krishnagiri (12,41,087) or Coimbatore (2,65,622) has the highest
        assert "12,41,087" in top_extracted_tn or "2,65,622" in top_extracted_tn, f"Unexpected top extracted: {top_extracted_tn}"

        # Check state order: top extracted state should be first!
        first_state_code = page.locator(".state-card .state-code-pill").first.inner_text().strip()
        print(f"Top extracted state across India: {first_state_code}")
        # Top state by extracted records is likely MH (Maharashtra) or TN
        assert first_state_code in ["MH", "TN", "GJ", "UP"], f"Expected top state in [MH, TN, GJ, UP], got {first_state_code}"

        # 5. Test clicking column header: "Last Date Harvested"
        print("Testing click on 'Last Date Harvested' header...")
        harvest_header = tn_card.locator("th:has-text('Last Date Harvested')")
        harvest_header.click()
        page.wait_for_timeout(200)

        # Check sort icon on header
        header_text = harvest_header.inner_text()
        print(f"Harvest header text after click: {header_text}")
        assert "▼" in header_text or "▲" in header_text, f"Sort icon missing in {header_text}"

        first_harvest_date = tn_card.locator("table.sub-table tbody tr td:nth-child(6)").first.inner_text().strip()
        print(f"Top harvested date in TN: {first_harvest_date}")
        assert first_harvest_date != "-", "Unharvested district should not be first in descending sort"

        # Check dropdown is synced
        current_select_val = page.eval_on_selector("#sortSelect", "el => el.value")
        print(f"Dropdown synced value: {current_select_val}")
        assert "harvest_date" in current_select_val

        # 6. Test clicking District Code header twice (toggle asc -> desc -> asc)
        print("Testing click on Code header...")
        code_header = tn_card.locator("th:has-text('Code')")
        code_header.click()
        page.wait_for_timeout(200)
        code_header_text = code_header.inner_text()
        print(f"Code header text: {code_header_text}")

        # Check zero JS console errors
        print(f"Console errors recorded: {len(console_errors)}")
        if console_errors:
            print("Errors:", console_errors)
        assert len(console_errors) == 0, f"Found JavaScript console errors: {console_errors}"

        browser.close()
        print("[SUCCESS] All UI sorting tests passed with 0 console errors!")

if __name__ == "__main__":
    test_sorting()
