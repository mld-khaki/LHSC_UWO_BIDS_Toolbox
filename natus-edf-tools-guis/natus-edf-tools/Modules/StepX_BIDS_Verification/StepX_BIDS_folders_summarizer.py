#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BIDS-like session/run scanner GUI
- Scans a root folder containing sub-### or sub-###-# folders.
- Each subject contains ses-### folders; session data live under ses-###/ieeg/.
- Per subject, a *_scans.tsv lists runs and metadata.
- Produces an Excel with columns:
    subject | session_number | tsv_date | tsv_duration | tsv_run_number | tsv_session_name | folder_size_gb
- Progress bar updates per run; errors are fatal (with a clear message).
Dependencies:
    - pandas
    - openpyxl
"""

import os
import re
import sys
import threading
import queue
import traceback
from glob import glob
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------- Parsing helpers ----------

FILENAME_RE = re.compile(
    r'(?P<ses>ses-(\d+))/.+?/(?P<subject>sub-\d+(?:-\d+)?)_ses-(?P<sesnum>\d+)_task-(?P<task>[^_]+)_run-(?P<run>\d+)_ieeg\..+',
    re.IGNORECASE
)

SUBJECT_DIR_RE = re.compile(r'^sub-\d+(?:-\d+)?$', re.IGNORECASE)
SESSION_DIR_RE = re.compile(r'^ses-(\d+)$', re.IGNORECASE)

REQUIRED_TSV_COLS = ["filename", "acq_time", "duration", "format"]

def human_gb(byte_count: int) -> float:
    gb = Decimal(byte_count) / Decimal(1024 ** 3)
    # 3 decimal places, round-half-up
    return float(gb.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))

def folder_size_bytes(path: str) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                # Treat unreadable files as error per strict policy
                raise
    return total

def parse_row_from_filename(relpath: str):
    """
    Parse fields from the TSV 'filename' column, e.g.:
    ses-026/ieeg/sub-007_ses-026_task-full_run-01_ieeg.edf.gz
    Returns: (subject, session_number, task_name, run_number)
    """
    m = FILENAME_RE.match(relpath)
    if not m:
        raise ValueError(f"Filename does not match expected pattern: {relpath}")
    subject = m.group("subject")
    session_number = m.group("sesnum")  # numeric string
    task = m.group("task")
    run = m.group("run")
    return subject, session_number, task, run

def validate_scans_df(df: pd.DataFrame, tsv_path: str) -> pd.DataFrame:
    """
    Validates and normalizes the columns of a *_scans.tsv file.
    Required: filename, acq_time, duration
    Optional: format (auto-filled as 'n/a' if missing)
    """
    required = ["filename", "acq_time", "duration"]
    optional = ["format"]
    lower_cols = [c.strip().lower() for c in df.columns]
    colmap = {}

    # Validate required
    for need in required:
        if need in lower_cols:
            colmap[need] = df.columns[lower_cols.index(need)]
        else:
            raise ValueError(f"Required column '{need}' missing in {tsv_path}")

    # Handle optional
    for opt in optional:
        if opt in lower_cols:
            colmap[opt] = df.columns[lower_cols.index(opt)]
        else:
            # Add default column with 'n/a'
            df[opt] = "n/a"
            colmap[opt] = opt

    # Return normalized DataFrame with unified column names
    return df.rename(columns={colmap[k]: k for k in colmap})[required + optional]


# ---------- Worker thread ----------

class ScannerWorker(threading.Thread):
    def __init__(self, root_dir, out_path, progress_cb, log_cb, done_cb):
        super().__init__(daemon=True)
        self.root_dir = root_dir
        self.out_path = out_path
        self.progress_cb = progress_cb
        self.log_cb = log_cb
        self.done_cb = done_cb
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            results = self._scan()
            # Write Excel
            df = pd.DataFrame(results, columns=[
                "subject",
                "session_number",
                "tsv_date",
                "tsv_duration",
                "tsv_run_number",
                "tsv_session_name",
                "folder_size_gb",
                "error"
            ])

            # Sort for convenience
            df = df.sort_values(["subject", "session_number", "tsv_run_number"], ignore_index=True)
            # Write with auto sheet
            with pd.ExcelWriter(self.out_path, engine="openpyxl") as xw:
                df.to_excel(xw, sheet_name="sessions", index=False)
            self.done_cb(success=True, message=f"Done. Wrote {len(df)} rows to:\n{self.out_path}")
        except Exception as e:
            tb = traceback.format_exc()
            self.log_cb(tb)
            self.done_cb(success=False, message=str(e))

    def _collect_subjects(self):
        subs = []
        for name in os.listdir(self.root_dir):
            path = os.path.join(self.root_dir, name)
            if os.path.isdir(path) and SUBJECT_DIR_RE.match(name):
                subs.append(path)
        if not subs:
            raise ValueError("No subject folders (sub-### or sub-###-#) found in the selected root.")
        return sorted(subs)

    def _count_total_runs(self, subs):
        total = 0
        for sub_path in subs:
            tsvs = glob(os.path.join(sub_path, "*_scans.tsv"))
            if not tsvs:
                raise ValueError(f"No *_scans.tsv found in {sub_path}")
            if len(tsvs) > 1:
                raise ValueError(f"Multiple *_scans.tsv files found in {sub_path}; expected exactly one.")
            tsv_path = tsvs[0]
            df = pd.read_csv(tsv_path, sep="\t", dtype=str, keep_default_na=False)
            df = validate_scans_df(df, tsv_path)
            # Count only rows that look like ieeg entries
            total += sum("ieeg/" in fn or "/ieeg/" in fn for fn in df["filename"])
        if total == 0:
            raise ValueError("No runs referencing ieeg data were found across all subjects.")
        return total

    def _scan(self):
        subs = self._collect_subjects()
        total_runs = self._count_total_runs(subs)
        self.progress_cb(mode="set_max", value=total_runs)
        self.log_cb(f"Found {len(subs)} subject(s), {total_runs} run(s) to process.")

        results = []
        processed = 0

        # Cache sizes per ieeg folder to avoid recomputing for multiple runs in same session
        ieeg_size_cache = {}

        for sub_path in subs:
            sub_name = os.path.basename(sub_path)

            # Validate session folders exist (not strictly required, but helpful)
            ses_dirs = []
            for n in os.listdir(sub_path):
                p = os.path.join(sub_path, n)
                if os.path.isdir(p) and SESSION_DIR_RE.match(n):
                    ses_dirs.append(p)

            if not ses_dirs:
                # Might still have ieeg references in scans.tsv; don't error here—TSV is the source of truth.
                self.log_cb(f"Warning: No ses-### subfolders in {sub_name}, relying on scans.tsv entries.")

            tsvs = glob(os.path.join(sub_path, "*_scans.tsv"))
            if not tsvs:
                raise ValueError(f"No *_scans.tsv found in {sub_path}")
            if len(tsvs) > 1:
                raise ValueError(f"Multiple *_scans.tsv files found in {sub_path}; expected exactly one.")
            tsv_path = tsvs[0]

            df = pd.read_csv(tsv_path, sep="\t", dtype=str, keep_default_na=False)
            df = validate_scans_df(df, tsv_path)

            # Iterate per row (per run), but only those pointing to ieeg
            for _, row in df.iterrows():
                relfile = row["filename"].strip()
                if "ieeg/" not in relfile and "/ieeg/" not in relfile:
                    continue  # skip non-iEEG rows

                subject, session_number, task_name, run_num = parse_row_from_filename(relfile)
                ses_prefix = relfile.split("/", 1)[0]
                ieeg_dir = os.path.join(sub_path, ses_prefix, "ieeg")

                # Default placeholders
                size_gb = "n/a"
                error_msg = ""

                try:
                    # --- iEEG directory check ---
                    if not os.path.isdir(ieeg_dir):
                        error_msg = f"iEEG directory missing: {ieeg_dir}"
                        raise FileNotFoundError(error_msg)

                    # --- File existence check (with flexible extension) ---
                    absfile = os.path.join(sub_path, relfile)
                    if not os.path.isfile(absfile):
                        base_noext = os.path.splitext(absfile)[0]
                        ieeg_dir = os.path.dirname(absfile)

                        if not os.path.isdir(ieeg_dir):
                            error_msg = f"Missing ieeg folder: {ieeg_dir}"
                            raise FileNotFoundError(error_msg)

                        candidates = [
                            f for f in os.listdir(ieeg_dir)
                            if os.path.splitext(f)[0] == os.path.basename(base_noext)
                        ]

                        if not candidates:
                            error_msg = f"No matching data file found for {relfile}"
                            raise FileNotFoundError(error_msg)

                        preferred = sorted(
                            candidates,
                            key=lambda f: (not f.lower().endswith((".edf", ".edf.gz", ".edf.zst"))),
                        )[0]
                        absfile = os.path.join(ieeg_dir, preferred)
                        self.log_cb(f"Note: used alternate file for {relfile} → {preferred}")

                    # --- Folder size computation ---
                    if ieeg_dir in ieeg_size_cache:
                        size_gb = ieeg_size_cache[ieeg_dir]
                    else:
                        size_bytes = folder_size_bytes(ieeg_dir)
                        size_gb = human_gb(size_bytes)
                        ieeg_size_cache[ieeg_dir] = size_gb

                    # --- Normal success log ---
                    self.log_cb(f"{subject} ses-{session_number} run-{run_num} • size={size_gb:.3f} GB")

                except Exception as e:
                    # Capture and log the error
                    error_msg = str(e)
                    self.log_cb(f"Error: {subject} ses-{session_number} run-{run_num} → {error_msg}")

                # --- Append row regardless of outcome ---
                results.append([
                    subject,
                    session_number,
                    row["acq_time"].strip(),
                    row["duration"].strip(),
                    run_num,
                    task_name,
                    size_gb,
                    error_msg,
                ])

                processed += 1
                self.progress_cb(mode="step", value=processed)


        return results

# ---------- GUI ----------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Session & Run Scanner → Excel")
        self.geometry("800x520")
        self.minsize(760, 520)

        self.root_dir = tk.StringVar()
        self.out_path = tk.StringVar()

        self._build_ui()

        self.worker = None

    def _build_ui(self):
        pad = {"padx": 10, "pady": 10}

        frm_top = ttk.Frame(self)
        frm_top.pack(fill="x", **pad)

        # Root folder
        ttk.Label(frm_top, text="Root folder (contains sub-###):").grid(row=0, column=0, sticky="w")
        e_root = ttk.Entry(frm_top, textvariable=self.root_dir)
        e_root.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        btn_root = ttk.Button(frm_top, text="Browse…", command=self.choose_root)
        btn_root.grid(row=1, column=1, sticky="e")
        frm_top.columnconfigure(0, weight=1)

        # Output file
        ttk.Label(frm_top, text="Excel output (.xlsx):").grid(row=2, column=0, sticky="w", pady=(16, 0))
        e_out = ttk.Entry(frm_top, textvariable=self.out_path)
        e_out.grid(row=3, column=0, sticky="ew", padx=(0, 8))
        btn_out = ttk.Button(frm_top, text="Save as…", command=self.choose_out)
        btn_out.grid(row=3, column=1, sticky="e")

        # Progress
        frm_prog = ttk.Frame(self)
        frm_prog.pack(fill="x", **pad)

        self.pb = ttk.Progressbar(frm_prog, orient="horizontal", mode="determinate", maximum=100, value=0)
        self.pb.pack(fill="x")
        self.lbl_status = ttk.Label(frm_prog, text="Idle")
        self.lbl_status.pack(anchor="w", pady=(6, 0))

        # Buttons
        frm_btns = ttk.Frame(self)
        frm_btns.pack(fill="x", **pad)
        self.btn_start = ttk.Button(frm_btns, text="Start", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_cancel = ttk.Button(frm_btns, text="Cancel", command=self.cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=(8, 0))

        # Log box
        frm_log = ttk.LabelFrame(self, text="Log")
        frm_log.pack(fill="both", expand=True, **pad)
        self.txt_log = tk.Text(frm_log, height=16, wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)

    def choose_root(self):
        path = filedialog.askdirectory(title="Select root folder")
        if path:
            self.root_dir.set(path)

    def choose_out(self):
        suggested = f"session_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        path = filedialog.asksaveasfilename(
            title="Save Excel file",
            defaultextension=".xlsx",
            initialfile=suggested,
            filetypes=[("Excel Workbook", "*.xlsx")]
        )
        if path:
            self.out_path.set(path)

    def _validate_inputs(self):
        root_dir = self.root_dir.get().strip()
        out_path = self.out_path.get().strip()

        if not root_dir:
            raise ValueError("Please select a root folder.")
        if not os.path.isdir(root_dir):
            raise ValueError(f"Root folder does not exist or is not a directory:\n{root_dir}")

        if not out_path:
            raise ValueError("Please choose an Excel output file.")
        out_dir = os.path.dirname(out_path) or "."
        if not os.path.isdir(out_dir):
            raise ValueError(f"Output directory does not exist:\n{out_dir}")

        return root_dir, out_path

    # Thread-safe queue for GUI updates
    def _post_log(self, msg: str):
        self.txt_log.insert("end", msg.rstrip() + "\n")
        self.txt_log.see("end")
        self.update_idletasks()

    def _progress_cb(self, mode: str, value: int):
        if mode == "set_max":
            self.pb["maximum"] = max(1, value)
            self.pb["value"] = 0
            self.lbl_status.config(text=f"Runs to process: {value}")
        elif mode == "step":
            self.pb["value"] = value
            self.lbl_status.config(text=f"Processed {int(value)}/{int(self.pb['maximum'])} runs")
        self.update_idletasks()

    def _log_cb(self, line: str):
        self._post_log(line)

    def _done_cb(self, success: bool, message: str):
        self.btn_start.config(state="normal")
        self.btn_cancel.config(state="disabled")
        if success:
            self._post_log(message)
            self.lbl_status.config(text="Completed")
            messagebox.showinfo("Success", message)
        else:
            self.lbl_status.config(text="Failed")
            messagebox.showerror("Error", message)

    def start(self):
        try:
            root_dir, out_path = self._validate_inputs()
        except Exception as e:
            messagebox.showerror("Input Error", str(e))
            return

        # Reset UI
        self.txt_log.delete("1.0", "end")
        self.pb["value"] = 0
        self.lbl_status.config(text="Starting…")
        self.btn_start.config(state="disabled")
        self.btn_cancel.config(state="normal")

        # Launch worker
        self.worker = ScannerWorker(
            root_dir=root_dir,
            out_path=out_path,
            progress_cb=self._progress_cb,
            log_cb=self._log_cb,
            done_cb=self._done_cb
        )
        self.worker.start()

    def cancel(self):
        if self.worker and self.worker.is_alive():
            # We can't safely kill the thread; we just inform the user and disable to avoid double-clicks.
            messagebox.showinfo("Cancel", "Cancelling is not supported mid-scan. Please close the app if needed.")
        self.btn_cancel.config(state="disabled")

def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
