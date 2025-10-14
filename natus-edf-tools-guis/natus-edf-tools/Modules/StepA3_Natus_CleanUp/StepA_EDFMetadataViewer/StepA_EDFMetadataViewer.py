#!/usr/bin/env python3
"""
EDF Quick Header Extractor GUI

Purpose
-------
Scan a folder of EDF/EDF+ (or BDF/BDF+) files *before anonymization* and extract
key header metadata (start date/time, duration, patient fields, device/equipment, etc.)
using the high‑speed reader `EDF_reader_mld.py`.

Features
--------
- Fast header scan (no samples loaded) using EDF_reader_mld.  
- Recursive or flat folder scan.
- Progress bar + live status.
- Results in a sortable table.
- Select rows (mouse or keyboard). Space toggles selection of focused row.
- Export selected (or all) rows to CSV.
- Double‑click a row for a full metadata popup.
- Open containing folder for a file.

Dependencies
------------
- Python 3.8+
- `EDF_reader_mld.py` in the same directory (or on `PYTHONPATH`).

Run
---
python edf_quick_header_gui.py

"""
from __future__ import annotations
import os
import sys
import csv
import threading
import queue
from datetime import datetime, timedelta
from typing import Dict, Any, List

# ---- EDF reader (user-provided) ----
# Expecting _lhsc_lib.EDF_reader_mld import path to be resolvable from current working directory
# We append a relative hint based on this script's location (two levels up).
current_script_dir = os.path.dirname(os.path.abspath(__file__))
two_levels_up_path = os.path.abspath(os.path.join(current_script_dir, '../../../../../'))
print(two_levels_up_path)
EDF_AVAILABLE = True
sys.path.append(two_levels_up_path)

try:
    # Prefer the high-speed reader the user provided
    from _lhsc_lib.EDF_reader_mld import EDFreader, EDFexception
except Exception as e:
    raise SystemExit(
        "Could not import EDF_reader_mld. Place EDF_reader_mld.py beside this script.\n"
        f"Import error: {e}"
    )

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

APP_TITLE = "EDF Quick Header Extractor (pre‑anonymization)"
SUPPORTED_EXT = {".edf", ".edfz", ".bdf", ".bdfz"}

# --------------------------- Utility helpers ---------------------------------

def human_duration(seconds: float) -> str:
    if seconds < 0:
        return ""
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def edf_meta(path: str) -> Dict[str, Any]:
    """Extract metadata from an EDF/BDF header quickly (no signal data).
    Returns a dict safe for table export.
    """
    meta: Dict[str, Any] = {
        "file": path,
        "start_datetime": "",
        "start_date": "",
        "start_time": "",
        "duration_sec": "",
        "duration_hms": "",
        "patient_plus_name": "",
        "patient_plus_code": "",
        "patient_plus_gender": "",
        "patient_plus_birthdate": "",
        "patient_plus_additional": "",
        "patient_raw": "",
        "technician": "",
        "equipment": "",
        "recording_additional": "",
        "num_signals": "",
        "notes": "",
    }
    try:
        r = EDFreader(path, read_annotations=False)
        try:
            # Start date/time
            dt: datetime = r.getStartDateTime()
            meta["start_datetime"] = dt.isoformat(sep=" ")
            meta["start_date"] = dt.strftime("%Y-%m-%d")
            meta["start_time"] = dt.strftime("%H:%M:%S")

            # Duration (reader uses 100 ns units internally)
            TICKS_PER_SEC = 10_000_000
            duration_ticks = r.getFileDuration()
            duration_sec = float(duration_ticks) / TICKS_PER_SEC
            meta["duration_sec"] = f"{duration_sec:.3f}"
            meta["duration_hms"] = human_duration(duration_sec)

            # Patient/Recording/Equipment (EDF+ only fills the "+" fields)
            meta["patient_plus_name"] = r.getPatientName() or ""
            meta["patient_plus_code"] = r.getPatientCode() or ""
            meta["patient_plus_gender"] = r.getPatientGender() or ""
            meta["patient_plus_birthdate"] = r.getPatientBirthDate() or ""
            meta["patient_plus_additional"] = r.getPatientAdditional() or ""
            meta["patient_raw"] = r.getPatient() or ""  # classic EDF patient field
            meta["technician"] = r.getTechnician() or ""
            meta["equipment"] = r.getEquipment() or ""
            meta["recording_additional"] = r.getRecordingAdditional() or ""
            meta["num_signals"] = r.getNumSignals()
        finally:
            r.close()
    except Exception as e:
        meta["notes"] = f"ERROR: {type(e).__name__}: {e}"
    return meta


# ------------------------------ GUI App --------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x650")
        self.minsize(980, 540)
        self._create_widgets()
        self._bind_keys()
        self.scan_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.q: queue.Queue[Dict[str, Any]] = queue.Queue()
        self.total_files = 0
        self.processed_files = 0

    # ---------- UI setup ----------
    def _create_widgets(self):
        pad = {"padx": 8, "pady": 6}

        top = ttk.Frame(self)
        top.pack(fill=tk.X)

        self.var_dir = tk.StringVar()
        ttk.Label(top, text="Folder:").pack(side=tk.LEFT, **pad)
        self.ent_dir = ttk.Entry(top, textvariable=self.var_dir)
        self.ent_dir.pack(side=tk.LEFT, fill=tk.X, expand=True, **pad)
        ttk.Button(top, text="Browse…", command=self.on_browse).pack(side=tk.LEFT, **pad)

        self.var_recursive = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Recursive", variable=self.var_recursive).pack(side=tk.LEFT, **pad)

        self.btn_scan = ttk.Button(top, text="Scan", command=self.on_scan)
        self.btn_scan.pack(side=tk.LEFT, **pad)
        self.btn_stop = ttk.Button(top, text="Stop", command=self.on_stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, **pad)

        # Progress bar + status line
        prog = ttk.Frame(self)
        prog.pack(fill=tk.X)
        self.pb = ttk.Progressbar(prog, mode="determinate")
        self.pb.pack(side=tk.LEFT, fill=tk.X, expand=True, **pad)
        self.var_status = tk.StringVar(value="Idle")
        ttk.Label(prog, textvariable=self.var_status, width=40, anchor="e").pack(side=tk.LEFT, **pad)

        # Table
        cols = [
            "file",
            "start_date",
            "start_time",
            "duration_hms",
            "patient_plus_name",
            "patient_plus_code",
            "patient_raw",
            "equipment",
            "technician",
            "num_signals",
            "notes",
        ]
        headings = {
            "file": "File",
            "start_date": "Start Date",
            "start_time": "Start Time",
            "duration_hms": "Duration",
            "patient_plus_name": "Patient (+)",
            "patient_plus_code": "Code (+)",
            "patient_raw": "Patient (raw)",
            "equipment": "Device/Equipment",
            "technician": "Technician",
            "num_signals": "#Sig",
            "notes": "Notes",
        }

        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            self.tree.heading(c, text=headings[c], command=lambda c=c: self._sort_by(c, False))
            self.tree.column(c, width=120 if c != "file" else 380, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.tree.bind("<Double-1>", self.on_row_double_click)

        # Bottom bar
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="Export CSV…", command=self.on_export).pack(side=tk.LEFT, **pad)
        ttk.Button(bottom, text="Open Containing Folder", command=self.on_open_folder).pack(side=tk.LEFT, **pad)
        ttk.Button(bottom, text="Clear", command=self.on_clear).pack(side=tk.LEFT, **pad)

    def _bind_keys(self):
        # Space toggles selection on the focused row
        self.tree.bind("<space>", self._toggle_focused_selection)

    # ---------- Event handlers ----------
    def on_browse(self):
        d = filedialog.askdirectory(title="Choose folder with EDF files…")
        if d:
            self.var_dir.set(d)

    def on_scan(self):
        root_dir = self.var_dir.get().strip()
        if not root_dir or not os.path.isdir(root_dir):
            messagebox.showerror("Invalid folder", "Please choose a valid folder.")
            return
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showwarning("Busy", "A scan is already running.")
            return
        self.stop_event.clear()
        self.btn_scan.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self._start_scan_thread(root_dir, self.var_recursive.get())
        self.after(100, self._drain_queue)

    def on_stop(self):
        self.stop_event.set()
        self.var_status.set("Stopping…")

    def on_export(self):
        if not self.tree.get_children():
            messagebox.showinfo("Nothing to export", "No rows in the table.")
            return
        path = filedialog.asksaveasfilename(
            title="Save CSV",
            defaultextension=".csv",
            filetypes=[("CSV", ".csv")],
            initialfile="edf_header_export.csv",
        )
        if not path:
            return
        rows = self._collect_rows(selected_only=True)
        if not rows:
            # if nothing selected, export all
            rows = self._collect_rows(selected_only=False)
        # Column order for export (more complete than on-screen)
        export_cols = [
            "file",
            "start_datetime",
            "start_date",
            "start_time",
            "duration_sec",
            "duration_hms",
            "patient_plus_name",
            "patient_plus_code",
            "patient_plus_gender",
            "patient_plus_birthdate",
            "patient_plus_additional",
            "patient_raw",
            "technician",
            "equipment",
            "recording_additional",
            "num_signals",
            "notes",
        ]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=export_cols)
                w.writeheader()
                for r in rows:
                    w.writerow({k: r.get(k, "") for k in export_cols})
            messagebox.showinfo("Export complete", f"Saved: {path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def on_open_folder(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Select a row", "Select a row first.")
            return
        item = self.tree.item(sel[0])
        path = item["values"][0]
        folder = os.path.dirname(path)
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)
            elif sys.platform == "darwin":
                os.system(f"open '{folder}'")
            else:
                os.system(f"xdg-open '{folder}'")
        except Exception as e:
            messagebox.showerror("Open failed", str(e))

    def on_clear(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.pb.config(value=0, maximum=1)
        self.var_status.set("Idle")
        self.total_files = 0
        self.processed_files = 0

    def on_row_double_click(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        meta = self.tree.set(iid)
        # fetch the full meta dict cached on the item (we store under "_full")
        meta_full = self.tree.item(iid, option="tags")
        # tags is a tuple; we stash a single JSON-ish repr in the first tag when inserting
        # Safer approach: store object refs in a companion dict
        meta_full = _ROW_CACHE.get(iid) or meta
        DetailDialog(self, meta_full)

    def _toggle_focused_selection(self, _event=None):
        focus = self.tree.focus()
        if not focus:
            return "break"
        if focus in self.tree.selection():
            self.tree.selection_remove(focus)
        else:
            self.tree.selection_add(focus)
        return "break"

    # ---------- Scan thread & queue ----------
    def _start_scan_thread(self, root_dir: str, recursive: bool):
        def worker():
            try:
                # 1) Build file list
                files: List[str] = []
                if recursive:
                    for r, _dirs, fnames in os.walk(root_dir):
                        for fn in fnames:
                            if os.path.splitext(fn)[1].lower() in SUPPORTED_EXT:
                                files.append(os.path.join(r, fn))
                else:
                    for fn in os.listdir(root_dir):
                        p = os.path.join(root_dir, fn)
                        if os.path.isfile(p) and os.path.splitext(fn)[1].lower() in SUPPORTED_EXT:
                            files.append(p)
                self.total_files = len(files)
                self.processed_files = 0
                self.q.put({"__control__": "set_total", "total": self.total_files})
                # 2) Scan
                for fp in files:
                    if self.stop_event.is_set():
                        break
                    meta = edf_meta(fp)
                    self.q.put(meta)
                self.q.put({"__control__": "done"})
            except Exception as e:
                self.q.put({"__control__": "error", "err": str(e)})
        self.scan_thread = threading.Thread(target=worker, daemon=True)
        self.scan_thread.start()

    def _drain_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, dict) and item.get("__control__") == "set_total":
                    total = int(item.get("total", 0))
                    self.pb.config(maximum=max(total, 1), value=0)
                    self.var_status.set(f"Found {total} files. Scanning…")
                elif isinstance(item, dict) and item.get("__control__") == "done":
                    self.btn_scan.config(state=tk.NORMAL)
                    self.btn_stop.config(state=tk.DISABLED)
                    if self.stop_event.is_set():
                        self.var_status.set("Stopped.")
                    else:
                        self.var_status.set("Done.")
                elif isinstance(item, dict) and item.get("__control__") == "error":
                    self.btn_scan.config(state=tk.NORMAL)
                    self.btn_stop.config(state=tk.DISABLED)
                    self.var_status.set("Error. See message.")
                    messagebox.showerror("Scan error", item.get("err", "Unknown error"))
                else:
                    self._insert_row(item)
                    self.processed_files += 1
                    self.pb.config(value=self.processed_files)
                    self.var_status.set(f"Processed {self.processed_files} / {self.total_files}")
        except queue.Empty:
            pass
        # keep polling if still running
        if self.scan_thread and self.scan_thread.is_alive():
            self.after(100, self._drain_queue)
        else:
            # ensure buttons reset even if queue drained after thread exit
            self.btn_scan.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)

    # ---------- Table helpers ----------
    def _insert_row(self, meta: Dict[str, Any]):
        values = [
            meta.get("file", ""),
            meta.get("start_date", ""),
            meta.get("start_time", ""),
            meta.get("duration_hms", ""),
            meta.get("patient_plus_name", ""),
            meta.get("patient_plus_code", ""),
            meta.get("patient_raw", ""),
            meta.get("equipment", ""),
            meta.get("technician", ""),
            meta.get("num_signals", ""),
            meta.get("notes", ""),
        ]
        iid = self.tree.insert("", tk.END, values=values)
        _ROW_CACHE[iid] = meta
        if meta.get("notes", "").startswith("ERROR"):
            self.tree.item(iid, tags=("error",))
            self.tree.tag_configure("error", background="#ffecec")

    def _collect_rows(self, selected_only: bool) -> List[Dict[str, Any]]:
        iids = list(self.tree.selection()) if selected_only else list(self.tree.get_children())
        out: List[Dict[str, Any]] = []
        for iid in iids:
            meta = _ROW_CACHE.get(iid)
            if meta:
                out.append(meta)
        return out

    def _sort_by(self, col: str, descending: bool):
        # grab values to sort by
        data = []
        for iid in self.tree.get_children(""):
            meta = _ROW_CACHE.get(iid) or {}
            v = meta.get(col, "")
            # try numeric sort for duration and num_signals
            if col in {"num_signals"}:
                try:
                    v = int(v)
                except Exception:
                    v = -1
            elif col in {"duration_hms"}:
                # convert H:MM:SS to seconds for sort
                parts = str(v).split(":")
                try:
                    if len(parts) == 3:
                        vv = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    elif len(parts) == 2:
                        vv = int(parts[0]) * 60 + int(parts[1])
                    else:
                        vv = 0
                except Exception:
                    vv = 0
                v = vv
            data.append((v, iid))
        data.sort(reverse=descending)
        for index, (_val, iid) in enumerate(data):
            self.tree.move(iid, "", index)
        # switch sort order next click
        self.tree.heading(col, command=lambda c=col: self._sort_by(c, not descending))


# cache of full meta dicts keyed by tree iid
_ROW_CACHE: Dict[str, Dict[str, Any]] = {}


class DetailDialog(tk.Toplevel):
    def __init__(self, master: App, meta: Dict[str, Any]):
        super().__init__(master)
        self.title("File details")
        self.geometry("720x480")
        self.transient(master)
        self.grab_set()
        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        # Two‑column grid of labels
        row = 0
        for k, v in meta.items():
            ttk.Label(frm, text=f"{k}", foreground="#444").grid(row=row, column=0, sticky="w", pady=2)
            ttk.Label(frm, text=str(v)).grid(row=row, column=1, sticky="w", pady=2)
            row += 1
        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=12, pady=(0,12))
        ttk.Button(btns, text="OK", command=self.destroy).pack(side=tk.RIGHT)


if __name__ == "__main__":
    app = App()
    app.mainloop()
