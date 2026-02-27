#!/usr/bin/env python3

import os
import sys
import glob
import argparse
import subprocess
import tempfile
import shutil
import hashlib
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from datetime import datetime
import threading
import queue

from common_libs.organizing_code.environment import load_env_file
# ============================================================
# Utilities
# ============================================================

def file_hash(path):
    """
    Hash file content after normalizing line endings.
    Treats CRLF and LF as identical.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        data = f.read()

    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    h.update(data)
    return h.hexdigest()



def init_logger(output_dir, gui_queue=None):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    ENV_PATH = os.path.join(SCRIPT_DIR, "../../../../log_path.env")

    env = load_env_file(ENV_PATH)

    base_log_dir = env.get(
        "LOG_BASE_DIR",
        os.path.join(os.path.dirname(output_dir), "logs")
    )

    os.makedirs(base_log_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(base_log_dir, f"redaction_{ts}.log")

    def log(msg):
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"

        # Console
        print(line)

        # File
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        # GUI
        if gui_queue is not None:
            gui_queue.put(line)

    log(f"Log file created at {log_path}")
    return log


# ============================================================
# Core processing logic
# ============================================================

def process_files(
    input_dir,
    output_dir,
    extension="tsv",
    recursive=False,
    gui_queue=None,
):
    input_dir = os.path.abspath(input_dir)
    output_dir = os.path.abspath(output_dir)

    os.makedirs(output_dir, exist_ok=True)
    log = init_logger(output_dir, gui_queue)

    log(f"Input directory : {input_dir}")
    log(f"Output directory: {output_dir}")
    log(f"Extension       : {extension}")
    log(f"Recursive       : {recursive}")

    pattern = f"**/*.{extension}" if recursive else f"*.{extension}"
    files = glob.glob(os.path.join(input_dir, pattern), recursive=recursive)

    if not files:
        log("No files found. Exiting.")
        return

    processed = 0
    skipped_uptodate = 0
    skipped_nochange = 0

    for idx, in_file in enumerate(files, 1):
        rel_path = os.path.relpath(in_file, input_dir)
        out_file = os.path.join(output_dir, rel_path)
        os.makedirs(os.path.dirname(out_file), exist_ok=True)

        if os.path.exists(out_file):
            if os.path.getmtime(out_file) >= os.path.getmtime(in_file):
                log(f"SKIP_UPTODATE ({idx}/{len(files)}) {rel_path}")
                skipped_uptodate += 1
                continue

        log(f"PROCESS ({idx}/{len(files)}) {rel_path}")

        with tempfile.NamedTemporaryFile(
            suffix="." + extension,
            delete=False
        ) as tmp:
            tmp_path = tmp.name

        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        PHI_REDACTOR = os.path.join(SCRIPT_DIR, "phi_redactor.py")

        cmd = [
            sys.executable,
            PHI_REDACTOR,
            "predict",
            "--pred_model_path", "../models/redactor/",
            "--checkpoint", os.path.join(SCRIPT_DIR, "output", "best"),
            "--input_tsv", in_file,
            "--output_tsv", tmp_path,
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

        except Exception as e:
            log(f"ERROR processing {rel_path}: {e}")
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        if file_hash(in_file) == file_hash(tmp_path):
            log(f"NO_CHANGE {rel_path} (output not created)")
            os.unlink(tmp_path)
            skipped_nochange += 1
            continue

        shutil.move(tmp_path, out_file)
        processed += 1
        log(f"UPDATED {rel_path}")

    log("DONE")
    log(f"Processed       : {processed}")
    log(f"Skipped uptodate: {skipped_uptodate}")
    log(f"Skipped nochange: {skipped_nochange}")


# ============================================================
# GUI
# ============================================================

def launch_gui():
    root = tk.Tk()
    root.title("PHI Redaction Runner")
    root.geometry("780x520")

    input_dir = tk.StringVar()
    output_dir = tk.StringVar()
    extension = tk.StringVar(value="tsv")
    recursive = tk.BooleanVar(value=False)

    log_queue = queue.Queue()

    def browse_input():
        path = filedialog.askdirectory(title="Select Input Folder")
        if path:
            input_dir.set(path)

    def browse_output():
        path = filedialog.askdirectory(title="Select Output Folder")
        if path:
            output_dir.set(path)

    def poll_log_queue():
        while not log_queue.empty():
            msg = log_queue.get_nowait()
            log_box.insert(tk.END, msg + "\n")
            log_box.see(tk.END)
        root.after(100, poll_log_queue)

    def run():
        if not input_dir.get():
            messagebox.showerror("Error", "Please select an input folder.")
            return
        if not output_dir.get():
            messagebox.showerror("Error", "Please select an output folder.")
            return

        run_btn.config(state=tk.DISABLED)

        def worker():
            try:
                process_files(
                    input_dir=input_dir.get(),
                    output_dir=output_dir.get(),
                    extension=extension.get().strip().lstrip("."),
                    recursive=recursive.get(),
                    gui_queue=log_queue,
                )
            finally:
                log_queue.put("=== FINISHED ===")
                run_btn.config(state=tk.NORMAL)

        threading.Thread(target=worker, daemon=True).start()

    tk.Label(root, text="Input Folder").grid(row=0, column=0, padx=10, pady=5, sticky="w")
    tk.Entry(root, textvariable=input_dir, width=60).grid(row=0, column=1)
    tk.Button(root, text="Browse", command=browse_input).grid(row=0, column=2, padx=5)

    tk.Label(root, text="Output Folder").grid(row=1, column=0, padx=10, pady=5, sticky="w")
    tk.Entry(root, textvariable=output_dir, width=60).grid(row=1, column=1)
    tk.Button(root, text="Browse", command=browse_output).grid(row=1, column=2, padx=5)

    tk.Label(root, text="Extension").grid(row=2, column=0, padx=10, pady=5, sticky="w")
    tk.Entry(root, textvariable=extension, width=10).grid(row=2, column=1, sticky="w")

    tk.Checkbutton(
        root,
        text="Recursive search",
        variable=recursive
    ).grid(row=3, column=1, sticky="w", pady=5)

    run_btn = tk.Button(
        root,
        text="Run Redaction",
        command=run,
        width=20
    )
    run_btn.grid(row=4, column=1, pady=10)

    log_box = scrolledtext.ScrolledText(
        root,
        height=18,
        width=95,
        state="normal"
    )
    log_box.grid(row=5, column=0, columnspan=3, padx=10, pady=10)

    poll_log_queue()
    root.mainloop()


# ============================================================
# CLI
# ============================================================

def parse_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--ext", default="tsv")
    parser.add_argument("--recursive", action="store_true")
    return parser.parse_args()


# ============================================================
# Entry point
# ============================================================

def main():
    if len(sys.argv) > 1:
        args = parse_cli()
        if not args.input or not args.output:
            print("[ERROR] --input and --output required in CLI mode")
            sys.exit(1)

        process_files(
            input_dir=args.input,
            output_dir=args.output,
            extension=args.ext,
            recursive=args.recursive,
        )
    else:
        launch_gui()


if __name__ == "__main__":
    main()
