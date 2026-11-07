"""
Udyam Live Web Extractor & Excel Exporter GUI.
Directly extracts details from the Udyam government portal for a list of Udyam numbers
using Playwright stealth automation, high-speed OCR, and two-stage HTML parsing.

New Features:
1. Re-check Failed Records: Selectively re-scrapes failed Udyam records and updates
   the existing Excel/CSV results file in-place, retaining all successful entries.
2. District Incremental Extraction: Auto-detects the highest Udyam number for any
   district (across archives, results, and sync reports) and runs incremental loads.
"""

import asyncio
import csv
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from client.core.parser import parse_udyam_html
from client.core.scraper import process_udyam_number, abort_unnecessary_resources
from client.core.district_manager import (
    discover_all_districts,
    find_district_last_number,
    generate_district_udyam_numbers,
    get_failed_udyam_numbers_from_file,
    save_or_update_records_file,
    normalize_district_code,
    CSV_FIELDS
)
from extract_list import export_records_to_excel
from scrapling.fetchers import AsyncStealthySession


class UdyamLiveExtractorApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("🏢 FlawlessTech Data | Udyam Extractor & Excel Exporter")
        self.geometry("1020x840")
        self.minsize(920, 720)
        self.configure(bg="#181825")

        self.is_running = False
        self.stop_requested = False
        self.output_file_path = Path("results.xlsx").resolve()

        # Operational Modes
        self.is_recheck_mode = False
        self.is_incremental_mode = False
        self.last_failed_numbers = []

        # Load known districts
        self.all_districts = discover_all_districts()
        self.current_district = "TN-02" if "TN-02" in self.all_districts else (self.all_districts[0] if self.all_districts else "TN-02")

        self._setup_styles()
        self._build_ui()
        self._init_district_data()

    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.style.configure(".", background="#181825", foreground="#cdd6f4")
        self.style.configure("TFrame", background="#181825")
        self.style.configure("Card.TFrame", background="#1e1e2e", relief="flat")
        self.style.configure("TLabel", background="#181825", foreground="#cdd6f4", font=("Segoe UI", 10))
        self.style.configure("Card.TLabel", background="#1e1e2e", foreground="#cdd6f4", font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", background="#181825", foreground="#89b4fa", font=("Segoe UI", 15, "bold"))
        self.style.configure("Subheader.TLabel", background="#1e1e2e", foreground="#89b4fa", font=("Segoe UI", 10, "bold"))
        self.style.configure("MetricVal.TLabel", background="#1e1e2e", foreground="#a6e3a1", font=("Segoe UI", 16, "bold"))
        self.style.configure("MetricLbl.TLabel", background="#1e1e2e", foreground="#9399b2", font=("Segoe UI", 9))
        self.style.configure("Badge.TLabel", background="#313244", foreground="#a6e3a1", font=("Segoe UI", 9, "bold"), padding=4)
        self.style.configure("Muted.TLabel", background="#1e1e2e", foreground="#6c7086", font=("Segoe UI", 8))

        # Buttons
        self.style.configure("Accent.TButton", background="#89b4fa", foreground="#11111b", font=("Segoe UI", 10, "bold"), borderwidth=0, padding=7)
        self.style.map("Accent.TButton", background=[("active", "#b4befe")])

        self.style.configure("Retry.TButton", background="#f9e2af", foreground="#11111b", font=("Segoe UI", 10, "bold"), borderwidth=0, padding=7)
        self.style.map("Retry.TButton", background=[("active", "#fae3b0")])

        self.style.configure("Green.TButton", background="#a6e3a1", foreground="#11111b", font=("Segoe UI", 9, "bold"), borderwidth=0, padding=6)
        self.style.map("Green.TButton", background=[("active", "#94e2d5")])

        self.style.configure("Stop.TButton", background="#f38ba8", foreground="#11111b", font=("Segoe UI", 10, "bold"), borderwidth=0, padding=7)
        self.style.map("Stop.TButton", background=[("active", "#eba0ac")])

        self.style.configure("Secondary.TButton", background="#313244", foreground="#cdd6f4", font=("Segoe UI", 9), borderwidth=0, padding=5)
        self.style.map("Secondary.TButton", background=[("active", "#45475a")])

        self.style.configure("TProgressbar", troughcolor="#313244", background="#89b4fa", thickness=14)

    def _build_ui(self):
        # 1. Header Frame
        header = ttk.Frame(self, padding=(20, 14, 20, 8))
        header.pack(fill="x")

        ttk.Label(header, text="🏢 FlawlessTech Data | Udyam Extractor & Excel Exporter", style="Header.TLabel").pack(side="left")
        self.status_badge = tk.Label(header, text="🌐 READY", bg="#313244", fg="#89b4fa", font=("Segoe UI", 9, "bold"), padx=10, pady=3)
        self.status_badge.pack(side="right")
        ttk.Button(header, text="📊 GSheet Coverage & Statistics", style="Accent.TButton", command=self.open_coverage_dialog).pack(side="right", padx=(0, 10))

        # 2. District Incremental Extraction Card (NEW)
        dist_card = ttk.Frame(self, style="Card.TFrame", padding=(14, 10))
        dist_card.pack(fill="x", padx=20, pady=(0, 10))

        dist_header_row = ttk.Frame(dist_card, style="Card.TFrame")
        dist_header_row.pack(fill="x", pady=(0, 6))

        ttk.Label(dist_header_row, text="🏛 District Incremental Extraction (Resume from Last Udayam Number)", style="Subheader.TLabel").pack(side="left")
        ttk.Label(dist_header_row, text="Auto-detects highest sequence & generates incremental batch", style="Muted.TLabel").pack(side="right")

        # District Controls Row
        dist_ctrl_row = ttk.Frame(dist_card, style="Card.TFrame")
        dist_ctrl_row.pack(fill="x", pady=(2, 6))

        ttk.Label(dist_ctrl_row, text="District:", style="Card.TLabel").pack(side="left")
        self.district_combo = ttk.Combobox(dist_ctrl_row, values=self.all_districts, width=11, font=("Segoe UI", 9))
        self.district_combo.set(self.current_district)
        self.district_combo.pack(side="left", padx=(6, 12))
        self.district_combo.bind("<<ComboboxSelected>>", self._on_district_changed)
        self.district_combo.bind("<KeyRelease>", self._on_district_changed)

        # Last Record Badge
        self.dist_last_lbl = tk.Label(
            dist_ctrl_row,
            text="📌 Last: Detecting...",
            bg="#313244",
            fg="#a6e3a1",
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=2
        )
        self.dist_last_lbl.pack(side="left", padx=(0, 14))

        # Start Number Entry
        ttk.Label(dist_ctrl_row, text="Start #:", style="Card.TLabel").pack(side="left")
        self.dist_start_entry = tk.Entry(dist_ctrl_row, bg="#313244", fg="#cdd6f4", insertbackground="#cdd6f4", relief="flat", font=("Segoe UI", 9), width=10)
        self.dist_start_entry.pack(side="left", padx=(4, 12), ipady=2)
        self.dist_start_entry.bind("<KeyRelease>", self._update_district_target)

        # Batch Count Spinbox
        ttk.Label(dist_ctrl_row, text="Batch Size:", style="Card.TLabel").pack(side="left")
        self.dist_count_spin = tk.Spinbox(dist_ctrl_row, from_=1, to=50000, width=6, bg="#313244", fg="#cdd6f4", relief="flat", font=("Segoe UI", 9))
        self.dist_count_spin.delete(0, tk.END)
        self.dist_count_spin.insert(0, "50")
        self.dist_count_spin.pack(side="left", padx=(4, 12))
        self.dist_count_spin.bind("<KeyRelease>", self._update_district_target)
        self.dist_count_spin.bind("<ButtonRelease-1>", self._update_district_target)

        # Target preview label
        self.dist_target_lbl = ttk.Label(dist_ctrl_row, text="➡ Target: ...", foreground="#89b4fa", font=("Segoe UI", 9, "bold"), style="Card.TLabel")
        self.dist_target_lbl.pack(side="left", padx=4)

        # District Action Buttons Row
        dist_btn_row = ttk.Frame(dist_card, style="Card.TFrame")
        dist_btn_row.pack(fill="x", pady=(4, 0))

        ttk.Button(dist_btn_row, text="📋 Populate into Input Box", style="Secondary.TButton", command=self.load_incremental_to_input).pack(side="left", padx=(0, 6))
        ttk.Button(dist_btn_row, text="🚀 Run Incremental Batch Now", style="Green.TButton", command=self.run_incremental_load).pack(side="left", padx=4)
        ttk.Button(dist_btn_row, text="🔍 Refresh Last #", style="Secondary.TButton", command=self._refresh_district_info).pack(side="left", padx=4)
        ttk.Button(dist_btn_row, text="📊 GSheet Coverage Drill-Down", style="Secondary.TButton", command=self.open_coverage_dialog).pack(side="left", padx=4)

        # 3. Input Card (List of Udyam Numbers)
        input_card = ttk.Frame(self, style="Card.TFrame", padding=14)
        input_card.pack(fill="x", padx=20, pady=(0, 10))

        top_row = ttk.Frame(input_card, style="Card.TFrame")
        top_row.pack(fill="x", pady=(0, 6))

        ttk.Label(top_row, text="Enter Udyam Numbers (Optional if extracting from folder):", font=("Segoe UI", 10, "bold"), style="Card.TLabel").pack(side="left")
        self.count_lbl = ttk.Label(top_row, text="0 Numbers Loaded", foreground="#89b4fa", font=("Segoe UI", 9, "bold"), style="Card.TLabel")
        self.count_lbl.pack(side="right")

        # Text area with scrollbar
        text_frame = ttk.Frame(input_card, style="Card.TFrame")
        text_frame.pack(fill="x")

        self.input_text = tk.Text(
            text_frame,
            bg="#11111b",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            font=("Consolas", 10),
            relief="flat",
            height=6,
            wrap="word"
        )
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.input_text.yview)
        self.input_text.configure(yscrollcommand=scroll.set)

        self.input_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.input_text.bind("<KeyRelease>", self._update_count)

        # Input action buttons
        input_btn_row = ttk.Frame(input_card, style="Card.TFrame")
        input_btn_row.pack(fill="x", pady=(8, 0))

        ttk.Button(input_btn_row, text="📂 Load from File (.txt / .csv)", style="Secondary.TButton", command=self.load_from_file).pack(side="left", padx=(0, 6))
        ttk.Button(input_btn_row, text="🔄 Load Failed Numbers", style="Secondary.TButton", command=self.load_failed_into_input).pack(side="left", padx=4)
        ttk.Button(input_btn_row, text="🧹 Clear", style="Secondary.TButton", command=self.clear_input).pack(side="left", padx=4)
        ttk.Button(input_btn_row, text="📋 Paste Example", style="Secondary.TButton", command=self.paste_example).pack(side="left", padx=4)

        # 4. Settings Card (Web Only Options)
        options_card = ttk.Frame(self, style="Card.TFrame", padding=14)
        options_card.pack(fill="x", padx=20, pady=(0, 10))

        # Output Excel/CSV Destination
        out_row = ttk.Frame(options_card, style="Card.TFrame")
        out_row.pack(fill="x")

        ttk.Label(out_row, text="Output File (.xlsx / .csv):", style="Card.TLabel").pack(side="left")
        self.out_entry = tk.Entry(out_row, bg="#313244", fg="#cdd6f4", insertbackground="#cdd6f4", relief="flat", font=("Segoe UI", 9), width=52)
        self.out_entry.insert(0, str(self.output_file_path))
        self.out_entry.pack(side="left", padx=(8, 8), ipady=2)
        ttk.Button(out_row, text="Save As...", style="Secondary.TButton", command=self.browse_output_file).pack(side="left")

        # Concurrency & Save HTML Toggle
        opt_row2 = ttk.Frame(options_card, style="Card.TFrame")
        opt_row2.pack(fill="x", pady=(10, 0))

        ttk.Label(opt_row2, text="Concurrent Browser Workers:", style="Card.TLabel").pack(side="left")
        self.concurrency_spin = tk.Spinbox(opt_row2, from_=1, to=4, width=4, bg="#313244", fg="#cdd6f4", relief="flat", font=("Segoe UI", 9))
        self.concurrency_spin.delete(0, tk.END)
        self.concurrency_spin.insert(0, "2")
        self.concurrency_spin.pack(side="left", padx=(8, 20))

        self.save_html_var = tk.BooleanVar(value=True)
        cb_save_html = tk.Checkbutton(
            opt_row2,
            text="Save downloaded raw HTML files locally",
            variable=self.save_html_var,
            bg="#1e1e2e",
            fg="#cdd6f4",
            activebackground="#1e1e2e",
            activeforeground="#89b4fa",
            selectcolor="#313244",
            font=("Segoe UI", 9)
        )
        cb_save_html.pack(side="left")

        # 5. Action & Progress Section
        progress_card = ttk.Frame(self, style="Card.TFrame", padding=14)
        progress_card.pack(fill="x", padx=20, pady=(0, 10))

        # Progress bar
        self.progress_bar = ttk.Progressbar(progress_card, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill="x", pady=(0, 8))

        # Control buttons & Progress text
        action_row = ttk.Frame(progress_card, style="Card.TFrame")
        action_row.pack(fill="x")

        self.start_btn = ttk.Button(action_row, text="▶ Start Two-Stage (Web -> Excel)", style="Accent.TButton", command=self.start_extraction)
        self.start_btn.pack(side="left", padx=(0, 6))

        self.recheck_btn = ttk.Button(action_row, text="🔄 Re-check Failed Records", style="Retry.TButton", command=self.recheck_failed_records)
        self.recheck_btn.pack(side="left", padx=4)

        self.parse_only_btn = ttk.Button(action_row, text="⚡ Extract from Local HTMLs", style="Secondary.TButton", command=self.extract_from_local_html_folder)
        self.parse_only_btn.pack(side="left", padx=4)

        self.stop_btn = ttk.Button(action_row, text="⏹ Stop", style="Stop.TButton", state="disabled", command=self.stop_extraction)
        self.stop_btn.pack(side="left", padx=4)

        ttk.Button(action_row, text="🌐 View HTML Report", style="Secondary.TButton", command=self.open_html_viewer).pack(side="right", padx=4)
        ttk.Button(action_row, text="📊 GSheet Stats", style="Secondary.TButton", command=self.open_coverage_dialog).pack(side="right", padx=4)
        ttk.Button(action_row, text="📊 Open Exported File", style="Secondary.TButton", command=self.open_output_file).pack(side="right", padx=4)
        ttk.Button(action_row, text="📁 Open Output Folder", style="Secondary.TButton", command=self.open_output_folder).pack(side="right", padx=4)

        self.progress_lbl = ttk.Label(action_row, text="Waiting to start extraction...", style="Card.TLabel", font=("Segoe UI", 9, "bold"))
        self.progress_lbl.pack(side="left", padx=(14, 0))

        # 6. Live Activity Log View
        log_frame = ttk.Frame(self, padding=(20, 0, 20, 14))
        log_frame.pack(fill="both", expand=True)

        ttk.Label(log_frame, text="LIVE PORTAL & PARSER AUDIT LOG", font=("Segoe UI", 9, "bold"), foreground="#6c7086").pack(anchor="w", pady=(0, 4))

        self.log_text = tk.Text(
            log_frame,
            bg="#11111b",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            font=("Consolas", 9),
            relief="flat",
            wrap="word",
            height=8
        )
        self.log_text.pack(fill="both", expand=True)

    def log(self, msg: str):
        t = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{t}] {msg}\n")
        self.log_text.see(tk.END)

    # =========================================================================
    # DISTRICT INCREMENTAL LOAD METHODS
    # =========================================================================

    def _init_district_data(self):
        """Initializes district combobox and target previews."""
        self._on_district_changed()

    def _on_district_changed(self, event=None):
        """Triggered when district combobox selection changes or text is typed."""
        raw_val = self.district_combo.get().strip()
        if not raw_val:
            return

        clean_dist = normalize_district_code(raw_val)
        self.current_district = clean_dist

        info = find_district_last_number(clean_dist)
        max_num = info["max_number"]
        last_rec = info["last_record"]
        next_start = info["next_start"]

        if max_num > 0:
            self.dist_last_lbl.config(
                text=f"📌 Last: {last_rec} (#{max_num:,})",
                fg="#a6e3a1",
                bg="#313244"
            )
        else:
            self.dist_last_lbl.config(
                text="📌 Last: No prior records (Start at #1)",
                fg="#f9e2af",
                bg="#313244"
            )

        # Update start number entry
        self.dist_start_entry.delete(0, tk.END)
        self.dist_start_entry.insert(0, str(next_start))

        self._update_district_target()

    def _refresh_district_info(self):
        """Re-scans directories for updated district metrics."""
        self._on_district_changed()
        self.log(f"Refreshed district status for {self.current_district}.")

    def _update_district_target(self, event=None):
        """Calculates and previews the ending Udyam sequence number."""
        raw_dist = self.district_combo.get().strip()
        clean_dist = normalize_district_code(raw_dist)

        try:
            start_num = int(self.dist_start_entry.get().strip())
        except ValueError:
            start_num = 1

        try:
            count = int(self.dist_count_spin.get().strip())
        except ValueError:
            count = 50

        end_num = start_num + max(1, count) - 1
        target_id = f"UDYAM-{clean_dist}-{end_num:07d}"
        self.dist_target_lbl.config(text=f"➡ Target: {target_id} ({count:,} records)")

    def load_incremental_to_input(self):
        """Generates the incremental batch of Udyam numbers and loads them into input box."""
        raw_dist = self.district_combo.get().strip()
        clean_dist = normalize_district_code(raw_dist)

        try:
            start_num = int(self.dist_start_entry.get().strip())
        except ValueError:
            start_num = 1

        try:
            count = int(self.dist_count_spin.get().strip())
        except ValueError:
            count = 50

        numbers = generate_district_udyam_numbers(clean_dist, start_num, count)
        text_content = "\n".join(numbers)

        self.input_text.delete("1.0", tk.END)
        self.input_text.insert(tk.END, text_content)
        self._update_count()

        end_num = start_num + count - 1
        self.log(f"[Incremental] Loaded {count} numbers for {clean_dist} (#{start_num:,} -> #{end_num:,}) into input.")

    def run_incremental_load(self):
        """One-click generation and execution of district incremental load."""
        self.load_incremental_to_input()
        self.is_incremental_mode = True
        self.is_recheck_mode = False
        self.log(f"[Incremental] Starting automated incremental extraction for {self.current_district}...")
        self.start_extraction()

    # =========================================================================
    # RE-CHECK FAILED RECORDS METHODS
    # =========================================================================

    def load_failed_into_input(self):
        """Reads failed numbers from results file or prompts file picker, loading into input box."""
        out_file = Path(self.out_entry.get().strip())
        target_file = None

        if out_file.exists():
            target_file = out_file
        else:
            filepath = filedialog.askopenfilename(
                title="Select Results or Failed File to Extract Failed Numbers",
                filetypes=[("Excel & CSV Files", "*.xlsx;*.csv"), ("All Files", "*.*")]
            )
            if filepath:
                target_file = Path(filepath)

        if not target_file or not target_file.exists():
            messagebox.showinfo("File Not Found", "No results file found to inspect for failures.")
            return

        failed_records = get_failed_udyam_numbers_from_file(target_file)
        if not failed_records:
            messagebox.showinfo("No Failures Found", f"No failed records found in {target_file.name}!\nAll records have status 'Success'.")
            return

        failed_numbers = [item[0] for item in failed_records]
        self.input_text.delete("1.0", tk.END)
        self.input_text.insert(tk.END, "\n".join(failed_numbers))
        self._update_count()

        self.log(f"[Re-check] Loaded {len(failed_numbers)} failed record(s) from {target_file.name}.")
        messagebox.showinfo(
            "Failed Records Loaded",
            f"Successfully loaded {len(failed_numbers)} failed number(s) from {target_file.name} into the input box.\n\n"
            f"Click '▶ Start Two-Stage' or '🔄 Re-check Failed Records' to execute."
        )

    def recheck_failed_records(self):
        """
        Scans for failed records, verifies them live against the portal, and updates
        the existing results workbook in-place.
        """
        out_file = Path(self.out_entry.get().strip()).resolve()

        # 1. Gather failed numbers: first check current session, then output file
        failed_candidates = []
        source_desc = ""

        if out_file.exists():
            failed_from_file = get_failed_udyam_numbers_from_file(out_file)
            if failed_from_file:
                failed_candidates = [item[0] for item in failed_from_file]
                source_desc = f"{out_file.name}"

        if not failed_candidates and self.last_failed_numbers:
            failed_candidates = list(self.last_failed_numbers)
            source_desc = "current session"

        if not failed_candidates:
            current_numbers = self._get_numbers()
            if current_numbers:
                failed_candidates = current_numbers
                source_desc = "input box"
            else:
                filepath = filedialog.askopenfilename(
                    title="Select Results File (.xlsx / .csv) with Failed Records",
                    filetypes=[("Excel & CSV Files", "*.xlsx;*.csv"), ("All Files", "*.*")]
                )
                if filepath:
                    out_file = Path(filepath).resolve()
                    self.out_entry.delete(0, tk.END)
                    self.out_entry.insert(0, str(out_file))
                    failed_from_file = get_failed_udyam_numbers_from_file(out_file)
                    if failed_from_file:
                        failed_candidates = [item[0] for item in failed_from_file]
                        source_desc = f"{out_file.name}"

        if not failed_candidates:
            messagebox.showinfo("No Failed Records", "No failed records were found to re-check.\nAll records appear to be successfully extracted.")
            return

        sample_str = "\n".join([f"  • {n}" for n in failed_candidates[:6]])
        if len(failed_candidates) > 6:
            sample_str += f"\n  ... and {len(failed_candidates) - 6} more"

        confirm = messagebox.askyesno(
            "Re-check Failed Records",
            f"Found {len(failed_candidates)} failed record(s) from {source_desc}:\n\n"
            f"{sample_str}\n\n"
            f"Do you want to re-scrape these live from the government portal and update {out_file.name} in-place?",
            icon="question"
        )
        if not confirm:
            return

        # Populate input box
        self.input_text.delete("1.0", tk.END)
        self.input_text.insert(tk.END, "\n".join(failed_candidates))
        self._update_count()

        self.is_recheck_mode = True
        self.is_incremental_mode = False

        self.log(f"==================================================")
        self.log(f"[RE-CHECK] Initiating live re-check for {len(failed_candidates)} failed record(s)...")
        self.log(f"==================================================")

        self.start_extraction(force_fresh=True)

    # =========================================================================
    # CORE INPUT & FILE BROWSER METHODS
    # =========================================================================

    def _get_numbers(self) -> list[str]:
        raw = self.input_text.get("1.0", tk.END)
        tokens = re.split(r"[\s,;]+", raw)
        seen = set()
        valid = []
        for t in tokens:
            cleaned = t.strip().upper()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                valid.append(cleaned)
        return valid

    def _update_count(self, event=None):
        count = len(self._get_numbers())
        self.count_lbl.config(text=f"{count:,} Numbers Loaded")

    def clear_input(self):
        self.input_text.delete("1.0", tk.END)
        self._update_count()

    def paste_example(self):
        example_data = (
            "UDYAM-TN-02-0000001\n"
            "UDYAM-TN-02-0000002\n"
            "UDYAM-TN-02-0000003\n"
            "UDYAM-AS-01-0000001\n"
            "UDYAM-KL-02-0000001\n"
        )
        self.input_text.delete("1.0", tk.END)
        self.input_text.insert(tk.END, example_data)
        self._update_count()

    def load_from_file(self):
        filepath = filedialog.askopenfilename(
            title="Select File with Udyam Numbers",
            filetypes=[("Text & CSV Files", "*.txt;*.csv"), ("All Files", "*.*")]
        )
        if not filepath:
            return

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            self.input_text.delete("1.0", tk.END)
            self.input_text.insert(tk.END, content)
            self._update_count()
            self.log(f"Loaded numbers from file: {Path(filepath).name}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read file: {e}")

    def browse_output_file(self):
        filepath = filedialog.asksaveasfilename(
            title="Save Extracted Data As",
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx"), ("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile="results.xlsx"
        )
        if filepath:
            self.out_entry.delete(0, tk.END)
            self.out_entry.insert(0, filepath)
            self.output_file_path = Path(filepath)

    # =========================================================================
    # EXTRACTION PIPELINE
    # =========================================================================

    def start_extraction(self, force_fresh: bool = False):
        numbers = self._get_numbers()
        if not numbers:
            messagebox.showwarning("No Input", "Please enter or load at least one Udyam registration number.")
            return

        out_file = Path(self.out_entry.get().strip()).resolve()
        html_save_dir = out_file.parent / "downloaded_html"
        save_html = self.save_html_var.get()
        try:
            concurrency = max(1, min(4, int(self.concurrency_spin.get().strip())))
        except ValueError:
            concurrency = 2

        self.is_running = True
        self.stop_requested = False
        self.start_btn.config(state="disabled")
        self.recheck_btn.config(state="disabled")
        self.parse_only_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

        if self.is_recheck_mode:
            self.status_badge.config(text="🔄 RE-CHECKING FAILED", bg="#f9e2af", fg="#11111b")
        elif self.is_incremental_mode:
            self.status_badge.config(text="🚀 INCREMENTAL LOAD", bg="#a6e3a1", fg="#11111b")
        else:
            self.status_badge.config(text="🌐 STAGE 1: WEB SCRAPING", bg="#89b4fa", fg="#11111b")

        self.progress_bar["maximum"] = len(numbers)
        self.progress_bar["value"] = 0

        self.log(f"==================================================")
        self.log(f"STAGE 1: Fetching HTML from web portal for {len(numbers)} numbers ({concurrency} workers)...")
        if force_fresh or self.is_recheck_mode:
            self.log(f"Force fresh web scrape enabled: bypassing local HTML cache for retry.")
        self.log(f"Raw HTMLs will be saved to: {html_save_dir}")
        self.log(f"==================================================")

        threading.Thread(
            target=self._run_two_stage_pipeline,
            args=(numbers, out_file, html_save_dir, concurrency, save_html, force_fresh or self.is_recheck_mode),
            daemon=True
        ).start()

    def stop_extraction(self):
        self.stop_requested = True
        self.log("Stop requested by user. Terminating active operations...")

    def _run_two_stage_pipeline(
        self,
        numbers: list[str],
        out_file: Path,
        html_dir: Path,
        concurrency: int,
        save_html: bool,
        force_fresh: bool = False
    ):
        t0 = time.perf_counter()

        # ==========================================
        # STAGE 1: SCRAPE FROM WEB PORTAL FIRST
        # ==========================================
        web_results = asyncio.run(
            self._async_scrape_web_stage(numbers, html_dir, concurrency, save_html, force_fresh=force_fresh)
        )

        if self.stop_requested:
            self.after(0, lambda: self._on_extraction_stopped("Web scraping stage was stopped by user."))
            return

        success_count = sum(1 for r in web_results if r["status"].startswith("Success"))
        failed_count = len(web_results) - success_count
        self.last_failed_numbers = [r["udyam_number"] for r in web_results if not r["status"].startswith("Success")]

        self.log(f"=== STAGE 1 COMPLETE: {success_count} HTMLs downloaded from web ({failed_count} not found / failed) ===")

        # ==========================================
        # STAGE 2: EXTRACT DETAILS FROM HTML -> FILE
        # ==========================================
        self.after(0, lambda: self._setup_stage2_ui(len(web_results)))
        self._extract_html_to_file_stage(web_results, out_file, html_dir)

        elapsed = round(time.perf_counter() - t0, 1)
        self.after(0, lambda: self._on_extraction_complete(len(web_results), success_count, failed_count, elapsed))

    async def _async_scrape_web_stage(
        self,
        numbers: list[str],
        html_dir: Path,
        concurrency: int,
        save_html: bool,
        force_fresh: bool = False
    ) -> list[dict]:
        total = len(numbers)
        if save_html:
            html_dir.mkdir(parents=True, exist_ok=True)

        results = []
        to_scrape = []

        # 1. Check if HTML is already downloaded locally (unless force_fresh is enabled)
        for num in numbers:
            html_path = html_dir / f"{num}.html"
            if not force_fresh and html_path.exists() and html_path.stat().st_size > 100:
                results.append({
                    "udyam_number": num,
                    "status": "Success",
                    "enterprise_name": "",
                    "html_content": None,
                    "html_path": html_path
                })
                self.log(f"[Stage 1: Web] [Cached] Already downloaded: {num}")
            else:
                to_scrape.append(num)

        cached_count = len(results)
        if cached_count > 0:
            self.log(f"-> Found {cached_count} / {total} records already in {html_dir.name} (skipping web query for them).")

        if not to_scrape:
            self.log(f"All {total} records are already downloaded locally. Proceeding immediately to Stage 2.")
            return results

        self.log(f"-> Fetching remaining {len(to_scrape)} records live from portal ({concurrency} workers)...")

        processed_count = cached_count
        queue = asyncio.Queue()
        for num in to_scrape:
            await queue.put(num)

        res_lock = asyncio.Lock()

        HOME_URL = "https://www.udyamregistration.gov.in/Default.aspx"
        VERIFY_URL = "https://www.udyamregistration.gov.in/Udyam_Verify.aspx"

        async def worker_task(worker_id: int):
            nonlocal processed_count
            async with AsyncStealthySession(headless=True) as session:
                page = await session.context.new_page()
                await page.route("**/*", abort_unnecessary_resources)

                # Pre-navigate to Udyam_Verify.aspx once per worker
                try:
                    await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=4000)
                    await page.goto(VERIFY_URL, wait_until="domcontentloaded", timeout=4000)
                    if "Default.aspx" in page.url:
                        menu_btn = page.locator('a:has-text("Print/Verify")').first
                        await menu_btn.hover()
                        await asyncio.sleep(0.2)
                        async with page.expect_navigation(wait_until="domcontentloaded", timeout=4000):
                            await page.locator('a:has-text("Verify Udyam Registration")').first.click()
                    await page.evaluate("document.querySelectorAll('header, #header, .navbar, #navmenu, .navmenu').forEach(el => el.remove());")
                except Exception as e:
                    logging.warning(f"[W-{worker_id}] Initial worker navigation warning: {e}")

                page_uses = 0

                while not queue.empty() and not self.stop_requested:
                    try:
                        num = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    # Refresh page after 40 records to clear memory leaks
                    if page_uses >= 40:
                        try:
                            await page.close()
                        except Exception:
                            pass
                        page = await session.context.new_page()
                        await page.route("**/*", abort_unnecessary_resources)
                        try:
                            await page.goto(VERIFY_URL, wait_until="domcontentloaded", timeout=4000)
                            await page.evaluate("document.querySelectorAll('header, #header, .navbar, #navmenu, .navmenu').forEach(el => el.remove());")
                        except Exception:
                            pass
                        page_uses = 0

                    t0 = time.perf_counter()
                    status, ent_name, html_content, _, _ = await process_udyam_number(page, num)
                    elapsed = round(time.perf_counter() - t0, 2)
                    page_uses += 1

                    html_file_path = None
                    if status.startswith("Success") and html_content:
                        if save_html:
                            html_file_path = html_dir / f"{num}.html"
                            try:
                                with open(html_file_path, "w", encoding="utf-8") as f:
                                    f.write(html_content)
                            except Exception as e:
                                logging.error(f"Error saving HTML for {num}: {e}")

                    async with res_lock:
                        processed_count += 1
                        results.append({
                            "udyam_number": num,
                            "status": status,
                            "enterprise_name": ent_name,
                            "html_content": html_content if html_content else None,
                            "html_path": html_file_path
                        })

                        if status.startswith("Success"):
                            self.log(f"[Stage 1: Web] [{processed_count}/{total}] [W-{worker_id}] Downloaded ({elapsed}s): {num} -> {ent_name or 'Found'}")
                        else:
                            self.log(f"[Stage 1: Web] [{processed_count}/{total}] [W-{worker_id}] {status} ({elapsed}s): {num}")

                        self.after(0, lambda c=processed_count: self._update_progress_ui(c, total, stage="Stage 1/2: Web Scraping"))

                    queue.task_done()

        workers = [asyncio.create_task(worker_task(i + 1)) for i in range(concurrency)]
        await asyncio.gather(*workers)
        return results

    def _setup_stage2_ui(self, total: int):
        self.status_badge.config(text="⚡ STAGE 2: PARSING HTML", bg="#f9e2af", fg="#11111b")
        self.progress_bar["maximum"] = total
        self.progress_bar["value"] = 0
        self.progress_lbl.config(text=f"Stage 2/2: Parsing HTML -> File (0 / {total})...")
        self.log(f"==================================================")
        self.log(f"STAGE 2: Parsing HTML documents and structuring 28+ fields...")
        self.log(f"==================================================")

    def _extract_html_to_file_stage(self, results: list[dict], out_file: Path, html_dir: Path):
        total = len(results)
        parsed_records = []

        for idx, item in enumerate(results, start=1):
            if self.stop_requested:
                break

            num = item["udyam_number"]
            status = item["status"]
            html_content = item.get("html_content")

            # If HTML is not in memory, read from disk
            if not html_content and item.get("html_path") and Path(item["html_path"]).exists():
                try:
                    with open(item["html_path"], "r", encoding="utf-8", errors="replace") as hf:
                        html_content = hf.read()
                except Exception:
                    pass
            elif not html_content:
                potential_path = html_dir / f"{num}.html"
                if potential_path.exists():
                    try:
                        with open(potential_path, "r", encoding="utf-8", errors="replace") as hf:
                            html_content = hf.read()
                    except Exception:
                        pass

            if status.startswith("Success") and html_content:
                rec = parse_udyam_html(html_content)
                rec["Udyam Number"] = num
                rec["Status"] = "Success"
                parsed_records.append(rec)
                name = rec.get("Enterprise Name", item.get("enterprise_name") or "N/A")
                ent_type = rec.get("Enterprise Type", "N/A")
                city = rec.get("City", "N/A")
                self.log(f"[Stage 2: Parse] [{idx}/{total}] Extracted: {num} -> {name} | {ent_type} | {city}")
            else:
                fail_rec = {f: "" for f in CSV_FIELDS}
                fail_rec["Udyam Number"] = num
                fail_rec["Enterprise Name"] = status
                fail_rec["Status"] = status
                parsed_records.append(fail_rec)
                self.log(f"[Stage 2: Parse] [{idx}/{total}] Recorded Status: {num} -> {status}")

            self.after(0, lambda c=idx: self._update_progress_ui(c, total, stage="Stage 2/2: HTML -> File"))

        out_file.parent.mkdir(parents=True, exist_ok=True)

        # Decide whether to update in-place (re-check or incremental) or overwrite
        update_in_place = (self.is_recheck_mode or self.is_incremental_mode) and out_file.exists()

        if update_in_place:
            self.log(f"Merging and updating records in existing file: {out_file.name}...")
            updated_count, appended_count = save_or_update_records_file(out_file, parsed_records, update_in_place=True)
            self.log(f"Merged successfully: {updated_count} updated in-place, {appended_count} newly appended.")
        else:
            self.log(f"Writing {len(parsed_records)} records to {out_file.name}...")
            save_or_update_records_file(out_file, parsed_records, update_in_place=False)

        self.log(f"Saved dataset to {out_file.resolve()}")

    def extract_from_local_html_folder(self):
        """Allows extracting directly to Excel/CSV from downloaded .html files (local folder)."""
        default_dir = str(Path("downloaded_html").resolve()) if Path("downloaded_html").exists() else str(Path(".").resolve())
        folder = filedialog.askdirectory(title="Select Folder Containing Downloaded .html Files", initialdir=default_dir)
        if not folder:
            return

        folder_path = Path(folder)
        input_numbers = self._get_numbers()
        results = []

        if input_numbers:
            self.log(f"Using {len(input_numbers)} numbers from input box to preserve order...")
            for num in input_numbers:
                hf = folder_path / f"{num}.html"
                if hf.exists() and hf.stat().st_size > 100:
                    results.append({
                        "udyam_number": num,
                        "status": "Success",
                        "html_content": None,
                        "html_path": hf
                    })
                else:
                    results.append({
                        "udyam_number": num,
                        "status": "Not Found / Missing HTML",
                        "html_content": None,
                        "html_path": None
                    })
        else:
            html_files = sorted(list(folder_path.glob("*.html")))
            if not html_files:
                messagebox.showinfo("No HTML Files", f"No .html files found in {folder}")
                return
            for hf in html_files:
                results.append({
                    "udyam_number": hf.stem,
                    "status": "Success",
                    "html_content": None,
                    "html_path": hf
                })

        out_file = Path(self.out_entry.get().strip())
        self.is_running = True
        self.stop_requested = False
        self.start_btn.config(state="disabled")
        self.recheck_btn.config(state="disabled")
        self.parse_only_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_badge.config(text="⚡ PARSING LOCAL HTML", bg="#f9e2af", fg="#11111b")

        self.log(f"Starting standalone extraction for {len(results)} records from {folder_path.name}...")

        def _worker():
            t0 = time.perf_counter()
            self._setup_stage2_ui(len(results))
            self._extract_html_to_file_stage(results, out_file, folder_path)
            elapsed = round(time.perf_counter() - t0, 1)
            success_count = sum(1 for r in results if r["status"].startswith("Success"))
            failed_count = len(results) - success_count
            self.after(0, lambda: self._on_extraction_complete(len(results), success_count, failed_count, elapsed))

        threading.Thread(target=_worker, daemon=True).start()

    def _update_progress_ui(self, current: int, total: int, stage: str = "Processing"):
        self.progress_bar["value"] = current
        pct = (current / total) * 100 if total > 0 else 0
        self.progress_lbl.config(text=f"{stage}: {current} / {total} ({pct:.1f}%)")

    def _on_extraction_stopped(self, reason: str):
        self.status_badge.config(text="⏹ STOPPED", bg="#f38ba8", fg="#11111b")
        self.start_btn.config(state="normal")
        self.recheck_btn.config(state="normal")
        self.parse_only_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.progress_lbl.config(text=f"Extraction stopped: {reason}")
        self.log(f"Extraction stopped: {reason}")
        self.is_recheck_mode = False
        self.is_incremental_mode = False

    def _on_extraction_complete(self, total: int, success: int, failed: int, elapsed: float):
        out_file = Path(self.out_entry.get().strip()).resolve()
        self.status_badge.config(text="🟢 COMPLETED", bg="#a6e3a1", fg="#11111b")
        self.start_btn.config(state="normal")
        self.recheck_btn.config(state="normal")
        self.parse_only_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.progress_lbl.config(text=f"Done! Extracted: {success}/{total} to {out_file.name} ({elapsed}s)")
        self.log(f"Extraction finished in {elapsed}s | Success: {success} | Failed/Not Found: {failed}")

        # Auto-generate HTML viewer if output is .xlsx
        if out_file.suffix.lower() == ".xlsx" and out_file.exists():
            try:
                from xlsx_to_html import convert_xlsx_to_html
                html_path = out_file.with_suffix(".html")
                convert_xlsx_to_html(out_file, html_path)
                self.log(f"Generated interactive HTML report: {html_path.name}")
            except Exception as e:
                self.log(f"HTML conversion note: {e}")

        # Update district cache if incremental run
        if self.is_incremental_mode:
            self._on_district_changed()

        mode_desc = ""
        if self.is_recheck_mode:
            mode_desc = "\n\n🔄 Re-check Mode: Succeeded records were updated in-place in the output file."
        elif self.is_incremental_mode:
            mode_desc = f"\n\n🚀 Incremental Mode: Batch for {self.current_district} appended to {out_file.name}."

        tip_desc = ""
        if failed > 0:
            tip_desc = f"\n\n💡 Tip: Click '🔄 Re-check Failed Records' anytime to retry the {failed} failed record(s)."

        messagebox.showinfo(
            "Extraction Complete",
            f"Successfully finished extraction!\n\n"
            f"- Output File: {out_file}\n"
            f"- HTML Viewer: {out_file.with_suffix('.html')}\n"
            f"- Total Processed: {total}\n"
            f"- Successful: {success}\n"
            f"- Failed / Missing: {failed}\n"
            f"- Total Time Taken: {elapsed} seconds"
            f"{mode_desc}"
            f"{tip_desc}"
        )

        self.is_recheck_mode = False
        self.is_incremental_mode = False

    def open_coverage_dialog(self):
        """Opens the hierarchical fleet coverage statistics and GSheet drill-down viewer."""
        from client.gui.coverage_dialog import UdyamCoverageStatsDialog
        UdyamCoverageStatsDialog(self, on_district_selected=self._on_coverage_district_selected)

    def _on_coverage_district_selected(self, district_code: str, run_now: bool = False):
        """Callback when a district is selected from the GSheet coverage drill-down."""
        clean_dist = normalize_district_code(district_code)
        self.district_combo.set(clean_dist)
        self._on_district_changed()
        self.log(f"[GSheet Drill-Down] Selected district: {clean_dist}")

        if run_now:
            self.run_incremental_load()
        else:
            self.load_incremental_to_input()

    def open_output_file(self):
        path = Path(self.out_entry.get().strip()).resolve()
        if path.exists():
            os.startfile(str(path))
        else:
            messagebox.showinfo("File Not Found", f"The output file does not exist yet: {path}")

    def open_html_viewer(self):
        out_file = Path(self.out_entry.get().strip()).resolve()
        html_file = out_file.with_suffix(".html")
        if not html_file.exists() and out_file.exists() and out_file.suffix.lower() == ".xlsx":
            try:
                from xlsx_to_html import convert_xlsx_to_html
                convert_xlsx_to_html(out_file, html_file)
            except Exception as e:
                messagebox.showerror("Error", f"Could not convert Excel to HTML: {e}")
                return
        if html_file.exists():
            import webbrowser
            webbrowser.open(html_file.as_uri())
        else:
            messagebox.showinfo("File Not Found", f"No HTML viewer or Excel file found at: {html_file}")

    def open_output_folder(self):
        path = Path(self.out_entry.get().strip()).parent.resolve()
        if path.exists():
            os.startfile(str(path))


def launch_live_extractor_gui():
    app = UdyamLiveExtractorApp()
    app.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1 and any(arg in sys.argv for arg in ["--cli", "--input", "-i", "--numbers", "-n", "--parse-only", "--help", "-h"]):
        from extract_list import main as cli_main
        cli_main()
    else:
        launch_live_extractor_gui()
