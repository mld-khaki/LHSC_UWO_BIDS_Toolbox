#!/usr/bin/env python3
"""
compare_files_visual.py

Compare two files chunk by chunk, produce:
  1) A text-based map on stdout (CLI) or in a GUI text box (GUI)
  2) A matplotlib visualization (0=identical, 1=diff)

USAGE (CLI):
    python compare_files_visual.py <file1> <file2>

USAGE (GUI):
    python compare_files_visual.py
    (If no args are provided, a GUI opens to select files and run the comparison.)

NOTES:
  - For very large files, this script compares MD5 hashes of chunks by default.
    Each chunk is represented as a single pixel in the visualization.
"""

import sys
import os
import math
import hashlib
import threading
import queue
import traceback

import numpy as np
import matplotlib.pyplot as plt

from tqdm import tqdm


# -----------------------------
# Core comparison functionality
# -----------------------------
def compare_files_chunk_md5(
    file1: str,
    file2: str,
    chunk_size: int = 2**20,
    wrap_width: int = 70,
    progress_cb=None,
    stop_event: threading.Event | None = None,
):
    """
    Compare two files by computing MD5 per chunk.

    Returns:
        filesize (int)
        file_blocks (int)
        differences (np.ndarray uint8) length file_blocks where 0=match, 1=diff
        text_lines (list[str]) chunk map lines
    """
    if not os.path.isfile(file1):
        raise FileNotFoundError(f"'{file1}' not found or not a file.")
    if not os.path.isfile(file2):
        raise FileNotFoundError(f"'{file2}' not found or not a file.")

    size1 = os.path.getsize(file1)
    size2 = os.path.getsize(file2)
    if size1 != size2:
        raise ValueError(f"Files differ in size ({size1} vs {size2} bytes).")

    filesize = size1
    file_blocks = (filesize + chunk_size - 1) // chunk_size

    differences = np.zeros(file_blocks, dtype=np.uint8)

    block_index = 0
    with open(file1, "rb") as f1, open(file2, "rb") as f2:
        while block_index < file_blocks:
            if stop_event is not None and stop_event.is_set():
                raise RuntimeError("Comparison cancelled by user.")

            data1 = f1.read(chunk_size)
            data2 = f2.read(chunk_size)

            if not data1 or not data2:
                break

            md5_1 = hashlib.md5(data1).digest()
            md5_2 = hashlib.md5(data2).digest()
            if md5_1 != md5_2:
                differences[block_index] = 1

            block_index += 1

            if progress_cb is not None:
                progress_cb(block_index, file_blocks)

    # Text-based map
    text_lines = []
    for i in range(0, file_blocks, wrap_width):
        row_slice = differences[i : i + wrap_width]
        row_str = "".join("." if x == 0 else "X" for x in row_slice)
        text_lines.append(row_str)

    return filesize, file_blocks, differences, text_lines


def visualize_differences(differences: np.ndarray, file_blocks: int, file1: str, file2: str):
    """
    Create a roughly square visualization of chunk differences.
    0 => same chunk, 1 => different chunk
    """
    width = int(math.sqrt(file_blocks))
    if width == 0:
        print("\nNo data to visualize.")
        return

    height = (file_blocks + width - 1) // width
    padded_size = width * height

    if padded_size != file_blocks:
        padded = np.zeros(padded_size, dtype=np.uint8)
        padded[:file_blocks] = differences
        differences_2d = padded.reshape((height, width))
    else:
        differences_2d = differences.reshape((height, width))

    print(f"\nGenerating visualization with shape {height} x {width} ...")

    plt.figure(figsize=(8, 8))
    plt.rc("axes", labelsize=16)
    plt.rc("xtick", labelsize=6)
    plt.rc("ytick", labelsize=6)

    plt.imshow(differences_2d, cmap="viridis", aspect="equal", interpolation="nearest")
    plt.title(f"Visual Difference Map\n'{file1}' vs '{file2}'")
    plt.xlabel(f"Width ~ sqrt(num_chunks={file_blocks}) => {width}")
    plt.ylabel(f"Height => {height}")
    plt.colorbar(label="0=same chunk, 1=different chunk")
    plt.tight_layout()

    ax = plt.gca()
    ax.set_xticks(np.arange(0, width, 1) + 0.5)
    ax.set_yticks(np.arange(0, height, 1) + 0.5)
    ax.set_xticklabels(np.arange(1, width + 1, 1))
    ax.set_yticklabels(np.arange(1, height + 1, 1))
    ax.grid(color="w", linestyle="-", linewidth=0.1)

    plt.show()


# -----------------------------
# CLI mode
# -----------------------------
def run_cli(file1: str, file2: str):
    # Parameters
    chunk_size = 2**20  # 1 MB
    wrap_width = 70

    # Pre-check sizes to show nicer messages
    if not os.path.isfile(file1):
        print(f"ERROR: '{file1}' not found or not a file.")
        sys.exit(1)
    if not os.path.isfile(file2):
        print(f"ERROR: '{file2}' not found or not a file.")
        sys.exit(1)

    size1 = os.path.getsize(file1)
    size2 = os.path.getsize(file2)
    if size1 != size2:
        print(f"ERROR: Files differ in size ({size1} vs {size2} bytes).")
        sys.exit(1)

    filesize = size1
    file_blocks = (filesize + chunk_size - 1) // chunk_size

    print(f"Comparing two files of {filesize} bytes each...")
    print(f"Reading in {file_blocks} chunk(s) of size {chunk_size} bytes each...\n")

    # Progress via tqdm in CLI
    last_reported = {"idx": 0}

    def progress_cb(done, total):
        # Update tqdm externally if needed; we’ll drive tqdm in loop below
        last_reported["idx"] = done

    # Use our comparison but keep tqdm progress feel:
    differences = np.zeros(file_blocks, dtype=np.uint8)
    block_index = 0

    with open(file1, "rb") as f1, open(file2, "rb") as f2:
        with tqdm(total=file_blocks, desc="Comparing chunks") as pbar:
            while block_index < file_blocks:
                data1 = f1.read(chunk_size)
                data2 = f2.read(chunk_size)
                if not data1 or not data2:
                    break

                md5_1 = hashlib.md5(data1).digest()
                md5_2 = hashlib.md5(data2).digest()
                if md5_1 != md5_2:
                    differences[block_index] = 1

                block_index += 1
                pbar.update(1)

    # Text-based map
    print("\nText-based chunk map ('.' = same, 'X' = different):")
    for i in range(0, file_blocks, wrap_width):
        row_slice = differences[i : i + wrap_width]
        row_str = "".join("." if x == 0 else "X" for x in row_slice)
        print(row_str)

    # Visualization
    visualize_differences(differences, file_blocks, file1, file2)


# -----------------------------
# GUI mode (no args)
# -----------------------------
def run_gui():
    # Tkinter is part of the standard library (on most Python installs)
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("Compare Two Files (Chunk MD5)")
    root.geometry("900x650")

    q = queue.Queue()
    stop_event = threading.Event()

    # --- Variables ---
    file1_var = tk.StringVar(value="")
    file2_var = tk.StringVar(value="")
    chunk_mb_var = tk.StringVar(value="1")   # default 1 MB
    wrap_width_var = tk.StringVar(value="70")

    # --- Helpers ---
    def append_output(text: str):
        output_text.configure(state="normal")
        output_text.insert("end", text)
        output_text.see("end")
        output_text.configure(state="disabled")

    def set_status(text: str):
        status_var.set(text)

    def browse_file(var: tk.StringVar):
        path = filedialog.askopenfilename()
        if path:
            var.set(path)

    def safe_int_from_var(var: tk.StringVar, name: str, min_val: int):
        try:
            v = int(var.get().strip())
        except Exception:
            raise ValueError(f"{name} must be an integer.")
        if v < min_val:
            raise ValueError(f"{name} must be >= {min_val}.")
        return v

    def start_compare():
        file1 = file1_var.get().strip()
        file2 = file2_var.get().strip()

        if not file1 or not file2:
            messagebox.showerror("Missing input", "Please choose both files.")
            return

        try:
            chunk_mb = safe_int_from_var(chunk_mb_var, "Chunk size (MB)", 1)
            wrap_width = safe_int_from_var(wrap_width_var, "Wrap width", 1)
        except Exception as e:
            messagebox.showerror("Invalid parameter", str(e))
            return

        chunk_size = chunk_mb * 1024 * 1024

        # Reset UI
        output_text.configure(state="normal")
        output_text.delete("1.0", "end")
        output_text.configure(state="disabled")

        progress_var.set(0)
        progress_bar.configure(maximum=100)
        stop_event.clear()

        btn_compare.configure(state="disabled")
        btn_cancel.configure(state="normal")

        set_status("Validating files...")

        def worker():
            try:
                def progress_cb(done, total):
                    q.put(("progress", done, total))

                filesize, file_blocks, differences, text_lines = compare_files_chunk_md5(
                    file1=file1,
                    file2=file2,
                    chunk_size=chunk_size,
                    wrap_width=wrap_width,
                    progress_cb=progress_cb,
                    stop_event=stop_event,
                )
                q.put(("result", filesize, file_blocks, differences, text_lines, file1, file2))
            except Exception as ex:
                q.put(("error", str(ex), traceback.format_exc()))

        threading.Thread(target=worker, daemon=True).start()

    def cancel_compare():
        stop_event.set()
        set_status("Cancelling...")

    def process_queue():
        try:
            while True:
                item = q.get_nowait()
                kind = item[0]

                if kind == "progress":
                    done, total = item[1], item[2]
                    if total > 0:
                        pct = (done / total) * 100.0
                    else:
                        pct = 0.0
                    progress_var.set(pct)
                    set_status(f"Comparing chunks: {done}/{total}")

                elif kind == "result":
                    filesize, file_blocks, differences, text_lines, f1, f2 = item[1:]
                    append_output(f"Comparing two files of {filesize} bytes each...\n")
                    append_output(
                        f"Reading in {file_blocks} chunk(s) of size {safe_int_from_var(chunk_mb_var, 'Chunk size (MB)', 1)} MB each...\n\n"
                    )
                    append_output("Text-based chunk map ('.' = same, 'X' = different):\n")
                    for line in text_lines:
                        append_output(line + "\n")

                    progress_var.set(100)
                    set_status("Done. Showing visualization...")

                    btn_compare.configure(state="normal")
                    btn_cancel.configure(state="disabled")

                    # Show plot (blocking, but comparison already finished)
                    visualize_differences(differences, file_blocks, f1, f2)
                    set_status("Done.")

                elif kind == "error":
                    msg, tb = item[1], item[2]
                    btn_compare.configure(state="normal")
                    btn_cancel.configure(state="disabled")
                    set_status("Error.")
                    messagebox.showerror("Error", msg)
                    # Also dump traceback to output box (helpful for debugging)
                    append_output("\n--- ERROR ---\n")
                    append_output(msg + "\n\n")
                    append_output(tb + "\n")

        except queue.Empty:
            pass

        root.after(100, process_queue)

    # --- Layout ---
    main_frame = ttk.Frame(root, padding=12)
    main_frame.pack(fill="both", expand=True)

    # File selectors
    row1 = ttk.Frame(main_frame)
    row1.pack(fill="x", pady=(0, 8))
    ttk.Label(row1, text="File 1:").pack(side="left")
    e1 = ttk.Entry(row1, textvariable=file1_var)
    e1.pack(side="left", fill="x", expand=True, padx=8)
    ttk.Button(row1, text="Browse...", command=lambda: browse_file(file1_var)).pack(side="left")

    row2 = ttk.Frame(main_frame)
    row2.pack(fill="x", pady=(0, 12))
    ttk.Label(row2, text="File 2:").pack(side="left")
    e2 = ttk.Entry(row2, textvariable=file2_var)
    e2.pack(side="left", fill="x", expand=True, padx=8)
    ttk.Button(row2, text="Browse...", command=lambda: browse_file(file2_var)).pack(side="left")

    # Params
    params = ttk.Frame(main_frame)
    params.pack(fill="x", pady=(0, 10))

    ttk.Label(params, text="Chunk size (MB):").pack(side="left")
    ttk.Entry(params, textvariable=chunk_mb_var, width=8).pack(side="left", padx=(6, 18))

    ttk.Label(params, text="Wrap width:").pack(side="left")
    ttk.Entry(params, textvariable=wrap_width_var, width=8).pack(side="left", padx=(6, 18))

    btn_compare = ttk.Button(params, text="Compare", command=start_compare)
    btn_compare.pack(side="left")

    btn_cancel = ttk.Button(params, text="Cancel", command=cancel_compare, state="disabled")
    btn_cancel.pack(side="left", padx=(8, 0))

    # Progress
    progress_row = ttk.Frame(main_frame)
    progress_row.pack(fill="x", pady=(0, 10))

    progress_var = tk.DoubleVar(value=0.0)
    progress_bar = ttk.Progressbar(progress_row, variable=progress_var, maximum=100)
    progress_bar.pack(side="left", fill="x", expand=True)

    status_var = tk.StringVar(value="Choose two files and click Compare.")
    ttk.Label(progress_row, textvariable=status_var).pack(side="left", padx=(10, 0))

    # Output box
    output_frame = ttk.LabelFrame(main_frame, text="Output")
    output_frame.pack(fill="both", expand=True)

    output_text = tk.Text(output_frame, wrap="none", height=20)
    output_text.pack(fill="both", expand=True, padx=8, pady=8)
    output_text.configure(state="disabled")

    # Start queue processing
    root.after(100, process_queue)
    root.mainloop()


# -----------------------------
# Entry point
# -----------------------------
def main():
    # If no args -> GUI
    if len(sys.argv) == 1:
        run_gui()
        return

    # CLI expects exactly 2 args after script name
    if len(sys.argv) != 3:
        print("Usage: python compare_files_visual.py <file1> <file2>")
        print("Or run with no arguments to use the GUI.")
        sys.exit(1)

    file1 = sys.argv[1]
    file2 = sys.argv[2]
    run_cli(file1, file2)


if __name__ == "__main__":
    main()