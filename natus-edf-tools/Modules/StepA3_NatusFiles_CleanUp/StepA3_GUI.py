#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unified EDF Post-Conversion Cleanup GUI (Windows, Tkinter)

Pipeline (single pass per subject):
1) Find <subject>.edf in Folder B and exact-matching subject folder in Folder A.
2) Require <subject>.edf_pass (and no .edf_fail).
3) Require size constraint: EDF size >= total size of subject folder.
4) Move deletable extensions (.avi, .erd) from subject folder -> Deletable root/<subject>/pre_archive/
5) RAR archive remaining subject folder -> FolderA/<subject>.rar (blocking)
6) RAR test archive; if OK:
   - Move the remaining subject folder -> Deletable root/<subject>/post_archive/
   - Rename EDF + EDF_PASS to *_verified_stpAcln.*
7) Log all actions to a centralized, timestamped log file.

All destructive operations are MOVE-to-Deletable (never hard delete).

Requirements:
- Windows with RAR installed.
- Tkinter (stdlib).
"""

import os
import sys
import shutil
import subprocess
import threading
import queue
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# -------------------------
# Configuration (hard-coded)
# -------------------------
DELETABLE_EXTENSIONS = {".avi", ".erd"}  # Q7: hard-coded list is fine
RENAME_SUFFIX = "_verified_stpAcln"      # matches if any existing patterns should change.
#DEFAULT_WINRAR_PATH = r"C:\Program Files\WinRAR\WinRAR.exe"
DEFAULT_RAR_PATH = r"C:\Program Files\WinRAR\rar.exe"

# -------------------------
# Utility helpers
# -------------------------

def human_bytes(n: int) -> str:
    """Human-readable bytes."""
    units = ["B","KB","MB","GB","TB","PB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units)-1:
        f /= 1024.0
        i += 1
    if i == 0:
        return f"{int(f)} {units[i]}"
    return f"{f:.2f} {units[i]}"

def safe_makedirs(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def folder_size_bytes(folder: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(folder):
        for name in files:
            try:
                fp = Path(root) / name
                total += fp.stat().st_size
            except Exception:
                pass
    return total

def run_subprocess_blocking(cmd_list, cwd=None) -> int:
    """Run a subprocess without popping up windows (Windows), return exit code."""
    try:
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            # CREATE_NO_WINDOW
            creationflags = 0x08000000
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # hide if any window style is used

        p = subprocess.Popen(
            cmd_list,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            startupinfo=startupinfo,
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
        )
        # Stream output to keep the UI responsive
        while True:
            line = p.stdout.readline()
            if not line and p.poll() is not None:
                break
        return p.returncode
    except FileNotFoundError:
        return -127
    except Exception:
        return -128


def move_tree(src: Path, dst: Path, dry_run: bool, log):
    """
    Move entire folder tree src -> dst (dst becomes src's new location).
    Creates parent dirs. If dst exists, we place inside dst/<src.name>.
    """
    if not src.exists():
        log(f"[WARN] move_tree: source missing: {src}")
        return
    if dry_run:
        log(f"[DRY] Would move tree: {src} -> {dst}")
        return
    # Ensure destination parent exists
    safe_makedirs(dst)
    # If dst exists and is a directory, place into dst/src.name
    target = dst
    if dst.exists() and dst.is_dir():
        target = dst / src.name
    # If target exists already, choose a unique suffix
    final_target = target
    k = 1
    while final_target.exists():
        final_target = Path(str(target) + f"_dup{k}")
        k += 1
    log(f"[MOVE] {src} -> {final_target}")
    shutil.move(str(src), str(final_target))

def move_selected_extensions(src_folder: Path, exts: set[str], dst_folder: Path, dry_run: bool, log):
    """
    Move files with specific extensions (case-insensitive) preserving relative paths.
    Only files directly under src_folder tree are processed.
    """
    exts_low = {e.lower() for e in exts}
    for root, dirs, files in os.walk(src_folder):
        for name in files:
            ext = Path(name).suffix.lower()
            if ext in exts_low:
                rel = Path(root).relative_to(src_folder)
                src_path = Path(root) / name
                dst_path = dst_folder / rel
                if dry_run:
                    log(f"[DRY] Would move deletable file: {src_path} -> {dst_path}")
                else:
                    safe_makedirs(dst_path)
                    final_path = dst_path / name
                    # If collision, add numeric suffix
                    candidate = final_path
                    idx = 1
                    while candidate.exists():
                        candidate = final_path.with_name(f"{final_path.stem}_dup{idx}{final_path.suffix}")
                        idx += 1
                    log(f"[MOVE] deletable: {src_path} -> {candidate}")
                    shutil.move(str(src_path), str(candidate))

def rename_pair(edf_path: Path, pass_path: Path, suffix: str, dry_run: bool, log):
    """Rename EDF and EDF_PASS to include suffix (if not already present)."""
    def apply_suffix(p: Path) -> Path:
        if p.stem.endswith(suffix):
            return p
        return p.with_name(p.stem + suffix + p.suffix)

    new_edf = apply_suffix(edf_path)
    new_pass = apply_suffix(pass_path)

    if dry_run:
        log(f"[DRY] Would rename: {edf_path.name} -> {new_edf.name}")
        log(f"[DRY] Would rename: {pass_path.name} -> {new_pass.name}")
        return new_edf, new_pass

    # If targets exist, add numeric suffix
    def unique(p: Path) -> Path:
        if not p.exists():
            return p
        base = p.stem
        ext = p.suffix
        k = 1
        while True:
            cand = p.with_name(f"{base}_dup{k}{ext}")
            if not cand.exists():
                return cand
            k += 1

    final_edf = unique(new_edf)
    final_pass = unique(new_pass)

    if final_edf != edf_path:
        log(f"[RENAME] {edf_path.name} -> {final_edf.name}")
        edf_path.rename(final_edf)
    if final_pass != pass_path:
        log(f"[RENAME] {pass_path.name} -> {final_pass.name}")
        pass_path.rename(final_pass)
    return final_edf, final_pass

def rar_add_archive(rar_exe: Path, folder_to_archive: Path, archive_path: Path, dry_run: bool, log) -> int:
    """
    Create archive: rar a -r -ep1 "archive.rar" "folder\*"
    Notes:
      - Using -ep1 to store relative paths without the drive/leading path
      - Omitting -df because we are NOT deleting; we move to Deletable after test.
    """
    cmd = [str(rar_exe), "a", "-r", "-ep1", str(archive_path), str(folder_to_archive / "*")]
    if dry_run:
        log(f"[DRY] Would run: {' '.join(cmd)}")
        return 0
    log(f"[CMD] {' '.join(cmd)}")
    return run_subprocess_blocking(cmd)

def rar_test_archive(rar_exe: Path, archive_path: Path, dry_run: bool, log) -> int:
    """
    Test archive: rar t "archive.rar"
    """
    cmd = [str(rar_exe), "t", str(archive_path)]
    if dry_run:
        log(f"[DRY] Would run: {' '.join(cmd)}")
        return 0
    log(f"[CMD] {' '.join(cmd)}")
    return run_subprocess_blocking(cmd)

# -------------------------
# Core processing
# -------------------------

class SubjectTask:
    def __init__(self, subject_name: str, edf_path: Path, pass_path: Path, subj_folder: Path):
        self.subject = subject_name
        self.edf = edf_path
        self.edf_pass = pass_path
        self.subj_folder = subj_folder
        self.folder_size = 0
        self.edf_size = 0
        self.size_ok = False
        self.status = "Pending"   # Pending/Skipped/OK/Failed
        self.details = ""

class Worker(threading.Thread):
    def __init__(self, app, items):
        super().__init__(daemon=True)
        self.app = app
        self.items = items
        self.cancel_flag = threading.Event()

    def cancel(self):
        self.cancel_flag.set()

    def log(self, msg: str):
        self.app.log(msg)

    def run(self):
        total = len(self.items)
        done = 0
        for item in self.items:
            if self.cancel_flag.is_set():
                self.log("[CANCEL] Run aborted by user.")
                break
            self._process_item(item)
            done += 1
            self.app.update_overall_progress(done, total)
        self.app.run_finished()

    def _process_item(self, t: SubjectTask):
        app = self.app
        dry = app.var_dry_run.get()
        rar_exe = Path(app.var_rar.get())
        folderA = Path(app.var_folderA.get())
        deletable_root = Path(app.var_deletable.get()) if app.var_deletable.get().strip() else (folderA / "deletable")
        safe_makedirs(deletable_root)

        # Update row status
        def set_status(s, d=""):
            t.status = s
            t.details = d
            app.update_row(t)

        self.log(f"--- Processing: {t.subject} ---")
        set_status("Running", "Starting...")

        # 1) Pre-archive: move deletable extensions
        pre_dst = deletable_root / t.subject / "pre_archive"
        self.log(f"[STEP] Moving deletable extensions to: {pre_dst}")
        try:
            move_selected_extensions(t.subj_folder, DELETABLE_EXTENSIONS, pre_dst, dry, self.log)
        except Exception as e:
            set_status("Failed", f"Move deletables error: {e}")
            self.log(f"[ERROR] move deletables: {e}")
            return

        # 2) Archive remaining subject folder
        archive_path = Path(app.var_folderA.get()) / f"{t.subject}.rar"
        self.log(f"[STEP] Archiving folder to: {archive_path}")
        rc = rar_add_archive(rar_exe, t.subj_folder, archive_path, dry, self.log)
        if rc != 0:
            set_status("Failed", f"RAR add rc={rc}")
            self.log(f"[ERROR] RAR add failed rc={rc}")
            return

        # 3) Test archive
        self.log(f"[STEP] Testing archive: {archive_path}")
        rc = rar_test_archive(rar_exe, archive_path, dry, self.log)
        if rc != 0:
            set_status("Failed", f"RAR test rc={rc}")
            self.log(f"[ERROR] RAR test failed rc={rc}")
            return

        # 4) Post-archive: move remaining subject folder (the rest) to deletable/post_archive
        post_dst = deletable_root / t.subject / "post_archive"
        self.log(f"[STEP] Moving remaining subject folder to: {post_dst}")
        try:
            if t.subj_folder.exists() and any(t.subj_folder.iterdir()):
                move_tree(t.subj_folder, post_dst, dry, self.log)
            else:
                self.log("[INFO] Subject folder already empty.")
        except Exception as e:
            set_status("Failed", f"Move post-archive error: {e}")
            self.log(f"[ERROR] move post-archive: {e}")
            return

        # 5) Rename EDF + EDF_PASS
        self.log("[STEP] Renaming EDF + EDF_PASS with suffix.")
        try:
            rename_pair(t.edf, t.edf_pass, RENAME_SUFFIX, dry, self.log)
        except Exception as e:
            set_status("Failed", f"Rename error: {e}")
            self.log(f"[ERROR] rename: {e}")
            return

        set_status("OK", "Completed.")
        self.log(f"--- Done: {t.subject} ---\n")

# -------------------------
# GUI
# -------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EDF Post-Conversion Cleanup (Unified)")
        self.geometry("1100x700")
        self.minsize(960, 640)

        # Variables
        self.var_folderA = tk.StringVar()
        self.var_folderB = tk.StringVar()
        self.var_rar = tk.StringVar(value=DEFAULT_RAR_PATH)
        self.var_deletable = tk.StringVar(value="")  # empty means use FolderA\deletable
        self.var_dry_run = tk.BooleanVar(value=True)

        # Logging
        self.log_q = queue.Queue()
        self.after(100, self._drain_log_queue)
        self.run_log_file = None
        self._open_run_log()

        # UI
        self._build_ui()

        # Data
        self.tasks: list[SubjectTask] = []
        self.worker: Worker | None = None

    # ------- Logging ------
    def _open_run_log(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        logs_dir = Path.cwd() / "logs"
        safe_makedirs(logs_dir)
        self.run_log_file = logs_dir / f"edf_cleanup_run_{ts}.log"

    def log(self, msg: str):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        self.log_q.put(line)
        try:
            with self.run_log_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _drain_log_queue(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                self.txt_log.insert(tk.END, line + "\n")
                self.txt_log.see(tk.END)
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    # ------- UI Build -----
    def _build_ui(self):
        # Top frame: inputs
        frm = ttk.LabelFrame(self, text="Inputs & Options")
        frm.pack(side=tk.TOP, fill=tk.X, padx=10, pady=8)

        # Row 1
        r = 0
        ttk.Label(frm, text="Folder A (Natus root):").grid(row=r, column=0, sticky="e", padx=6, pady=6)
        ttk.Entry(frm, textvariable=self.var_folderA, width=70).grid(row=r, column=1, sticky="we", padx=6)
        ttk.Button(frm, text="Browse", command=self._browse_folderA).grid(row=r, column=2, padx=6)
        r += 1

        ttk.Label(frm, text="Folder B (EDFs root):").grid(row=r, column=0, sticky="e", padx=6, pady=6)
        ttk.Entry(frm, textvariable=self.var_folderB, width=70).grid(row=r, column=1, sticky="we", padx=6)
        ttk.Button(frm, text="Browse", command=self._browse_folderB).grid(row=r, column=2, padx=6)
        r += 1

        ttk.Label(frm, text="RAR.exe:").grid(row=r, column=0, sticky="e", padx=6, pady=6)
        ttk.Entry(frm, textvariable=self.var_rar, width=70).grid(row=r, column=1, sticky="we", padx=6)
        ttk.Button(frm, text="Browse", command=self._browse_rar).grid(row=r, column=2, padx=6)
        r += 1

        ttk.Label(frm, text="Deletable root (optional):").grid(row=r, column=0, sticky="e", padx=6, pady=6)
        ttk.Entry(frm, textvariable=self.var_deletable, width=70).grid(row=r, column=1, sticky="we", padx=6)
        ttk.Button(frm, text="Browse", command=self._browse_deletable).grid(row=r, column=2, padx=6)
        r += 1

        ttk.Checkbutton(frm, text="Dry-run (preview only)", variable=self.var_dry_run).grid(row=r, column=1, sticky="w", padx=6, pady=6)
        r += 1

        for c in range(3):
            frm.grid_columnconfigure(c, weight=1)

        # Middle: actions
        act = ttk.Frame(self)
        act.pack(side=tk.TOP, fill=tk.X, padx=10, pady=6)
        ttk.Button(act, text="Scan", command=self.on_scan).pack(side=tk.LEFT, padx=4)
        self.btn_run = ttk.Button(act, text="Run", command=self.on_run, state=tk.DISABLED)
        self.btn_run.pack(side=tk.LEFT, padx=4)
        self.btn_cancel = ttk.Button(act, text="Cancel", command=self.on_cancel, state=tk.DISABLED)
        self.btn_cancel.pack(side=tk.LEFT, padx=4)

        # Progress bars
        pfrm = ttk.Frame(self)
        pfrm.pack(side=tk.TOP, fill=tk.X, padx=10, pady=2)
        ttk.Label(pfrm, text="Item:").pack(side=tk.LEFT)
        self.pb_item = ttk.Progressbar(pfrm, maximum=100)
        self.pb_item.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        ttk.Label(pfrm, text="Overall:").pack(side=tk.LEFT, padx=(12,0))
        self.pb_all = ttk.Progressbar(pfrm, maximum=100)
        self.pb_all.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        # Treeview for candidates
        tvf = ttk.LabelFrame(self, text="Candidates")
        tvf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=6)

        cols = ("subject","edf","edf_size","folder_size","size_ok","status","details")
        self.tv = ttk.Treeview(tvf, columns=cols, show="headings", height=10)
        for c, w in zip(cols, (160,260,100,120,70,80,260)):
            self.tv.heading(c, text=c)
            self.tv.column(c, width=w, anchor="w")
        self.tv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb = ttk.Scrollbar(tvf, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Log pane
        lgf = ttk.LabelFrame(self, text="Log (centralized, timestamped)")
        lgf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=6)
        self.txt_log = tk.Text(lgf, height=10, wrap="none")
        self.txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lvsb = ttk.Scrollbar(lgf, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=lvsb.set)
        lvsb.pack(side=tk.RIGHT, fill=tk.Y)

    # ------- UI callbacks ------
    def _browse_folderA(self):
        p = filedialog.askdirectory(title="Select Folder A (Natus subjects root)")
        if p:
            self.var_folderA.set(p)

    def _browse_folderB(self):
        p = filedialog.askdirectory(title="Select Folder B (EDFs root)")
        if p:
            self.var_folderB.set(p)

    def _browse_rar(self):
        p = filedialog.askopenfilename(
            title="Select RAR.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")]
        )
        if p:
            self.var_rar.set(p)

    def _browse_deletable(self):
        p = filedialog.askdirectory(title="Select Deletable root")
        if p:
            self.var_deletable.set(p)

    def on_scan(self):
        folderA = Path(self.var_folderA.get().strip())
        folderB = Path(self.var_folderB.get().strip())
        rar_exe = Path(self.var_rar.get().strip())
        if not folderA.exists() or not folderA.is_dir():
            messagebox.showerror("Error", "Folder A is invalid.")
            return
        if not folderB.exists() or not folderB.is_dir():
            messagebox.showerror("Error", "Folder B is invalid.")
            return
        if not rar_exe.exists():
            messagebox.showerror("Error", "RAR.exe not found.")
            return

        self.log("=== SCAN START ===")
        self.tasks.clear()
        for row in self.tv.get_children():
            self.tv.delete(row)

        # Build set of available subject folders in A for exact match
        subjectsA = {p.name: p for p in folderA.iterdir() if p.is_dir()}

        # Scan EDFs in B
        edf_files = sorted(folderB.glob("*.edf"))
        count_candidates = 0
        for edf in edf_files:
            subj = edf.stem
            edf_pass = edf.with_suffix(edf.suffix + "_pass")  # "<name>.edf_pass"
            edf_fail = edf.with_suffix(edf.suffix + "_fail")  # "<name>.edf_fail"

            # criteria: pass exists, fail absent
            if not edf_pass.exists():
                continue
            if edf_fail.exists():
                self.log(f"[SKIP] {edf.name}: found .edf_fail")
                continue
            # exact match subject folder
            subj_folder = subjectsA.get(subj)
            if subj_folder is None:
                self.log(f"[SKIP] {edf.name}: no exact folder match in Folder A")
                continue

            t = SubjectTask(subj, edf, edf_pass, subj_folder)
            # Size constraint: EDF >= folder size
            try:
                t.edf_size = edf.stat().st_size
                t.folder_size = folder_size_bytes(subj_folder)
                t.size_ok = (t.edf_size >= t.folder_size)
            except Exception:
                t.size_ok = False

            if not t.size_ok:
                self.log(f"[SKIP] {edf.name}: size check failed (EDF {human_bytes(t.edf_size)} < folder {human_bytes(t.folder_size)})")
                continue

            self.tasks.append(t)
            count_candidates += 1
            self._insert_row(t)

        self.log(f"=== SCAN DONE: {count_candidates} candidate(s) ===")
        self.btn_run.config(state=(tk.NORMAL if self.tasks else tk.DISABLED))
        self.update_overall_progress(0, max(1, len(self.tasks)))

    def on_run(self):
        if not self.tasks:
            messagebox.showinfo("Info", "No candidates to process. Please Scan first.")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Busy", "Processing already running.")
            return
        self.log("=== RUN START ===")
        self.btn_run.config(state=tk.DISABLED)
        self.btn_cancel.config(state=tk.NORMAL)
        self.worker = Worker(self, self.tasks)
        self.worker.start()

    def on_cancel(self):
        if self.worker and self.worker.is_alive():
            self.worker.cancel()
            self.btn_cancel.config(state=tk.DISABLED)

    # ------- Table handling ------
    def _insert_row(self, t: SubjectTask):
        self.tv.insert("", tk.END, iid=t.subject, values=(
            t.subject,
            str(t.edf),
            human_bytes(t.edf_size),
            human_bytes(t.folder_size),
            "YES" if t.size_ok else "NO",
            t.status,
            t.details
        ))

    def update_row(self, t: SubjectTask):
        if self.tv.exists(t.subject):
            self.tv.item(t.subject, values=(
                t.subject,
                str(t.edf),
                human_bytes(t.edf_size),
                human_bytes(t.folder_size),
                "YES" if t.size_ok else "NO",
                t.status,
                t.details
            ))
        # brief item progress tick (we don't have fine-grained per-file progress from RAR)
        self.pb_item["value"] = 100 if t.status in ("OK", "Failed", "Skipped") else 50
        self.update_idletasks()

    def update_overall_progress(self, done, total):
        pct = 0 if total == 0 else (done / total) * 100.0
        self.pb_all["value"] = pct
        self.update_idletasks()

    def run_finished(self):
        self.btn_cancel.config(state=tk.DISABLED)
        self.btn_run.config(state=tk.NORMAL)
        self.pb_item["value"] = 0
        self.update_idletasks()
        self.log("=== RUN FINISHED ===")

# -------------------------
# Main
# -------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
