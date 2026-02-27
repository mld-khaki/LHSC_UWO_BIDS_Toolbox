import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import string
from typing import Optional, Callable


# -----------------------------
# Helper functions
# -----------------------------

def is_meaningful_event(text: str) -> bool:
    """
    Returns True if event text contains any printable, non-whitespace character.
    Filters out control chars like \\x14 and blank fields.
    """
    if text is None:
        return False

    cleaned = "".join(ch for ch in text if ch in string.printable)
    return cleaned.strip() != ""


def redact_phi(text: str) -> str:
    """
    Lightweight regex-based PHI redaction for TSV 'event' text.
    This is NOT a medical-grade deidentifier; it's a "belt & suspenders"
    pass intended to reduce obvious leakage (emails, MRN-like IDs, dates, phones).
    """
    if text is None:
        return ""

    s = text

    # Email addresses
    s = re.sub(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", s)

    # Phone-ish patterns (very approximate)
    s = re.sub(r"\b(\+?\d{1,2}[\s\-]?)?(\(?\d{3}\)?[\s\-]?)\d{3}[\s\-]?\d{4}\b", "[REDACTED_PHONE]", s)

    # Dates: YYYY-MM-DD, MM/DD/YYYY, DD/MM/YYYY (approx)
    s = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "[REDACTED_DATE]", s)
    s = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", "[REDACTED_DATE]", s)

    # MRN / ID-like: long digit sequences (>=7)
    s = re.sub(r"\b\d{7,}\b", "[REDACTED_ID]", s)

    # Remove non-printable controls
    s = "".join(ch for ch in s if ch.isprintable())

    return s


def prune_tsv_file(
    input_path: str,
    output_path: str,
    stop_flag,
    log_func: Callable,
    do_redact: bool,
    file_progress_cb: Callable[[int, int], None] = None,   # (bytes_done, file_size)
    total_progress_cb: Callable[[int], None] = None,        # (bytes_done_this_file)
):
    """
    Reads a TSV file, removes rows with empty/non-meaningful 'event' column,
    optionally redacts PHI-like patterns in the event column, and writes output.

    Progress callbacks:
      file_progress_cb(bytes_read, file_size)  – called periodically within the file
      total_progress_cb(chunk_bytes)           – called with each chunk so the caller
                                                 can accumulate total bytes done
    """
    kept = 0
    removed = 0
    redacted = 0
    removed_col_mismatch = 0
    removed_empty_event = 0
    first_drops: list = []           # store up to 3 sample dropped rows for diagnostics

    file_size = os.path.getsize(input_path)
    bytes_read = 0
    UPDATE_EVERY = max(1, file_size // 200)   # ~200 UI ticks per file
    last_update_at = 0

    with open(input_path, "r", encoding="utf-8", errors="replace") as fin, \
         open(output_path, "w", encoding="utf-8", errors="replace") as fout:

        header_cols = None

        for line in fin:
            if stop_flag.is_set():
                log_func("Stopping current file...")
                return

            chunk = len(line.encode("utf-8", errors="replace"))
            bytes_read += chunk

            # Progress updates (throttled)
            if bytes_read - last_update_at >= UPDATE_EVERY:
                delta = bytes_read - last_update_at
                last_update_at = bytes_read
                if file_progress_cb:
                    file_progress_cb(bytes_read, file_size)
                if total_progress_cb:
                    total_progress_cb(delta)

            # Keep comment/header lines
            if line.startswith("#"):
                fout.write(line)
                continue

            stripped = line.rstrip("\n")

            # BIDS TSV_EMPTY_LINE: skip completely empty lines
            if not stripped.strip():
                removed += 1
                continue

            # Detect header row
            if header_cols is None:
                header_cols = stripped.split("\t")
                fout.write(line)
                continue

            parts = stripped.split("\t")

            # BIDS TSV_EQUAL_ROWS: skip rows with wrong column count
            if len(parts) != len(header_cols):
                removed += 1
                removed_col_mismatch += 1
                if len(first_drops) < 3:
                    first_drops.append(
                        f"  col_mismatch (expected {len(header_cols)}, got {len(parts)}): {repr(stripped[:120])}"
                    )
                continue

            event_text = parts[-1]

            # Optionally redact
            if do_redact and event_text:
                new_event = redact_phi(event_text)
                if new_event != event_text:
                    redacted += 1
                parts[-1] = new_event
                line_out = "\t".join(parts) + "\n"
            else:
                line_out = line

            if is_meaningful_event(parts[-1]):
                fout.write(line_out)
                kept += 1
            else:
                removed += 1
                removed_empty_event += 1
                if len(first_drops) < 3:
                    first_drops.append(
                        f"  empty_event (last_col={repr(parts[-1][:60])}): {repr(stripped[:120])}"
                    )

    # Final tick: mark file as fully read
    if file_progress_cb:
        file_progress_cb(file_size, file_size)
    remaining_delta = bytes_read - last_update_at
    if remaining_delta > 0 and total_progress_cb:
        total_progress_cb(remaining_delta)

    summary = (
        f"Finished: {os.path.basename(input_path)} | "
        f"kept={kept}, removed={removed}"
        + (f" (col_mismatch={removed_col_mismatch}, empty_event={removed_empty_event})" if removed else "")
        + (f", redacted_rows={redacted}" if do_redact else "")
    )
    log_func(summary)
    if first_drops:
        log_func("  First dropped rows (diagnostic):")
        for d in first_drops:
            log_func(d)


def find_tsv_files(root_dir: str):
    for root, _dirs, files in os.walk(root_dir):
        for fn in files:
            if fn.lower().endswith(".tsv"):
                yield os.path.join(root, fn)


def fmt_gb(n_bytes: float) -> str:
    """Human-readable size string."""
    gb = n_bytes / 1_073_741_824
    if gb >= 0.1:
        return f"{gb:.2f} GB"
    mb = n_bytes / 1_048_576
    if mb >= 0.1:
        return f"{mb:.1f} MB"
    return f"{n_bytes / 1024:.1f} KB"


# -----------------------------
# GUI Application
# -----------------------------

class TSVPrunerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TSV Event Pruner")
        self.root.geometry("860x680")

        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.redact_var = tk.BooleanVar(value=False)

        # Progress state (written by worker thread, read by UI via after())
        self._total_bytes: int = 0
        self._done_bytes: int = 0
        self._file_bytes: int = 0
        self._file_done: int = 0
        self._current_file_name: str = ""
        self._lock = threading.Lock()

        self.stop_flag = threading.Event()
        self.worker_thread = None

        self.build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def build_ui(self):
        pad = 6
        frm = ttk.Frame(self.root)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        # Input folder
        ttk.Label(frm, text="Input Folder (recursive search):").grid(
            row=0, column=0, sticky="w", pady=pad)
        ttk.Entry(frm, textvariable=self.input_dir, width=80).grid(
            row=1, column=0, padx=pad, sticky="we")
        ttk.Button(frm, text="Browse", command=self.browse_input).grid(
            row=1, column=1, padx=pad)

        # Output folder
        ttk.Label(frm, text="Output Folder:").grid(
            row=2, column=0, sticky="w", pady=pad)
        ttk.Entry(frm, textvariable=self.output_dir, width=80).grid(
            row=3, column=0, padx=pad, sticky="we")
        ttk.Button(frm, text="Browse", command=self.browse_output).grid(
            row=3, column=1, padx=pad)

        # Options
        ttk.Checkbutton(
            frm,
            text="Redact PHI-like patterns in event text (emails/IDs/dates/phones)",
            variable=self.redact_var,
        ).grid(row=4, column=0, sticky="w", pady=(8, 4))

        # ── Progress section ───────────────────────────────────────────

        prog_frame = ttk.LabelFrame(frm, text="Progress", padding=8)
        prog_frame.grid(row=5, column=0, columnspan=2, sticky="we", pady=(8, 4))
        prog_frame.columnconfigure(0, weight=1)

        # Current file bar
        ttk.Label(prog_frame, text="Current file:").grid(
            row=0, column=0, sticky="w")
        self.file_label = ttk.Label(prog_frame, text="—", foreground="#555555")
        self.file_label.grid(row=0, column=1, sticky="e")

        self.file_bar = ttk.Progressbar(
            prog_frame, orient="horizontal", length=700, mode="determinate")
        self.file_bar.grid(row=1, column=0, columnspan=2, sticky="we", pady=(2, 6))

        self.file_pct_label = ttk.Label(prog_frame, text="0 %")
        self.file_pct_label.grid(row=2, column=0, sticky="w")

        self.file_size_label = ttk.Label(prog_frame, text="")
        self.file_size_label.grid(row=2, column=1, sticky="e")

        ttk.Separator(prog_frame, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky="we", pady=6)

        # Overall / total bar
        ttk.Label(prog_frame, text="All files remaining:").grid(
            row=4, column=0, sticky="w")
        self.total_label = ttk.Label(prog_frame, text="—", foreground="#555555")
        self.total_label.grid(row=4, column=1, sticky="e")

        self.total_bar = ttk.Progressbar(
            prog_frame, orient="horizontal", length=700, mode="determinate")
        self.total_bar.grid(row=5, column=0, columnspan=2, sticky="we", pady=(2, 6))

        self.total_pct_label = ttk.Label(prog_frame, text="0 %")
        self.total_pct_label.grid(row=6, column=0, sticky="w")

        self.total_size_label = ttk.Label(prog_frame, text="")
        self.total_size_label.grid(row=6, column=1, sticky="e")

        # ── Buttons ────────────────────────────────────────────────────

        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=10)

        self.start_btn = ttk.Button(btn_frame, text="Start", command=self.start)
        self.start_btn.pack(side="left", padx=10)

        self.stop_btn = ttk.Button(
            btn_frame, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=10)

        # Log box
        ttk.Label(frm, text="Status / Log:").grid(row=7, column=0, sticky="w")
        self.log_box = tk.Text(frm, height=14, wrap="word")
        self.log_box.grid(row=8, column=0, columnspan=2, sticky="nsew", pady=pad)

        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(8, weight=1)

    # ------------------------------------------------------------------
    # Browse helpers
    # ------------------------------------------------------------------

    def browse_input(self):
        d = filedialog.askdirectory(title="Select input folder")
        if d:
            self.input_dir.set(d)

    def browse_output(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self.output_dir.set(d)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, msg: str):
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")

    # ------------------------------------------------------------------
    # Progress UI refresh (runs on main thread via after())
    # ------------------------------------------------------------------

    def _refresh_progress(self):
        with self._lock:
            total = self._total_bytes
            done = self._done_bytes
            f_size = self._file_bytes
            f_done = self._file_done
            fname = self._current_file_name

        # ── current file ──
        if f_size > 0:
            f_pct = min(100.0, f_done / f_size * 100)
            remaining = max(0, f_size - f_done)
            self.file_bar["value"] = f_pct
            self.file_pct_label.config(text=f"{f_pct:.1f} %")
            self.file_label.config(text=fname or "—")
            self.file_size_label.config(
                text=f"{fmt_gb(f_done)} / {fmt_gb(f_size)}  |  {fmt_gb(remaining)} remaining")
        else:
            self.file_bar["value"] = 0
            self.file_pct_label.config(text="0 %")
            self.file_size_label.config(text="")

        # ── total / queue ──
        if total > 0:
            t_pct = min(100.0, done / total * 100)
            remaining_total = max(0, total - done)
            self.total_bar["value"] = t_pct
            self.total_pct_label.config(text=f"{t_pct:.1f} %")
            self.total_label.config(text=f"{fmt_gb(done)} processed")
            self.total_size_label.config(
                text=f"{fmt_gb(remaining_total)} remaining  (total {fmt_gb(total)})")

        # Keep refreshing while worker is alive
        if self.worker_thread and self.worker_thread.is_alive():
            self.root.after(150, self._refresh_progress)

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------

    def start(self):
        in_dir = self.input_dir.get().strip()
        out_dir = self.output_dir.get().strip()

        if not in_dir or not os.path.isdir(in_dir):
            messagebox.showerror("Error", "Please select a valid input folder.")
            return
        if not out_dir:
            messagebox.showerror("Error", "Please select a valid output folder.")
            return

        self.stop_flag.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

        do_redact = bool(self.redact_var.get())

        # Reset progress widgets
        self.file_bar["value"] = 0
        self.total_bar["value"] = 0
        self.file_pct_label.config(text="0 %")
        self.total_pct_label.config(text="0 %")
        self.file_label.config(text="scanning…")
        self.total_label.config(text="—")
        self.file_size_label.config(text="")
        self.total_size_label.config(text="")

        def worker():
            try:
                # ── Phase 1: discover files & measure total size ──
                tsv_files = list(find_tsv_files(in_dir))
                total_bytes = sum(os.path.getsize(p) for p in tsv_files)

                with self._lock:
                    self._total_bytes = total_bytes
                    self._done_bytes = 0

                self.log(f"Found {len(tsv_files)} TSV files  ({fmt_gb(total_bytes)} total)")

                # ── Phase 2: process each file ──
                for tsv_path in tsv_files:
                    if self.stop_flag.is_set():
                        self.log("Stopped.")
                        return

                    file_size = os.path.getsize(tsv_path)
                    rel = os.path.relpath(tsv_path, in_dir)
                    out_path = os.path.join(out_dir, rel)
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)

                    # Reset per-file counters
                    with self._lock:
                        self._file_bytes = file_size
                        self._file_done = 0
                        self._current_file_name = os.path.basename(tsv_path)

                    self.log(f"Processing: {rel}  ({fmt_gb(file_size)})")

                    def file_cb(bytes_done, fsize, _path=tsv_path):
                        with self._lock:
                            self._file_done = bytes_done

                    def total_cb(delta):
                        with self._lock:
                            self._done_bytes += delta

                    prune_tsv_file(
                        tsv_path, out_path,
                        self.stop_flag, self.log,
                        do_redact=do_redact,
                        file_progress_cb=file_cb,
                        total_progress_cb=total_cb,
                    )

                self.log(f"Done. Processed {len(tsv_files)} TSV files.")

                # Ensure bars show 100 %
                with self._lock:
                    self._done_bytes = total_bytes
                    self._file_done = self._file_bytes

            finally:
                self.start_btn.configure(state="normal")
                self.stop_btn.configure(state="disabled")

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

        # Kick off UI refresh loop
        self.root.after(150, self._refresh_progress)

    def stop(self):
        self.stop_flag.set()


def main():
    root = tk.Tk()
    app = TSVPrunerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
