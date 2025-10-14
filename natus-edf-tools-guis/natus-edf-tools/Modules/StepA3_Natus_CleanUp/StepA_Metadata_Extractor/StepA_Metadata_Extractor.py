#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Natus Session Finder GUI
------------------------

What's new in this version
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

        # Row 3: bulk selection + session I/O + copy script
        ttk.Button(frm, text="Select All", command=self._select_all).grid(row=2, column=1, sticky="w", pady=(6,0))
        ttk.Button(frm, text="Select None", command=self._select_none).grid(row=2, column=1, sticky="e", pady=(6,0))
        ttk.Button(frm, text="Save Session", command=self._save_session).grid(row=2, column=4, pady=(6,0))
        ttk.Button(frm, text="Load Session", command=self._load_session).grid(row=2, column=5, pady=(6,0))

        self.var_script_move = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Script: move instead of copy", variable=self.var_script_move).grid(row=2, column=6, pady=(6,0), sticky="w")
        ttk.Button(frm, text="Export Copy Script", command=self._export_copy_script).grid(row=2, column=7, pady=(6,0), padx=6)

        for i in range(9):
            frm.columnconfigure(i, weight=1)

        # Progress bar + label
        pfrm = ttk.Frame(self)
        pfrm.pack(fill="x", padx=10, pady=(0,8))
        self.progress = ttk.Progressbar(pfrm, orient="horizontal", mode="determinate", length=500, maximum=100)
        self.progress.grid(row=0, column=0, sticky="w")
        self.progress_label = ttk.Label(pfrm, text="")
        self.progress_label.grid(row=0, column=1, sticky="w", padx=10)

        # Table with scrollbars
        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True, padx=10, pady=8)

        cols = [
            "selected", "status", "folder_name", "dominant_date", "dom_fraction",
            "total_files", "total_size", "has_eeg", "recent", "study_name",
            "rec_start", "rec_end", "eegno", "machine"
        ]
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=20, selectmode="extended")
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
            "eegno": "EegNo",
            "machine": "Machine",
        }
        widths = {
            "selected": 56, "status": 90, "folder_name": 320, "dominant_date": 120, "dom_fraction": 110,
            "total_files": 80, "total_size": 120, "has_eeg": 70, "recent": 100,
            "study_name": 220, "rec_start": 180, "rec_end": 180, "eegno": 140, "machine": 150
        }
        for c in cols:
            self.tree.heading(c, text=headers[c], command=lambda c=c: self._sort_by(c, False))
            self.tree.column(c, width=widths[c], anchor="w", stretch=True)

        # row coloring via tags
        self.tree.tag_configure("missing", foreground="red")
        self.tree.tag_configure("new", foreground="blue")
        self.tree.tag_configure("present", foreground="black")

        # Mouse + keyboard bindings
        self.tree.bind("<Double-1>", self._toggle_selected_event)
        # Space toggles selection for focused row or all highlighted rows
        self.tree.bind("<space>", self._space_toggle)
        self.tree.focus_set()

        # Log area
        lf = ttk.LabelFrame(self, text="Log")
        lf.pack(fill="both", expand=False, padx=10, pady=(0,10))
        self.txt_log = tk.Text(lf, height=10)
        self.txt_log.pack(fill="both", expand=True)

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
        vals = [
            "Yes" if r.selected else "",
            r.status,
            r.folder_name,
            r.dominant_date,
            f"{r.dom_fraction*100:.1f}%",
            r.total_files,
            human_size(r.total_size),
            "Yes" if r.has_eeg else "No",
            recent_label,
            r.study_name or "",
            r.rec_start or "",
            r.rec_end or "",
            r.eegno or "",
            r.machine or ""
        ]
        tag = "present"
        if r.status == "Missing":
            tag = "missing"
        elif r.status == "New":
            tag = "new"
        self.tree.insert("", "end", iid=r.folder_path, values=vals, tags=(tag,))

    def _refresh_row_in_tree(self, r, recent_label):
        vals = [
            "Yes" if r.selected else "",
            r.status,
            r.folder_name,
            r.dominant_date,
            f"{r.dom_fraction*100:.1f}%",
            r.total_files,
            human_size(r.total_size),
            "Yes" if r.has_eeg else "No",
            recent_label,
            r.study_name or "",
            r.rec_start or "",
            r.rec_end or "",
            r.eegno or "",
            r.machine or ""
        ]
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
                    vals = list(self.tree.item(iid, "values"))
                    vals[0] = "Yes" if r.selected else ""
                    self.tree.item(iid, values=vals)
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
        col_index = self.tree["columns"].index(col)
        data = []
        for iid in self.tree.get_children(""):
            vals = self.tree.item(iid, "values")
            key = vals[col_index]
            try:
                if isinstance(key, str) and key.endswith("%"):
                    k = float(key[:-1])
                else:
                    k = float(str(key).replace(",",""))
            except Exception:
                k = str(key)
            data.append((k, iid, vals))
        data.sort(reverse=descending, key=lambda t: t[0])
        for idx, (_, iid, _) in enumerate(data):
            self.tree.move(iid, "", idx)
        self.tree.heading(col, command=lambda c=col: self._sort_by(c, not descending))

    def _selected_rows(self):
        return [r for r in self.rows if r.selected]

    def _select_all(self):
        for r in self.rows:
            r.selected = True
            if self.tree.exists(r.folder_path):
                vals = list(self.tree.item(r.folder_path, "values"))
                vals[0] = "Yes"
                self.tree.item(r.folder_path, values=vals)

    def _select_none(self):
        for r in self.rows:
            r.selected = False
            if self.tree.exists(r.folder_path):
                vals = list(self.tree.item(r.folder_path, "values"))
                vals[0] = ""
                self.tree.item(r.folder_path, values=vals)

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
                    self.log(f"[meta {i}/{total}] Skipped missing: {r.folder_name}")
                    self._progress_step(step=1, text=f"Quick metadata... {i}/{total or 1}")
                    continue

                meta = quick_extract_metadata(Path(r.folder_path), log=self.log)
                r.study_name = meta.get("StudyName", "") or r.study_name
                r.rec_start = meta.get("RecordingStartTime", "") or r.rec_start
                r.rec_end = meta.get("RecordingEndTime", "") or r.rec_end
                r.eegno = meta.get("EegNo", "") or r.eegno
                r.machine = meta.get("Machine", "") or r.machine

                vals = self.tree.item(r.folder_path, "values")
                recent_label = vals[8] if len(vals) > 8 else "—"
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

# ---- main ----

def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
