"""
Generates sample_integrated_dashboard.html showcasing the unified State Coverage & Fleet Status dual-view dashboard.
"""

from pathlib import Path

def generate_sample():
    src_path = Path("public/index.html")
    if not src_path.exists():
        raise FileNotFoundError("public/index.html not found.")
        
    html = src_path.read_text(encoding="utf-8")
    
    # 1. Remove any previous modal and duplicate script that was added earlier
    modal_idx = html.find('<!-- Central Fleet Health Modal -->')
    if modal_idx != -1:
        end_body_idx = html.find('</body>', modal_idx)
        html = html[:modal_idx] + html[end_body_idx:]
        
    old_modal_idx = html.find('<!-- Fleet Status Modal -->')
    if old_modal_idx != -1:
        end_body_idx = html.find('</body>', old_modal_idx)
        html = html[:old_modal_idx] + html[end_body_idx:]

    # Remove any existing modal JS logic from public/index.html
    old_modal_js_start = html.find("// Fleet Status Live Modal Logic")
    if old_modal_js_start != -1:
        render_view_call = html.find("renderView();", old_modal_js_start)
        if render_view_call != -1:
            html = html[:old_modal_js_start] + html[render_view_call:]
        else:
            last_script = html.rfind("</script>")
            html = html[:old_modal_js_start] + "renderView();\n" + html[last_script:]
    elif "const FLEET_API_URL" in html:
        fleet_url_idx = html.find("const FLEET_API_URL")
        render_view_call = html.find("renderView();", fleet_url_idx)
        if render_view_call != -1:
            html = html[:fleet_url_idx] + html[render_view_call:]
        else:
            last_script = html.rfind("</script>")
            html = html[:fleet_url_idx] + "renderView();\n" + html[last_script:]

    # 2. Add Custom CSS for View Switcher and Fleet Status View
    custom_css = """
    /* View Switcher Controls */
    .view-switch-group {
      display: inline-flex;
      background: rgba(15, 23, 42, 0.75);
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 10px;
      padding: 4px;
      gap: 4px;
    }
    .view-tab-btn {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      background: transparent;
      color: var(--text-muted);
      border: none;
      padding: 0.55rem 1.15rem;
      border-radius: 7px;
      font-family: var(--font-body);
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .view-tab-btn:hover {
      color: #fff;
      background: rgba(255, 255, 255, 0.06);
    }
    .view-tab-btn.active {
      background: #38bdf8;
      color: #090d16;
      font-weight: 700;
      box-shadow: 0 2px 10px rgba(56, 189, 248, 0.4);
    }
    .view-tab-btn.active .header-count-pill {
      background: #090d16;
      color: #38bdf8;
    }
    .header-count-pill {
      font-size: 0.72rem;
      font-weight: 700;
      padding: 0.15rem 0.55rem;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.12);
      color: #34d399;
      transition: all 0.2s;
    }

    /* Fleet View Styles */
    .fleet-view-container {
      margin-top: 0.5rem;
      animation: fadeIn 0.2s ease-in-out;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .fleet-hero-banner {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      background: linear-gradient(135deg, rgba(24, 24, 37, 0.95), rgba(17, 17, 27, 0.98));
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: 14px;
      padding: 1.1rem 1.6rem;
      margin-bottom: 1.25rem;
      gap: 1rem;
    }
    .fleet-hero-left {
      display: flex;
      align-items: center;
      gap: 1rem;
    }
    .fleet-hero-title h2 {
      font-family: var(--font-heading);
      font-size: 1.25rem;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }
    .fleet-hero-title p {
      font-size: 0.82rem;
      color: var(--text-muted);
      margin-top: 3px;
    }
    .fleet-kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1rem;
      margin-bottom: 1.25rem;
    }
    .fleet-kpi-card {
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 14px;
      padding: 1.25rem 1.4rem;
      transition: all 0.2s;
    }
    .fleet-kpi-card:hover {
      border-color: rgba(56, 189, 248, 0.4);
      background: var(--bg-card-hover);
    }
    .fleet-kpi-label {
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.6px;
      margin-bottom: 0.4rem;
    }
    .fleet-kpi-value {
      font-family: var(--font-heading);
      font-size: 1.85rem;
      font-weight: 800;
      color: #fff;
    }
    .fleet-kpi-sub {
      font-size: 0.78rem;
      color: var(--text-muted);
      margin-top: 0.25rem;
    }
    .fleet-table-card {
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 14px;
      padding: 1.25rem;
      overflow: hidden;
    }
    .fleet-table-toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
      margin-bottom: 1rem;
    }
    .fleet-search-box {
      background: var(--bg-base);
      border: 1px solid var(--border-card);
      border-radius: 8px;
      padding: 0.55rem 0.95rem;
      color: #fff;
      font-family: var(--font-body);
      font-size: 0.85rem;
      width: 280px;
      outline: none;
    }
    .fleet-search-box:focus {
      border-color: #38bdf8;
    }
    .fleet-filter-chips {
      display: flex;
      gap: 0.4rem;
      flex-wrap: wrap;
    }
    .fleet-filter-chip {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 0.35rem 0.8rem;
      border-radius: 6px;
      font-size: 0.78rem;
      cursor: pointer;
      font-weight: 600;
      transition: all 0.2s;
    }
    .fleet-filter-chip:hover {
      background: rgba(255, 255, 255, 0.1);
      color: #fff;
    }
    .fleet-filter-chip.active {
      background: rgba(56, 189, 248, 0.2);
      border-color: rgba(56, 189, 248, 0.5);
      color: #38bdf8;
    }
    .fleet-status-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.86rem;
    }
    .fleet-status-table th {
      background: rgba(255, 255, 255, 0.03);
      color: var(--text-muted);
      font-weight: 600;
      text-align: left;
      padding: 0.75rem 1rem;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      border-bottom: 1px solid var(--border-subtle);
    }
    .fleet-status-table td {
      padding: 0.85rem 1rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      color: var(--text-main);
    }
    .fleet-status-table tr:hover td {
      background: rgba(255, 255, 255, 0.02);
    }
    """
    
    html = html.replace("</style>", custom_css + "\n  </style>")
    
    # 3. Replace Header brand-right
    start_br = html.find('<div class="brand-right"')
    end_br = html.find('</header>', start_br)
    
    new_header_right = """<div class="brand-right" style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
        <!-- Integrated View Switcher -->
        <div class="view-switch-group">
          <button id="nav-btn-coverage" class="view-tab-btn active" onclick="switchMainView('coverage')">
            📊 State Coverage View
          </button>
          <button id="nav-btn-fleet" class="view-tab-btn" onclick="switchMainView('fleet')">
            <span class="pulse-dot"></span> 🌐 Fleet Status View <span id="header-fleet-badge" class="header-count-pill">-- Active</span>
          </button>
        </div>
        <button class="btn btn-primary" onclick="exportFilteredExcel()">📊 Export Excel (.xlsx)</button>
      </div>
    """
    html = html[:start_br] + new_header_right + html[end_br:]
    
    # 4. Wrap Coverage Section
    cov_start_marker = '<div class="portal-banner">'
    cov_end_marker = 'id="emptyMessage"'
    
    idx_cov_start = html.find(cov_start_marker)
    idx_cov_end_temp = html.find(cov_end_marker)
    # Find closing tag of emptyMessage div
    idx_cov_end = html.find('</div>', idx_cov_end_temp) + 6
    
    coverage_content = html[idx_cov_start:idx_cov_end]
    
    fleet_view_html = """
    <!-- ========================================== -->
    <!-- VIEW 2: CENTRAL FLEET STATUS MONITOR VIEW  -->
    <!-- ========================================== -->
    <div id="view-fleet" class="fleet-view-container" style="display: none;">
      <!-- Fleet Hero Banner -->
      <div class="fleet-hero-banner">
        <div class="fleet-hero-left">
          <span style="font-size: 2.2rem;">🌐</span>
          <div class="fleet-hero-title">
            <h2>Central Fleet Live Health & Daemon Monitor <span class="pill-badge"><span class="pulse-dot"></span> Live Telemetry</span></h2>
            <p>Real-time autonomous tracking across Raspberry Pi 5, Pi 4, Jetson Nano & Cloud Workers</p>
          </div>
        </div>
        <div style="display: flex; gap: 10px; align-items: center;">
          <span id="fleetSyncTimerMsg" style="font-size: 0.8rem; color: var(--text-dim);">Auto-refreshing every 15s</span>
          <button onclick="fetchFleetStatus()" class="btn" style="background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.18); color: #fff; font-size: 0.82rem; padding: 0.5rem 0.9rem; cursor: pointer; border-radius: 8px;">
            🔄 Refresh Telemetry
          </button>
        </div>
      </div>

      <!-- Fleet KPI Grid -->
      <div class="fleet-kpi-grid">
        <div class="fleet-kpi-card">
          <div class="fleet-kpi-label">Active Daemons</div>
          <div class="fleet-kpi-value" id="kpiActiveDaemons" style="color: #34d399;">--</div>
          <div class="fleet-kpi-sub">SBCs & Workers Scraping Now</div>
        </div>
        <div class="fleet-kpi-card">
          <div class="fleet-kpi-label">Districts Harvested</div>
          <div class="fleet-kpi-value" id="kpiDistrictsCompleted" style="color: #38bdf8;">--</div>
          <div class="fleet-kpi-sub">Total Leased & Completed (788 All India)</div>
        </div>
        <div class="fleet-kpi-card">
          <div class="fleet-kpi-label">Fleet Aggregate Speed</div>
          <div class="fleet-kpi-value" id="kpiAggregateSpeed" style="color: #fbbf24;">--</div>
          <div class="fleet-kpi-sub">Combined Records / Minute</div>
        </div>
        <div class="fleet-kpi-card">
          <div class="fleet-kpi-label">Last Coordinator Ping</div>
          <div class="fleet-kpi-value" id="kpiLastSync" style="font-size: 1.4rem; color: #c084fc;">--</div>
          <div class="fleet-kpi-sub">Google Apps Script Live Sync</div>
        </div>
      </div>

      <!-- Live Daemon Status Table Card -->
      <div class="fleet-table-card">
        <div class="fleet-table-toolbar">
          <input type="text" id="fleetSearchInput" class="fleet-search-box" placeholder="Search Machine / Daemon or District..." oninput="filterFleetTable()">
          <div class="fleet-filter-chips">
            <button class="fleet-filter-chip active" data-filter="all" onclick="setFleetFilter('all')">All Daemons</button>
            <button class="fleet-filter-chip" data-filter="active" onclick="setFleetFilter('active')">🟢 Active</button>
            <button class="fleet-filter-chip" data-filter="lagging" onclick="setFleetFilter('lagging')">🟡 Lagging</button>
            <button class="fleet-filter-chip" data-filter="stalled" onclick="setFleetFilter('stalled')">🟠 Stalled</button>
            <button class="fleet-filter-chip" data-filter="offline" onclick="setFleetFilter('offline')">🔴 Offline</button>
          </div>
        </div>

        <div style="overflow-x: auto;">
          <table class="fleet-status-table">
            <thead>
              <tr>
                <th>Machine / Daemon Name</th>
                <th>Hardware / Role</th>
                <th>Live Status</th>
                <th>Assigned District</th>
                <th>Current Progress Record</th>
                <th>Speed (rpm)</th>
                <th>Last Heartbeat</th>
              </tr>
            </thead>
            <tbody id="fleetTableBody">
              <tr>
                <td colspan="7" style="text-align: center; color: var(--text-dim); padding: 2.5rem;">
                  Connecting to Central Coordinator & fetching live fleet telemetry...
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """
    
    integrated_body = f"""
    <!-- ========================================== -->
    <!-- VIEW 1: STATE COVERAGE DASHBOARD VIEW     -->
    <!-- ========================================== -->
    <div id="view-coverage" class="coverage-view-container" style="display: block;">
      {coverage_content}
    </div>

    {fleet_view_html}
    """
    
    html = html[:idx_cov_start] + integrated_body + html[idx_cov_end:]
    
    # 5. Inject Clean JavaScript functions for View Switching & Live Polling
    js_logic = """
    // ==========================================
    // DUAL-VIEW INTEGRATION & REAL-TIME FLEET TELEMETRY
    // ==========================================
    const FLEET_API_URL = "https://script.google.com/macros/s/AKfycby3tmgH9PtjUhl6XfGrBfgRNZFQZaSLR0N4Dnff9tt9K5qjatyarJy_nnE0ulCtMNm2xA/exec";
    let currentMainView = 'coverage';
    let fleetRawData = [];
    let currentFleetFilter = 'all';
    let fleetPollingTimer = null;

    function switchMainView(viewName) {
      currentMainView = viewName;
      const coverageView = document.getElementById('view-coverage');
      const fleetView = document.getElementById('view-fleet');
      const btnCoverage = document.getElementById('nav-btn-coverage');
      const btnFleet = document.getElementById('nav-btn-fleet');

      if (viewName === 'coverage') {
        if (coverageView) coverageView.style.display = 'block';
        if (fleetView) fleetView.style.display = 'none';
        if (btnCoverage) btnCoverage.classList.add('active');
        if (btnFleet) btnFleet.classList.remove('active');
      } else {
        if (coverageView) coverageView.style.display = 'none';
        if (fleetView) fleetView.style.display = 'block';
        if (btnCoverage) btnCoverage.classList.remove('active');
        if (btnFleet) btnFleet.classList.add('active');
        fetchFleetStatus();
      }
    }

    async function fetchFleetStatus() {
      const msg = document.getElementById('fleetSyncTimerMsg');
      try {
        const resp = await fetch(`${FLEET_API_URL}?action=fleet_status`);
        const data = await resp.json();
        if (data && data.status === 'ok') {
          fleetRawData = data.active_workers || [];
          updateFleetUI(data);
          if (msg) msg.textContent = `Last synced: ${new Date().toLocaleTimeString()} (auto-refresh 15s)`;
        }
      } catch (err) {
        if (msg) msg.textContent = `Sync note: ${err.message}`;
      }
    }

    function updateFleetUI(data) {
      const activeWorkers = data.active_workers || [];
      const actCountEl = document.getElementById('kpiActiveDaemons');
      const compCountEl = document.getElementById('kpiDistrictsCompleted');
      const spdEl = document.getElementById('kpiAggregateSpeed');
      const syncEl = document.getElementById('kpiLastSync');
      const navBadge = document.getElementById('header-fleet-badge');

      if (compCountEl) compCountEl.textContent = `${data.districts_completed || 0} / ${data.total_districts || 788}`;
      if (syncEl) syncEl.textContent = new Date().toLocaleTimeString();

      let activeCount = 0;
      let totalSpeed = 0.0;

      activeWorkers.forEach(w => {
        const mins = w.minutesAgo || 0;
        const spd = parseFloat(w.speed) || 0.0;
        if (mins <= 5) {
          activeCount++;
          totalSpeed += spd;
        } else if (mins <= 15) {
          activeCount++;
          totalSpeed += spd;
        }
      });

      if (actCountEl) actCountEl.textContent = `${activeCount} Active`;
      if (spdEl) spdEl.textContent = `${totalSpeed.toFixed(1)} rpm`;
      if (navBadge) {
        navBadge.textContent = `${activeCount} Active`;
        navBadge.style.color = activeCount > 0 ? '#34d399' : '#94a3b8';
      }

      renderFleetTable();
    }

    function setFleetFilter(filter) {
      currentFleetFilter = filter;
      document.querySelectorAll('.fleet-filter-chip').forEach(c => {
        c.classList.toggle('active', c.getAttribute('data-filter') === filter);
      });
      renderFleetTable();
    }

    function filterFleetTable() {
      renderFleetTable();
    }

    function renderFleetTable() {
      const tbody = document.getElementById('fleetTableBody');
      if (!tbody) return;

      const query = (document.getElementById('fleetSearchInput')?.value || '').toLowerCase().trim();

      let filtered = fleetRawData.filter(w => {
        const mach = (w.machine || '').toLowerCase();
        const dist = (w.district || '').toLowerCase();
        if (query && !mach.includes(query) && !dist.includes(query)) return false;

        const mins = w.minutesAgo || 0;
        if (currentFleetFilter === 'active' && mins > 5) return false;
        if (currentFleetFilter === 'lagging' && (mins <= 5 || mins > 15)) return false;
        if (currentFleetFilter === 'stalled' && (mins <= 15 || mins > 60)) return false;
        if (currentFleetFilter === 'offline' && mins <= 60) return false;

        return true;
      });

      if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-dim); padding: 2rem;">No worker daemons matching current filter.</td></tr>';
        return;
      }

      filtered.sort((a, b) => (a.minutesAgo || 0) - (b.minutesAgo || 0));

      let rows = '';
      filtered.forEach(w => {
        const mins = w.minutesAgo || 0;
        const spd = parseFloat(w.speed) || 0.0;
        let badgeClass = 'status-live';
        let badgeText = '🟢 Active';

        if (mins <= 5) {
          badgeClass = 'status-live';
          badgeText = '🟢 Active';
        } else if (mins <= 15) {
          badgeClass = 'status-outdated-progress';
          badgeText = '🟡 Lagging';
        } else if (mins <= 60) {
          badgeClass = 'status-outdated-progress';
          badgeText = '🟠 Stalled';
        } else {
          badgeClass = 'status-outdated';
          badgeText = '🔴 Offline';
        }

        const machName = w.machine || 'Unknown';
        let hwBadge = '💻 Worker';
        if (machName.toLowerCase().includes('pi5')) hwBadge = '🍓 Pi 5 (ARM64)';
        else if (machName.toLowerCase().includes('pi4')) hwBadge = '🍓 Pi 4 (ARM64)';
        else if (machName.toLowerCase().includes('jetson')) hwBadge = '⚡ Jetson Nano';
        else if (machName.toLowerCase().includes('colab')) hwBadge = '☁️ Colab Cloud';
        else if (machName.toLowerCase().includes('github')) hwBadge = '🐙 GitHub Runner';

        const lastPingText = mins === 0 ? 'Just now' : (mins === 1 ? '1 min ago' : (mins < 60 ? `${mins} mins ago` : `${(mins/60).toFixed(1)} hrs ago`));

        rows += `
          <tr>
            <td style="font-weight: 600; color: #fff;">${machName}</td>
            <td><span class="pill-badge" style="background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); color: var(--text-muted); font-size: 0.74rem;">${hwBadge}</span></td>
            <td><span class="status-badge ${badgeClass}">${badgeText}</span></td>
            <td class="dist-code">${w.district || '-'}</td>
            <td class="mono-num" style="color: #93c5fd; font-size: 0.88rem;">${w.lastRecord || '-'}</td>
            <td class="mono-num" style="color: #34d399; font-weight: 600;">${spd.toFixed(1)} rpm</td>
            <td style="color: var(--text-muted); font-size: 0.82rem;">${lastPingText}</td>
          </tr>
        `;
      });

      tbody.innerHTML = rows;
    }

    // Start background polling every 15s
    fetchFleetStatus();
    fleetPollingTimer = setInterval(fetchFleetStatus, 15000);
    """
    
    last_script_idx = html.rfind("</script>")
    if last_script_idx != -1:
        html = html[:last_script_idx] + js_logic + "\n  " + html[last_script_idx:]
    else:
        html += f"<script>{js_logic}</script>"
    
    out_file = Path("sample_integrated_dashboard.html")
    out_file.write_text(html, encoding="utf-8")
    print(f"[OK] Generated clean sample: {out_file.resolve()} ({out_file.stat().st_size:,} bytes)")

if __name__ == "__main__":
    generate_sample()
