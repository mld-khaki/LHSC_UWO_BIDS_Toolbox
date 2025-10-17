#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    Natus Session Finder GUI Version 1.2

    Author: Dr. Milad Khaki 

    Latest update: 2025/10/17
------------------------

What’s new in Version 1.2

* Coverage checker improvements
    - Now computes **unique per-day coverage** as the union of intervals (not the sum).
    - First and last days are no longer flagged for <23 h coverage.
    - Added detection and tagging for:
        = **Multiple sessions per day**
        = **Overlapping sessions** (time overlap)
        = **Below-threshold coverage** (< 23 h in middle days)
    - Inline detailed report includes:
        = Folder, RecStart, RecEnd, EegNo, StudyName (times clipped per day)
        = [OVERLAP] marker where sessions overlap
    - Added faint overlay for per-day union coverage visualization.

* Gantt chart visualization
    - New **“Show Coverage (Selected)”** button generates both:
        = The per-day textual report
        = A Gantt-style chart of selected sessions
    - Sessions spanning multiple days are clipped appropriately.
    - Bars grouped **by date**, with click tooltips showing Folder, Start, End, EegNo, StudyName.
    - Save dialog prompts for base name and exports both:
        = `<basename>_gantt.png` (chart)
        = `<basename>_gantt.tsv` (clipped intervals, with overlap/multiple/below-threshold flags)

* INI-based configuration extended
    - Added `[gantt]` section:
        = gantt_show_grid = true
        = gantt_tick_hours = 1
        = coverage_show_details = inline
        = gantt_dpi = 150
        = gantt_width = 1200
        = gantt_height = 700
    - [checker] keeps threshold_hours = 23.
    - Coverage and Gantt behaviors now respect these settings.

* Additional updates
    - Report sections now include “Details for days with multiple sessions” inline.
    - Improved log output with overlap and coverage summaries.
    - Duration, sorting, and INI-based column visibility retained from Version 1.1.
    - Minor UI and performance optimizations for refresh and re-check cycles.


What’s new in Version 1.1

* Sorting & columns
    - Type-aware sorting for:
        = RecStart / RecEnd as real datetimes (YYYY-MM-DD HH:MM:SS)
        = Dominant Date as a real date
        = Size parsed to bytes (so “1.2 GB”, “512 MB”, etc. sort correctly)
        = Duration parsed to seconds (see below)

    - Missing/empty values always sort last in both directions.

    - New Duration column = RecEnd - RecStart shown as HH:MM:SS, sortable.

* Coverage checker (TSV-style, no TSV needed)

    - New “Check Coverage (Selected)” button:
        = Computes per-day total hours, missing days, <23h days, and days with multiple sessions using only the selected sessions.
        = Skips rows without RecStart/RecEnd (as requested).
        = Opens a report window with a Re-check button for quick repeat runs.
        = Mirrors summary to the Log pane.

    - Threshold (default 23 h) comes from the INI file (see below).

* Context menu (right-click on the list)
    - Toggle selection (applies to the single selected row).
    - Delete item from list (list only; never touches disk).
    - Refresh (selected item) recalculates stats for that one row.
    - Quick metadata (selected item) runs the same quick-meta path, only for that row.

* INI-based defaults (file beside the .py)
    - Auto-creates StepA_Natus_Raw_Metadata_Extractor_GUI.ini on first run.
    - [columns]: choose which columns show (true/false). Includes the new duration key.
    - [checker]: threshold_hours = 23 (you can change it).
    - The UI reads the INI at startup and builds the table accordingly.

* Two-part export for copy/move
    - Export now produces two outputs:
    - A standalone Python script (copy or move, per your toggle).
    - A paired CSV list (*_items.csv) of (src_path, dest_subfolder_name).
    - The main script reads the CSV at runtime to process items.
    - Missing-at-export items are noted in comments in the generated script.

* Robustness & QoL touches
    - Row insertion/refresh logic is column-order aware (works even if some columns are hidden via INI).
    - Quick-meta/refresh use existing labels (e.g., Recent) if present, or recompute when needed.
    - Log messages for coverage, quick-meta, refresh, and export are clearer.

What's new in version 1.0
- Load Session now **asks** if you want to **Rescan** disk to refresh stats, or use saved stats.
- Load Session shows a **progress bar** (deterministic) while reconciling items.
- Row highlighting stays: Missing (red), New (blue), Present (black).

Previously added features
- Optional filters: patient prefix (blank=off), last N days (blank/invalid=off).
- Scan computes dominant date, files, size, has EEG, latest ts; auto-selects "Recent" rows if days filter is on.
- Bulk select: Select All / Select None.
- Spacebar toggles selection (focused row or all highlighted rows).
- Quick metadata for selected (.eeg/.ent): StudyName, Start/End, EegNo, Machine.
- Copy selected (Dry-run supported); Stop cancels Scan/Meta/Copy.
- Export CSV of rows.
- Save / Load Session (JSON) with reconciliation: Present / Missing / New + Status column + colored rows.
- Scrollbars (vertical + horizontal) for the table.
- Export Copy Script: generates a Python script to copy/move selected folders to Destination, excluding .avi by default.

Requires: Python 3.8+ (standard library only: tkinter)
"""

import os
import sys
import csv
import json
import time
import queue
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ----------------------------
# Utilities (dates, sizes, io)
# ----------------------------

def safe_earliest_ts(path: Path) -> float:
    st = path.stat()
    return min(st.st_ctime, st.st_mtime)

def safe_latest_ts(path: Path) -> float:
    st = path.stat()
    return max(st.st_ctime, st.st_mtime)

def to_date_floor(epoch_seconds: float) -> datetime.date:
    return datetime.fromtimestamp(epoch_seconds).date()

def human_size(nbytes: int) -> str:
    units = ["B","KB","MB","GB","TB","PB","EB","ZB","YB"]
    size = float(nbytes)
    for u in units:
        if size < 1024.0:
            return f"{size:.1f} {u}"
        size /= 1024.0
    return f"{size:.1f} YB"

def within_last_days(target_epoch: float, days: int) -> bool:
    cutoff = time.time() - days * 86400
    return target_epoch >= cutoff

# -----------------------------------------
# Quick metadata extraction from .eeg/.ent
# -----------------------------------------

EXCEL_EPOCH = datetime(1899, 12, 30)
BINARY_HEADER_SIZE = 361  # typical small binary header

def excel_to_str(excel_float: str) -> str:
    try:
        x = float(excel_float)
        if x < 0 or x > 80000:
            return excel_float
        dt = EXCEL_EPOCH + timedelta(days=x)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return excel_float

def quick_extract_metadata(folder: Path, log=None) -> dict:
    """
    Minimal peek: StudyName, RecordingStartTime, RecordingEndTime, EegNo, Machine.
    """
    try:
        candidate = None
        for ext in ("*.eeg", "*.ent"):
            for f in folder.glob(ext):
                candidate = f
                break
            if candidate:
                break
        if not candidate:
            return {}

        with open(candidate, "rb") as fh:
            raw = fh.read()
        text = raw[BINARY_HEADER_SIZE:].decode("utf-8", errors="ignore")

        import re
        simple = {
            "StudyName": r'\(\."StudyName",\s*"([^"]+)"\)',
            "EegNo": r'\(\."EegNo",\s*"([^"]+)"\)',
            "Machine": r'\(\."Machine",\s*"([^"]+)"\)'
        }
        out = {}
        for k, pat in simple.items():
            m = re.search(pat, text)
            if m:
                out[k] = m.group(1)

        def grab_times(labels):
            for lbl in labels:
                m = re.search(rf'"{lbl}"\s*,\s*([0-9.]+)', text, flags=re.IGNORECASE)
                if m:
                    return excel_to_str(m.group(1))
            return ""

        out["RecordingStartTime"] = grab_times(["RECORDINGSTARTTIME","StartTime","Start_Time","RecStart"])
        out["RecordingEndTime"]   = grab_times(["RECORDINGENDTIME","EndTime","End_Time","RecEnd"])
        return out

    except Exception as e:
        if log:
            log(f"[quick_extract_metadata] {folder}: {e}")
        return {}

# ---------------------------------------------
# Folder scan: top-level dirs, stats, filtering
# ---------------------------------------------

class FolderRow:
    __slots__ = (
        "selected", "status", "folder_name", "folder_path", "dominant_date", "dom_count",
        "dom_fraction", "total_files", "total_size", "has_eeg", "latest_ts",
        "study_name", "rec_start", "rec_end", "eegno", "machine"
    )
    def __init__(self, folder_name, folder_path):
        self.selected = False
        self.status = "Present"   # "Present" | "Missing" | "New"
        self.folder_name = folder_name
        self.folder_path = str(folder_path)
        self.dominant_date = ""
        self.dom_count = 0
        self.dom_fraction = 0.0
        self.total_files = 0
        self.total_size = 0
        self.has_eeg = False
        self.latest_ts = 0.0
        self.study_name = ""
        self.rec_start = ""
        self.rec_end = ""
        self.eegno = ""
        self.machine = ""

def analyze_folder(folder: Path, log=None):
    from os import walk
    date_counter = Counter()
    total_files = 0
    total_size = 0
    latest = 0.0
    has_eeg = False

    try:
        for root, _, files in walk(folder):
            rp = Path(root)
            for fn in files:
                p = rp / fn
                try:
                    e = safe_earliest_ts(p)
                    l = safe_latest_ts(p)
                    date_counter[to_date_floor(e)] += 1
                    total_files += 1
                    total_size += p.stat().st_size
                    if l > latest:
                        latest = l
                    if p.suffix.lower() in (".eeg", ".ent"):
                        has_eeg = True
                except Exception as ex:
                    if log:
                        log(f"[scan] {p}: {ex}")
                    continue
    except Exception as e:
        if log:
            log(f"[scan-root] {folder}: {e}")

    if total_files == 0:
        return {
            "dominant_date": "",
            "dom_count": 0,
            "dom_fraction": 0.0,
            "total_files": 0,
            "total_size": 0,
            "latest_ts": 0.0,
            "has_eeg": False
        }

    common = date_counter.most_common(1)[0]
    dom_date = common[0]
    dom_count = common[1]
    dom_fraction = dom_count / total_files if total_files else 0.0

    return {
        "dominant_date": dom_date.strftime("%Y-%m-%d"),
        "dom_count": dom_count,
        "dom_fraction": dom_fraction,
        "total_files": total_files,
        "total_size": total_size,
        "latest_ts": latest,
        "has_eeg": has_eeg
    }

# -------------------
# GUI + worker logic
# -------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Natus Session Finder")
        self.geometry("1400x860")

        self._log_queue = queue.Queue()
        self._stop_event = threading.Event()

        # progress state
        self._progress_total = 0
        self._progress_value = 0

        # worker threads
        self._scan_thread = None
        self._copy_thread = None
        self._meta_thread = None

        # data rows
        self.rows = []

        self._build_ui()
        self._poll_log_queue()

    # --- UI ---

    def _build_ui(self):
        import configparser
        # Controls frame
        frm = ttk.Frame(self)
        frm.pack(fill="x", padx=10, pady=8)

        # Root dir
        ttk.Label(frm, text="Root:").grid(row=0, column=0, sticky="w")
        self.var_root = tk.StringVar()
        ent_root = ttk.Entry(frm, textvariable=self.var_root, width=64)
        ent_root.grid(row=0, column=1, sticky="we", padx=5)
        ttk.Button(frm, text="Browse...", command=self._choose_root).grid(row=0, column=2, padx=5)

        # Prefix (optional)
        ttk.Label(frm, text="Patient prefix (optional):").grid(row=0, column=3, sticky="e")
        self.var_prefix = tk.StringVar()
        ent_prefix = ttk.Entry(frm, textvariable=self.var_prefix, width=22)
        ent_prefix.grid(row=0, column=4, padx=5)

        # Last N days (optional)
        ttk.Label(frm, text="Last N days (optional):").grid(row=0, column=5, sticky="e")
        self.var_days = tk.StringVar(value="")
        ent_days = ttk.Entry(frm, textvariable=self.var_days, width=8)
        ent_days.grid(row=0, column=6, padx=5)

        # Buttons row 1
        ttk.Button(frm, text="Scan", command=self._start_scan).grid(row=0, column=7, padx=8)
        ttk.Button(frm, text="Stop", command=self._request_stop).grid(row=0, column=8, padx=4)

        # Row 2: Destination / actions
        ttk.Label(frm, text="Destination:").grid(row=1, column=0, sticky="w", pady=(6,0))
        self.var_dest = tk.StringVar()
        ent_dest = ttk.Entry(frm, textvariable=self.var_dest, width=64)
        ent_dest.grid(row=1, column=1, sticky="we", padx=5, pady=(6,0))
        ttk.Button(frm, text="Browse...", command=self._choose_dest).grid(row=1, column=2, padx=5, pady=(6,0))
        self.var_dryrun = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Dry run (don’t copy)", variable=self.var_dryrun).grid(row=1, column=3, padx=5, pady=(6,0))
        ttk.Button(frm, text="Copy selected", command=self._start_copy).grid(row=1, column=4, padx=6, pady=(6,0))
        ttk.Button(frm, text="Quick metadata for selected", command=self._start_quick_meta).grid(row=1, column=5, padx=6, pady=(6,0))
        ttk.Button(frm, text="Export CSV", command=self._export_csv).grid(row=1, column=6, padx=6, pady=(6,0))

        # Row 3: bulk selection + session I/O + copy/move script + coverage
        ttk.Button(frm, text="Select All", command=self._select_all).grid(row=2, column=1, sticky="w", pady=(6,0))
        ttk.Button(frm, text="Select None", command=self._select_none).grid(row=2, column=1, sticky="e", pady=(6,0))
        ttk.Button(frm, text="Save Session", command=self._save_session).grid(row=2, column=4, pady=(6,0))
        ttk.Button(frm, text="Load Session", command=self._load_session).grid(row=2, column=5, pady=(6,0))

        self.var_script_move = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Script: move instead of copy", variable=self.var_script_move).grid(row=2, column=6, pady=(6,0), sticky="w")
        ttk.Button(frm, text="Export Copy/Move (code + CSV)", command=self._export_copy_script).grid(row=2, column=7, pady=(6,0), padx=6)
        ttk.Button(frm, text="Check Coverage (Selected)", command=self._start_coverage_check).grid(row=2, column=8, pady=(6,0), padx=6)

        for i in range(10):
            frm.columnconfigure(i, weight=1)

        # Progress bar + label
        pfrm = ttk.Frame(self)
        pfrm.pack(fill="x", padx=10, pady=(0,8))
        self.progress = ttk.Progressbar(pfrm, orient="horizontal", mode="determinate", length=500, maximum=100)
        self.progress.grid(row=0, column=0, sticky="w")
        self.progress_label = ttk.Label(pfrm, text="")
        self.progress_label.grid(row=0, column=1, sticky="w", padx=10)

        # --- Configuration (INI) ---
        from pathlib import Path
        self._ini_path = Path(__file__).with_suffix(".ini")
        self._config = configparser.ConfigParser()
        default_columns = [
            "selected", "status", "folder_name", "dominant_date", "dom_fraction",
            "total_files", "total_size", "has_eeg", "recent", "study_name",
            "rec_start", "rec_end", "duration", "eegno", "machine"
        ]
        # Ensure file exists with defaults
        if not self._ini_path.exists():
            self._config["columns"] = {c: "true" for c in default_columns}
            self._config["checker"] = {"threshold_hours": "23"}
            self._config["gantt"] = {
                "gantt_show_grid": "true",
                "gantt_tick_hours": "1",
                "coverage_show_details": "inline",
                "gantt_dpi": "150",
                "gantt_width": "1200",
                "gantt_height": "700"
            }
            try:
                with open(self._ini_path, "w") as fh:
                    self._config.write(fh)
            except Exception:
                pass
        # Load (and merge defaults)
        self._config.read(self._ini_path)
        if "columns" not in self._config:
            self._config["columns"] = {c: "true" for c in default_columns}
        if "checker" not in self._config:
            self._config["checker"] = {"threshold_hours": "23"}
        if "gantt" not in self._config:
            self._config["gantt"] = {
                "gantt_show_grid": "true",
                "gantt_tick_hours": "1",
                "coverage_show_details": "inline",
                "gantt_dpi": "150",
                "gantt_width": "1200",
                "gantt_height": "700"
            }

        # Columns to show
        enabled_cols = []
        for c in default_columns:
            try:
                if self._config.getboolean("columns", c, fallback=True):
                    enabled_cols.append(c)
            except Exception:
                enabled_cols.append(c)

        # Table with scrollbars
        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True, padx=10, pady=8)

        self.tree = ttk.Treeview(table_frame, columns=enabled_cols, show="headings", height=20, selectmode="extended")
        vbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        headers = {
            "selected": "✓",
            "status": "Status",
            "folder_name": "Folder",
            "dominant_date": "Dominant Date",
            "dom_fraction": "Dominant %",
            "total_files": "Files",
            "total_size": "Size",
            "has_eeg": "EEG?",
            "recent": "Recent?",
            "study_name": "StudyName",
            "rec_start": "RecStart",
            "rec_end": "RecEnd",
            "duration": "Duration",
            "eegno": "EegNo",
            "machine": "Machine",
        }
        widths = {
            "selected": 56, "status": 90, "folder_name": 320, "dominant_date": 120, "dom_fraction": 110,
            "total_files": 80, "total_size": 120, "has_eeg": 70, "recent": 100,
            "study_name": 220, "rec_start": 180, "rec_end": 180, "duration": 110, "eegno": 140, "machine": 150
        }
        for c in enabled_cols:
            self.tree.heading(c, text=headers[c], command=lambda c=c: self._sort_by(c, False))
            self.tree.column(c, width=widths[c], anchor="w", stretch=True)

        # row coloring via tags
        self.tree.tag_configure("missing", foreground="red")
        self.tree.tag_configure("new", foreground="blue")
        self.tree.tag_configure("present", foreground="black")

        # Mouse + keyboard bindings
        self.tree.bind("<Double-1>", self._toggle_selected_event)
        # Right-click context menu
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        # Space toggles selection
        self.tree.bind("<space>", self._space_toggle)
        self.tree.focus_set()

        # Build context menu
        self._ctx_menu = tk.Menu(self, tearoff=0)
        self._ctx_menu.add_command(label="Toggle selection", command=self._ctx_toggle_selected)
        self._ctx_menu.add_command(label="Delete item from list", command=self._ctx_delete_item)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="Refresh (selected item)", command=self._ctx_refresh_selected)
        self._ctx_menu.add_command(label="Quick metadata (selected item)", command=self._ctx_quick_meta_selected)

        # Log area
        lf = ttk.LabelFrame(self, text="Log")
        lf.pack(fill="both", expand=False, padx=10, pady=(0,10))
        self.txt_log = tk.Text(lf, height=10, width=120, wrap="word")
        self.txt_log.pack(fill="both", expand=True)

        # Progress init
        self._progress_total = 0
        self._progress_value = 0

        # worker threads
        self._scan_thread = None
        self._copy_thread = None
        self._meta_thread = None

        # data rows
        self.rows = []



    # --- Log ---

    def log(self, msg: str):
        self._log_queue.put(msg)

    def _poll_log_queue(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.txt_log.insert("end", msg + "\n")
                self.txt_log.see("end")
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    # --- Progress helpers (run on main thread) ---

    def _progress_reset(self, total=0, text=""):
        def _do():
            self._progress_total = max(1, int(total))  # avoid zero-maximum
            self._progress_value = 0
            self.progress["mode"] = "determinate"
            self.progress["maximum"] = self._progress_total
            self.progress["value"] = 0
            self.progress_label.config(text=text)
            self.update_idletasks()
        self.after(0, _do)

    def _progress_step(self, step=1, text=None):
        def _do():
            self._progress_value = min(self._progress_value + step, self._progress_total)
            self.progress["value"] = self._progress_value
            if text is not None:
                self.progress_label.config(text=text)
            self.update_idletasks()
        self.after(0, _do)

    def _progress_done(self, text=""):
        def _do():
            self.progress["value"] = 0
            self.progress_label.config(text=text)
            self.update_idletasks()
        self.after(0, _do)

    # --- Helpers ---

    def _choose_root(self):
        d = filedialog.askdirectory(title="Select root (all patients)")
        if d:
            self.var_root.set(d)

    def _choose_dest(self):
        d = filedialog.askdirectory(title="Select destination")
        if d:
            self.var_dest.set(d)

    def _parse_days_optional(self):
        s = self.var_days.get().strip()
        if s == "":
            return None
        try:
            d = int(s)
            if d <= 0:
                return None
            return d
        except Exception:
            return None

    def _clear_table(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)

    def _recent_label_from_days(self, days, dominant_date, latest_ts):
        if days is None:
            return "—", False
        is_recent = False
        try:
            if dominant_date:
                dom_dt = datetime.strptime(dominant_date, "%Y-%m-%d")
                if (datetime.now() - dom_dt) <= timedelta(days=days):
                    is_recent = True
            if not is_recent and latest_ts > 0:
                is_recent = within_last_days(latest_ts, days)
        except Exception:
            pass
        return ("Yes" if is_recent else "No"), is_recent

    def _insert_row(self, r, recent_label: str):
        # Build a value map for ALL possible columns, then project to visible columns order.
        def duration_str():
            try:
                if r.rec_start and r.rec_end:
                    t0 = datetime.strptime(r.rec_start, "%Y-%m-%d %H:%M:%S")
                    t1 = datetime.strptime(r.rec_end, "%Y-%m-%d %H:%M:%S")
                    secs = max(0, int((t1 - t0).total_seconds()))
                    hh = secs // 3600
                    mm = (secs % 3600) // 60
                    ss = secs % 60
                    return f"{hh:02d}:{mm:02d}:{ss:02d}"
            except Exception:
                pass
            return ""
        valmap = {
            "selected": "Yes" if r.selected else "",
            "status": r.status,
            "folder_name": r.folder_name,
            "dominant_date": r.dominant_date,
            "dom_fraction": f"{r.dom_fraction*100:.1f}%",
            "total_files": r.total_files,
            "total_size": human_size(r.total_size),
            "has_eeg": "Yes" if r.has_eeg else "No",
            "recent": recent_label,
            "study_name": r.study_name or "",
            "rec_start": r.rec_start or "",
            "rec_end": r.rec_end or "",
            "duration": duration_str(),
            "eegno": r.eegno or "",
            "machine": r.machine or "",
        }
        cols = list(self.tree["columns"])
        vals = [valmap.get(c, "") for c in cols]
        tag = "present"
        if r.status == "Missing":
            tag = "missing"
        elif r.status == "New":
            tag = "new"
        self.tree.insert("", "end", iid=r.folder_path, values=vals, tags=(tag,))


    def _refresh_row_in_tree(self, r, recent_label):
        def duration_str():
            try:
                if r.rec_start and r.rec_end:
                    t0 = datetime.strptime(r.rec_start, "%Y-%m-%d %H:%M:%S")
                    t1 = datetime.strptime(r.rec_end, "%Y-%m-%d %H:%M:%S")
                    secs = max(0, int((t1 - t0).total_seconds()))
                    hh = secs // 3600
                    mm = (secs % 3600) // 60
                    ss = secs % 60
                    return f"{hh:02d}:{mm:02d}:{ss:02d}"
            except Exception:
                pass
            return ""
        valmap = {
            "selected": "Yes" if r.selected else "",
            "status": r.status,
            "folder_name": r.folder_name,
            "dominant_date": r.dominant_date,
            "dom_fraction": f"{r.dom_fraction*100:.1f}%",
            "total_files": r.total_files,
            "total_size": human_size(r.total_size),
            "has_eeg": "Yes" if r.has_eeg else "No",
            "recent": recent_label,
            "study_name": r.study_name or "",
            "rec_start": r.rec_start or "",
            "rec_end": r.rec_end or "",
            "duration": duration_str(),
            "eegno": r.eegno or "",
            "machine": r.machine or "",
        }
        cols = list(self.tree["columns"])
        vals = [valmap.get(c, "") for c in cols]
        tag = "present"
        if r.status == "Missing":
            tag = "missing"
        elif r.status == "New":
            tag = "new"
        self.tree.item(r.folder_path, values=vals, tags=(tag,))


    def _toggle_rows(self, iids):
        if not iids:
            return
        for iid in iids:
            for r in self.rows:
                if r.folder_path == iid:
                    r.selected = not r.selected
                    # recompute 'recent' label if needed
                    cols = list(self.tree["columns"])
                    if "recent" in cols:
                        idx = cols.index("recent")
                        vals = self.tree.item(iid, "values")
                        recent_label = vals[idx] if idx < len(vals) else "—"
                    else:
                        days = self._parse_days_optional()
                        recent_label, _ = self._recent_label_from_days(days, r.dominant_date, r.latest_ts)
                    self._refresh_row_in_tree(r, recent_label)
                    break


    def _toggle_selected_event(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self._toggle_rows([item])

    def _space_toggle(self, event):
        iids = list(self.tree.selection())
        if not iids:
            focus = self.tree.focus()
            if focus:
                iids = [focus]
        self._toggle_rows(iids)
        return "break"  # stop spacebar from scrolling

    def _sort_by(self, col, descending):
        """
        Stable sort with type-aware keys and "missing last" policy.

        Special handling:
          - rec_start / rec_end: parse "YYYY-MM-DD HH:MM:SS" to timestamp.
          - dominant_date: parse "YYYY-MM-DD" to date ordinal.
          - total_size: parse human size ("1.2 GB") to bytes.
          - dom_fraction: parse "NN.N%" to float.
          - duration: parse "HH:MM:SS" to seconds.

        For any unparsable/missing values, those rows are always placed LAST
        in both ascending and descending sorts.
        """
        cols = list(self.tree["columns"])
        if col not in cols:
            return
        col_index = cols.index(col)

        def parse_datetime(s: str):
            try:
                return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S").timestamp()
            except Exception:
                return None

        def parse_date(s: str):
            try:
                return datetime.strptime(s.strip(), "%Y-%m-%d").toordinal()
            except Exception:
                return None

        def parse_size(s: str):
            # Accept forms like "1.2 GB", "512 MB", "123", "123,456"
            if s is None:
                return None
            if isinstance(s, (int, float)):
                return float(s)
            txt = str(s).strip()
            if not txt:
                return None
            try:
                return float(txt.replace(',', ''))
            except Exception:
                pass
            parts = txt.split()
            try:
                if len(parts) == 2:
                    num = float(parts[0])
                    unit = parts[1].upper()
                    units = ["B","KB","MB","GB","TB","PB","EB","ZB","YB"]
                    if unit in units:
                        idx = units.index(unit)
                        return num * (1024.0 ** idx)
            except Exception:
                return None
            return None

        def parse_percent(s: str):
            try:
                if isinstance(s, str) and s.endswith('%'):
                    return float(s[:-1])
            except Exception:
                pass
            return None

        def parse_duration(s: str):
            # HH:MM:SS
            try:
                hh, mm, ss = str(s).split(':')
                return int(hh) * 3600 + int(mm) * 60 + int(float(ss))
            except Exception:
                return None

        present = []
        missing = []

        for iid in self.tree.get_children(""):
            vals = self.tree.item(iid, "values")
            raw = vals[col_index] if col_index < len(vals) else ""

            key = None
            if col in ("rec_start", "rec_end"):
                key = parse_datetime(raw)
            elif col == "dominant_date":
                key = parse_date(raw)
            elif col == "total_size":
                key = parse_size(raw)
            elif col == "dom_fraction":
                key = parse_percent(raw)
            elif col == "duration":
                key = parse_duration(raw)
            else:
                # try numeric else casefold string
                try:
                    key = float(str(raw).replace(',', ''))
                except Exception:
                    key = str(raw).casefold() if raw is not None else ""

            item = (iid, vals, key)
            if key is None or key == "":
                missing.append(item)
            else:
                present.append(item)

        # Sort present according to key type/direction
        present.sort(key=lambda it: it[2], reverse=descending)

        # Reattach rows: present first, then missing
        new_order = [iid for (iid, _, _) in present] + [iid for (iid, _, _) in missing]

        # Reinsert in this order
        for idx, iid in enumerate(new_order):
            self.tree.move(iid, '', idx)


    def _selected_rows(self):
        return [r for r in self.rows if r.selected]

    def _select_all(self):
        for r in self.rows:
            r.selected = True
            if self.tree.exists(r.folder_path):
                cols = list(self.tree["columns"])
                if "recent" in cols:
                    idx = cols.index("recent")
                    vals = self.tree.item(r.folder_path, "values")
                    recent_label = vals[idx] if idx < len(vals) else "—"
                else:
                    days = self._parse_days_optional()
                    recent_label, _ = self._recent_label_from_days(days, r.dominant_date, r.latest_ts)
                self._refresh_row_in_tree(r, recent_label)


    def _select_none(self):
        for r in self.rows:
            r.selected = False
            if self.tree.exists(r.folder_path):
                cols = list(self.tree["columns"])
                if "recent" in cols:
                    idx = cols.index("recent")
                    vals = self.tree.item(r.folder_path, "values")
                    recent_label = vals[idx] if idx < len(vals) else "—"
                else:
                    days = self._parse_days_optional()
                    recent_label, _ = self._recent_label_from_days(days, r.dominant_date, r.latest_ts)
                self._refresh_row_in_tree(r, recent_label)


    # --- Stop control ---

    def _request_stop(self):
        self._stop_event.set()
        self.log("Stop requested.")

    def _reset_stop(self):
        self._stop_event.clear()

    # --- Worker: Scan ---

    def _start_scan(self):
        root = self.var_root.get().strip()
        prefix = self.var_prefix.get().strip()
        days = self._parse_days_optional()

        if not root or not os.path.isdir(root):
            messagebox.showerror("Input error", "Please select a valid root folder.")
            return

        self._reset_stop()
        self._clear_table()
        self.rows = []

        self.log(f"Starting scan in: {root} | prefix: {prefix or '(disabled)'} | date filter: {f'last {days} day(s)' if days is not None else '(disabled)'}")

        self._scan_thread = threading.Thread(target=self._scan_worker, args=(root, prefix, days), daemon=True)
        self._scan_thread.start()

    def _scan_worker(self, root, prefix, days):
        try:
            root_path = Path(root)
            candidates = []

            with os.scandir(root_path) as it:
                for entry in it:
                    if self._stop_event.is_set():
                        self.log("Scan cancelled before listing finished.")
                        break
                    if not entry.is_dir():
                        continue
                    name = entry.name
                    if prefix:
                        if name.lower().startswith(prefix.lower()):
                            candidates.append(Path(entry.path))
                    else:
                        candidates.append(Path(entry.path))

            if self._stop_event.is_set():
                self.log("Scan cancelled.")
                return

            total = len(candidates)
            self.log(f"Found {total} candidate folders.")
            self._progress_reset(total=max(1,total), text="Scanning...")

            for idx, folder in enumerate(sorted(candidates), 1):
                if self._stop_event.is_set():
                    self.log("Scan cancelled during analysis.")
                    break

                r = FolderRow(folder.name, folder)
                stats = analyze_folder(folder, log=self.log)
                r.dominant_date = stats["dominant_date"]
                r.dom_count = stats["dom_count"]
                r.dom_fraction = stats["dom_fraction"]
                r.total_files = stats["total_files"]
                r.total_size = stats["total_size"]
                r.latest_ts = stats["latest_ts"]
                r.has_eeg = stats["has_eeg"]
                r.status = "Present"

                recent_label, is_recent = self._recent_label_from_days(days, r.dominant_date, r.latest_ts)
                r.selected = bool(days is not None and is_recent)

                self.rows.append(r)
                self._insert_row(r, recent_label)

                self._progress_step(step=1, text=f"Scanning... {idx}/{total or 1}")
                self.log(f"[{idx}/{total}] {folder.name} | files={r.total_files} | dom={r.dominant_date} ({r.dom_fraction*100:.1f}%) | eeg={r.has_eeg} | recent={recent_label}")

            if not self._stop_event.is_set():
                self.log("Scan complete.")
            self._progress_done(text="Ready.")
        except Exception as e:
            self.log(f"[scan error] {e}")
            self._progress_done(text="Error.")

    # --- Worker: Quick metadata ---

    def _start_quick_meta(self):
        rows = self._selected_rows()
        if not rows:
            messagebox.showinfo("Nothing selected", "Select one or more rows first.")
            return
        self._reset_stop()
        self._meta_thread = threading.Thread(target=self._meta_worker, args=(rows,), daemon=True)
        self._meta_thread.start()

    def _meta_worker(self, rows):
        total = len(rows)
        self.log("Fetching quick metadata for selected folders...")
        self._progress_reset(total=max(1,total), text="Quick metadata...")
        try:
            for i, r in enumerate(rows, 1):
                if self._stop_event.is_set():
                    self.log("Quick metadata cancelled.")
                    break
                if r.status == "Missing":
                    self._progress_step(step=1, text=f"Quick metadata... {i}/{total or 1}")
                    continue

                meta = quick_extract_metadata(Path(r.folder_path), log=self.log)
                r.study_name = meta.get("StudyName", "") or r.study_name
                r.rec_start = meta.get("RecordingStartTime", "") or r.rec_start
                r.rec_end = meta.get("RecordingEndTime", "") or r.rec_end
                r.eegno = meta.get("EegNo", "") or r.eegno
                r.machine = meta.get("Machine", "") or r.machine

                # Determine the current 'recent' label safely
                cols = list(self.tree["columns"])
                if "recent" in cols:
                    idx = cols.index("recent")
                    vals = self.tree.item(r.folder_path, "values")
                    recent_label = vals[idx] if idx < len(vals) else "—"
                else:
                    days = self._parse_days_optional()
                    recent_label, _ = self._recent_label_from_days(days, r.dominant_date, r.latest_ts)

                self._refresh_row_in_tree(r, recent_label)

                self._progress_step(step=1, text=f"Quick metadata... {i}/{total or 1}")
                self.log(f"[meta {i}/{total}] {r.folder_name}: StudyName='{r.study_name}' Start='{r.rec_start}' End='{r.rec_end}'")

            if not self._stop_event.is_set():
                self.log("Quick metadata complete.")
            self._progress_done(text="Ready.")
        except Exception as e:
            self.log(f"[quick meta error] {e}")
            self._progress_done(text="Error.")


    # --- Worker: Copy ---

    def _start_copy(self):
        dest = self.var_dest.get().strip()
        if not dest:
            messagebox.showerror("Destination required", "Choose a destination folder.")
            return
        if not os.path.isdir(dest):
            try:
                os.makedirs(dest, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Destination error", f"Cannot create destination:\n{e}")
                return

        rows = self._selected_rows()
        if not rows:
            messagebox.showinfo("Nothing selected", "Select one or more rows first.")
            return

        self._reset_stop()
        self._copy_thread = threading.Thread(target=self._copy_worker, args=(rows, dest, self.var_dryrun.get()), daemon=True)
        self._copy_thread.start()

    def _copy_worker(self, rows, dest, dryrun):
        total = len(rows)
        self.log(f"Copying {total} folder(s) to: {dest} | dry-run={dryrun}")
        self._progress_reset(total=max(1,total), text="Copying...")
        try:
            for idx, r in enumerate(rows, 1):
                if self._stop_event.is_set():
                    self.log("Copy cancelled.")
                    break
                if r.status == "Missing":
                    self.log(f"[{idx}/{total}] Skipped missing: {r.folder_name}")
                    self._progress_step(step=1, text=f"Copying... {idx}/{total or 1}")
                    continue

                src = Path(r.folder_path)
                target = Path(dest) / src.name
                if dryrun:
                    exists = target.exists()
                    self.log(f"[{idx}/{total}] would copy: {src} -> {target} (exists={exists})")
                    self._progress_step(step=1, text=f"Copying... {idx}/{total or 1}")
                    continue

                # Resolve collisions
                t = target
                n = 1
                while t.exists():
                    if self._stop_event.is_set():
                        self.log("Copy cancelled during target resolution.")
                        break
                    t = Path(str(target) + f"_copy{n}")
                    n += 1
                if self._stop_event.is_set():
                    break

                self.log(f"[{idx}/{total}] copying: {src} -> {t}")
                shutil.copytree(src, t)
                self._progress_step(step=1, text=f"Copying... {idx}/{total or 1}")

            if not self._stop_event.is_set():
                if dryrun:
                    self.log("Dry run complete (no files copied).")
                else:
                    self.log("Copy complete.")
            self._progress_done(text="Ready.")
        except Exception as e:
            self.log(f"[copy error] {e}")
            self._progress_done(text="Error.")

    # --- Export CSV ---

    def _export_csv(self):
        if not self.rows:
            messagebox.showinfo("Nothing to export", "Scan first to populate the table.")
            return
        f = filedialog.asksaveasfilename(
            title="Export CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")]
        )
        if not f:
            return
        try:
            cols = [
                "selected","status","folder_name","folder_path","dominant_date","dom_count","dom_fraction",
                "total_files","total_size","has_eeg","latest_ts",
                "study_name","rec_start","rec_end","eegno","machine"
            ]
            with open(f, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(cols)
                for r in self.rows:
                    w.writerow([
                        int(r.selected), r.status, r.folder_name, r.folder_path, r.dominant_date, r.dom_count, f"{r.dom_fraction:.5f}",
                        r.total_files, r.total_size, int(r.has_eeg), int(r.latest_ts),
                        r.study_name, r.rec_start, r.rec_end, r.eegno, r.machine
                    ])
            self.log(f"Exported to {f}")
        except Exception as e:
            messagebox.showerror("Export error", str(e))

    # --- Save / Load Session (JSON) ---

    def _serialize_row(self, r: FolderRow) -> dict:
        return {
            "selected": bool(r.selected),
            "status": r.status,
            "folder_name": r.folder_name,
            "folder_path": r.folder_path,
            "dominant_date": r.dominant_date,
            "dom_count": r.dom_count,
            "dom_fraction": r.dom_fraction,
            "total_files": r.total_files,
            "total_size": r.total_size,
            "has_eeg": bool(r.has_eeg),
            "latest_ts": float(r.latest_ts),
            "study_name": r.study_name,
            "rec_start": r.rec_start,
            "rec_end": r.rec_end,
            "eegno": r.eegno,
            "machine": r.machine,
        }

    def _deserialize_row(self, d: dict) -> FolderRow:
        r = FolderRow(d.get("folder_name",""), d.get("folder_path",""))
        r.selected = bool(d.get("selected", False))
        r.status = d.get("status", "Present")
        r.dominant_date = d.get("dominant_date","")
        r.dom_count = int(float(d.get("dom_count", 0)))
        r.dom_fraction = float(d.get("dom_fraction", 0.0))
        r.total_files = int(float(d.get("total_files", 0)))
        r.total_size = int(float(d.get("total_size", 0)))
        r.has_eeg = bool(d.get("has_eeg", False))
        r.latest_ts = float(d.get("latest_ts", 0.0))
        r.study_name = d.get("study_name","")
        r.rec_start = d.get("rec_start","")
        r.rec_end = d.get("rec_end","")
        r.eegno = d.get("eegno","")
        r.machine = d.get("machine","")
        return r

    def _save_session(self):
        if not self.rows:
            messagebox.showinfo("Nothing to save", "Scan or load data first.")
            return
        f = filedialog.asksaveasfilename(
            title="Save Session",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if not f:
            return
        try:
            days = self._parse_days_optional()
            payload = {
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "root": self.var_root.get().strip(),
                "prefix": self.var_prefix.get().strip(),
                "days": days,  # may be None
                "rows": [self._serialize_row(r) for r in self.rows],
            }
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            self.log(f"Session saved to {f}")
        except Exception as e:
            messagebox.showerror("Save error", str(e))

    def _load_session(self):
        f = filedialog.askopenfilename(
            title="Load Session",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if not f:
            return
        try:
            with open(f, "r", encoding="utf-8") as fh:
                sess = json.load(fh)
        except Exception as e:
            messagebox.showerror("Load error", f"Could not open session:\n{e}")
            return

        saved_rows = sess.get("rows", [])
        saved_root = sess.get("root", "")

        # If current root is empty, adopt saved root
        if not self.var_root.get().strip() and saved_root:
            self.var_root.set(saved_root)

        root = self.var_root.get().strip()
        prefix = self.var_prefix.get().strip()
        days = self._parse_days_optional()

        # Build current candidates by name from disk
        current_candidates = {}
        if root and os.path.isdir(root):
            try:
                with os.scandir(root) as it:
                    for entry in it:
                        if not entry.is_dir():
                            continue
                        name = entry.name
                        if prefix:
                            if name.lower().startswith(prefix.lower()):
                                current_candidates[name] = Path(entry.path)
                        else:
                            current_candidates[name] = Path(entry.path)
            except Exception as e:
                self.log(f"[load] error scanning current root: {e}")
        else:
            self.log("Load session: current root is invalid; marking based on saved paths only.")

        # Ask whether to rescan present items
        rescan = messagebox.askyesno(
            "Rescan during Load?",
            "Do you want to RESCAN current folders on disk to refresh stats?\n\n"
            "Yes: recompute stats for Present folders.\n"
            "No: use saved stats for Present folders."
        )

        self._reset_stop()
        self._clear_table()
        self.rows = []

        total_steps = len(saved_rows) + max(0, len(current_candidates) - len(saved_rows))
        self._progress_reset(total=max(1, total_steps), text="Loading session...")

        try:
            # 1) Place saved entries: mark Present/Missing; optionally rescan if Present
            for i, d in enumerate(saved_rows, 1):
                if self._stop_event.is_set():
                    self.log("Load session cancelled.")
                    break

                name = d.get("folder_name","")
                if name in current_candidates:
                    # It exists now
                    p = current_candidates.pop(name)

                    if rescan:
                        # Recompute stats from disk
                        r = FolderRow(name, p)
                        stats = analyze_folder(p, log=self.log)
                        r.dominant_date = stats["dominant_date"]
                        r.dom_count = stats["dom_count"]
                        r.dom_fraction = stats["dom_fraction"]
                        r.total_files = stats["total_files"]
                        r.total_size = stats["total_size"]
                        r.latest_ts = stats["latest_ts"]
                        r.has_eeg = stats["has_eeg"]
                        r.status = "Present"
                        # keep saved quick meta (can re-run via Quick Metadata if you want fresh)
                        sr = self._deserialize_row(d)
                        r.study_name = sr.study_name
                        r.rec_start = sr.rec_start
                        r.rec_end = sr.rec_end
                        r.eegno = sr.eegno
                        r.machine = sr.machine
                        r.selected = bool(d.get("selected", False))
                        self.log(f"[load] Present (rescanned): {name}")
                    else:
                        # Use saved stats, but update path and status
                        r = self._deserialize_row(d)
                        r.folder_path = str(p)  # update to current path
                        r.status = "Present"
                        self.log(f"[load] Present (saved stats): {name}")
                else:
                    # Missing -> use saved data and mark Missing
                    r = self._deserialize_row(d)
                    r.status = "Missing"
                    self.log(f"[load] Missing: {name}")

                recent_label, _ = self._recent_label_from_days(days, r.dominant_date, r.latest_ts)
                self.rows.append(r)
                self._insert_row(r, recent_label)
                self._progress_step(step=1, text=f"Loading session... {i}/{total_steps or 1}")

            # 2) Remaining current candidates are "New"
            for j, (name, path) in enumerate(sorted(current_candidates.items()), 1):
                if self._stop_event.is_set():
                    break
                r = FolderRow(name, path)
                stats = analyze_folder(path, log=self.log) if rescan else analyze_folder(path, log=self.log)
                r.dominant_date = stats["dominant_date"]
                r.dom_count = stats["dom_count"]
                r.dom_fraction = stats["dom_fraction"]
                r.total_files = stats["total_files"]
                r.total_size = stats["total_size"]
                r.latest_ts = stats["latest_ts"]
                r.has_eeg = stats["has_eeg"]
                r.status = "New"
                recent_label, is_recent = self._recent_label_from_days(days, r.dominant_date, r.latest_ts)
                r.selected = bool(days is not None and is_recent)

                self.rows.append(r)
                self._insert_row(r, recent_label)
                self._progress_step(step=1, text=f"Loading session... {len(saved_rows)+j}/{total_steps or 1}")
                self.log(f"[load] New: {name}")

            if not self._stop_event.is_set():
                self.log(f"Session loaded from {os.path.basename(f)} (rescan={'Yes' if rescan else 'No'}).")
            self._progress_done(text="Ready.")
        except Exception as e:
            self.log(f"[load error] {e}")
            self._progress_done(text="Error.")

    # --- Export Copy Script (.py) ---

    def _export_copy_script(self):
        dest = self.var_dest.get().strip()
        if not dest:
            messagebox.showerror("Destination required", "Choose a destination folder first.")
            return
        rows = self._selected_rows()
        if not rows:
            messagebox.showinfo("Nothing selected", "Select one or more rows first.")
            return

        # Default filename in destination
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"copy_selected_{ts}.py"
        initial_dir = dest if os.path.isdir(dest) else None

        f = filedialog.asksaveasfilename(
            title="Export Copy Script",
            initialdir=initial_dir,
            initialfile=default_name,
            defaultextension=".py",
            filetypes=[("Python", "*.py"), ("All files", "*.*")]
        )
        if not f:
            return

        move_mode = bool(self.var_script_move.get())

        # Build mapping and also collect missing (comment them)
        present_items = []
        missing_items = []
        for r in rows:
            if r.status == "Missing":
                missing_items.append((r.folder_name, r.folder_path))
            else:
                present_items.append((r.folder_name, r.folder_path))

        try:
            script = self._generate_copy_script(dest, present_items, missing_items, move_mode)
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(script)
            self.log(f"Copy script exported to {f}")
        except Exception as e:
            messagebox.showerror("Export error", str(e))
            
    def _on_tree_right_click(self, event):
        # select the item under cursor; apply actions to that single item
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        else:
            # click on empty area: clear selection
            self.tree.selection_remove(self.tree.selection())

    def _ctx_toggle_selected(self):
        iids = list(self.tree.selection())
        if not iids:
            return
        iid = iids[0]
        for r in self.rows:
            if r.folder_path == iid:
                r.selected = not r.selected
                cols = list(self.tree["columns"])
                if "recent" in cols:
                    idx = cols.index("recent")
                    recent_label = self.tree.item(iid, "values")[idx]
                else:
                    days = self._parse_days_optional()
                    recent_label, _ = self._recent_label_from_days(days, r.dominant_date, r.latest_ts)
                self._refresh_row_in_tree(r, recent_label)
                break

    def _ctx_delete_item(self):
        # Remove only from the table/list; do NOT delete from disk
        iids = list(self.tree.selection())
        if not iids:
            return
        iid = iids[0]
        self.rows = [r for r in self.rows if r.folder_path != iid]
        if self.tree.exists(iid):
            self.tree.delete(iid)
        self.log(f"Removed from list: {iid}")

    def _ctx_refresh_selected(self):
        iids = list(self.tree.selection())
        if not iids:
            return
        iid = iids[0]
        row = next((r for r in self.rows if r.folder_path == iid), None)
        if not row:
            return
        # Recompute stats for this one folder
        def worker():
            try:
                stats = analyze_folder(Path(row.folder_path), log=self.log)
                row.dominant_date = stats.get("dominant_date","")
                row.dom_count = stats.get("dom_count",0)
                row.dom_fraction = stats.get("dom_fraction",0.0)
                row.total_files = stats.get("total_files",0)
                row.total_size = stats.get("total_size",0)
                row.has_eeg = bool(stats.get("has_eeg",False))
                row.latest_ts = float(stats.get("latest_ts",0.0))
                # recent label recompute
                days = self._parse_days_optional()
                recent_label, _is_recent = self._recent_label_from_days(days, row.dominant_date, row.latest_ts)
                self._refresh_row_in_tree(row, recent_label)
                self.log(f"[refresh] {row.folder_name}: files={row.total_files} size={human_size(row.total_size)}")
            except Exception as e:
                self.log(f"[refresh error] {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _ctx_quick_meta_selected(self):
        # Run quick metadata only for the selected (single) item
        iids = list(self.tree.selection())
        if not iids:
            return
        iid = iids[0]
        row = next((r for r in self.rows if r.folder_path == iid), None)
        if not row:
            return
        def worker():
            try:
                meta = quick_extract_metadata(Path(row.folder_path), log=self.log)
                row.study_name = meta.get("StudyName","") or row.study_name
                row.rec_start = meta.get("RecordingStartTime","") or row.rec_start
                row.rec_end = meta.get("RecordingEndTime","") or row.rec_end
                row.eegno = meta.get("EegNo","") or row.eegno
                row.machine = meta.get("Machine","") or row.machine
                # recent label from table (if present) else recompute quickly
                recent_label = "—"
                cols = list(self.tree["columns"])
                if "recent" in cols:
                    idx = cols.index("recent")
                    recent_label = self.tree.item(iid, "values")[idx]
                else:
                    days = self._parse_days_optional()
                    recent_label, _ = self._recent_label_from_days(days, row.dominant_date, row.latest_ts)
                self._refresh_row_in_tree(row, recent_label)
                self.log(f"[meta] {row.folder_name}: Start='{row.rec_start}' End='{row.rec_end}'")
            except Exception as e:
                self.log(f"[meta error] {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _start_coverage_check(self):
        from tkinter import messagebox
        rows = self._selected_rows()
        if not rows:
            messagebox.showinfo("Nothing selected", "Select one or more rows first.")
            return

        valid = [r for r in rows if r.rec_start and r.rec_end]
        skipped = [r for r in rows if not (r.rec_start and r.rec_end)]
        if skipped:
            self.log(f"[coverage] Skipping {len(skipped)} item(s) with missing start/end metadata.")

        # Threshold from INI
        try:
            threshold_hours = float(self._config.get("checker", "threshold_hours", fallback="23"))
        except Exception:
            threshold_hours = 23.0

        if not valid:
            messagebox.showinfo("No valid sessions", "No selected rows have both RecStart and RecEnd.")
            return

        bars_by_day = self._clip_selected_sessions_per_day(valid)  # dict[date] -> list of bars
        per_day = self._compute_union_and_flags(bars_by_day, threshold_hours)  # union, flags

        report = self._make_coverage_report(bars_by_day, per_day, threshold_hours)
        self._show_coverage_window(bars_by_day, per_day, report, threshold_hours)


    def _compute_coverage_report(self, rows, threshold_hours: float):
        """
        rows: list of FolderRow with rec_start/rec_end strings "YYYY-MM-DD HH:MM:SS"
        Returns a multi-line string report.
        """
        from collections import defaultdict

        if not rows:
            return "No valid sessions (start/end) to evaluate."

        # Build intervals and per-day contributions
        intervals = []
        for r in rows:
            try:
                t0 = datetime.strptime(r.rec_start, "%Y-%m-%d %H:%M:%S")
                t1 = datetime.strptime(r.rec_end, "%Y-%m-%d %H:%M:%S")
                if t1 < t0:
                    t0, t1 = t1, t0
                intervals.append((r.folder_name, t0, t1))
            except Exception:
                continue

        if not intervals:
            return "No parsable session intervals."

        start_day = min(t0.date() for _, t0, _ in intervals)
        end_day   = max(t1.date() for _, _, t1 in intervals)
        day = start_day

        per_day_seconds = {}
        per_day_sessions = {}
        from datetime import timedelta as _td
        while day <= end_day:
            day_start = datetime.combine(day, datetime.min.time())
            day_end = day_start + _td(days=1)
            # sum coverage seconds for this day
            total = 0
            ses_names = set()
            for name, s0, s1 in intervals:
                # intersection of [s0,s1] with [day_start, day_end]
                a = max(s0, day_start)
                b = min(s1, day_end)
                if b > a:
                    total += int((b - a).total_seconds())
                    ses_names.add(name)
            per_day_seconds[day] = total
            per_day_sessions[day] = ses_names
            day += _td(days=1)

        # Missing days (no seconds at all)
        missing_days = [d for d, secs in per_day_seconds.items() if secs == 0]
        # Below-threshold days (keep the rule simple as requested: 23 h for all days)
        fails = [d for d, secs in per_day_seconds.items() if secs < int(threshold_hours*3600)]

        # Multiple sessions per day
        multi = [d for d, names in per_day_sessions.items() if len(names) > 1]

        # Build report
        lines = []
        lines.append(f"Coverage window: {start_day.isoformat()}  →  {end_day.isoformat()}")
        lines.append(f"Threshold: {threshold_hours:.2f} h/day")
        lines.append("")
        lines.append("Per-day totals:")
        for d in sorted(per_day_seconds.keys()):
            secs = per_day_seconds[d]
            hours = secs/3600.0
            flag = ""
            if d in missing_days:
                flag = "  [MISSING]"
            elif d in fails:
                flag = "  [< threshold]"
            if d in multi:
                flag += "  [MULTIPLE SESSIONS]"
            lines.append(f"  {d.isoformat()}  {hours:6.2f} h{flag}")
        lines.append("")
        if missing_days:
            lines.append(f"Missing days ({len(missing_days)}): " + ", ".join(d.isoformat() for d in sorted(missing_days)))
        else:
            lines.append("Missing days: none")
        if fails:
            lines.append(f"Below-threshold days ({len(fails)}): " + ", ".join(d.isoformat() for d in sorted(fails)))
        else:
            lines.append("Below-threshold days: none")
        if multi:
            lines.append(f"Days with multiple sessions ({len(multi)}): " + ", ".join(d.isoformat() for d in sorted(multi)))
        else:
            lines.append("Days with multiple sessions: none")

        return "\n".join(lines)

    def _show_coverage_report(self, text: str):
        # Simple dialog with a re-check button
        win = tk.Toplevel(self)
        win.title("Coverage Check (Selected)")
        win.geometry("800x520")
        txt = tk.Text(win, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", text)
        txt.configure(state="disabled")
        btn = ttk.Button(win, text="Re-check", command=lambda: self._coverage_recheck_into(txt))
        btn.pack(pady=6)

    def _coverage_recheck_into(self, text_widget):
        # Recompute against current selection and replace the text
        rows = self._selected_rows()
        valid = [r for r in rows if r.rec_start and r.rec_end]
        threshold_hours = 23.0
        try:
            if hasattr(self, "_config"):
                threshold_hours = float(self._config.get("checker", "threshold_hours", fallback="23"))
        except Exception:
            pass
        report = self._compute_coverage_report(valid, threshold_hours)
        text_widget.configure(state="normal")
        text_widget.delete("1.0", "end")
        text_widget.insert("1.0", report)
        text_widget.configure(state="disabled")
        self.log("Coverage re-checked.")

    def _export_copy_script(self):
        dest = self.var_dest.get().strip()
        if not dest:
            messagebox.showerror("Destination required", "Choose a destination folder first.")
            return
        rows = self._selected_rows()
        if not rows:
            messagebox.showinfo("Nothing selected", "Select one or more rows first.")
            return

        # Default filename in destination (main script only)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"copy_selected_{ts}.py"
        initial_dir = dest if os.path.isdir(dest) else None

        f = filedialog.asksaveasfilename(
            title="Save main script",
            initialdir=initial_dir,
            initialfile=default_name,
            defaultextension=".py",
            filetypes=[("Python", "*.py"), ("All files", "*.*")]
        )
        if not f:
            return
        dest_base = dest
        move_mode = bool(self.var_script_move.get())

        # Prepare items
        present_items = []
        missing_items = []
        for r in rows:
            p = r.folder_path
            if os.path.isdir(p):
                present_items.append((r.folder_name, p))
            else:
                missing_items.append((r.folder_name, p))

        # CSV path (same folder, paired name)
        base_no_ext = os.path.splitext(f)[0]
        csv_path = base_no_ext + "_items.csv"

        # Write CSV list
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as cfh:
                w = csv.writer(cfh)
                w.writerow(["src_path", "dest_subfolder_name"])
                for name, src in present_items:
                    w.writerow([os.path.abspath(src), name])
            self.log(f"Exported items CSV: {csv_path}")
            if missing_items:
                self.log(f"Missing at export time (not in CSV): {len(missing_items)}")
        except Exception as e:
            messagebox.showerror("Export error", f"Failed to write CSV:\n{e}")
            return

        # Write main script
        try:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(self._generate_copy_script_main_two_part(dest_base, move_mode, csv_path, missing_items))
            self.log(f"Exported main script: {f}")
        except Exception as e:
            messagebox.showerror("Export error", f"Failed to write main script:\n{e}")
            return

    def _show_coverage_window(self, bars_by_day, per_day, report_text, threshold_hours: float):
        import tkinter as tk
        from tkinter import ttk
        from tkinter import messagebox
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        # Build window
        win = tk.Toplevel(self)
        win.title("Coverage & Gantt (Selected)")
        win.geometry("1200x820")

        # --- Top control row
        topf = ttk.Frame(win)
        topf.pack(fill="x", padx=8, pady=6)

        ttk.Button(topf, text="Re-check", command=lambda: self._coverage_recheck_window(win)).pack(side="left", padx=4)
        ttk.Button(topf, text="Save… (PNG + TSV)", command=lambda: self._save_gantt_and_tsv(win)).pack(side="left", padx=4)
        ttk.Button(topf, text="Save Interactive (HTML)", command=lambda: self._save_gantt_interactive(win)).pack(side="left", padx=4)

        ttk.Label(topf, text=" | ").pack(side="left", padx=2)
        ttk.Button(topf, text="Tick −", command=lambda: self._change_tick_hours(win, -1)).pack(side="left", padx=(6,2))
        ttk.Button(topf, text="Tick +", command=lambda: self._change_tick_hours(win, +1)).pack(side="left", padx=2)
        win._tick_label_var = tk.StringVar(value="")
        ttk.Label(topf, textvariable=win._tick_label_var).pack(side="left", padx=8)

        ttk.Label(topf, text=" | ").pack(side="left", padx=2)
        ttk.Button(topf, text="Gantt ↑", command=lambda: self._nudge_gantt_height(win, -80)).pack(side="left", padx=2)
        ttk.Button(topf, text="Gantt ↓", command=lambda: self._nudge_gantt_height(win, +80)).pack(side="left", padx=2)

        # --- Paned window (draggable sash between report and chart)
        paned = ttk.Panedwindow(win, orient="vertical")
        paned.pack(fill="both", expand=True, padx=8, pady=(0,8))

        repf = ttk.LabelFrame(paned, text="Coverage report")
        ganttf = ttk.LabelFrame(paned, text="Gantt (grouped by date)")
        paned.add(repf, weight=1)
        paned.add(ganttf, weight=2)

        # Report text
        txt = tk.Text(repf, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", report_text)
        txt.configure(state="disabled")

        # Build Gantt figure with current tick hours
        try:
            tick_hours = int(self._config.get("gantt", "gantt_tick_hours", fallback="1"))
        except Exception:
            tick_hours = 1
        win._gantt_tick_hours = max(1, tick_hours)

        fig = self._build_gantt_figure(bars_by_day, per_day, tick_hours=win._gantt_tick_hours)
        canvas = FigureCanvasTkAgg(fig, master=ganttf)
        canvas.draw()
        canvas_widget = canvas.get_tk_widget()
        canvas_widget.pack(fill="both", expand=True)

        # Update tick label text
        win._tick_label_var.set(f"Tick: {win._gantt_tick_hours} h")

        # Stash state for re-check/save/resize controls
        win._coverage_text = txt
        win._coverage_fig = fig
        win._coverage_canvas = canvas
        win._coverage_canvas_widget = canvas_widget
        win._coverage_paned = paned
        win._coverage_bars_by_day = bars_by_day
        win._coverage_per_day = per_day
        win._coverage_threshold = threshold_hours


    def _generate_copy_script_main_two_part(self, dest_base, move_mode, csv_path, missing_items):
        """
        Returns the text of the standalone main script that reads a CSV list of items to process.
        """
        dest_base = os.path.abspath(dest_base)
        lines = []
        lines.append("#!/usr/bin/env python3")
        lines.append("# -*- coding: utf-8 -*-")
        lines.append("")
        lines.append("# Auto-generated by Natus Session Finder GUI")
        lines.append("# This script will {} selected folders into DEST_BASE, excluding certain extensions.".format("MOVE" if move_mode else "COPY"))
        lines.append("")
        lines.append("import os, sys, csv, shutil")
        lines.append("from pathlib import Path")
        lines.append("")
        lines.append(f"DEST_BASE = r'''{dest_base}'''")
        lines.append(f"MOVE_MODE = {str(move_mode)}  # True = move, False = copy")
        lines.append("EXCLUDE_EXTS = ['.avi']  # Edit this list if needed")
        lines.append("")
        lines.append("# CSV list of items to process (src_path, dest_subfolder_name)")
        lines.append(f"ITEMS_CSV = r'''{os.path.abspath(csv_path)}'''")
        lines.append("")
        if missing_items:
            lines.append("# The following were missing at export time (not in CSV):")
            for name, src in missing_items:
                lines.append(f"#    MISSING: {name}  ({src})")
            lines.append("")
        lines.append("def ensure_dir(p: Path):")
        lines.append("    p.mkdir(parents=True, exist_ok=True)")
        lines.append("")
        lines.append("def copy_file(src: Path, dst: Path):")
        lines.append("    dst.parent.mkdir(parents=True, exist_ok=True)")
        lines.append("    shutil.copy2(src, dst)")
        lines.append("")
        lines.append("def process_folder(src_root: Path, dest_root: Path):")
        lines.append("    for root, dirs, files in os.walk(src_root):")
        lines.append("        rp = Path(root)")
        lines.append("        rel = rp.relative_to(src_root)")
        lines.append("        out_dir = dest_root / rel")
        lines.append("        ensure_dir(out_dir)")
        lines.append("        for fn in files:")
        lines.append("            s = rp / fn")
        lines.append("            if s.suffix.lower() in [e.lower() for e in EXCLUDE_EXTS]:")
        lines.append("                continue")
        lines.append("            d = out_dir / fn")
        lines.append("            if MOVE_MODE:")
        lines.append("                print(f\"MOVE  {s} -> {d}\")")
        lines.append("                d.parent.mkdir(parents=True, exist_ok=True)")
        lines.append("                try:")
        lines.append("                    s.replace(d)")
        lines.append("                except Exception:")
        lines.append("                    # fallback to copy+unlink if cross-device")
        lines.append("                    copy_file(s, d)")
        lines.append("                    try: s.unlink()")
        lines.append("                    except Exception: pass")
        lines.append("            else:")
        lines.append("                print(f\"COPY  {s} -> {d}\")")
        lines.append("                copy_file(s, d)")
        lines.append("")
        lines.append("def load_items(csv_path: Path):")
        lines.append("    items = []")
        lines.append("    with open(csv_path, 'r', encoding='utf-8') as fh:")
        lines.append("        rdr = csv.reader(fh)")
        lines.append("        header = next(rdr, None)")
        lines.append("        for row in rdr:")
        lines.append("            if not row: continue")
        lines.append("            src = Path(row[0]).expanduser()")
        lines.append("            name = row[1]")
        lines.append("            items.append((src, name))")
        lines.append("    return items")
        lines.append("")
        lines.append("def main():")
        lines.append("    dest = Path(DEST_BASE).resolve()")
        lines.append("    ensure_dir(dest)")
        lines.append("    csv_p = Path(ITEMS_CSV)")
        lines.append("    if not csv_p.is_absolute():")
        lines.append("        # resolve relative to the script location")
        lines.append("        csv_p = Path(__file__).resolve().parent / csv_p")
        lines.append("    items = load_items(csv_p)")
        lines.append("    for src, dest_name in items:")
        lines.append("        if not src.exists():")
        lines.append("            print(f\"MISSING (skip): {src}\")")
        lines.append("            continue")
        lines.append("        target = dest / dest_name")
        lines.append("        # Resolve name collision by appending _copyN if needed")
        lines.append("        t = target")
        lines.append("        n = 1")
        lines.append("        while t.exists():")
        lines.append("            t = Path(str(target) + f\"_copy{n}\")")
        lines.append("            n += 1")
        lines.append("        print(f\"PROCESS: {src} -> {t}  (mode={'MOVE' if MOVE_MODE else 'COPY'})\")")
        lines.append("        ensure_dir(t)")
        lines.append("        process_folder(src, t)")
        lines.append("")
        lines.append("if __name__ == '__main__':")
        lines.append("    try:")
        lines.append("        main()")
        lines.append("    except KeyboardInterrupt:")
        lines.append("        print('Interrupted.')")
        lines.append("")
        return '\n'.join(lines)

    def _clip_selected_sessions_per_day(self, rows):
        """
        Returns dict[date] -> list of bars, where each bar is:
          {
            'folder': str,
            'start_dt': datetime (clipped within date),
            'end_dt': datetime (clipped within date),
            'eegno': str or '',
            'study_name': str or ''
          }
        Sessions that span midnight produce 2 bars (one per day).
        """
        from datetime import datetime, timedelta
        from collections import defaultdict

        out = defaultdict(list)
        for r in rows:
            try:
                t0 = datetime.strptime(r.rec_start, "%Y-%m-%d %H:%M:%S")
                t1 = datetime.strptime(r.rec_end, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if t1 < t0:
                t0, t1 = t1, t0

            day = t0.date()
            while day <= t1.date():
                day_start = datetime.combine(day, datetime.min.time())
                day_end = day_start + timedelta(days=1)
                a = max(t0, day_start)
                b = min(t1, day_end)
                if b > a:
                    out[day].append({
                        "folder": r.folder_name,
                        "start_dt": a,
                        "end_dt": b,
                        "eegno": r.eegno or "",
                        "study_name": r.study_name or ""
                    })
                day = day + timedelta(days=1)

        # sort by start time
        for d in list(out.keys()):
            out[d].sort(key=lambda x: x["start_dt"])
        return dict(out)

    def _compute_union_and_flags(self, bars_by_day, threshold_hours: float):
        """
        For each day:
          - compute union intervals and total covered seconds,
          - detect multiple sessions (>=2 bars),
          - detect overlapping sessions and build overlaps map,
          - mark below-threshold (except first/last day).
        Returns dict[date] -> {
            'union': [(start_dt, end_dt), ...],           # merged intervals for faint overlay
            'total_secs': int,
            'multiple': bool,
            'overlap': bool,
            'overlaps_map': {idx: [folder_names...]},     # per-bar overlaps (by index in bars list)
            'below_threshold': bool
        }
        """
        from datetime import timedelta
        days = sorted(bars_by_day.keys())
        first_day = days[0] if days else None
        last_day = days[-1] if days else None

        per_day = {}
        for d in days:
            bars = bars_by_day.get(d, [])
            # Union merge
            intervals = [(b["start_dt"], b["end_dt"]) for b in bars]
            intervals.sort(key=lambda t: t[0])
            merged = []
            for s, e in intervals:
                if not merged:
                    merged.append([s,e])
                else:
                    ps, pe = merged[-1]
                    if s <= pe:
                        if e > pe: merged[-1][1] = e
                    else:
                        merged.append([s,e])
            merged = [(s,e) for s,e in merged]
            total_secs = sum(int((e - s).total_seconds()) for s, e in merged)

            # Multiple & overlap detection
            multiple = len(bars) >= 2
            overlaps_map = {i: [] for i in range(len(bars))}
            overlap_flag = False
            for i in range(len(bars)):
                for j in range(i+1, len(bars)):
                    a1, a2 = bars[i]["start_dt"], bars[i]["end_dt"]
                    b1, b2 = bars[j]["start_dt"], bars[j]["end_dt"]
                    if b1 < a2 and a1 < b2:
                        # overlap
                        overlaps_map[i].append(bars[j]["folder"])
                        overlaps_map[j].append(bars[i]["folder"])
                        overlap_flag = True

            # Below-threshold (skip first/last day tagging)
            below = (total_secs < int(threshold_hours * 3600))
            if d == first_day or d == last_day:
                below = False

            per_day[d] = {
                "union": merged,
                "total_secs": total_secs,
                "multiple": multiple,
                "overlap": overlap_flag,
                "overlaps_map": overlaps_map,
                "below_threshold": below
            }
        return per_day

    def _make_coverage_report(self, bars_by_day, per_day, threshold_hours: float):
        """
        Build the human-readable report with:
          - per-day totals and flags,
          - "Details for days with multiple sessions" (inline, clipped times),
          - "Days with overlapping sessions",
          - "Below-threshold days" (excluding first/last day).
        """
        from datetime import datetime
        lines = []
        if not bars_by_day:
            return "No valid sessions to evaluate."

        days = sorted(bars_by_day.keys())
        start_day = days[0]
        end_day = days[-1]

        lines.append(f"Coverage window: {start_day.isoformat()}  →  {end_day.isoformat()}")
        lines.append(f"Threshold: {threshold_hours:.2f} h/day (first/last day excluded from 'below threshold' tagging)")
        lines.append("")
        lines.append("Per-day totals (union coverage):")

        below_days = []
        multi_days = []
        overlap_days = []

        for d in days:
            secs = per_day[d]["total_secs"]
            hours = secs / 3600.0
            flags = []
            if per_day[d]["multiple"]:
                flags.append("MULTIPLE")
                multi_days.append(d)
            if per_day[d]["overlap"]:
                flags.append("OVERLAPPING")
                overlap_days.append(d)
            if per_day[d]["below_threshold"]:
                flags.append("< threshold")
                below_days.append(d)
            flag_txt = ("  [" + ", ".join(flags) + "]") if flags else ""
            lines.append(f"  {d.isoformat()}  {hours:6.2f} h{flag_txt}")

        # Inline details for days with multiple sessions
        if multi_days:
            lines.append("")
            lines.append("Details for days with multiple sessions:")
            for d in sorted(set(multi_days)):
                lines.append(f"  {d.isoformat()}:")
                bars = bars_by_day[d]
                overlaps_map = per_day[d]["overlaps_map"]
                for idx, b in enumerate(bars):
                    s = b["start_dt"].strftime("%H:%M:%S")
                    e = b["end_dt"].strftime("%H:%M:%S")
                    mark = " [OVERLAP]" if overlaps_map.get(idx) else ""
                    lines.append(f"    • {b['folder']} | {s} → {e} | EegNo={b['eegno']} | StudyName={b['study_name']}{mark}")

        # Overlapping sessions section
        if overlap_days:
            lines.append("")
            lines.append("Days with overlapping sessions:")
            for d in sorted(set(overlap_days)):
                lines.append(f"  {d.isoformat()}:")
                bars = bars_by_day[d]
                overlaps_map = per_day[d]["overlaps_map"]
                for idx, targets in overlaps_map.items():
                    if targets:
                        s = bars[idx]["start_dt"].strftime("%H:%M:%S")
                        e = bars[idx]["end_dt"].strftime("%H:%M:%S")
                        lines.append(f"    • {bars[idx]['folder']}  ({s} → {e})  overlaps with: {', '.join(sorted(set(targets)))}")

        # Below-threshold days (excluding first/last)
        lines.append("")
        if below_days:
            lines.append(f"Below-threshold days ({len(below_days)}): " + ", ".join(d.isoformat() for d in sorted(below_days)))
        else:
            lines.append("Below-threshold days: none")

        return "\n".join(lines)

    def _generate_copy_script(self, dest_base, present_items, missing_items, move_mode):
        """
        Create a standalone Python script that:
        - Ensures dest_base exists
        - Copies or moves each selected folder into dest_base
        - Skips files with extensions in EXCLUDE_EXTS (default ['.avi'])
        - Recreates directory structure
        """
        dest_base = os.path.abspath(dest_base)
        lines = []
        lines.append("#!/usr/bin/env python3")
        lines.append("# -*- coding: utf-8 -*-")
        lines.append("")
        lines.append("# Auto-generated by Natus Session Finder GUI")
        lines.append("# This script will {} selected folders into DEST_BASE, excluding certain extensions.".format("MOVE" if move_mode else "COPY"))
        lines.append("")
        lines.append("import os")
        lines.append("import sys")
        lines.append("import shutil")
        lines.append("from pathlib import Path")
        lines.append("")
        lines.append(f"DEST_BASE = r'''{dest_base}'''")
        lines.append(f"MOVE_MODE = {str(move_mode)}  # True = move, False = copy")
        lines.append("EXCLUDE_EXTS = ['.avi']  # Edit this list if needed")
        lines.append("")
        lines.append("# Folders to process (source_path -> dest_subfolder_name):")
        lines.append("ITEMS = [")
        for name, src in present_items:
            lines.append(f"    (r'''{os.path.abspath(src)}''', r'''{name}'''),")
        lines.append("]")
        if missing_items:
            lines.append("")
            lines.append("# The following were missing at export time (not processed):")
            for name, src in missing_items:
                lines.append(f"#    MISSING: {name}  ({src})")
        lines.append("")
        lines.append("def ensure_dir(p: Path):")
        lines.append("    p.mkdir(parents=True, exist_ok=True)")
        lines.append("")
        lines.append("def should_skip(file_path: Path) -> bool:")
        lines.append("    return file_path.suffix.lower() in (ext.lower() for ext in EXCLUDE_EXTS)")
        lines.append("")
        lines.append("def copy_file(src: Path, dst: Path):")
        lines.append("    ensure_dir(dst.parent)")
        lines.append("    shutil.copy2(src, dst)")
        lines.append("")
        lines.append("def move_file(src: Path, dst: Path):")
        lines.append("    ensure_dir(dst.parent)")
        lines.append("    shutil.move(str(src), str(dst))")
        lines.append("")
        lines.append("def process_folder(src_root: Path, dest_root: Path):")
        lines.append("    for root, dirs, files in os.walk(src_root):")
        lines.append("        rpath = Path(root)")
        lines.append("        rel = rpath.relative_to(src_root)")
        lines.append("        out_dir = dest_root / rel")
        lines.append("        for d in dirs:")
        lines.append("            ensure_dir(out_dir / d)")
        lines.append("        for fn in files:")
        lines.append("            s = rpath / fn")
        lines.append("            if should_skip(s):")
        lines.append("                print(f\"SKIP  {s}\")")
        lines.append("                continue")
        lines.append("            d = out_dir / fn")
        lines.append("            if MOVE_MODE:")
        lines.append("                print(f\"MOVE  {s} -> {d}\")")
        lines.append("                move_file(s, d)")
        lines.append("            else:")
        lines.append("                print(f\"COPY  {s} -> {d}\")")
        lines.append("                copy_file(s, d)")
        lines.append("")
        lines.append("def main():")
        lines.append("    dest = Path(DEST_BASE).resolve()")
        lines.append("    ensure_dir(dest)")
        lines.append("    for src_path, dest_name in ITEMS:")
        lines.append("        src = Path(src_path)")
        lines.append("        if not src.exists():")
        lines.append("            print(f\"MISSING (skip): {src}\")")
        lines.append("            continue")
        lines.append("        target = dest / dest_name")
        lines.append("        # Resolve name collision by appending _copyN if needed")
        lines.append("        t = target")
        lines.append("        n = 1")
        lines.append("        while t.exists():")
        lines.append("            t = Path(str(target) + f\"_copy{n}\")")
        lines.append("            n += 1")
        lines.append("        print(f\"PROCESS: {src} -> {t}  (mode={'MOVE' if MOVE_MODE else 'COPY'})\")")
        lines.append("        ensure_dir(t)")
        lines.append("        process_folder(src, t)")
        lines.append("")
        lines.append("if __name__ == '__main__':")
        lines.append("    try:")
        lines.append("        main()")
        lines.append("    except KeyboardInterrupt:")
        lines.append("        print('Interrupted.')")
        lines.append("")
        return "\n".join(lines)

    def _build_gantt_figure(self, bars_by_day, per_day, tick_hours=None):
        """
        Build the Gantt figure with:
          - Unique, deterministic color PER FOLDER (session) across the whole chart
            so each different session gets a distinct color, and split/multi-day
            segments of the same session stay the same color.
          - Faint per-day union overlay
          - Click to show info; click on empty space to close info
          - Optional mpld3 tooltips support via invisible scatter
        """
        import matplotlib
        matplotlib.use("Agg")  # embed in Tk; TkAgg canvas wraps drawing
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import colorsys

        # ---- Settings
        show_grid = True
        dpi = 150
        fig_w = 1200
        fig_h = 700
        if tick_hours is None:
            try:
                tick_hours = int(self._config.get("gantt", "gantt_tick_hours", fallback="1"))
            except Exception:
                tick_hours = 1
        try:
            show_grid = self._config.getboolean("gantt", "gantt_show_grid", fallback=True)
            dpi = int(self._config.get("gantt", "gantt_dpi", fallback="150"))
            fig_w = int(self._config.get("gantt", "gantt_width", fallback="1200"))
            fig_h = int(self._config.get("gantt", "gantt_height", fallback="700"))
        except Exception:
            pass
        tick_hours = max(1, int(tick_hours))

        # ---- Figure / Axes
        fig = plt.Figure(figsize=(max(4, fig_w/96), max(3, fig_h/96)), dpi=dpi)
        ax = fig.add_subplot(111)

        # ---- Collect days and compute x-limits
        days = sorted(bars_by_day.keys())
        if not days:
            ax.text(0.5, 0.5, "No data", ha="center", va="center")
            return fig

        all_starts, all_ends = [], []
        for d in days:
            for b in bars_by_day[d]:
                all_starts.append(b["start_dt"])
                all_ends.append(b["end_dt"])
            for s, e in per_day[d]["union"]:
                all_starts.append(s); all_ends.append(e)
        xmin, xmax = min(all_starts), max(all_ends)

        # ---- Y axis mapping (one row per day)
        y_positions = {d: i for i, d in enumerate(days)}
        y_labels = [d.isoformat() for d in days]

        # ---- UNIQUE color per folder (session), consistent across all days
        # Gather all unique folder names present in the visible data
        unique_folders = []
        seen = set()
        for d in days:
            for b in bars_by_day[d]:
                f = b["folder"]
                if f not in seen:
                    seen.add(f)
                    unique_folders.append(f)

        # Try to use Matplotlib base cycle first, then generate more colors if needed
        base_cycle = []
        try:
            base_cycle = plt.rcParams['axes.prop_cycle'].by_key().get('color', [])
        except Exception:
            base_cycle = []
        # Ensure we have at least N distinct colors
        N = len(unique_folders)
        colors_list = list(base_cycle[:N]) if len(base_cycle) >= N else list(base_cycle)
        if len(colors_list) < N:
            # Generate additional distinct colors in HSV and append
            needed = N - len(colors_list)
            # Evenly spaced hues with medium saturation/value
            gen = []
            for i in range(needed):
                h = i / max(1, needed)   # 0..1
                s = 0.65
                v = 0.9
                r, g, b = colorsys.hsv_to_rgb(h, s, v)
                gen.append((r, g, b))
            colors_list.extend(gen)

        folder_color = {folder: colors_list[i] for i, folder in enumerate(unique_folders)}

        # ---- Faint union overlay (background)
        for d in days:
            y = y_positions[d]
            for s, e in per_day[d]["union"]:
                ax.barh(
                    y=y,
                    width=(mdates.date2num(e) - mdates.date2num(s)),
                    left=mdates.date2num(s),
                    height=0.6, alpha=0.15, align='center'
                )

        # ---- Draw session bars with the per-folder color map
        bar_rects = []
        bar_meta = []
        point_x, point_y, point_labels = [], [], []
        for d in days:
            y = y_positions[d]
            for b in bars_by_day[d]:
                left = mdates.date2num(b["start_dt"])
                width = mdates.date2num(b["end_dt"]) - left
                c = folder_color.get(b["folder"], None)
                rects = ax.barh(
                    y=y, width=width, left=left, height=0.35, align='center',
                    picker=5, color=c
                )
                rect = rects[0]
                bar_rects.append(rect)
                meta = {
                    "date": d,
                    "folder": b["folder"],
                    "start": b["start_dt"],
                    "end": b["end_dt"],
                    "eegno": b["eegno"],
                    "study_name": b["study_name"]
                }
                bar_meta.append(meta)
                # midpoint used for HTML tooltips (mpld3)
                point_x.append(left + width/2.0)
                point_y.append(y)
                s_txt = meta["start"].strftime("%Y-%m-%d %H:%M:%S")
                e_txt = meta["end"].strftime("%Y-%m-%d %H:%M:%S")
                point_labels.append(
                    f"<b>{meta['folder']}</b><br/>{s_txt} → {e_txt}<br/>"
                    f"EegNo={meta['eegno']} &nbsp;&nbsp; StudyName={meta['study_name']}"
                )

        # ---- Axes formatting
        ax.set_yticks(list(y_positions.values()))
        ax.set_yticklabels(y_labels)
        ax.set_ylim(-1, len(days))
        ax.set_xlim(mdates.date2num(xmin), mdates.date2num(xmax))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=tick_hours))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
        if show_grid:
            ax.grid(True, axis="x", linestyle="--", alpha=0.3)
        fig.autofmt_xdate()
        ax.set_xlabel("Time")
        ax.set_ylabel("Date")

        # ---- Click-to-show info (Tk) and click blank to close
        annot = ax.annotate(
            "", xy=(0,0), xytext=(20,20), textcoords="offset points",
            bbox=dict(boxstyle="round", fc="w", ec="0.5", alpha=0.9),
            arrowprops=dict(arrowstyle="->")
        )
        annot.set_visible(False)

        def _format_meta(i):
            m = bar_meta[i]
            s = m["start"].strftime("%Y-%m-%d %H:%M:%S")
            e = m["end"].strftime("%Y-%m-%d %H:%M:%S")
            return (f"{m['folder']}\n{s} → {e}\nEegNo={m['eegno']}  StudyName={m['study_name']}")

        def on_pick(event):
            if event.artist in bar_rects:
                i = bar_rects.index(event.artist)
                rect = bar_rects[i]
                x = rect.get_x() + rect.get_width()/2
                y = rect.get_y() + rect.get_height()/2
                annot.xy = (x, y)
                annot.set_text(_format_meta(i))
                annot.set_visible(True)
                fig.canvas.draw_idle()

        def on_click(event):
            # If click not on any rect: hide annotation (close info)
            if not event.inaxes:
                return
            hit = False
            for r in bar_rects:
                contains, _ = r.contains(event)
                if contains:
                    hit = True
                    break
            if not hit:
                annot.set_visible(False)
                fig.canvas.draw_idle()

        fig.canvas.mpl_connect("pick_event", on_pick)
        fig.canvas.mpl_connect("button_press_event", on_click)

        # ---- Invisible scatter for HTML tooltips (mpld3)
        try:
            sc = ax.scatter(point_x, point_y, alpha=0.0)  # invisible anchors
            fig._tooltip_scatter = sc
            fig._tooltip_labels = point_labels
        except Exception:
            pass

        return fig



    def _coverage_recheck_window(self, win):
        # Recompute from current selection and refresh both widgets
        rows = self._selected_rows()
        valid = [r for r in rows if r.rec_start and r.rec_end]
        if not valid:
            from tkinter import messagebox
            messagebox.showinfo("No valid sessions", "No selected rows have both RecStart and RecEnd.")
            return

        try:
            threshold_hours = float(self._config.get("checker", "threshold_hours", fallback="23"))
        except Exception:
            threshold_hours = 23.0

        bars_by_day = self._clip_selected_sessions_per_day(valid)
        per_day = self._compute_union_and_flags(bars_by_day, threshold_hours)
        report = self._make_coverage_report(bars_by_day, per_day, threshold_hours)

        # Update report text
        txt = win._coverage_text
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.insert("1.0", report)
        txt.configure(state="disabled")

        # Rebuild chart, preserving current tick hours
        tick_hours = getattr(win, "_gantt_tick_hours", 1)
        fig = self._build_gantt_figure(bars_by_day, per_day, tick_hours=max(1, int(tick_hours)))
        canvas = win._coverage_canvas
        win._coverage_fig = fig
        canvas.figure = fig
        canvas.draw()

        # Update state
        win._coverage_bars_by_day = bars_by_day
        win._coverage_per_day = per_day
        win._coverage_threshold = threshold_hours
        self.log("Coverage re-checked.")



    def _save_gantt_and_tsv(self, win):
        import os, csv
        from tkinter import filedialog, messagebox

        fig = win._coverage_fig
        bars_by_day = win._coverage_bars_by_day
        per_day = win._coverage_per_day

        # Prompt for base name; write .png and .tsv
        f = filedialog.asksaveasfilename(
            title="Save Gantt (choose base name)",
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("All files", "*.*")]
        )
        if not f:
            return
        base_no_ext, _ = os.path.splitext(f)
        png_path = base_no_ext + ".png"
        tsv_path = base_no_ext + ".tsv"

        # PNG
        try:
            dpi = int(self._config.get("gantt", "gantt_dpi", fallback="150"))
        except Exception:
            dpi = 150
        try:
            fig.savefig(png_path, dpi=dpi, bbox_inches="tight")
            self.log(f"Saved Gantt PNG: {png_path}")
        except Exception as e:
            messagebox.showerror("Save error", f"Failed to save PNG:\n{e}")
            return

        # TSV: one row per clipped bar
        try:
            with open(tsv_path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh, delimiter='\t')
                w.writerow(["date", "start_time", "end_time", "duration_hours",
                            "folder", "eegno", "study_name",
                            "overlaps_with", "is_multiple_day", "is_overlapping", "is_below_threshold_day"])
                for d in sorted(bars_by_day.keys()):
                    bars = bars_by_day[d]
                    overlaps_map = per_day[d]["overlaps_map"]
                    is_multiple = "true" if per_day[d]["multiple"] else "false"
                    is_below = "true" if per_day[d]["below_threshold"] else "false"
                    for idx, b in enumerate(bars):
                        s = b["start_dt"]
                        e = b["end_dt"]
                        dur_h = (e - s).total_seconds() / 3600.0
                        overlaps_with = ";".join(sorted(set(overlaps_map.get(idx, []))))
                        is_overlap = "true" if overlaps_with else "false"
                        w.writerow([
                            d.isoformat(),
                            s.strftime("%H:%M:%S"),
                            e.strftime("%H:%M:%S"),
                            f"{dur_h:.3f}",
                            b["folder"],
                            b["eegno"],
                            b["study_name"],
                            overlaps_with,
                            is_multiple,
                            is_overlap,
                            is_below
                        ])
            self.log(f"Saved Gantt TSV: {tsv_path}")
        except Exception as e:
            messagebox.showerror("Save error", f"Failed to save TSV:\n{e}")
            return

    def _save_gantt_interactive(self, win):
        import os
        from tkinter import filedialog, messagebox
        try:
            import mpld3
            from mpld3 import plugins
        except Exception:
            messagebox.showinfo(
                "Interactive export",
                "To save an interactive HTML, please install mpld3:\n\n    pip install mpld3"
            )
            return

        f = filedialog.asksaveasfilename(
            title="Save Interactive Gantt (HTML)",
            defaultextension=".html",
            filetypes=[("HTML", "*.html"), ("All files", "*.*")]
        )
        if not f:
            return

        fig = win._coverage_fig

        # Attach tooltips to the invisible scatter we created in _build_gantt_figure
        try:
            sc = getattr(fig, "_tooltip_scatter", None)
            labels = getattr(fig, "_tooltip_labels", None)
            if sc is not None and labels:
                tooltip = plugins.PointHTMLTooltip(sc, labels=labels, voffset=10, hoffset=10, css=None)
                plugins.connect(fig, tooltip)
            # Basic zoom/pan are included by mpld3 by default
        except Exception:
            pass

        # Get the report text
        try:
            report_text = win._coverage_text.get("1.0", "end-1c")
        except Exception:
            report_text = ""

        try:
            html_fig = mpld3.fig_to_html(fig)
            html = f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>Interactive Gantt</title>
    <style>
    body {{ font-family: sans-serif; }}
    pre {{ background:#f7f7f7; padding:10px; border:1px solid #ddd; }}
    </style>
    </head>
    <body>
    <h2>Coverage report</h2>
    <pre>{report_text}</pre>
    <h2>Gantt</h2>
    {html_fig}
    </body>
    </html>
    """
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(html)
            self.log(f"Saved interactive Gantt HTML: {f}")
        except Exception as e:
            messagebox.showerror("Save error", f"Failed to save HTML:\n{e}")

    def _change_tick_hours(self, win, delta):
        # Update tick size and rebuild the chart
        try:
            win._gantt_tick_hours = max(1, int(win._gantt_tick_hours) + int(delta))
        except Exception:
            win._gantt_tick_hours = 1
        win._tick_label_var.set(f"Tick: {win._gantt_tick_hours} h")

        bars_by_day = win._coverage_bars_by_day
        per_day = win._coverage_per_day
        fig = self._build_gantt_figure(bars_by_day, per_day, tick_hours=win._gantt_tick_hours)
        win._coverage_fig = fig
        win._coverage_canvas.figure = fig
        win._coverage_canvas.draw()

    def _nudge_gantt_height(self, win, delta_pixels):
        # Move the sash between report and chart by a few pixels
        paned = win._coverage_paned
        try:
            cur = paned.sashpos(0)
            new_pos = max(80, cur + int(delta_pixels))
            paned.sashpos(0, new_pos)
        except Exception:
            pass

# ---- main ----

def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
