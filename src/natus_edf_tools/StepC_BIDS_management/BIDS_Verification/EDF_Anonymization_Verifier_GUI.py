#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EDF Anonymization Verifier  v1.0
────────────────────────────────────────────────────────────────────────────────
Interactive GUI tool that recursively scans a folder for EDF/BDF files
(plain or inside compressed archives), verifies that every file has been
correctly anonymized, and reports results with full timing information.

Features
  • Folder browser with recursive EDF/archive discovery
  • Overall progress bar  +  per-file archive-peek progress bar
  • Live treeview: file name, type, status, header ✓/✗, annotations ✓/✗,
    time per file, notes
  • ETA, elapsed, avg per file, files remaining counters
  • Abort button (graceful cancellation)
  • Checkbox to enable/disable annotation checking
  • Spinbox to set archive peek size in MB
  • Export results as JSON (full detail) and CSV (summary table)

Architecture
  ┌────────────────────────────────────────┐
  │  Main thread  (Tkinter event loop)     │
  │    App._poll()  ← root.after(80 ms)   │
  └────────────────┬───────────────────────┘
                   │  queue.Queue (thread-safe)
  ┌────────────────▼───────────────────────┐
  │  Worker thread  (_ScanWorker.run)      │
  │    • discovers files                   │
  │    • calls verify_edf_anonymized()     │
  │    • streams archives via              │
  │      stream_edf_bytes()               │
  └────────────────────────────────────────┘

Queue message format: (tag, payload_dict)
  scan_start    {}
  files_found   {total: int}
  file_start    {idx: int, path: str, type: str}
  peek_progress {idx: int, received: int, total: int}
  file_done     {idx: int, path: str, type: str, elapsed: float, result: dict}
  file_error    {idx: int, path: str, type: str, elapsed: float, error: str}
  scan_done     {total_elapsed: float}
  aborted       {completed: int, total: int}
  fatal_error   {error: str}

Path layout:
  EDF_Anonymization_Verifier_GUI.py
    → BIDS_Verification/          (parents[0])
    → StepC_BIDS_management/      (parents[1])
    → natus_edf_tools/             (parents[2])
    → src/                         (parents[3])

Author: Dr. Milad Khaki  (LHSC / Western University)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import csv
import io
import json
import os
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

# ── path bootstrap ────────────────────────────────────────────────────────────
_HERE     = Path(__file__).resolve()
_SRC_ROOT = str(_HERE.parents[3])          # …/src
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from common_libs.anonymization.edf_anonymizer import verify_edf_anonymized   # noqa: E402
from common_libs.archiving.edf_archive_peek import (                         # noqa: E402
    ArchiveStreamError,
    ARCHIVE_SUFFIXES,
    EDF_SUFFIXES,
    MB,
    stream_edf_bytes,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Constants / helpers
# ══════════════════════════════════════════════════════════════════════════════

_APP_TITLE   = "EDF Anonymization Verifier"
_POLL_MS     = 80        # GUI poll interval (ms)
_DEFAULT_MB  = 32        # default archive peek size in MB

# Treeview column definitions: (id, heading, anchor, min_w, stretch)
_TV_COLS = [
    ("#",        "#",          "center",  40,  False),
    ("File",     "File",       "w",      320,  True),
    ("Type",     "Type",       "center",  65,  False),
    ("Status",   "Status",     "center",  80,  False),
    ("Header",   "Header ✓/✗", "center",  85,  False),
    ("Annots",   "Annots ✓/✗", "center",  85,  False),
    ("Time",     "Time (s)",   "center",  70,  False),
    ("Notes",    "Notes",      "w",      200,  True),
]

# Row color tags
_TAG_PASS    = "pass"
_TAG_FAIL    = "fail"
_TAG_ERROR   = "error"
_TAG_RUNNING = "running"
_TAG_PENDING = "pending"

# Which archive suffixes are multi-char (need special endswith logic)
_MULTI_SUFFIXES = {".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar", ".edf.gz", ".bdf.gz"}


def _is_archive(path: Path) -> bool:
    """Return True if *path* looks like a supported compressed archive."""
    name = path.name.lower()
    for s in ARCHIVE_SUFFIXES:
        if name.endswith(s):
            return True
    return False


def _is_plain_edf(path: Path) -> bool:
    return path.suffix.lower() in EDF_SUFFIXES


def _discover_files(root: str) -> list[tuple[Path, str]]:
    """
    Walk *root* recursively and return a list of (path, type) pairs where
    type is 'EDF/BDF' or the archive suffix string.
    """
    found: list[tuple[Path, str]] = []
    for dirpath, _dirs, files in os.walk(root):
        for fname in sorted(files):
            p = Path(dirpath) / fname
            if _is_plain_edf(p):
                found.append((p, "EDF/BDF"))
            elif _is_archive(p):
                # Determine archive type label
                name = fname.lower()
                suffix = ""
                for s in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
                    if name.endswith(s):
                        suffix = s
                        break
                found.append((p, suffix.lstrip(".")))
    return found


def _fmt_seconds(s: float) -> str:
    """Format a duration in seconds as H:MM:SS or M:SS."""
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _safe_str(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "✓" if v else "✗"
    return str(v)


# ══════════════════════════════════════════════════════════════════════════════
#  Worker thread
# ══════════════════════════════════════════════════════════════════════════════

class _ScanWorker(threading.Thread):
    """
    Background thread that scans a folder and verifies every EDF.
    Posts progress messages to *out_queue*.
    """

    def __init__(
        self,
        folder:         str,
        out_queue:      queue.Queue,
        peek_mb:        int,
        check_annots:   bool,
        abort_event:    threading.Event,
    ):
        super().__init__(daemon=True, name="ScanWorker")
        self._folder      = folder
        self._q           = out_queue
        self._peek_bytes  = peek_mb * MB
        self._annots      = check_annots
        self._abort       = abort_event

    # ── helpers ──────────────────────────────────────────────────────────────

    def _post(self, tag: str, **kw):
        self._q.put((tag, kw))

    def _verify_plain(self, path: str, idx: int, file_type: str) -> None:
        self._post("file_start", idx=idx, path=path, type=file_type)
        t0 = time.perf_counter()
        try:
            result = verify_edf_anonymized(
                path,
                require_blank_annotations=self._annots,
            )
            elapsed = time.perf_counter() - t0
            self._post("file_done", idx=idx, path=path, type=file_type,
                       elapsed=elapsed, result=result)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            self._post("file_error", idx=idx, path=path, type=file_type,
                       elapsed=elapsed, error=str(exc))

    def _verify_archive(self, path: str, idx: int, file_type: str) -> None:
        self._post("file_start", idx=idx, path=path, type=file_type)
        t0  = time.perf_counter()
        tmp = None
        try:
            def _pcb(received: int, total: int):
                self._post("peek_progress", idx=idx,
                           received=received, total=total)

            bio, edf_name = stream_edf_bytes(path, self._peek_bytes, _pcb)

            # Write the peeked bytes to a temp file so verify_edf_anonymized
            # can use normal file I/O.
            suffix = Path(edf_name).suffix or ".edf"
            fd, tmp = tempfile.mkstemp(suffix=suffix, prefix="_verif_")
            with os.fdopen(fd, "wb") as fout:
                fout.write(bio.getvalue())

            result = verify_edf_anonymized(
                tmp,
                require_blank_annotations=self._annots,
            )
            # Replace the temp path with the real archive path in the result
            result["path"] = os.path.abspath(path)
            result["archive_member"] = edf_name

            elapsed = time.perf_counter() - t0
            self._post("file_done", idx=idx, path=path, type=file_type,
                       elapsed=elapsed, result=result)

        except (ArchiveStreamError, Exception) as exc:
            elapsed = time.perf_counter() - t0
            self._post("file_error", idx=idx, path=path, type=file_type,
                       elapsed=elapsed, error=str(exc))
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    # ── main run loop ─────────────────────────────────────────────────────────

    def run(self):
        try:
            self._post("scan_start")
            files = _discover_files(self._folder)
            self._post("files_found", total=len(files))
            t_start = time.perf_counter()

            for idx, (path, file_type) in enumerate(files):
                if self._abort.is_set():
                    self._post("aborted", completed=idx, total=len(files))
                    return
                path_str = str(path)
                if file_type == "EDF/BDF":
                    self._verify_plain(path_str, idx, file_type)
                else:
                    self._verify_archive(path_str, idx, file_type)

            self._post("scan_done", total_elapsed=time.perf_counter() - t_start)

        except Exception as exc:
            import traceback
            self._post("fatal_error", error=traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════════════
#  Main application
# ══════════════════════════════════════════════════════════════════════════════

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(_APP_TITLE)
        self.minsize(900, 560)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # State
        self._q:           queue.Queue      = queue.Queue()
        self._abort_event: threading.Event  = threading.Event()
        self._worker:      _ScanWorker | None = None
        self._results:     list[dict]        = []   # one dict per file
        self._total_files: int               = 0
        self._done_files:  int               = 0
        self._t_scan_start: float            = 0.0
        self._running:     bool              = False

        self._build_ui()
        self._set_idle()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        outer = ttk.Frame(self, padding=8)
        outer.grid(sticky="nsew")
        outer.columnconfigure(0, weight=1)

        row = 0

        # ── Folder row ──────────────────────────────────────────────────────
        folder_frame = ttk.LabelFrame(outer, text="Folder to scan", padding=4)
        folder_frame.grid(row=row, column=0, sticky="ew", pady=(0, 6))
        folder_frame.columnconfigure(1, weight=1)

        ttk.Label(folder_frame, text="Folder:").grid(row=0, column=0, padx=(0, 4))
        self._folder_var = tk.StringVar()
        ttk.Entry(folder_frame, textvariable=self._folder_var).grid(
            row=0, column=1, sticky="ew", padx=(0, 4))
        ttk.Button(folder_frame, text="Browse…", command=self._browse).grid(
            row=0, column=2)
        row += 1

        # ── Options row ─────────────────────────────────────────────────────
        opt_frame = ttk.LabelFrame(outer, text="Options", padding=4)
        opt_frame.grid(row=row, column=0, sticky="ew", pady=(0, 6))

        self._check_annots_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt_frame,
            text="Check annotation channels for residual PHI",
            variable=self._check_annots_var,
        ).pack(side="left", padx=(0, 20))

        ttk.Label(opt_frame, text="Archive peek size:").pack(side="left")
        self._peek_mb_var = tk.IntVar(value=_DEFAULT_MB)
        ttk.Spinbox(
            opt_frame,
            from_=4, to=512, increment=4,
            textvariable=self._peek_mb_var,
            width=5,
        ).pack(side="left", padx=(4, 2))
        ttk.Label(opt_frame, text="MB").pack(side="left")
        row += 1

        # ── Action buttons ──────────────────────────────────────────────────
        btn_frame = ttk.Frame(outer)
        btn_frame.grid(row=row, column=0, sticky="ew", pady=(0, 6))

        self._start_btn = ttk.Button(
            btn_frame, text="▶  Start Scan", command=self._start_scan, width=18)
        self._start_btn.pack(side="left", padx=(0, 6))

        self._abort_btn = ttk.Button(
            btn_frame, text="⏹  Abort", command=self._abort_scan,
            width=12, state="disabled")
        self._abort_btn.pack(side="left", padx=(0, 20))

        self._export_json_btn = ttk.Button(
            btn_frame, text="Export JSON", command=self._export_json,
            state="disabled", width=14)
        self._export_json_btn.pack(side="left", padx=(0, 6))

        self._export_csv_btn = ttk.Button(
            btn_frame, text="Export CSV", command=self._export_csv,
            state="disabled", width=14)
        self._export_csv_btn.pack(side="left")
        row += 1

        # ── Progress section ────────────────────────────────────────────────
        prog_frame = ttk.LabelFrame(outer, text="Progress", padding=6)
        prog_frame.grid(row=row, column=0, sticky="ew", pady=(0, 6))
        prog_frame.columnconfigure(1, weight=1)

        ttk.Label(prog_frame, text="Overall:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._overall_bar = ttk.Progressbar(
            prog_frame, orient="horizontal", mode="determinate")
        self._overall_bar.grid(row=0, column=1, sticky="ew")
        self._overall_pct = ttk.Label(prog_frame, text="0 / 0", width=14, anchor="e")
        self._overall_pct.grid(row=0, column=2, padx=(6, 0))

        ttk.Label(prog_frame, text="Archive peek:").grid(row=1, column=0, sticky="w", padx=(0, 6))
        self._peek_bar = ttk.Progressbar(
            prog_frame, orient="horizontal", mode="determinate")
        self._peek_bar.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        self._peek_pct = ttk.Label(prog_frame, text="", width=14, anchor="e")
        self._peek_pct.grid(row=1, column=2, padx=(6, 0))
        row += 1

        # ── Stats row ───────────────────────────────────────────────────────
        stats_frame = ttk.Frame(outer)
        stats_frame.grid(row=row, column=0, sticky="ew", pady=(0, 4))

        def _stat(label):
            ttk.Label(stats_frame, text=label + ":").pack(side="left")
            var = tk.StringVar(value="—")
            ttk.Label(stats_frame, textvariable=var, width=10, anchor="w",
                      foreground="#444").pack(side="left", padx=(2, 16))
            return var

        self._elapsed_var  = _stat("Elapsed")
        self._eta_var      = _stat("ETA")
        self._avg_var      = _stat("Avg/file")
        self._pass_var     = _stat("Pass")
        self._fail_var     = _stat("Fail")
        self._err_var      = _stat("Error")
        row += 1

        # ── Status label ────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(outer, textvariable=self._status_var,
                  foreground="#555").grid(row=row, column=0, sticky="w")
        row += 1

        # ── Treeview ────────────────────────────────────────────────────────
        tv_frame = ttk.Frame(outer)
        tv_frame.grid(row=row, column=0, sticky="nsew", pady=(4, 0))
        tv_frame.columnconfigure(0, weight=1)
        tv_frame.rowconfigure(0, weight=1)
        outer.rowconfigure(row, weight=1)

        col_ids = [c[0] for c in _TV_COLS]
        self._tv = ttk.Treeview(
            tv_frame,
            columns=col_ids,
            show="headings",
            selectmode="browse",
        )
        for col_id, heading, anchor, min_w, stretch in _TV_COLS:
            self._tv.heading(col_id, text=heading)
            self._tv.column(col_id, anchor=anchor, minwidth=min_w,
                            width=min_w, stretch=stretch)

        vsb = ttk.Scrollbar(tv_frame, orient="vertical",   command=self._tv.yview)
        hsb = ttk.Scrollbar(tv_frame, orient="horizontal", command=self._tv.xview)
        self._tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        # Row colour tags
        self._tv.tag_configure(_TAG_PASS,    foreground="#0a6b00", background="#e9f7ea")
        self._tv.tag_configure(_TAG_FAIL,    foreground="#7b0000", background="#fff0f0")
        self._tv.tag_configure(_TAG_ERROR,   foreground="#6b3800", background="#fff8ec")
        self._tv.tag_configure(_TAG_RUNNING, foreground="#003a7b", background="#eaf2ff")
        self._tv.tag_configure(_TAG_PENDING, foreground="#555",    background="#f5f5f5")

        # Internal bookkeeping: map idx → iid
        self._iid_map:   dict[int, str]  = {}
        self._row_data:  list[dict]       = []   # mirrors self._results, richer

    # ── State helpers ─────────────────────────────────────────────────────────

    def _set_idle(self):
        self._start_btn.config(state="normal")
        self._abort_btn.config(state="disabled")
        self._running = False

    def _set_running(self):
        self._start_btn.config(state="disabled")
        self._abort_btn.config(state="normal")
        self._running = True

    # ── Folder browse ─────────────────────────────────────────────────────────

    def _browse(self):
        d = filedialog.askdirectory(
            title="Select folder to scan for EDF files",
            mustexist=True,
        )
        if d:
            self._folder_var.set(d)

    # ── Start / abort ─────────────────────────────────────────────────────────

    def _start_scan(self):
        folder = self._folder_var.get().strip()
        if not folder:
            messagebox.showwarning(_APP_TITLE, "Please choose a folder first.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror(_APP_TITLE, f"Not a directory:\n{folder}")
            return

        # Reset state
        self._results.clear()
        self._row_data.clear()
        self._iid_map.clear()
        self._total_files = 0
        self._done_files  = 0
        self._t_scan_start = time.perf_counter()
        for item in self._tv.get_children():
            self._tv.delete(item)
        self._overall_bar["value"] = 0
        self._peek_bar["value"]    = 0
        self._peek_pct["text"]     = ""
        self._export_json_btn.config(state="disabled")
        self._export_csv_btn.config(state="disabled")
        self._pass_var.set("0")
        self._fail_var.set("0")
        self._err_var.set("0")
        self._elapsed_var.set("0:00")
        self._eta_var.set("—")
        self._avg_var.set("—")

        self._abort_event.clear()
        self._worker = _ScanWorker(
            folder       = folder,
            out_queue    = self._q,
            peek_mb      = self._peek_mb_var.get(),
            check_annots = self._check_annots_var.get(),
            abort_event  = self._abort_event,
        )
        self._worker.start()
        self._set_running()
        self.after(_POLL_MS, self._poll)

    def _abort_scan(self):
        self._abort_event.set()
        self._status_var.set("Aborting…")
        self._abort_btn.config(state="disabled")

    # ── Queue poll ────────────────────────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                tag, payload = self._q.get_nowait()
                self._handle_message(tag, payload)
        except queue.Empty:
            pass

        if self._running:
            # Keep updating elapsed / ETA even between messages
            self._refresh_timing()
            self.after(_POLL_MS, self._poll)

    def _handle_message(self, tag: str, p: dict):
        if tag == "scan_start":
            self._status_var.set("Discovering files…")

        elif tag == "files_found":
            n = p["total"]
            self._total_files = n
            self._overall_bar["maximum"] = max(n, 1)
            self._status_var.set(f"Found {n} file(s). Verifying…")
            if n == 0:
                self._status_var.set("No EDF/BDF or archive files found.")
                self._set_idle()
                self._enable_export()

        elif tag == "file_start":
            idx, path, ftype = p["idx"], p["path"], p["type"]
            short = Path(path).name
            iid = self._tv.insert(
                "", "end",
                values=(idx + 1, short, ftype, "⏳", "…", "…", "…", ""),
                tags=(_TAG_RUNNING,),
            )
            self._tv.see(iid)
            self._iid_map[idx] = iid
            self._row_data.append({
                "idx": idx, "path": path, "type": ftype,
                "status": "running", "result": None, "error": None,
                "elapsed": None,
            })
            self._status_var.set(f"[{idx + 1}/{self._total_files}] {short}")
            self._peek_bar["value"] = 0
            self._peek_pct["text"]  = ""

        elif tag == "peek_progress":
            received, total = p["received"], p["total"]
            self._peek_bar["maximum"] = total
            self._peek_bar["value"]   = received
            pct = 100 * received // total if total else 0
            self._peek_pct["text"]    = f"{received // (1024*1024)}/{total // (1024*1024)} MB  ({pct}%)"

        elif tag == "file_done":
            self._on_file_done(p)

        elif tag == "file_error":
            self._on_file_error(p)

        elif tag == "scan_done":
            elapsed = p["total_elapsed"]
            self._status_var.set(
                f"Scan complete. {self._total_files} file(s) in {_fmt_seconds(elapsed)}.")
            self._set_idle()
            self._enable_export()
            self._peek_bar["value"] = 0
            self._peek_pct["text"]  = ""

        elif tag == "aborted":
            done, total = p["completed"], p["total"]
            self._status_var.set(f"Aborted after {done}/{total} file(s).")
            self._set_idle()
            if self._results:
                self._enable_export()
            self._peek_bar["value"] = 0
            self._peek_pct["text"]  = ""

        elif tag == "fatal_error":
            self._status_var.set("Worker crashed — see error dialog.")
            self._set_idle()
            messagebox.showerror(_APP_TITLE,
                                  f"Scan worker crashed:\n\n{p['error']}")
            if self._results:
                self._enable_export()

    def _on_file_done(self, p: dict):
        idx, path, ftype = p["idx"], p["path"], p["type"]
        elapsed = p["elapsed"]
        result  = p["result"]
        iid     = self._iid_map.get(idx)

        header_ok = result.get("header_ok", False)
        annots_ok = result.get("annotations_blank_ok", None)
        annots_str = _safe_str(annots_ok) if annots_ok is not None else "—"

        overall_pass = header_ok and (annots_ok is not False)
        tag = _TAG_PASS if overall_pass else _TAG_FAIL
        status_str = "PASS" if overall_pass else "FAIL"
        notes_list = result.get("notes", [])
        if result.get("archive_member"):
            notes_list = [f"[{result['archive_member']}]"] + notes_list
        notes_str = "  ".join(notes_list)[:120]

        if iid:
            self._tv.item(iid, values=(
                idx + 1,
                Path(path).name,
                ftype,
                status_str,
                _safe_str(header_ok),
                annots_str,
                f"{elapsed:.2f}",
                notes_str,
            ), tags=(tag,))

        self._done_files += 1
        self._overall_bar["value"] = self._done_files

        rd = {
            "idx": idx, "path": path, "type": ftype,
            "status": status_str, "result": result, "error": None,
            "elapsed": elapsed,
        }
        self._results.append(rd)
        if idx < len(self._row_data):
            self._row_data[idx] = rd

        self._refresh_counts()
        self._refresh_timing()

    def _on_file_error(self, p: dict):
        idx, path, ftype = p["idx"], p["path"], p["type"]
        elapsed = p["elapsed"]
        error   = p["error"]
        iid     = self._iid_map.get(idx)

        if iid:
            self._tv.item(iid, values=(
                idx + 1,
                Path(path).name,
                ftype,
                "ERROR",
                "—", "—",
                f"{elapsed:.2f}",
                error[:120],
            ), tags=(_TAG_ERROR,))

        self._done_files += 1
        self._overall_bar["value"] = self._done_files

        rd = {
            "idx": idx, "path": path, "type": ftype,
            "status": "ERROR", "result": None, "error": error,
            "elapsed": elapsed,
        }
        self._results.append(rd)
        if idx < len(self._row_data):
            self._row_data[idx] = rd

        self._refresh_counts()
        self._refresh_timing()

    def _refresh_counts(self):
        n_pass = sum(1 for r in self._results if r["status"] == "PASS")
        n_fail = sum(1 for r in self._results if r["status"] == "FAIL")
        n_err  = sum(1 for r in self._results if r["status"] == "ERROR")
        self._pass_var.set(str(n_pass))
        self._fail_var.set(str(n_fail))
        self._err_var.set(str(n_err))
        self._overall_pct["text"] = f"{self._done_files} / {self._total_files}"

    def _refresh_timing(self):
        elapsed = time.perf_counter() - self._t_scan_start
        self._elapsed_var.set(_fmt_seconds(elapsed))

        if self._done_files > 0:
            avg = elapsed / self._done_files
            self._avg_var.set(f"{avg:.1f} s")
            remaining = self._total_files - self._done_files
            if remaining > 0:
                eta = avg * remaining
                self._eta_var.set(_fmt_seconds(eta))
            else:
                self._eta_var.set("—")
        else:
            self._avg_var.set("—")
            self._eta_var.set("—")

    def _enable_export(self):
        self._export_json_btn.config(state="normal")
        self._export_csv_btn.config(state="normal")

    # ── Export ────────────────────────────────────────────────────────────────

    def _build_export_data(self) -> list[dict]:
        """Return serialisable list of result records."""
        out = []
        for r in self._results:
            rec: dict = {
                "index":        r["idx"] + 1,
                "path":         r["path"],
                "type":         r["type"],
                "status":       r["status"],
                "elapsed_s":    round(r["elapsed"], 3) if r["elapsed"] is not None else None,
                "error":        r["error"],
            }
            res = r.get("result") or {}
            # Header checks
            rec["header_ok"]           = res.get("header_ok")
            rec["header_patient_ok"]   = res.get("header_patient_ok")
            rec["header_recording_ok"] = res.get("header_recording_ok")
            # EDF structure info
            rec["n_signals"]                   = res.get("n_signals")
            rec["n_records"]                   = res.get("n_records")
            rec["record_duration_s"]           = res.get("record_duration_s")
            rec["n_annotation_channels"]       = res.get("n_annotation_channels")
            rec["annotation_channel_labels"]   = res.get("annotation_channel_labels", [])
            rec["annotation_channels_present"] = res.get("annotation_channels_present")
            # Annotation blank check results
            rec["annotations_blank_ok"]        = res.get("annotations_blank_ok")
            rec["n_records_checked"]           = res.get("n_records_checked")
            rec["n_records_with_phi"]          = res.get("n_records_with_phi")
            rec["non_blank_byte_count"]        = res.get("non_blank_byte_count")
            rec["first_failing_record"]        = res.get("first_failing_record")
            # Annotation content sample (PHI evaluation)
            rec["annotation_content_sample"]   = res.get("annotation_content_sample")
            # Archive info
            rec["archive_member"]              = res.get("archive_member")
            rec["notes"]                       = res.get("notes", [])
            out.append(rec)
        return out

    def _export_json(self):
        if not self._results:
            messagebox.showinfo(_APP_TITLE, "No results to export yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Save JSON results",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="edf_anonymization_results.json",
        )
        if not path:
            return
        data = {
            "tool":    _APP_TITLE,
            "folder":  self._folder_var.get(),
            "results": self._build_export_data(),
            "summary": {
                "total":  self._total_files,
                "pass":   int(self._pass_var.get() or 0),
                "fail":   int(self._fail_var.get() or 0),
                "error":  int(self._err_var.get() or 0),
                "elapsed_s": round(time.perf_counter() - self._t_scan_start, 2),
            },
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            messagebox.showinfo(_APP_TITLE, f"JSON saved:\n{path}")
        except Exception as exc:
            messagebox.showerror(_APP_TITLE, f"Failed to save JSON:\n{exc}")

    def _export_csv(self):
        if not self._results:
            messagebox.showinfo(_APP_TITLE, "No results to export yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Save CSV results",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="edf_anonymization_results.csv",
        )
        if not path:
            return
        records = self._build_export_data()
        fieldnames = [
            "index", "path", "type", "status", "elapsed_s",
            "header_ok", "header_patient_ok", "header_recording_ok",
            "n_signals", "n_records", "record_duration_s",
            "n_annotation_channels", "annotation_channel_labels",
            "annotation_channels_present", "annotations_blank_ok",
            "n_records_checked", "n_records_with_phi",
            "non_blank_byte_count", "first_failing_record",
            "annotation_content_sample",
            "archive_member", "notes", "error",
        ]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames,
                                        extrasaction="ignore")
                writer.writeheader()
                for rec in records:
                    rec = dict(rec)
                    # Flatten list fields to semicolon-separated strings for CSV
                    rec["notes"] = "; ".join(rec.get("notes") or [])
                    rec["annotation_channel_labels"] = "; ".join(rec.get("annotation_channel_labels") or [])
                    # Flatten TAL sample to "onset: text1, text2 | onset: text1 ..." for CSV
                    sample = rec.get("annotation_content_sample") or []
                    rec["annotation_content_sample"] = " | ".join(
                        f"{e['onset']}: {', '.join(e['texts'])}" for e in sample if e.get("texts")
                    ) or ""
                    writer.writerow(rec)
            messagebox.showinfo(_APP_TITLE, f"CSV saved:\n{path}")
        except Exception as exc:
            messagebox.showerror(_APP_TITLE, f"Failed to save CSV:\n{exc}")


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
