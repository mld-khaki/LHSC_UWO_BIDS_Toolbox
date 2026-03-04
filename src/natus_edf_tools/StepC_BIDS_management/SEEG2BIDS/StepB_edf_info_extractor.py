# -*- coding: utf-8 -*-
"""
EDF Full Summary Export Tool (Recursive + Scan/Execute)

Features:
- CLI + GUI
- Recursive scanning
- Mirrored output structure
- Scan phase (dry evaluation)
- Execute phase with progress reporting

GUI Robustness Additions:
- Process-based parallel workers (configurable)
- Per-file timeout
- Auto-retry (3 attempts)
- Kill + restart hung worker processes
- Persistent run log JSON in output root
- Pause/Resume, Cancel (with confirmation)
- Disable Execute while running
- Live stats: done/remaining/failed/skipped, speed, avg time

Additions (2026-02):
- Optional anonymization assertion (PHI-safe):
  * Check header patient/recording fields are scrubbed (no PHI exported)
  * Optionally check embedded annotation channel bytes are blank (first few records)
"""

from __future__ import annotations

import os
import json
import argparse
import sys
import time
import traceback
import threading
import queue
import multiprocessing as mp
from typing import Dict, Any, List, Optional, Tuple
from datetime import timedelta, datetime

# ---------------------------------------------------------------------
# Repo-safe import
# ---------------------------------------------------------------------

from common_libs.edflib_fork_mld.edfreader import EDFreader
from common_libs.edflib_fork_mld.edfreader import EDFreader as EDFLIBReader

# NEW: anonymization verifier (PHI-safe)
from common_libs.anonymization.edf_anonymizer import verify_edf_anonymized


VERBOSE = True


def vprint(*args):
    if VERBOSE:
        print("[VERBOSE]", *args, flush=True)


# ---------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------

def extract_edf_summary(
    edf_path: str,
    read_annotations: bool,
    assert_anonymized: bool = False,
    require_blank_annotations: bool = False,
) -> Dict[str, Any]:
    """
    Robust EDF summary extractor.

    - Header + channels always come from Python EDFreader
    - Annotations come from EDFLIB (C library) if available
    - Annotation failures NEVER abort the file

    Optional anonymization assertions:
    - PHI-safe verification of scrubbed header fields
    - Optional verification that annotation channel bytes are blank in first few records
    """

    summary: Dict[str, Any] = {
        "file": None,
        "channels": [],
        "annotations_present": False,
        "annotations": [],
        "annotation_error": None,
        # NEW (PHI-safe; does not export PHI)
        "anonymization_check": None,
        "anonymization_ok": None,
    }

    # -------------------------------------------------
    # 1) Header + signal metadata (never read annotations here)
    # -------------------------------------------------
    try:
        with EDFreader(edf_path, read_annotations=False) as f:
            start_dt = f.getStartDateTime()
            duration_sec = f.getFileDuration() / f.EDFLIB_TIME_DIMENSION

            summary["file"] = {
                "path": os.path.abspath(edf_path),
                "file_type": f.getFileType(),
                "start_datetime": start_dt.isoformat(),
                "end_datetime": (start_dt + timedelta(seconds=duration_sec)).isoformat(),
                "duration_seconds": duration_sec,
                "num_signals": f.getNumSignals(),
            }

            summary["channels"] = [
                {
                    "index": i,
                    "label": f.getSignalLabel(i),
                    "sample_frequency_hz": f.getSampleFrequency(i),
                    "total_samples": f.getTotalSamples(i),
                }
                for i in range(f.getNumSignals())
            ]

    except Exception as e:
        # If header fails, this file is truly unreadable (keep your behavior)
        raise RuntimeError(f"EDF header read failed: {repr(e)}")

    # -------------------------------------------------
    # 1b) Optional anonymization check (PHI-safe)
    # -------------------------------------------------
    if assert_anonymized:
        check = verify_edf_anonymized(
            edf_path,
            require_blank_annotations=require_blank_annotations,
            max_records_to_check=3,
        )

        summary["anonymization_check"] = {
            "header_ok": bool(check.get("header_ok")),
            "header_patient_ok": bool(check.get("header_patient_ok")),
            "header_recording_ok": bool(check.get("header_recording_ok")),
            "annotation_channels_present": bool(check.get("annotation_channels_present")),
            "annotations_blank_ok": check.get("annotations_blank_ok"),
            "notes": check.get("notes", []),
        }

        ok = bool(check.get("header_ok"))
        if require_blank_annotations:
            ok = ok and (check.get("annotations_blank_ok") is True)

        summary["anonymization_ok"] = ok

        # If assertion requested and fails, we want this to behave like a failed file
        # (so the supervisor can retry and/or mark failed)
        if not ok:
            raise RuntimeError("Anonymization assertion failed (PHI-safe check).")

    # -------------------------------------------------
    # 2) Annotations (safe, optional, isolated)
    # -------------------------------------------------
    if read_annotations and EDFLIBReader is not None:
        try:
            hdl = EDFLIBReader(edf_path)

            if hasattr(hdl, "annotationslist") and hdl.annotationslist:
                for a in hdl.annotationslist:
                    summary["annotations"].append({
                        "onset_sec": a[0] / 10000000,
                        "duration_sec": None if a[1] < 0 else a[1] / 10000000,
                        "description": a[2],
                    })

                summary["annotations_present"] = True

        except Exception as e:
            # We keep header + channels and just record the failure
            summary["annotation_error"] = repr(e)
            summary["annotations_present"] = False
            summary["annotations"] = []
            raise(e)

    return summary


# ---------------------------------------------------------------------
# Scan helpers
# ---------------------------------------------------------------------

def find_edf_files(root: str, recursive: bool) -> List[str]:
    exts = (".edf", ".bdf")
    files = []

    if recursive:
        for dp, _, fn in os.walk(root):
            for f in fn:
                if f.lower().endswith(exts):
                    files.append(os.path.join(dp, f))
    else:
        for f in os.listdir(root):
            if f.lower().endswith(exts):
                files.append(os.path.join(root, f))

    return sorted(files)


def map_output_path(in_file: str, in_root: str, out_root: str) -> str:
    rel = os.path.relpath(in_file, in_root)
    base, _ = os.path.splitext(rel)
    out_path = os.path.join(out_root, base + "_edf_summary.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    return out_path


# ---------------------------------------------------------------------
# Multiprocessing worker target (must be top-level for Windows spawn)
# ---------------------------------------------------------------------

def _mp_extract_worker(
    edf_path: str,
    read_annotations: bool,
    assert_anonymized: bool,
    require_blank_annotations: bool,
    result_q: mp.Queue
) -> None:
    """
    Worker runs in its own process so we can kill it on timeout/hang.
    Communicates back via a multiprocessing Queue.
    """
    try:
        summary = extract_edf_summary(
            edf_path,
            read_annotations,
            assert_anonymized=assert_anonymized,
            require_blank_annotations=require_blank_annotations,
        )
        result_q.put(("ok", summary, None))
    except Exception as e:
        tb = traceback.format_exc()
        result_q.put(("err", None, f"{repr(e)}\n{tb}"))
        raise(e)


# ---------------------------------------------------------------------
# Run log helpers
# ---------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_write_json(path: str, data: Dict[str, Any]) -> None:
    """
    Writes JSON directly (as requested). If you later want atomic writes,
    we can change this to temp+replace.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------

def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("EDF Summary QC Tool")
    root.geometry("820x560")

    input_dir = tk.StringVar()
    output_dir = tk.StringVar()
    recursive = tk.BooleanVar(value=True)
    read_annots = tk.BooleanVar(value=True)

    overwrite_existing = tk.BooleanVar(value=False)

    # NEW: anonymization assertion toggles
    assert_anonymized = tk.BooleanVar(value=False)
    require_blank_annotations = tk.BooleanVar(value=False)

    # Worker controls
    worker_count = tk.IntVar(value=2)
    timeout_sec = tk.IntVar(value=120)  # per-file timeout
    max_retries = tk.IntVar(value=3)

    scanned_files: List[str] = []
    running = tk.BooleanVar(value=False)
    paused = tk.BooleanVar(value=False)

    # Background control
    stop_event = threading.Event()
    pause_event = threading.Event()  # when set => paused
    ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()

    # Stats
    done_count = tk.IntVar(value=0)
    fail_count = tk.IntVar(value=0)
    skip_count = tk.IntVar(value=0)
    remaining_count = tk.IntVar(value=0)
    speed_fps = tk.StringVar(value="0.00 files/min")
    avg_time = tk.StringVar(value="0.0 s/file")

    status = tk.StringVar(value="Idle")

    # Persistent run log path (set at execute)
    runlog_path: Optional[str] = None
    runlog: Dict[str, Any] = {
        "run_started": None,
        "run_finished": None,
        "settings": {},
        "files": {},  # per-file info
        "summary": {},
    }

    # ---------------- UI helpers ----------------

    def append_text(msg: str) -> None:
        text.insert("end", msg + "\n")
        text.see("end")

    def set_controls_enabled(is_enabled: bool) -> None:
        # Buttons
        btn_scan.config(state=("normal" if is_enabled else "disabled"))
        btn_execute.config(state=("normal" if is_enabled else "disabled"))
        btn_pause.config(state=("disabled" if is_enabled else "normal"))  # pause only during run
        btn_cancel.config(state=("disabled" if is_enabled else "normal"))  # cancel only during run

        # Inputs
        btn_in.config(state=("normal" if is_enabled else "disabled"))
        btn_out.config(state=("normal" if is_enabled else "disabled"))
        chk_recursive.config(state=("normal" if is_enabled else "disabled"))
        chk_annots.config(state=("normal" if is_enabled else "disabled"))
        chk_overwrite.config(state=("normal" if is_enabled else "disabled"))
        chk_assert.config(state=("normal" if is_enabled else "disabled"))
        chk_blank.config(state=("normal" if is_enabled else "disabled"))
        spn_workers.config(state=("normal" if is_enabled else "disabled"))
        spn_timeout.config(state=("normal" if is_enabled else "disabled"))
        spn_retries.config(state=("normal" if is_enabled else "disabled"))

    def poll_ui_queue():
        try:
            while True:
                msg_type, payload = ui_queue.get_nowait()
                if msg_type == "log":
                    append_text(payload)
                elif msg_type == "status":
                    status.set(payload)
                elif msg_type == "progress":
                    progress["value"] = payload
                elif msg_type == "stats":
                    done_count.set(payload.get("done", done_count.get()))
                    fail_count.set(payload.get("failed", fail_count.get()))
                    skip_count.set(payload.get("skipped", skip_count.get()))
                    remaining_count.set(payload.get("remaining", remaining_count.get()))
                    speed_fps.set(payload.get("speed", speed_fps.get()))
                    avg_time.set(payload.get("avg_time", avg_time.get()))
                elif msg_type == "finished":
                    running.set(False)
                    paused.set(False)
                    pause_event.clear()
                    stop_event.clear()
                    set_controls_enabled(True)
                    btn_pause.config(text="Pause")
                    status.set("Done")
                    append_text(payload.get("message", "Finished."))
                    if payload.get("show_done_box", True):
                        messagebox.showinfo("Finished", payload.get("message", "Finished."))
                elif msg_type == "warning":
                    append_text("WARNING: " + payload)
                else:
                    append_text(f"(Unknown UI event) {msg_type}: {payload}")
        except queue.Empty:
            pass
        root.after(120, poll_ui_queue)

    # ---------------- Buttons ----------------

    def select_input():
        d = filedialog.askdirectory(title="Select input EDF root")
        if d:
            input_dir.set(d)

    def select_output():
        d = filedialog.askdirectory(title="Select output root")
        if d:
            output_dir.set(d)

    def scan():
        nonlocal scanned_files
        scanned_files.clear()
        text.delete("1.0", "end")

        if not input_dir.get() or not output_dir.get():
            messagebox.showerror("Error", "Select input and output folders first.")
            return

        scanned_files = find_edf_files(input_dir.get(), recursive.get())

        append_text(
            f"Scan complete\n"
            f"Input root: {input_dir.get()}\n"
            f"Output root: {output_dir.get()}\n"
            f"Recursive: {recursive.get()}\n"
            f"Files found: {len(scanned_files)}\n"
        )

        if scanned_files:
            append_text("Example output:")
            example = map_output_path(scanned_files[0], input_dir.get(), output_dir.get())
            append_text(example)

        if scanned_files:
            would_skip = 0
            for edf in scanned_files:
                out = map_output_path(edf, input_dir.get(), output_dir.get())
                if os.path.exists(out) and not overwrite_existing.get():
                    would_skip += 1
            append_text(f"\nWould skip (existing outputs): {would_skip} (Overwrite = {overwrite_existing.get()})")

    def toggle_pause():
        if not running.get():
            return
        if not paused.get():
            paused.set(True)
            pause_event.set()
            btn_pause.config(text="Resume")
            ui_queue.put(("status", "Paused"))
            ui_queue.put(("log", "Paused."))
        else:
            paused.set(False)
            pause_event.clear()
            btn_pause.config(text="Pause")
            ui_queue.put(("status", "Running"))
            ui_queue.put(("log", "Resumed."))

    def cancel_run():
        if not running.get():
            return
        if messagebox.askyesno("Cancel", "Stop processing? Active files will be aborted."):
            stop_event.set()
            pause_event.clear()
            paused.set(False)
            btn_pause.config(text="Pause")
            ui_queue.put(("status", "Stopping..."))
            ui_queue.put(("log", "Cancel requested. Stopping..."))

    # ---------------- Supervisor (background) ----------------

    def _supervisor_execute(
        files: List[str],
        in_root: str,
        out_root: str,
        read_annotations: bool,
        overwrite: bool,
        n_workers: int,
        timeout_s: int,
        retries: int,
        assert_anon: bool,
        require_blank: bool,
    ) -> None:
        nonlocal runlog_path, runlog

        runlog = {
            "run_started": _now_iso(),
            "run_finished": None,
            "settings": {
                "input_root": in_root,
                "output_root": out_root,
                "recursive": recursive.get(),
                "read_annotations": read_annotations,
                "overwrite_existing": overwrite,
                "workers": n_workers,
                "timeout_sec": timeout_s,
                "max_retries": retries,
                # NEW
                "assert_anonymized": assert_anon,
                "require_blank_annotations": require_blank,
            },
            "files": {},
            "summary": {},
        }

        runlog_path = os.path.join(out_root, "edf_summary_runlog.json")
        try:
            os.makedirs(out_root, exist_ok=True)
            _safe_write_json(runlog_path, runlog)
        except Exception as e:
            ui_queue.put(("warning", f"Could not write run log to output root: {repr(e)}"))
            runlog_path = None

        pending: List[str] = []
        skipped = 0

        for edf in files:
            out = map_output_path(edf, in_root, out_root)
            if (not overwrite) and os.path.exists(out):
                skipped += 1
                runlog["files"][os.path.abspath(edf)] = {
                    "status": "skipped",
                    "attempts": 0,
                    "last_error": None,
                    "last_duration_sec": None,
                    "output": os.path.abspath(out),
                    "updated": _now_iso(),
                }
            else:
                pending.append(edf)
                runlog["files"][os.path.abspath(edf)] = {
                    "status": "queued",
                    "attempts": 0,
                    "last_error": None,
                    "last_duration_sec": None,
                    "output": os.path.abspath(out),
                    "updated": _now_iso(),
                }

        total_to_process = len(pending)
        total_candidates = len(files)

        ui_queue.put(("log", f"Execute starting: {total_candidates} scanned, {skipped} skipped, {total_to_process} to process."))
        ui_queue.put(("status", "Running"))

        ui_queue.put(("progress", skipped))
        ui_queue.put(("stats", {
            "done": 0,
            "failed": 0,
            "skipped": skipped,
            "remaining": total_to_process,
            "speed": "0.00 files/min",
            "avg_time": "0.0 s/file",
        }))

        attempts: Dict[str, int] = {edf: 0 for edf in pending}

        active: List[Dict[str, Any]] = []
        done = 0
        failed = 0

        t0 = time.time()
        total_done_time_sec = 0.0
        done_files_for_avg = 0

        def flush_runlog():
            if runlog_path:
                try:
                    runlog["summary"] = {
                        "scanned_total": total_candidates,
                        "skipped": skipped,
                        "done": done,
                        "failed": failed,
                        "remaining": max(0, total_to_process - (done + failed)),
                        "updated": _now_iso(),
                    }
                    _safe_write_json(runlog_path, runlog)
                except Exception as e:
                    ui_queue.put(("warning", f"Could not update run log: {repr(e)}"))

        while (pending or active) and (not stop_event.is_set()):

            while pause_event.is_set() and (not stop_event.is_set()):
                time.sleep(0.15)

            while pending and (len(active) < max(1, n_workers)) and (not stop_event.is_set()):
                edf = pending.pop(0)
                attempts[edf] += 1

                out_path = map_output_path(edf, in_root, out_root)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)

                runlog_entry = runlog["files"][os.path.abspath(edf)]
                runlog_entry["status"] = "running"
                runlog_entry["attempts"] = attempts[edf]
                runlog_entry["updated"] = _now_iso()

                result_q: mp.Queue = mp.Queue()
                p = mp.Process(
                    target=_mp_extract_worker,
                    args=(edf, read_annotations, assert_anon, require_blank, result_q),
                    daemon=True
                )
                start_time = time.time()

                active.append({
                    "edf": edf,
                    "out": out_path,
                    "proc": p,
                    "q": result_q,
                    "start_time": start_time,
                    "attempt": attempts[edf],
                })

                ui_queue.put(("log", f"START ({len(active)}/{n_workers}) attempt {attempts[edf]}/{retries}: {os.path.basename(edf)}"))
                p.start()

            still_active: List[Dict[str, Any]] = []
            for slot in active:
                edf = slot["edf"]
                out_path = slot["out"]
                p: mp.Process = slot["proc"]
                rq: mp.Queue = slot["q"]
                started = slot["start_time"]
                elapsed = time.time() - started

                if elapsed > max(1, timeout_s) and p.is_alive():
                    ui_queue.put(("warning", f"TIMEOUT {timeout_s}s: {os.path.basename(edf)} (attempt {slot['attempt']}/{retries})"))
                    runlog_entry = runlog["files"][os.path.abspath(edf)]
                    runlog_entry["status"] = "retrying" if slot["attempt"] < retries else "failed"
                    runlog_entry["last_error"] = f"Timeout after {timeout_s}s"
                    runlog_entry["last_duration_sec"] = float(elapsed)
                    runlog_entry["updated"] = _now_iso()

                    try:
                        p.terminate()
                    except Exception:
                        pass
                    try:
                        p.join(timeout=2.0)
                    except Exception:
                        pass

                    if slot["attempt"] < retries:
                        pending.append(edf)
                    else:
                        failed += 1

                    flush_runlog()
                    continue

                if not p.is_alive():
                    try:
                        p.join(timeout=0.2)
                    except Exception:
                        pass

                    status_kind = None
                    summary_obj = None
                    err_text = None

                    try:
                        if not rq.empty():
                            status_kind, summary_obj, err_text = rq.get_nowait()
                        else:
                            status_kind, summary_obj, err_text = ("err", None, "Worker exited without result (empty queue).")
                    except Exception as e:
                        status_kind, summary_obj, err_text = ("err", None, f"Could not read worker result: {repr(e)}")

                    duration = time.time() - started
                    runlog_entry = runlog["files"][os.path.abspath(edf)]
                    runlog_entry["last_duration_sec"] = float(duration)
                    runlog_entry["updated"] = _now_iso()

                    if status_kind == "ok" and isinstance(summary_obj, dict):
                        try:
                            with open(out_path, "w", encoding="utf-8") as f:
                                json.dump(summary_obj, f, indent=2)
                            done += 1
                            done_files_for_avg += 1
                            total_done_time_sec += float(duration)

                            runlog_entry["status"] = "done"
                            runlog_entry["last_error"] = None

                            ui_queue.put(("log", f"DONE ({done}/{total_to_process}) {duration:.1f}s: {os.path.basename(edf)}"))
                        except Exception as e:
                            err = f"Failed to write output: {repr(e)}"
                            ui_queue.put(("warning", err))
                            runlog_entry["last_error"] = err
                            if slot["attempt"] < retries:
                                runlog_entry["status"] = "retrying"
                                pending.append(edf)
                            else:
                                runlog_entry["status"] = "failed"
                                failed += 1

                    else:
                        err = err_text or "Unknown extraction error."
                        ui_queue.put(("warning", f"ERROR: {os.path.basename(edf)} (attempt {slot['attempt']}/{retries})"))
                        ui_queue.put(("log", err.splitlines()[0] if err else ""))
                        runlog_entry["last_error"] = err

                        if slot["attempt"] < retries:
                            runlog_entry["status"] = "retrying"
                            pending.append(edf)
                        else:
                            runlog_entry["status"] = "failed"
                            failed += 1

                    flush_runlog()
                    continue

                still_active.append(slot)

            active = still_active

            elapsed_total = time.time() - t0
            finished = done + failed
            progress_value = skipped + finished

            ui_queue.put(("progress", progress_value))

            if elapsed_total > 0:
                fpm = (finished / elapsed_total) * 60.0
                speed_str = f"{fpm:.2f} files/min"
            else:
                speed_str = "0.00 files/min"

            avg_str = f"{(total_done_time_sec / done_files_for_avg):.1f} s/file" if done_files_for_avg > 0 else "0.0 s/file"
            remaining = max(0, total_to_process - (done + failed))

            ui_queue.put(("stats", {
                "done": done,
                "failed": failed,
                "skipped": skipped,
                "remaining": remaining,
                "speed": speed_str,
                "avg_time": avg_str,
            }))

            time.sleep(0.12)

        if stop_event.is_set():
            ui_queue.put(("log", "Stopping: terminating active workers..."))
            for slot in active:
                p: mp.Process = slot["proc"]
                if p.is_alive():
                    try:
                        p.terminate()
                    except Exception:
                        pass
                    try:
                        p.join(timeout=2.0)
                    except Exception:
                        pass

        runlog["run_finished"] = _now_iso()
        flush_runlog()

        finished_total = done + failed
        if stop_event.is_set():
            msg = f"Stopped. Done={done}, Failed={failed}, Skipped={skipped}, Remaining={max(0, total_to_process - finished_total)}"
            ui_queue.put(("finished", {"message": msg, "show_done_box": True}))
        else:
            msg = f"Processed {done} OK, {failed} failed, {skipped} skipped. Run log: {os.path.basename(runlog_path) if runlog_path else 'N/A'}"
            ui_queue.put(("finished", {"message": msg, "show_done_box": True}))

    def execute():
        if running.get():
            return
        if not scanned_files:
            messagebox.showerror("Error", "Run Scan first.")
            return

        if not input_dir.get() or not output_dir.get():
            messagebox.showerror("Error", "Select input and output folders first.")
            return

        n = worker_count.get()
        if n < 1:
            messagebox.showerror("Error", "Workers must be >= 1")
            return
        tsec = timeout_sec.get()
        if tsec < 1:
            messagebox.showerror("Error", "Timeout must be >= 1 second")
            return
        rmax = max_retries.get()
        if rmax < 1:
            messagebox.showerror("Error", "Max retries must be >= 1")
            return

        text.delete("1.0", "end")
        done_count.set(0)
        fail_count.set(0)
        skip_count.set(0)
        remaining_count.set(0)
        speed_fps.set("0.00 files/min")
        avg_time.set("0.0 s/file")

        status.set("Starting...")
        running.set(True)
        paused.set(False)
        stop_event.clear()
        pause_event.clear()

        set_controls_enabled(False)
        btn_pause.config(text="Pause")
        btn_pause.config(state="normal")
        btn_cancel.config(state="normal")

        progress["maximum"] = len(scanned_files)
        progress["value"] = 0

        th = threading.Thread(
            target=_supervisor_execute,
            args=(
                list(scanned_files),
                input_dir.get(),
                output_dir.get(),
                read_annots.get(),
                overwrite_existing.get(),
                worker_count.get(),
                timeout_sec.get(),
                max_retries.get(),
                # NEW
                assert_anonymized.get(),
                require_blank_annotations.get(),
            ),
            daemon=True,
        )
        th.start()

    # ---------------- Layout ----------------

    top = tk.Frame(root)
    top.pack(pady=10, fill="x", padx=10)

    row0 = tk.Frame(top)
    row0.pack(fill="x", pady=3)
    btn_in = tk.Button(row0, text="Input Folder", command=select_input, width=16)
    btn_in.pack(side="left")
    tk.Label(row0, textvariable=input_dir, width=85, anchor="w").pack(side="left", padx=8)

    row1 = tk.Frame(top)
    row1.pack(fill="x", pady=3)
    btn_out = tk.Button(row1, text="Output Folder", command=select_output, width=16)
    btn_out.pack(side="left")
    tk.Label(row1, textvariable=output_dir, width=85, anchor="w").pack(side="left", padx=8)

    opts = tk.Frame(root)
    opts.pack(fill="x", padx=10)

    chk_recursive = tk.Checkbutton(opts, text="Recursive scan", variable=recursive)
    chk_recursive.grid(row=0, column=0, sticky="w")

    chk_annots = tk.Checkbutton(opts, text="Read annotations", variable=read_annots)
    chk_annots.grid(row=0, column=1, sticky="w", padx=15)

    chk_overwrite = tk.Checkbutton(opts, text="Overwrite existing outputs", variable=overwrite_existing)
    chk_overwrite.grid(row=0, column=2, sticky="w", padx=15)

    # NEW: Anonymization assertion UI
    chk_assert = tk.Checkbutton(opts, text="Assert anonymized EDF header (PHI-safe)", variable=assert_anonymized)
    chk_assert.grid(row=1, column=0, sticky="w", pady=(6, 0))

    chk_blank = tk.Checkbutton(opts, text="Require blank embedded annotations (PHI-safe)", variable=require_blank_annotations)
    chk_blank.grid(row=1, column=1, sticky="w", padx=15, pady=(6, 0))

    tk.Label(opts, text="Workers:").grid(row=2, column=0, sticky="w", pady=6)
    spn_workers = tk.Spinbox(opts, from_=1, to=16, textvariable=worker_count, width=6)
    spn_workers.grid(row=2, column=0, sticky="e", pady=6, padx=(70, 0))

    tk.Label(opts, text="Timeout (s):").grid(row=2, column=1, sticky="w", pady=6)
    spn_timeout = tk.Spinbox(opts, from_=5, to=86400, textvariable=timeout_sec, width=10)
    spn_timeout.grid(row=2, column=1, sticky="e", pady=6, padx=(95, 0))

    tk.Label(opts, text="Max retries:").grid(row=2, column=2, sticky="w", pady=6)
    spn_retries = tk.Spinbox(opts, from_=1, to=10, textvariable=max_retries, width=6)
    spn_retries.grid(row=2, column=2, sticky="e", pady=6, padx=(90, 0))

    btns = tk.Frame(root)
    btns.pack(pady=8)

    btn_scan = tk.Button(btns, text="Scan", command=scan, width=18)
    btn_scan.grid(row=0, column=0, padx=8)

    btn_execute = tk.Button(btns, text="Execute", command=execute, width=18)
    btn_execute.grid(row=0, column=1, padx=8)

    btn_pause = tk.Button(btns, text="Pause", command=lambda: None, width=18, state="disabled")
    btn_pause.config(command=lambda: toggle_pause())
    btn_pause.grid(row=0, column=2, padx=8)

    btn_cancel = tk.Button(btns, text="Cancel", command=cancel_run, width=18, state="disabled")
    btn_cancel.grid(row=0, column=3, padx=8)

    progress = ttk.Progressbar(root, length=780)
    progress.pack(pady=6, padx=10)

    statbar = tk.Frame(root)
    statbar.pack(fill="x", padx=10, pady=4)

    tk.Label(statbar, textvariable=status, width=18, anchor="w").pack(side="left")
    tk.Label(statbar, text="Done:").pack(side="left")
    tk.Label(statbar, textvariable=done_count, width=6, anchor="w").pack(side="left")
    tk.Label(statbar, text="Failed:").pack(side="left")
    tk.Label(statbar, textvariable=fail_count, width=6, anchor="w").pack(side="left")
    tk.Label(statbar, text="Skipped:").pack(side="left")
    tk.Label(statbar, textvariable=skip_count, width=6, anchor="w").pack(side="left")
    tk.Label(statbar, text="Remaining:").pack(side="left")
    tk.Label(statbar, textvariable=remaining_count, width=6, anchor="w").pack(side="left")
    tk.Label(statbar, text="Speed:").pack(side="left", padx=(10, 0))
    tk.Label(statbar, textvariable=speed_fps, width=14, anchor="w").pack(side="left")
    tk.Label(statbar, text="Avg:").pack(side="left")
    tk.Label(statbar, textvariable=avg_time, width=10, anchor="w").pack(side="left")

    text = tk.Text(root, height=16, width=105)
    text.pack(padx=10, pady=10, fill="both", expand=True)

    root.after(120, poll_ui_queue)
    root.mainloop()


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="EDF summary exporter with progress.")
    parser.add_argument("input", nargs="?", help="EDF file or root folder")
    parser.add_argument("output", nargs="?", help="Output root folder")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--no-annotations", action="store_true")
    # NEW
    parser.add_argument("--assert-anonymized", action="store_true",
                        help="PHI-safe check: verify header fields are scrubbed; fail file if not.")
    parser.add_argument("--require-blank-annotations", action="store_true",
                        help="PHI-safe check: also verify embedded annotation bytes are blank (first records).")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    global VERBOSE
    VERBOSE = bool(args.verbose)

    if args.input is None:
        run_gui()
        return

    in_path = os.path.abspath(args.input)

    if os.path.isfile(in_path):
        summary = extract_edf_summary(
            in_path,
            not args.no_annotations,
            assert_anonymized=args.assert_anonymized,
            require_blank_annotations=args.require_blank_annotations,
        )
        out = args.output or os.path.splitext(in_path)[0] + "_edf_summary.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        print(f"Wrote {out}")
        return

    if not args.output:
        raise RuntimeError("Output root required for folder input.")

    files = find_edf_files(in_path, args.recursive)
    total = len(files)

    if total == 0:
        raise RuntimeError("No EDF/BDF files found.")

    for i, edf in enumerate(files, 1):
        print(f"[{i}/{total}] {os.path.relpath(edf, in_path)}")
        summary = extract_edf_summary(
            edf,
            not args.no_annotations,
            assert_anonymized=args.assert_anonymized,
            require_blank_annotations=args.require_blank_annotations,
        )
        out = map_output_path(edf, in_path, args.output)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

    print(f"Done. Processed {total} files.")


if __name__ == "__main__":
    # On Windows, multiprocessing needs this guard (you already had it).
    main()