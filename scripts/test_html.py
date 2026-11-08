import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def check():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        errors = []
        logs = []
        page.on('pageerror', lambda e: errors.append(f'PAGE_ERROR: {e}'))
        page.on('console', lambda msg: logs.append(f'[{msg.type}] {msg.text}'))
        
        file_url = Path('sample_integrated_dashboard.html').resolve().as_uri()
        print(f'Loading: {file_url}')
        
        await page.goto(file_url, wait_until='networkidle')
        await asyncio.sleep(3)
        
        # Check initial state
        coverage_visible = await page.is_visible('#view-coverage')
        fleet_visible = await page.is_visible('#view-fleet')
        print(f'Initial View: coverage={coverage_visible}, fleet={fleet_visible}')
        
        # Check header count badge
        badge_text = await page.inner_text('#header-fleet-badge')
        print(f'Header fleet badge text: "{badge_text}"')
        
        # Click Fleet tab
        print('Clicking Fleet Status Tab...')
        await page.click('#nav-btn-fleet')
        await asyncio.sleep(2)
        
        coverage_visible_after = await page.is_visible('#view-coverage')
        fleet_visible_after = await page.is_visible('#view-fleet')
        print(f'After Click: coverage={coverage_visible_after}, fleet={fleet_visible_after}')
        
        # Check fleet table content
        rows = await page.locator('#fleetTableBody tr').count()
        print(f'Fleet table rows: {rows}')
        
        first_row_text = await page.locator('#fleetTableBody tr').first.inner_text()
        print(f'First row text: {first_row_text.strip()[:100]}...')
        
        # Check KPI values
        kpi_active = await page.inner_text('#kpiActiveDaemons')
        kpi_completed = await page.inner_text('#kpiDistrictsCompleted')
        kpi_speed = await page.inner_text('#kpiAggregateSpeed')
        kpi_sync = await page.inner_text('#kpiLastSync')
        print(f'KPIs: Active={kpi_active}, Completed={kpi_completed}, Speed={kpi_speed}, LastSync={kpi_sync}')
        
        # Switch back to coverage
        print('Clicking State Coverage Tab...')
        await page.click('#nav-btn-coverage')
        await asyncio.sleep(1)
        print(f'Coverage visible after switch back: {await page.is_visible("#view-coverage")}')
        
        print('\n--- Browser Console Messages ---')
        for log in logs:
            print(log)
            
        print('\n--- Page Errors ---')
        if not errors:
            print('ZERO JavaScript / rendering errors!')
        else:
            for err in errors:
                print(err)
                
        await browser.close()

if __name__ == '__main__':
    asyncio.run(check())

