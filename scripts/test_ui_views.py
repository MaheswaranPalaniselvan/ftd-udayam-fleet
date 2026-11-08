from playwright.sync_api import sync_playwright
from pathlib import Path

def test_ui():
    html_path = Path('public/index.html').resolve()
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append(str(e)))
        
        page.goto(html_path.as_uri(), wait_until='networkidle')
        assert page.locator('#view-coverage').is_visible(), "Coverage view should be visible initially"
        
        # Click 1-Click Fleet Setup tab
        page.click('#nav-btn-onboarding')
        page.wait_for_timeout(200)
        assert page.locator('#view-onboarding').is_visible(), "Onboarding view should be visible"
        assert not page.locator('#view-coverage').is_visible(), "Coverage view should be hidden"
        
        # Test device tabs
        for dev in ['jetson', 'windows', 'cloud', 'pi']:
            page.click(f'.device-tab-btn[data-device="{dev}"]')
            page.wait_for_timeout(100)
            panel_vis = page.locator(f'#device-panel-{dev}').is_visible()
            print(f'Device panel {dev} visible: {panel_vis}')
            assert panel_vis, f"Device panel {dev} was not visible"
            
        print(f'Console errors: {len(errors)}')
        assert len(errors) == 0, f"Errors found: {errors}"
        browser.close()
        print('ALL PLAYWRIGHT CHECKS PASSED!')

if __name__ == "__main__":
    test_ui()
