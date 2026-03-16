#!/usr/bin/env python3
"""
PHI Redaction Runner  – GUI + CLI
==================================
Index CSV location
------------------
The index CSV path is no longer fixed.  Two modes are supported:

  Auto    – the file is placed inside the output folder, named
            phi_redactor_index.csv.  This is the default when no
            previous setting exists.
  Custom  – the user browses to any .csv file (existing or new).

The resolved path is saved to phi_redactor_settings.ini so the same
choice is restored on the next launch.

Status values written to the index
-----------------------------------
  checked          – user manually set; file is skipped on every run
  processed        – successfully redacted this run
  skipped_uptodate – output file is newer than input; not reprocessed
  skipped_nochange – subprocess produced output identical to input
  error            – subprocess returned non-zero / hard-crashed
  missing          – file listed by glob but not found on disk

Other changes vs original
--------------------------
* Subprocess errors no longer crash the whole run – they are caught,
  logged with the Windows hex exit code, and written to the index so
  the next file continues.
* Settings are persisted to phi_redactor_settings.ini next to this
  script and reloaded automatically on launch.
* An initial sweep runs before processing: missing files get a
  "missing" entry in the index (no exception raised).
"""

import argparse
import configparser
import csv
import glob
import hashlib
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext

from common_libs.organizing_code.environment import load_env_file


# ============================================================
# Script-level constants
# ============================================================

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
SETTINGS_INI  = os.path.join(SCRIPT_DIR, "phi_redactor_settings.ini")
INDEX_COLUMNS = ["rel_path", "status", "last_updated", "notes"]

# Sentinel stored in the INI to mean "place the CSV in the output folder"
AUTO_INDEX = "__auto__"


# ============================================================
# Settings helpers
# ============================================================

def load_settings() -> dict:
    """Return settings dict with sensible defaults."""
    defaults = {
        "input_dir":  "",
        "output_dir": "",
        "extension":  "tsv",
        "recursive":  "false",
        "index_csv":  AUTO_INDEX,   # AUTO_INDEX  or  an absolute path
    }
    cfg = configparser.ConfigParser()
    if os.path.exists(SETTINGS_INI):
        cfg.read(SETTINGS_INI, encoding="utf-8")
        if cfg.has_section("redactor"):
            for key in defaults:
                if cfg.has_option("redactor", key):
                    defaults[key] = cfg.get("redactor", key)
    return defaults


def save_settings(input_dir: str, output_dir: str, extension: str,
                  recursive: bool, index_csv: str) -> None:
    cfg = configparser.ConfigParser()
    cfg["redactor"] = {
        "input_dir":  input_dir,
        "output_dir": output_dir,
        "extension":  extension,
        "recursive":  str(recursive).lower(),
        "index_csv":  index_csv,
    }
    with open(SETTINGS_INI, "w", encoding="utf-8") as fh:
        cfg.write(fh)


def resolve_index_path(index_csv_setting: str, output_dir: str) -> str:
    """
    Turn the raw setting value into an absolute file path.

    AUTO_INDEX  ->  <output_dir>/phi_redactor_index.csv
    anything else -> the literal path stored in the setting
    """
    if index_csv_setting == AUTO_INDEX or not index_csv_setting.strip():
        return os.path.join(os.path.abspath(output_dir),
                            "phi_redactor_index.csv")
    return os.path.abspath(index_csv_setting)


# ============================================================
# Index CSV helpers
# ============================================================

def load_index(index_csv: str) -> dict:
    """Return {rel_path: row_dict} from the index CSV."""
    index = {}
    if not os.path.exists(index_csv):
        return index
    with open(index_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            index[row["rel_path"]] = dict(row)
    return index


def save_index(index: dict, index_csv: str) -> None:
    """Overwrite the index CSV with current in-memory state."""
    os.makedirs(os.path.dirname(index_csv), exist_ok=True)
    with open(index_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=INDEX_COLUMNS)
        writer.writeheader()
        for entry in index.values():
            writer.writerow({col: entry.get(col, "") for col in INDEX_COLUMNS})


def update_index_entry(index: dict, rel_path: str,
                       status: str, notes: str = "") -> None:
    """Upsert one record in the in-memory index."""
    index[rel_path] = {
        "rel_path":     rel_path,
        "status":       status,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "notes":        notes,
    }


# ============================================================
# Utilities
# ============================================================

def file_hash(path: str) -> str:
    """SHA-256 of file content with normalised line endings."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        data = fh.read()
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    h.update(data)
    return h.hexdigest()


def init_logger(output_dir: str, gui_queue=None):
    env_path = os.path.join(SCRIPT_DIR, "../../../../log_path.env")
    env = load_env_file(env_path) if os.path.exists(env_path) else {}

    base_log_dir = env.get(
        "LOG_BASE_DIR",
        os.path.join(os.path.dirname(output_dir), "logs"),
    )
    os.makedirs(base_log_dir, exist_ok=True)

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(base_log_dir, f"redaction_{ts}.log")

    def log(msg: str) -> None:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        if gui_queue is not None:
            gui_queue.put(line)

    log(f"Log file: {log_path}")
    return log


# ============================================================
# Core processing logic
# ============================================================

def process_files(
    input_dir:  str,
    output_dir: str,
    extension:  str  = "tsv",
    recursive:  bool = False,
    index_csv:  str  = AUTO_INDEX,
    gui_queue         = None,
) -> None:

    input_dir  = os.path.abspath(input_dir)
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Resolve AUTO_INDEX so the core logic always sees an explicit path
    index_csv = resolve_index_path(index_csv, output_dir)

    log   = init_logger(output_dir, gui_queue)
    index = load_index(index_csv)

    log(f"Input  : {input_dir}")
    log(f"Output : {output_dir}")
    log(f"Ext    : {extension}   Recursive: {recursive}")
    log(f"Index  : {index_csv}")

    # ── Collect candidates ───────────────────────────────────
    pattern = f"**/*.{extension}" if recursive else f"*.{extension}"
    files   = glob.glob(os.path.join(input_dir, pattern), recursive=recursive)

    if not files:
        log("No files found matching the pattern. Exiting.")
        return

    log(f"Found {len(files)} candidate file(s).  Running initial sweep ...")

    # ── Initial sweep: flag missing files ────────────────────
    candidates = []
    for in_file in files:
        rel_path = os.path.relpath(in_file, input_dir)
        exists   = os.path.isfile(in_file)
        if not exists:
            log(f"WARNING (sweep) - file not found, will skip: {rel_path}")
            update_index_entry(index, rel_path, "missing",
                               "File not found during initial sweep")
        candidates.append((in_file, rel_path, exists))

    save_index(index, index_csv)   # flush missing warnings immediately

    # ── Main loop ────────────────────────────────────────────
    total              = len(candidates)
    n_processed        = 0
    n_skipped_checked  = 0
    n_skipped_uptodate = 0
    n_skipped_nochange = 0
    n_missing          = 0
    n_errors           = 0

    phi_redactor_script = os.path.join(SCRIPT_DIR, "phi_redactor.py")

    for idx, (in_file, rel_path, exists) in enumerate(candidates, 1):
        prefix = f"({idx}/{total}) {rel_path}"

        if not exists:
            n_missing += 1
            continue

        # Skip files the user has manually marked as reviewed
        if index.get(rel_path, {}).get("status") == "checked":
            log(f"SKIP_CHECKED {prefix}")
            n_skipped_checked += 1
            continue

        # Skip if the output is already newer than the input
        out_file = os.path.join(output_dir, rel_path)
        os.makedirs(os.path.dirname(out_file), exist_ok=True)

        if os.path.exists(out_file):
            if os.path.getmtime(out_file) >= os.path.getmtime(in_file):
                log(f"SKIP_UPTODATE {prefix}")
                update_index_entry(index, rel_path, "skipped_uptodate")
                n_skipped_uptodate += 1
                continue

        log(f"PROCESS {prefix}")

        with tempfile.NamedTemporaryFile(
            suffix="." + extension, delete=False
        ) as tmp:
            tmp_path = tmp.name

        cmd = [
            sys.executable,
            phi_redactor_script,
            "predict",
            "--pred_model_path", "../models/redactor/",
            "--checkpoint",      os.path.join(SCRIPT_DIR, "output", "best"),
            "--input_tsv",       in_file,
            "--output_tsv",      tmp_path,
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                log(line.rstrip())
            proc.wait()

            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, cmd)

        except Exception as exc:
            rc      = getattr(exc, "returncode", 0) or 0
            err_msg = (
                f"Subprocess exited with code {rc} "
                f"(0x{rc & 0xFFFFFFFF:08X}). {exc}"
            )
            log(f"ERROR {prefix}: {err_msg}")
            update_index_entry(index, rel_path, "error", err_msg)
            n_errors += 1
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            save_index(index, index_csv)
            continue   # do NOT re-raise; move on to next file

        # No PHI found: output is identical to input
        if file_hash(in_file) == file_hash(tmp_path):
            log(f"NO_CHANGE {prefix} (output not written)")
            os.unlink(tmp_path)
            update_index_entry(index, rel_path, "skipped_nochange",
                               "Hash identical to input - no PHI detected")
            n_skipped_nochange += 1
        else:
            shutil.move(tmp_path, out_file)
            update_index_entry(index, rel_path, "processed")
            n_processed += 1
            log(f"UPDATED {prefix}")

        save_index(index, index_csv)

    # ── Summary ──────────────────────────────────────────────
    log("=" * 60)
    log("DONE")
    log(f"  Processed        : {n_processed}")
    log(f"  Errors (skipped) : {n_errors}")
    log(f"  Skip - checked   : {n_skipped_checked}")
    log(f"  Skip - up-to-date: {n_skipped_uptodate}")
    log(f"  Skip - no change : {n_skipped_nochange}")
    log(f"  Missing (warned) : {n_missing}")
    log(f"  Index file       : {index_csv}")
    log("=" * 60)


# ============================================================
# GUI
# ============================================================

def launch_gui() -> None:
    settings = load_settings()

    root = tk.Tk()
    root.title("PHI Redaction Runner")
    root.geometry("860x660")
    root.resizable(True, True)

    # ── tk variables ─────────────────────────────────────────
    input_dir  = tk.StringVar(value=settings["input_dir"])
    output_dir = tk.StringVar(value=settings["output_dir"])
    extension  = tk.StringVar(value=settings["extension"])
    recursive  = tk.BooleanVar(value=settings["recursive"].lower() == "true")

    # index_mode: "auto" or "custom"
    stored     = settings.get("index_csv", AUTO_INDEX)
    index_mode = tk.StringVar(
        value="auto" if stored == AUTO_INDEX else "custom"
    )
    index_custom = tk.StringVar(
        value="" if stored == AUTO_INDEX else stored
    )

    log_queue = queue.Queue()

    # ── folder browsers ──────────────────────────────────────
    def browse_input():
        path = filedialog.askdirectory(title="Select Input Folder")
        if path:
            input_dir.set(path)

    def browse_output():
        path = filedialog.askdirectory(title="Select Output Folder")
        if path:
            output_dir.set(path)

    def browse_index():
        path = filedialog.asksaveasfilename(
            title="Select or Create Index CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            index_custom.set(path)
            index_mode.set("custom")

    # ── index mode toggle ────────────────────────────────────
    def on_index_mode_change(*_):
        is_custom = index_mode.get() == "custom"
        state = "normal" if is_custom else "disabled"
        index_entry.config(state=state)
        index_browse_btn.config(state=state)
        update_footer()

    # ── path resolution helpers ──────────────────────────────
    def resolved_index_setting() -> str:
        """Return the value to pass to process_files / save_settings."""
        if index_mode.get() == "auto":
            return AUTO_INDEX
        path = index_custom.get().strip()
        return path if path else AUTO_INDEX

    def index_csv_display() -> str:
        """Human-readable resolved path for the footer label."""
        raw = resolved_index_setting()
        if raw == AUTO_INDEX:
            od = output_dir.get().strip()
            if od:
                return os.path.join(os.path.abspath(od),
                                    "phi_redactor_index.csv")
            return "<output folder>/phi_redactor_index.csv"
        return os.path.abspath(raw)

    def open_index():
        path = index_csv_display()
        if "<" in path:
            messagebox.showinfo(
                "Index location",
                "Set an output folder first so the path can be resolved.",
            )
            return
        if os.path.exists(path):
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
        else:
            messagebox.showinfo(
                "Index not found",
                f"No index file yet.\nIt will be created here:\n{path}",
            )

    # ── footer ───────────────────────────────────────────────
    footer_var = tk.StringVar()

    def update_footer(*_):
        footer_var.set(
            f"Settings : {SETTINGS_INI}\n"
            f"Index CSV: {index_csv_display()}\n"
            "(Set status='checked' in the CSV to permanently skip a file)"
        )

    # ── log polling ──────────────────────────────────────────
    def poll_log_queue():
        while not log_queue.empty():
            msg = log_queue.get_nowait()
            log_box.insert(tk.END, msg + "\n")
            log_box.see(tk.END)
        root.after(100, poll_log_queue)

    # ── run ──────────────────────────────────────────────────
    def run():
        if not input_dir.get():
            messagebox.showerror("Error", "Please select an input folder.")
            return
        if not output_dir.get():
            messagebox.showerror("Error", "Please select an output folder.")
            return
        if index_mode.get() == "custom" and not index_custom.get().strip():
            messagebox.showerror(
                "Error",
                "Custom index mode is selected but no path has been entered.\n"
                "Browse to a file or switch back to Auto.",
            )
            return

        raw_index = resolved_index_setting()

        save_settings(
            input_dir.get(),
            output_dir.get(),
            extension.get().strip().lstrip("."),
            recursive.get(),
            raw_index,
        )

        run_btn.config(state=tk.DISABLED)

        def worker():
            try:
                process_files(
                    input_dir  = input_dir.get(),
                    output_dir = output_dir.get(),
                    extension  = extension.get().strip().lstrip("."),
                    recursive  = recursive.get(),
                    index_csv  = raw_index,
                    gui_queue  = log_queue,
                )
            finally:
                log_queue.put("=== FINISHED ===")
                run_btn.config(state=tk.NORMAL)

        threading.Thread(target=worker, daemon=True).start()

    # ── Widget layout ────────────────────────────────────────
    pad = {"padx": 10, "pady": 5}

    # Row 0 – input folder
    tk.Label(root, text="Input Folder").grid(
        row=0, column=0, sticky="w", **pad)
    tk.Entry(root, textvariable=input_dir, width=60).grid(
        row=0, column=1, columnspan=2, sticky="ew")
    tk.Button(root, text="Browse", command=browse_input).grid(
        row=0, column=3, padx=5)

    # Row 1 – output folder
    tk.Label(root, text="Output Folder").grid(
        row=1, column=0, sticky="w", **pad)
    tk.Entry(root, textvariable=output_dir, width=60).grid(
        row=1, column=1, columnspan=2, sticky="ew")
    tk.Button(root, text="Browse", command=browse_output).grid(
        row=1, column=3, padx=5)

    # Row 2 – extension
    tk.Label(root, text="Extension").grid(
        row=2, column=0, sticky="w", **pad)
    tk.Entry(root, textvariable=extension, width=10).grid(
        row=2, column=1, sticky="w")

    # Row 3 – recursive
    tk.Checkbutton(
        root, text="Recursive search", variable=recursive
    ).grid(row=3, column=1, sticky="w", pady=5)

    # Row 4 – index CSV  (label | Auto radio | Custom radio + entry + browse)
    tk.Label(root, text="Index CSV").grid(
        row=4, column=0, sticky="w", **pad)

    index_frame = tk.Frame(root)
    index_frame.grid(row=4, column=1, columnspan=3, sticky="w", pady=5)

    tk.Radiobutton(
        index_frame,
        text="Auto (inside output folder)",
        variable=index_mode,
        value="auto",
        command=on_index_mode_change,
    ).pack(side=tk.LEFT)

    tk.Radiobutton(
        index_frame,
        text="Custom:",
        variable=index_mode,
        value="custom",
        command=on_index_mode_change,
    ).pack(side=tk.LEFT, padx=(14, 0))

    index_entry = tk.Entry(index_frame, textvariable=index_custom, width=36)
    index_entry.pack(side=tk.LEFT, padx=(2, 0))

    index_browse_btn = tk.Button(
        index_frame, text="Browse", command=browse_index
    )
    index_browse_btn.pack(side=tk.LEFT, padx=4)

    on_index_mode_change()   # set initial widget states

    # Row 5 – action buttons
    btn_frame = tk.Frame(root)
    btn_frame.grid(row=5, column=0, columnspan=4, pady=10)

    run_btn = tk.Button(
        btn_frame, text="Run Redaction", command=run, width=18
    )
    run_btn.pack(side=tk.LEFT, padx=8)

    tk.Button(
        btn_frame, text="Open Index CSV", command=open_index, width=18
    ).pack(side=tk.LEFT, padx=8)

    # Row 6 – log box
    log_box = scrolledtext.ScrolledText(
        root, height=18, width=100, state="normal"
    )
    log_box.grid(row=6, column=0, columnspan=4, padx=10, pady=5)

    # Row 7 – footer showing resolved paths
    tk.Label(
        root,
        textvariable=footer_var,
        justify="left",
        fg="#555555",
        font=("TkDefaultFont", 8),
    ).grid(row=7, column=0, columnspan=4, sticky="w", padx=10, pady=(0, 6))

    # Keep footer live as fields change
    for var in (output_dir, index_mode, index_custom):
        var.trace_add("write", update_footer)
    update_footer()

    poll_log_queue()
    root.mainloop()


# ============================================================
# CLI
# ============================================================

def parse_cli():
    parser = argparse.ArgumentParser(
        description="PHI Redaction Runner - CLI mode"
    )
    parser.add_argument("--input",     required=True,
                        help="Input folder containing TSV files")
    parser.add_argument("--output",    required=True,
                        help="Output folder for redacted files")
    parser.add_argument("--ext",       default="tsv",
                        help="File extension to process (default: tsv)")
    parser.add_argument("--recursive", action="store_true",
                        help="Search subfolders recursively")
    parser.add_argument(
        "--index", default=AUTO_INDEX,
        help=(
            "Path to the index CSV.  "
            "Omit to place it automatically inside --output."
        ),
    )
    return parser.parse_args()


# ============================================================
# Entry point
# ============================================================

def main():
    if len(sys.argv) > 1:
        args = parse_cli()
        process_files(
            input_dir  = args.input,
            output_dir = args.output,
            extension  = args.ext,
            recursive  = args.recursive,
            index_csv  = args.index,
        )
    else:
        launch_gui()


if __name__ == "__main__":
    main()
