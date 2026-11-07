"""
Modern Desktop Dashboard for Udyam Distributed Scraper Worker.
Built with Tkinter (zero external GUI dependencies for 100% portable packaging).
Dark Theme: Catppuccin / Modern Slate aesthetic.
"""

import asyncio
import os
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from client.core.coordinator import CentralCoordinator, get_default_machine_name
from client.core.scraper import execute_district_extraction
from client.core.archiver import compress_and_upload_district


class UdyamDashboard(tk.Tk):
    def __init__(self, web_app_url: str = None):
        super().__init__()

        self.title("⚡ FlawlessTech Data | Udyam Fleet Worker")
        self.geometry("860x680")
        self.minsize(780, 600)
        self.configure(bg="#181825")

        self.web_app_url = web_app_url or os.getenv("GOOGLE_APPS_SCRIPT_URL", "")
        self.machine_name = os.getenv("WORKER_MACHINE_NAME") or get_default_machine_name()

        self.coordinator = CentralCoordinator(self.web_app_url, self.machine_name)
        self.is_running = False
        self.stop_event = asyncio.Event()

        self.total_success_session = 0
        self.total_failed_session = 0
        self.current_speed = 0.0

        self.loop = None
        self.worker_thread = None

        self._setup_styles()
        self._build_ui()

    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # Configure dark aesthetic
        self.style.configure(".", background="#181825", foreground="#cdd6f4")
        self.style.configure("TFrame", background="#181825")
        self.style.configure("Card.TFrame", background="#1e1e2e", relief="flat")
        self.style.configure("TLabel", background="#181825", foreground="#cdd6f4", font=("Segoe UI", 10))
        self.style.configure("Card.TLabel", background="#1e1e2e", foreground="#cdd6f4", font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", background="#181825", foreground="#89b4fa", font=("Segoe UI", 15, "bold"))
        self.style.configure("Subheader.TLabel", background="#181825", foreground="#a6adc8", font=("Segoe UI", 10))
        self.style.configure("MetricVal.TLabel", background="#1e1e2e", foreground="#a6e3a1", font=("Segoe UI", 18, "bold"))
        self.style.configure("MetricLbl.TLabel", background="#1e1e2e", foreground="#9399b2", font=("Segoe UI", 9))

        # Buttons
        self.style.configure("Accent.TButton", background="#89b4fa", foreground="#11111b", font=("Segoe UI", 10, "bold"), borderwidth=0, padding=6)
        self.style.map("Accent.TButton", background=[("active", "#b4befe")])

        self.style.configure("Stop.TButton", background="#f38ba8", foreground="#11111b", font=("Segoe UI", 10, "bold"), borderwidth=0, padding=6)
        self.style.map("Stop.TButton", background=[("active", "#eba0ac")])

        self.style.configure("Secondary.TButton", background="#313244", foreground="#cdd6f4", font=("Segoe UI", 9), borderwidth=0, padding=5)
        self.style.map("Secondary.TButton", background=[("active", "#45475a")])

        # Progress bar
        self.style.configure("TProgressbar", troughcolor="#313244", background="#89b4fa", thickness=12)

    def _build_ui(self):
        # 1. Header Frame
        header = ttk.Frame(self, padding=(20, 16, 20, 10))
        header.pack(fill="x")

        title_lbl = ttk.Label(header, text="⚡ FlawlessTech Data | Udyam Fleet Worker", style="Header.TLabel")
        title_lbl.pack(side="left")

        # Connection status badge
        self.status_badge = tk.Label(
            header,
            text="🟢 READY",
            bg="#313244",
            fg="#a6e3a1",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=3
        )
        self.status_badge.pack(side="right")

        # 2. Machine & Server Config Card
        config_frame = ttk.Frame(self, style="Card.TFrame", padding=14)
        config_frame.pack(fill="x", padx=20, pady=(0, 12))

        # Row 1: Machine Name & Preferred State
        r1 = ttk.Frame(config_frame, style="Card.TFrame")
        r1.pack(fill="x")

        ttk.Label(r1, text="Machine Name:", style="Card.TLabel").pack(side="left")
        self.machine_entry = tk.Entry(r1, bg="#313244", fg="#cdd6f4", insertbackground="#cdd6f4", relief="flat", font=("Segoe UI", 10))
        self.machine_entry.insert(0, self.machine_name)
        self.machine_entry.pack(side="left", padx=(8, 20), ipady=2)

        ttk.Label(r1, text="Preferred State / District:", style="Card.TLabel").pack(side="left")
        self.filter_entry = tk.Entry(r1, bg="#313244", fg="#cdd6f4", insertbackground="#cdd6f4", relief="flat", font=("Segoe UI", 10), width=12)
        self.filter_entry.insert(0, "")
        self.filter_entry.pack(side="left", padx=(8, 10), ipady=2)
        ttk.Label(r1, text="(e.g. 'TN' or leave blank for auto)", font=("Segoe UI", 8), foreground="#6c7086", style="Card.TLabel").pack(side="left")

        # Row 2: Central URL
        r2 = ttk.Frame(config_frame, style="Card.TFrame")
        r2.pack(fill="x", pady=(10, 0))

        ttk.Label(r2, text="Central Coordinator URL:", style="Card.TLabel").pack(side="left")
        self.url_entry = tk.Entry(r2, bg="#313244", fg="#cdd6f4", insertbackground="#cdd6f4", relief="flat", font=("Segoe UI", 9), width=58)
        self.url_entry.insert(0, self.web_app_url)
        self.url_entry.pack(side="left", padx=(8, 10), ipady=2)

        # 3. Telemetry Metrics Cards
        metrics_container = ttk.Frame(self, padding=(20, 0, 20, 12))
        metrics_container.pack(fill="x")

        # Card 1: Active District
        c1 = ttk.Frame(metrics_container, style="Card.TFrame", padding=12)
        c1.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ttk.Label(c1, text="CURRENT DISTRICT", style="MetricLbl.TLabel").pack(anchor="w")
        self.dist_lbl = ttk.Label(c1, text="IDLE", style="MetricVal.TLabel")
        self.dist_lbl.pack(anchor="w", pady=(2, 0))

        # Card 2: Extracted Count
        c2 = ttk.Frame(metrics_container, style="Card.TFrame", padding=12)
        c2.pack(side="left", fill="both", expand=True, padx=6)
        ttk.Label(c2, text="RECORDS EXTRACTED", style="MetricLbl.TLabel").pack(anchor="w")
        self.extracted_lbl = ttk.Label(c2, text="0", style="MetricVal.TLabel")
        self.extracted_lbl.pack(anchor="w", pady=(2, 0))

        # Card 3: Speedometer
        c3 = ttk.Frame(metrics_container, style="Card.TFrame", padding=12)
        c3.pack(side="left", fill="both", expand=True, padx=6)
        ttk.Label(c3, text="SPEED (REC / MIN)", style="MetricLbl.TLabel").pack(anchor="w")
        self.speed_lbl = ttk.Label(c3, text="0.0", style="MetricVal.TLabel")
        self.speed_lbl.pack(anchor="w", pady=(2, 0))

        # Card 4: Latest DOR
        c4 = ttk.Frame(metrics_container, style="Card.TFrame", padding=12)
        c4.pack(side="left", fill="both", expand=True, padx=(6, 0))
        ttk.Label(c4, text="LATEST REG. DATE", style="MetricLbl.TLabel").pack(anchor="w")
        self.dor_lbl = ttk.Label(c4, text="N/A", style="MetricVal.TLabel")
        self.dor_lbl.pack(anchor="w", pady=(2, 0))

        # 4. Action & Progress Section
        progress_card = ttk.Frame(self, style="Card.TFrame", padding=14)
        progress_card.pack(fill="x", padx=20, pady=(0, 12))

        p_row = ttk.Frame(progress_card, style="Card.TFrame")
        p_row.pack(fill="x")

        self.curr_record_lbl = ttk.Label(p_row, text="Current Record: Waiting to start...", font=("Segoe UI", 10, "bold"), style="Card.TLabel")
        self.curr_record_lbl.pack(side="left")

        # Action Buttons
        btn_frame = ttk.Frame(progress_card, style="Card.TFrame")
        btn_frame.pack(fill="x", pady=(10, 0))

        self.start_btn = ttk.Button(btn_frame, text="▶ Start Auto-Extract", style="Accent.TButton", command=self.on_start_clicked)
        self.start_btn.pack(side="left", padx=(0, 8))

        self.stop_btn = ttk.Button(btn_frame, text="⏹ Stop", style="Stop.TButton", state="disabled", command=self.on_stop_clicked)
        self.stop_btn.pack(side="left", padx=8)

        ttk.Button(btn_frame, text="📁 Results Folder", style="Secondary.TButton", command=self.open_results_folder).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="📊 Open Sync Report", style="Secondary.TButton", command=self.open_sync_report).pack(side="right", padx=4)

        # 5. Live Activity Log View
        log_frame = ttk.Frame(self, padding=(20, 0, 20, 16))
        log_frame.pack(fill="both", expand=True)

        ttk.Label(log_frame, text="ACTIVITY LOG", font=("Segoe UI", 9, "bold"), foreground="#6c7086").pack(anchor="w", pady=(0, 4))

        self.log_text = tk.Text(
            log_frame,
            bg="#11111b",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            font=("Consolas", 9),
            relief="flat",
            wrap="word",
            height=12
        )
        self.log_text.pack(fill="both", expand=True)

    def log(self, message: str):
        now = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{now}] {message}\n")
        self.log_text.see(tk.END)

    def on_start_clicked(self):
        url = self.url_entry.get().strip()
        machine = self.machine_entry.get().strip() or get_default_machine_name()
        pref = self.filter_entry.get().strip()

        self.coordinator = CentralCoordinator(url, machine)
        self.is_running = True
        self.stop_event.clear()

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_badge.config(text="🚜 SCRAPING", bg="#a6e3a1", fg="#11111b")

        self.log(f"Starting worker engine for machine '{machine}'...")

        self.worker_thread = threading.Thread(target=self._run_async_worker, args=(pref,), daemon=True)
        self.worker_thread.start()

    def on_stop_clicked(self):
        self.log("Stopping extraction at next boundary...")
        self.stop_event.set()
        self.is_running = False
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_badge.config(text="🟡 STOPPING", bg="#f9e2af", fg="#11111b")

    def _run_async_worker(self, preferred_filter: str):
        asyncio.run(self._worker_main(preferred_filter))

    async def _worker_main(self, preferred_filter: str):
        while not self.stop_event.is_set():
            pref_state = preferred_filter if len(preferred_filter) == 2 else None
            pref_dist = preferred_filter if "-" in preferred_filter else None

            self.log("Claiming next task from Google Sheet...")
            claim_res = await self.coordinator.claim_task(preferred_state=pref_state, preferred_district=pref_dist)

            if not claim_res.get("success"):
                self.log(f"[!] {claim_res.get('message', 'No tasks available.')}")
                if not self.coordinator.web_app_url:
                    self.log("Standalone mode: Provide a state/district prefix in filter to run without Google Sheet.")
                    break
                await asyncio.sleep(10)
                continue

            dist_code = claim_res.get("district_code")
            start_num = claim_res.get("start_num", 1)
            limit = claim_res.get("limit", 500000)
            prev_extracted = int(claim_res.get("prev_extracted") or 0)
            last_record = claim_res.get("last_record", "")
            last_dor = claim_res.get("last_dor", "")

            self.after(0, lambda d=dist_code: self.dist_lbl.config(text=d))
            self.log(f"[CLAIMED] District {dist_code} | Resuming at #{start_num} | Prev Extracted: {prev_extracted}")

            # Define heartbeat callback
            async def on_heartbeat(**kwargs):
                rec = kwargs.get("current_record", "")
                dor = kwargs.get("current_dor", "")
                ext = kwargs.get("total_extracted", 0)
                spd = kwargs.get("speed_rpm", 0.0)

                self.after(0, lambda r=rec, d=dor, e=ext, s=spd: self._update_ui_telemetry(r, d, e, s))
                await self.coordinator.send_heartbeat(
                    district_code=dist_code,
                    current_record=rec,
                    current_dor=dor,
                    total_extracted=ext,
                    total_failed=kwargs.get("total_failed", 0),
                    speed_rpm=spd
                )

            # Run scraper
            res = await execute_district_extraction(
                prefix=dist_code,
                start_num=start_num,
                limit=limit,
                heartbeat_callback=on_heartbeat,
                stop_event=self.stop_event,
                initial_success_count=prev_extracted,
                existing_last_record=last_record,
                existing_last_dor=last_dor
            )

            final_record = res.get("last_record") or last_record
            final_dor = res.get("last_dor") or last_dor
            total_extracted = res.get("total_extracted") if res.get("total_extracted") is not None else prev_extracted
            total_failed = res.get("total_failed", 0)

            # Complete task
            self.log(f"District {dist_code} completed. Finalizing in Google Sheet (Total: {total_extracted}, DOR: {final_dor})...")
            await self.coordinator.complete_task(
                district_code=dist_code,
                final_record=final_record,
                final_dor=final_dor,
                total_extracted=total_extracted,
                total_failed=total_failed
            )

            # Auto compress & upload
            self.log(f"Compressing {dist_code} into .7z and uploading to Google Drive...")
            await compress_and_upload_district(dist_code, coordinator=self.coordinator)

            if self.stop_event.is_set():
                break

        self.after(0, self._on_worker_stopped)

    def _update_ui_telemetry(self, current_record: str, dor: str, total_extracted: int, speed: float):
        if current_record:
            self.curr_record_lbl.config(text=f"Current: {current_record}")
        if dor:
            self.dor_lbl.config(text=dor)
        self.extracted_lbl.config(text=f"{total_extracted:,}")
        self.speed_lbl.config(text=f"{speed:.1f}")

    def _on_worker_stopped(self):
        self.status_badge.config(text="🟢 READY", bg="#313244", fg="#a6e3a1")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.log("Worker idle.")

    def open_results_folder(self):
        path = Path("results").resolve()
        path.mkdir(exist_ok=True)
        os.startfile(str(path))

    def open_sync_report(self):
        report = Path("sync_report.csv").resolve()
        if report.exists():
            os.startfile(str(report))
        else:
            messagebox.showinfo("Sync Report", "No sync_report.csv found. Run sync_existing_archives.py first.")


def launch_dashboard(web_app_url: str = None):
    app = UdyamDashboard(web_app_url=web_app_url)
    app.mainloop()


if __name__ == "__main__":
    launch_dashboard()
