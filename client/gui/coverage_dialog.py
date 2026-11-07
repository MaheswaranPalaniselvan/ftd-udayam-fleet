"""
Hierarchical Fleet Coverage & Google Sheets Statistics Drill-Down Dialog.
Visualizes:
- States covered & progress percentages
- Districts covered per state
- Last extracted Udyam number per district
- Last date registered (DOR) as recorded in the extract
- Live synchronization with Google Sheet & local archives
- Direct selection for incremental load execution
"""

import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from client.core.gsheet_sync import (
    fetch_gsheet_statistics,
    export_coverage_stats_to_excel,
    get_cached_or_local_statistics
)
from client.core.district_manager import find_district_last_number


class UdyamCoverageStatsDialog(tk.Toplevel):
    def __init__(self, parent, gsheet_url: str = None, on_district_selected = None):
        super().__init__(parent)

        self.parent = parent
        self.gsheet_url = gsheet_url
        self.on_district_selected = on_district_selected

        self.title("📊 FlawlessTech Data | Fleet Coverage & GSheet Statistics Drill-Down")
        self.geometry("1100x720")
        self.minsize(940, 580)
        self.configure(bg="#181825")

        self.stats_data = {}
        self.selected_district_code = None
        self.selected_district_info = None

        self._setup_dialog_styles()
        self._build_dialog_ui()

        # Immediate synchronous render from local cache / archives (< 0.05s)
        cached_stats = get_cached_or_local_statistics()
        if cached_stats and cached_stats.get("states"):
            self._on_data_loaded(cached_stats)
            self.source_badge.config(text="🟡 INITIALIZING...", bg="#313244", fg="#f9e2af")

        # Asynchronously fetch live Google Sheet updates in background thread
        self.refresh_data(show_loading=False if (cached_stats and cached_stats.get("states")) else True)

    def _setup_dialog_styles(self):
        self.style = ttk.Style(self)

        self.style.configure("Coverage.TFrame", background="#181825")
        self.style.configure("CoverageCard.TFrame", background="#1e1e2e", relief="flat")
        self.style.configure("CoverageHeader.TLabel", background="#181825", foreground="#89b4fa", font=("Segoe UI", 14, "bold"))
        self.style.configure("CoverageMuted.TLabel", background="#181825", foreground="#6c7086", font=("Segoe UI", 8))

        # KPI labels
        self.style.configure("CovKpiVal.TLabel", background="#1e1e2e", foreground="#a6e3a1", font=("Segoe UI", 16, "bold"))
        self.style.configure("CovKpiLbl.TLabel", background="#1e1e2e", foreground="#9399b2", font=("Segoe UI", 9))

        # Treeview styling for dark theme
        self.style.configure(
            "Coverage.Treeview",
            background="#1e1e2e",
            foreground="#cdd6f4",
            fieldbackground="#1e1e2e",
            font=("Segoe UI", 9),
            rowheight=24,
            borderwidth=0
        )
        self.style.configure(
            "Coverage.Treeview.Heading",
            background="#181825",
            foreground="#89b4fa",
            font=("Segoe UI", 9, "bold"),
            padding=4
        )
        self.style.map("Coverage.Treeview", background=[("selected", "#313244")], foreground=[("selected", "#89b4fa")])

        # Buttons
        self.style.configure("AccentSmall.TButton", background="#89b4fa", foreground="#11111b", font=("Segoe UI", 9, "bold"), borderwidth=0, padding=5)
        self.style.map("AccentSmall.TButton", background=[("active", "#b4befe")])

        self.style.configure("GreenSmall.TButton", background="#a6e3a1", foreground="#11111b", font=("Segoe UI", 9, "bold"), borderwidth=0, padding=5)
        self.style.map("GreenSmall.TButton", background=[("active", "#94e2d5")])

        self.style.configure("SecSmall.TButton", background="#313244", foreground="#cdd6f4", font=("Segoe UI", 8), borderwidth=0, padding=4)
        self.style.map("SecSmall.TButton", background=[("active", "#45475a")])

    def _build_dialog_ui(self):
        # 1. Header Frame
        header = ttk.Frame(self, style="Coverage.TFrame", padding=(20, 14, 20, 8))
        header.pack(fill="x")

        title_box = ttk.Frame(header, style="Coverage.TFrame")
        title_box.pack(side="left")

        ttk.Label(title_box, text="📊 Fleet Coverage & GSheet Statistics Drill-Down", style="CoverageHeader.TLabel").pack(anchor="w")
        self.sync_meta_lbl = ttk.Label(title_box, text="Connecting to Google Sheet [UDAYAM extract]...", style="CoverageMuted.TLabel")
        self.sync_meta_lbl.pack(anchor="w")

        right_actions = ttk.Frame(header, style="Coverage.TFrame")
        right_actions.pack(side="right")

        self.source_badge = tk.Label(right_actions, text="🔄 FETCHING...", bg="#313244", fg="#f9e2af", font=("Segoe UI", 9, "bold"), padx=10, pady=3)
        self.source_badge.pack(side="right", padx=(8, 0))

        ttk.Button(right_actions, text="🔄 Refresh from GSheet", style="AccentSmall.TButton", command=self.refresh_data).pack(side="right")

        # 2. KPI Cards Row
        kpi_container = ttk.Frame(self, style="Coverage.TFrame", padding=(20, 0, 20, 10))
        kpi_container.pack(fill="x")

        # Card 1: States Covered
        c1 = ttk.Frame(kpi_container, style="CoverageCard.TFrame", padding=10)
        c1.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ttk.Label(c1, text="STATES COVERED", style="CovKpiLbl.TLabel").pack(anchor="w")
        self.kpi_states_lbl = ttk.Label(c1, text="0 / 0", style="CovKpiVal.TLabel")
        self.kpi_states_lbl.pack(anchor="w", pady=(2, 0))

        # Card 2: Districts Covered
        c2 = ttk.Frame(kpi_container, style="CoverageCard.TFrame", padding=10)
        c2.pack(side="left", fill="both", expand=True, padx=6)
        ttk.Label(c2, text="DISTRICTS COVERED", style="CovKpiLbl.TLabel").pack(anchor="w")
        self.kpi_districts_lbl = ttk.Label(c2, text="0 / 0", style="CovKpiVal.TLabel")
        self.kpi_districts_lbl.pack(anchor="w", pady=(2, 0))

        # Card 3: Total Extracted Records
        c3 = ttk.Frame(kpi_container, style="CoverageCard.TFrame", padding=10)
        c3.pack(side="left", fill="both", expand=True, padx=6)
        ttk.Label(c3, text="TOTAL RECORDS EXTRACTED", style="CovKpiLbl.TLabel").pack(anchor="w")
        self.kpi_extracted_lbl = ttk.Label(c3, text="0", style="CovKpiVal.TLabel")
        self.kpi_extracted_lbl.pack(anchor="w", pady=(2, 0))

        # Card 4: Total Failed Records
        c4 = ttk.Frame(kpi_container, style="CoverageCard.TFrame", padding=10)
        c4.pack(side="left", fill="both", expand=True, padx=(6, 0))
        ttk.Label(c4, text="TOTAL FAILED RECORDS", style="CovKpiLbl.TLabel").pack(anchor="w")
        self.kpi_failed_lbl = ttk.Label(c4, text="0", style="CovKpiVal.TLabel", foreground="#f38ba8")
        self.kpi_failed_lbl.pack(anchor="w", pady=(2, 0))

        # 3. Toolbar (Search, Filter, Expand, Export)
        toolbar = ttk.Frame(self, style="Coverage.TFrame", padding=(20, 0, 20, 8))
        toolbar.pack(fill="x")

        # Search filter
        ttk.Label(toolbar, text="🔍 Search:", style="TLabel").pack(side="left", padx=(0, 4))
        self.search_entry = tk.Entry(toolbar, bg="#313244", fg="#cdd6f4", insertbackground="#cdd6f4", relief="flat", font=("Segoe UI", 9), width=28)
        self.search_entry.pack(side="left", padx=(0, 14), ipady=2)
        self.search_entry.bind("<KeyRelease>", lambda e: self._render_tree())

        # Coverage status filter
        ttk.Label(toolbar, text="Filter:", style="TLabel").pack(side="left", padx=(0, 4))
        self.filter_var = tk.StringVar(value="All")
        self.filter_combo = ttk.Combobox(toolbar, textvariable=self.filter_var, values=["All", "Covered Only", "Pending Only"], state="readonly", width=14, font=("Segoe UI", 9))
        self.filter_combo.pack(side="left", padx=(0, 14))
        self.filter_combo.bind("<<ComboboxSelected>>", lambda e: self._render_tree())

        # Expand / Collapse buttons
        ttk.Button(toolbar, text="➕ Expand All", style="SecSmall.TButton", command=self.expand_all).pack(side="left", padx=2)
        ttk.Button(toolbar, text="➖ Collapse All", style="SecSmall.TButton", command=self.collapse_all).pack(side="left", padx=2)

        # Export to Excel button
        ttk.Button(toolbar, text="📥 Export Report to Excel (.xlsx)", style="SecSmall.TButton", command=self.export_excel).pack(side="right")

        # 4. Hierarchical Drill-Down Treeview
        tree_frame = ttk.Frame(self, style="Coverage.TFrame", padding=(20, 0, 20, 8))
        tree_frame.pack(fill="both", expand=True)

        columns = ("name", "status", "last_record", "last_dor", "extracted", "failed", "source")
        self.tree = ttk.Treeview(tree_frame, columns=columns, style="Coverage.Treeview", selectmode="browse")

        self.tree.heading("#0", text="State / District Code", anchor="w")
        self.tree.heading("name", text="Location Name", anchor="w")
        self.tree.heading("status", text="Coverage Status", anchor="center")
        self.tree.heading("last_record", text="Last Extracted Udyam Number", anchor="center")
        self.tree.heading("last_dor", text="Last Date Registered (DOR)", anchor="center")
        self.tree.heading("extracted", text="Extracted Count", anchor="e")
        self.tree.heading("failed", text="Failed Count", anchor="e")
        self.tree.heading("source", text="Data Source", anchor="center")

        self.tree.column("#0", width=170, minwidth=140)
        self.tree.column("name", width=220, minwidth=160)
        self.tree.column("status", width=110, minwidth=90, anchor="center")
        self.tree.column("last_record", width=200, minwidth=160, anchor="center")
        self.tree.column("last_dor", width=140, minwidth=110, anchor="center")
        self.tree.column("extracted", width=110, minwidth=90, anchor="e")
        self.tree.column("failed", width=95, minwidth=80, anchor="e")
        self.tree.column("source", width=130, minwidth=100, anchor="center")

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # 5. Bottom Selected District Action Card
        bottom_card = ttk.Frame(self, style="CoverageCard.TFrame", padding=12)
        bottom_card.pack(fill="x", padx=20, pady=(0, 14))

        self.selected_info_lbl = ttk.Label(
            bottom_card,
            text="👉 Click any district row in the tree above to view statistics or trigger an incremental extraction.",
            font=("Segoe UI", 9, "bold"),
            style="Card.TLabel"
        )
        self.selected_info_lbl.pack(side="left", fill="x", expand=True)

        self.copy_btn = ttk.Button(bottom_card, text="📋 Copy Last #", style="SecSmall.TButton", state="disabled", command=self.copy_last_number)
        self.copy_btn.pack(side="right", padx=4)

        self.populate_btn = ttk.Button(bottom_card, text="📋 Transfer to Input Box", style="SecSmall.TButton", state="disabled", command=self.transfer_to_main_input)
        self.populate_btn.pack(side="right", padx=4)

        self.run_btn = ttk.Button(bottom_card, text="🚀 Run Incremental for District", style="GreenSmall.TButton", state="disabled", command=self.run_incremental_for_selected)
        self.run_btn.pack(side="right", padx=4)

    # =========================================================================
    # DATA FETCHING & RENDERING
    # =========================================================================

    def refresh_data(self, show_loading: bool = True):
        """Fetches latest metrics from Google Sheet in a daemon thread."""
        if show_loading:
            self.source_badge.config(text="🔄 FETCHING GSHEET...", bg="#313244", fg="#f9e2af")
            self.sync_meta_lbl.config(text="Querying Google Sheet [UDAYAM extract]...")

        def _worker():
            try:
                data = fetch_gsheet_statistics(gsheet_url=self.gsheet_url, merge_local=True)
                self.after(0, lambda: self._on_data_loaded(data))
            except Exception as e:
                self.after(0, lambda: self._on_data_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_data_loaded(self, data: dict):
        self.stats_data = data
        summary = data.get("summary", {})

        tot_states = summary.get("total_states", 0)
        cov_states = summary.get("states_covered", 0)
        tot_dist = summary.get("total_districts", 0)
        cov_dist = summary.get("districts_covered", 0)
        tot_ext = summary.get("total_extracted", 0)
        tot_fail = summary.get("total_failed", 0)
        source = summary.get("source", "Live Google Sheet")
        time_str = summary.get("last_sync_time", "")

        self.kpi_states_lbl.config(text=f"{cov_states:,} / {tot_states:,} ({summary.get('coverage_pct', 0)}%)")
        self.kpi_districts_lbl.config(text=f"{cov_dist:,} / {tot_dist:,}")
        self.kpi_extracted_lbl.config(text=f"{tot_ext:,}")
        self.kpi_failed_lbl.config(text=f"{tot_fail:,}")

        if "Live" in source:
            self.source_badge.config(text="🟢 LIVE GSHEET", bg="#313244", fg="#a6e3a1")
        else:
            self.source_badge.config(text="🟡 CACHED GSHEET", bg="#313244", fg="#f9e2af")

        self.sync_meta_lbl.config(text=f"Source: {source} • Last Synced: {time_str} • Auto-merged with local archives")

        self._render_tree()

    def _on_data_error(self, err_msg: str):
        if self.stats_data and self.stats_data.get("states"):
            self.source_badge.config(text="⚠️ OFFLINE MODE", bg="#313244", fg="#fab387")
            self.sync_meta_lbl.config(text=f"Live Google Sheet sync timed out. Displaying local cached data.")
        else:
            self.source_badge.config(text="⚠️ SYNC ERROR", bg="#f38ba8", fg="#11111b")
            self.sync_meta_lbl.config(text=f"Error connecting to Google Sheet: {err_msg}")
            messagebox.showerror("Sync Error", f"Failed to fetch live statistics from Google Sheet:\n{err_msg}")

    def _render_tree(self):
        """Builds or filters the hierarchical Treeview items."""
        self.tree.delete(*self.tree.get_children())

        search_query = self.search_entry.get().strip().lower()
        filter_mode = self.filter_var.get()

        states = self.stats_data.get("states", {})

        for code, s in sorted(states.items()):
            state_name = s.get("name", code)
            st_cov = s.get("districts_covered", 0)
            st_tot = s.get("districts_total", 0)
            st_status = s.get("status", "Pending")

            # District filtering
            matching_districts = []
            for d in s.get("districts", []):
                d_code = d.get("district_code", "").lower()
                d_name = d.get("district_name", "").lower()
                is_cov = d.get("is_covered", False)

                # Filter by status
                if filter_mode == "Covered Only" and not is_cov:
                    continue
                if filter_mode == "Pending Only" and is_cov:
                    continue

                # Filter by search query
                if search_query:
                    if search_query not in d_code and search_query not in d_name and search_query not in code.lower() and search_query not in state_name.lower():
                        continue

                matching_districts.append(d)

            # If search query given and neither state nor any district matched, skip state
            if search_query and not matching_districts:
                if search_query not in code.lower() and search_query not in state_name.lower():
                    continue

            # State status label
            status_display = f"{st_status} ({st_cov}/{st_tot})"

            # Insert State Parent Node
            state_id = self.tree.insert(
                "",
                "end",
                text=f"▶ [{code}] {state_name}",
                values=(
                    state_name,
                    status_display,
                    s.get("districts", [{}])[0].get("last_record", "") if st_cov > 0 else "N/A",
                    s.get("latest_dor", "N/A"),
                    f"{s.get('total_extracted', 0):,}",
                    f"{s.get('total_failed', 0):,}",
                    "State Aggregate"
                ),
                open=bool(search_query or (filter_mode == "Covered Only" and st_cov > 0))
            )

            # Insert District Child Nodes
            for d in matching_districts:
                d_code = d.get("district_code", "")
                d_name = d.get("district_name", "")
                d_cov = d.get("is_covered", False)
                status_text = "Covered" if d_cov else "Pending"

                self.tree.insert(
                    state_id,
                    "end",
                    text=f"    {d_code}",
                    values=(
                        d_name,
                        status_text,
                        d.get("last_record") or "(No records yet)",
                        d.get("last_dor") or "N/A",
                        f"{d.get('extracted', 0):,}",
                        f"{d.get('failed', 0):,}",
                        d.get("source", "GSheet")
                    ),
                    tags=(d_code,)
                )

    def expand_all(self):
        for item in self.tree.get_children():
            self.tree.item(item, open=True)

    def collapse_all(self):
        for item in self.tree.get_children():
            self.tree.item(item, open=False)

    def _on_tree_select(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return

        item = selected[0]
        parent = self.tree.parent(item)

        # Check if selected item is a district (has a parent)
        if parent:
            text = self.tree.item(item, "text").strip()
            vals = self.tree.item(item, "values")
            dist_code = text.replace("UDYAM-", "")

            self.selected_district_code = dist_code
            self.selected_district_info = {
                "district_code": dist_code,
                "district_name": vals[0] if len(vals) > 0 else "",
                "status": vals[1] if len(vals) > 1 else "",
                "last_record": vals[2] if len(vals) > 2 else "",
                "last_dor": vals[3] if len(vals) > 3 else "",
                "extracted": vals[4] if len(vals) > 4 else "0",
                "failed": vals[5] if len(vals) > 5 else "0",
            }

            self.selected_info_lbl.config(
                text=f"📍 Selected: {dist_code} ({vals[0]}) • Last Record: {vals[2]} • DOR: {vals[3]} • Extracted: {vals[4]}",
                foreground="#89b4fa"
            )
            self.run_btn.config(state="normal")
            self.populate_btn.config(state="normal")
            self.copy_btn.config(state="normal")
        else:
            self.selected_district_code = None
            self.selected_district_info = None
            self.selected_info_lbl.config(
                text="ℹ️ State selected. Expand to select an individual district for incremental extraction.",
                foreground="#cdd6f4"
            )
            self.run_btn.config(state="disabled")
            self.populate_btn.config(state="disabled")
            self.copy_btn.config(state="disabled")

    def _on_tree_double_click(self, event=None):
        """Double clicking a district row triggers immediate selection."""
        if self.selected_district_code:
            self.transfer_to_main_input()

    def copy_last_number(self):
        if self.selected_district_info and self.selected_district_info.get("last_record"):
            num = self.selected_district_info["last_record"]
            if num and num != "(No records yet)":
                self.clipboard_clear()
                self.clipboard_append(num)
                messagebox.showinfo("Copied", f"Copied {num} to clipboard!")

    def transfer_to_main_input(self):
        """Transfers the selected district and its incremental sequence to the main window."""
        if not self.selected_district_code:
            return

        dist_code = self.selected_district_code
        if self.on_district_selected:
            self.on_district_selected(dist_code, run_now=False)
            self.destroy()

    def run_incremental_for_selected(self):
        """Transfers the selected district and immediately starts incremental extraction."""
        if not self.selected_district_code:
            return

        dist_code = self.selected_district_code
        if self.on_district_selected:
            self.on_district_selected(dist_code, run_now=True)
            self.destroy()

    def export_excel(self):
        """Exports the full hierarchical coverage dataset to an Excel file."""
        if not self.stats_data:
            messagebox.showinfo("No Data", "No coverage statistics available to export.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Export Coverage Report As",
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx"), ("All Files", "*.*")],
            initialfile=f"fleet_coverage_report_{datetime.now().strftime('%Y%m%d')}.xlsx"
        )
        if not file_path:
            return

        try:
            export_coverage_stats_to_excel(self.stats_data, Path(file_path))
            messagebox.showinfo("Export Successful", f"Coverage statistics successfully exported to:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export Excel report: {e}")
