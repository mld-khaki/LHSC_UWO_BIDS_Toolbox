#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EDF Time Calculator + Header Viewer (Tkinter, no external EDF libs)

New features:
- "Load EDF..." button to select an .edf/.bdf file.
- Parses the EDF/EDF+ (and BDF) header directly from bytes (no third-party libs).
- Auto-fills "Total Records", "Total Duration", and "Recording Start Time" from the header.
- Shows a full, human-readable dump of the EDF header (including per-signal info) in a status box.
- Keeps the original calculator behavior and CLI interface.

Notes:
- Number of data records may be -1 (unknown) in EDF+. In that case we compute it from file size.
- For BDF (24-bit samples), total records are computed assuming 3 bytes/sample if header reports -1.
- This reader is intentionally minimalistic and robust for typical EDF(+)/BDF files.
"""

import argparse
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import messagebox, filedialog
from tkinter import scrolledtext

# -----------------------------
# Utility: time helpers
# -----------------------------

def time_to_seconds(hhmmss: str) -> int:
    """Convert 'HH:MM:SS' (or 'HH.MM.SS') to seconds."""
    hhmmss = hhmmss.strip().replace('.', ':')
    h, m, s = map(int, hhmmss.split(':'))
    return h * 3600 + m * 60 + s

def seconds_to_hhmmss(seconds: float | int) -> str:
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def normalize_hhmmss(s: str) -> str:
    """Normalize strings like '12.34.56' or '12:34:56' to '12:34:56'."""
    s = s.strip().replace('.', ':')
    parts = [p.zfill(2) for p in s.split(':')]
    if len(parts) != 3:
        raise ValueError(f"Invalid time string: {s}")
    return ":".join(parts)

# -----------------------------
# EDF/BDF header parsing
# -----------------------------

@dataclass
class EdfSignal:
    label: str
    transducer_type: str
    physical_dimension: str
    physical_min: str
    physical_max: str
    digital_min: str
    digital_max: str
    prefiltering: str
    samples_per_record: int
    reserved: str

@dataclass
class EdfHeader:
    version: str
    patient_id: str
    recording_id: str
    start_date: str         # dd.mm.yy
    start_time: str         # hh.mm.ss
    header_bytes: int
    reserved: str
    num_records: int        # -1 for unknown
    duration_of_record: float  # seconds
    num_signals: int
    signals: list[EdfSignal]
    file_size: int
    bytes_per_record: int
    computed_num_records: int | None
    total_duration_seconds: float
    total_duration_hhmmss: str
    is_bdf: bool
    is_edf_plus: bool
    start_time_hhmmss_colon: str  # normalized with colons

def _read_ascii(b: bytes) -> str:
    # EDF is ASCII; strip NULs and spaces.
    return b.decode('ascii', errors='ignore').strip()

def _chunked_read(f, n) -> bytes:
    b = f.read(n)
    if len(b) != n:
        raise ValueError("Unexpected EOF while reading EDF header.")
    return b

def _read_grouped_fields(f, ns: int, field_len: int) -> list[str]:
    # Reads ns * field_len bytes arranged as a single block and splits into ns strings
    block = _chunked_read(f, ns * field_len)
    return [_read_ascii(block[i*field_len:(i+1)*field_len]) for i in range(ns)]

def parse_edf_header(path: str) -> EdfHeader:
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        # Fixed 256-byte main header
        version       = _read_ascii(_chunked_read(f, 8))
        patient_id    = _read_ascii(_chunked_read(f, 80))
        recording_id  = _read_ascii(_chunked_read(f, 80))
        start_date    = _read_ascii(_chunked_read(f, 8))   # dd.mm.yy
        start_time    = _read_ascii(_chunked_read(f, 8))   # hh.mm.ss
        header_bytes  = int(_read_ascii(_chunked_read(f, 8)) or "0")
        reserved      = _read_ascii(_chunked_read(f, 44))
        num_records_s = _read_ascii(_chunked_read(f, 8))
        try:
            num_records = int(num_records_s)
        except ValueError:
            # EDF+ sometimes uses -1 or blank; default to -1 for unknown
            num_records = -1
        duration_of_record = float(_read_ascii(_chunked_read(f, 8)) or "0")
        num_signals   = int(_read_ascii(_chunked_read(f, 4)) or "0")

        # Signal headers are grouped by field across all signals
        labels             = _read_grouped_fields(f, num_signals, 16)
        transducers        = _read_grouped_fields(f, num_signals, 80)
        phys_dims          = _read_grouped_fields(f, num_signals, 8)
        phys_mins          = _read_grouped_fields(f, num_signals, 8)
        phys_maxs          = _read_grouped_fields(f, num_signals, 8)
        dig_mins           = _read_grouped_fields(f, num_signals, 8)
        dig_maxs           = _read_grouped_fields(f, num_signals, 8)
        prefilters         = _read_grouped_fields(f, num_signals, 80)
        samples_per_record = _read_grouped_fields(f, num_signals, 8)
        sig_reserved       = _read_grouped_fields(f, num_signals, 32)

    # Build signals list
    signals: list[EdfSignal] = []
    samples_per_record_int: list[int] = []
    for i in range(num_signals):
        spr_s = samples_per_record[i].strip() or "0"
        try:
            spr_i = int(float(spr_s))  # some files store "256 " or "256.0"
        except ValueError:
            spr_i = 0
        samples_per_record_int.append(spr_i)
        signals.append(EdfSignal(
            label=labels[i],
            transducer_type=transducers[i],
            physical_dimension=phys_dims[i],
            physical_min=phys_mins[i],
            physical_max=phys_maxs[i],
            digital_min=dig_mins[i],
            digital_max=dig_maxs[i],
            prefiltering=prefilters[i],
            samples_per_record=spr_i,
            reserved=sig_reserved[i],
        ))

    # Detect BDF (24-bit) vs EDF (16-bit)
    ext = os.path.splitext(path)[1].lower()
    is_bdf = (ext == ".bdf") or ("BDF" in reserved.upper())
    bytes_per_sample = 3 if is_bdf else 2

    # Compute bytes per record = sum(samples_per_record)*bytes_per_sample
    bytes_per_record = sum(samples_per_record_int) * bytes_per_sample

    # Compute total records if unknown
    computed_num_records: int | None = None
    if num_records < 0:
        # header_bytes bytes of header; remainder is data records
        if header_bytes <= 0:
            # fallback: EDF header is 256 + ns*256
            header_bytes = 256 + num_signals * 256
        data_bytes = max(0, size - header_bytes)
        computed_num_records = data_bytes // bytes_per_record if bytes_per_record > 0 else 0
        total_records = computed_num_records
    else:
        total_records = num_records

    # Total duration in seconds = total_records * duration_of_record
    total_duration_seconds = float(total_records) * float(duration_of_record)
    total_duration_hhmmss = seconds_to_hhmmss(total_duration_seconds)

    # Detect EDF+ (reserved usually contains 'EDF+C' or 'EDF+D')
    is_edf_plus = "EDF+" in reserved.upper() or "EDF+C" in reserved.upper() or "EDF+D" in reserved.upper()

    # Normalize start time to colons for GUI
    start_time_norm = start_time.replace('.', ':')

    return EdfHeader(
        version=version,
        patient_id=patient_id,
        recording_id=recording_id,
        start_date=start_date,
        start_time=start_time,
        header_bytes=header_bytes,
        reserved=reserved,
        num_records=num_records,
        duration_of_record=float(duration_of_record),
        num_signals=num_signals,
        signals=signals,
        file_size=size,
        bytes_per_record=bytes_per_record,
        computed_num_records=computed_num_records,
        total_duration_seconds=total_duration_seconds,
        total_duration_hhmmss=total_duration_hhmmss,
        is_bdf=is_bdf,
        is_edf_plus=is_edf_plus,
        start_time_hhmmss_colon=start_time_norm,
    )

def format_header_for_display(h: EdfHeader, path: str) -> str:
    lines = []
    lines.append(f"File: {path}")
    lines.append(f"Size: {h.file_size:,} bytes")
    lines.append("")
    lines.append("=== Main Header ===")
    lines.append(f"Version              : {h.version}")
    lines.append(f"Patient ID           : {h.patient_id}")
    lines.append(f"Recording ID         : {h.recording_id}")
    lines.append(f"Start Date           : {h.start_date}")
    lines.append(f"Start Time           : {h.start_time} (normalized: {h.start_time_hhmmss_colon})")
    lines.append(f"Header Bytes         : {h.header_bytes}")
    lines.append(f"Reserved             : {h.reserved}")
    lines.append(f"EDF+                 : {h.is_edf_plus}")
    lines.append(f"BDF (24-bit)         : {h.is_bdf}")
    lines.append(f"Number of Records    : {h.num_records}")
    if h.computed_num_records is not None:
        lines.append(f"Computed Records     : {h.computed_num_records} (from file size)")
    lines.append(f"Duration/Record (s)  : {h.duration_of_record}")
    lines.append(f"Bytes/Record         : {h.bytes_per_record}")
    lines.append(f"Signals              : {h.num_signals}")
    lines.append(f"Total Duration (s)   : {h.total_duration_seconds:.3f}")
    lines.append(f"Total Duration (H:M:S): {h.total_duration_hhmmss}")
    lines.append("")
    lines.append("=== Signals ===")
    if h.num_signals == 0:
        lines.append("(No signal headers)")
    else:
        hdr = f"{'Idx':>3}  {'Label':<16}  {'Dim':<8}  {'PhysMin':>8}  {'PhysMax':>8}  {'DigMin':>8}  {'DigMax':>8}  {'Samp/Rec':>8}  {'Prefilter':<30}"
        lines.append(hdr)
        lines.append("-"*len(hdr))
        for i, s in enumerate(h.signals):
            lines.append(f"{i:>3}  {s.label:<16}  {s.physical_dimension:<8}  {s.physical_min:>8}  {s.physical_max:>8}  {s.digital_min:>8}  {s.digital_max:>8}  {s.samples_per_record:>8}  {s.prefiltering[:30]:<30}")
    return "\n".join(lines)

# -----------------------------
# Original record range logic
# -----------------------------

def compute_record_indices(
    total_records: int,
    total_duration_str: str,
    recording_start_time_str: str,
    target_start_str: str,
    target_end_str: str,
    pre_offset_minutes: int = 30,
    post_offset_minutes: int = 30
) -> str:
    total_duration_seconds = time_to_seconds(total_duration_str)
    recording_start_seconds = time_to_seconds(recording_start_time_str)
    target_start_seconds = time_to_seconds(target_start_str)
    target_end_seconds = time_to_seconds(target_end_str)

    records_per_second = total_records / total_duration_seconds if total_duration_seconds > 0 else 0.0

    adjusted_start = target_start_seconds - (pre_offset_minutes * 60)
    adjusted_end = target_end_seconds + (post_offset_minutes * 60)

    # Handle wrapping across midnight relative to recording start
    if adjusted_start < recording_start_seconds:
        adjusted_start += 24 * 3600
    if adjusted_end < recording_start_seconds:
        adjusted_end += 24 * 3600

    seconds_from_start_to_adjusted_start = adjusted_start - recording_start_seconds
    seconds_from_start_to_adjusted_end = adjusted_end - recording_start_seconds

    record_start = round(seconds_from_start_to_adjusted_start * records_per_second)
    record_end = round(seconds_from_start_to_adjusted_end * records_per_second) - 1  # inclusive end

    actual_recording_start = datetime.strptime(normalize_hhmmss(recording_start_time_str), "%H:%M:%S")
    start_timestamp = actual_recording_start + timedelta(seconds=seconds_from_start_to_adjusted_start)
    end_timestamp = actual_recording_start + timedelta(seconds=seconds_from_start_to_adjusted_end)

    result = (
        f"Adjusted Start Time: {start_timestamp.time()} -> Record #{record_start}\n"
        f"Adjusted End Time:   {end_timestamp.time()} -> Record #{record_end}"
    )
    return result

# -----------------------------
# GUI
# -----------------------------

def run_gui():
    # State that persists across callbacks
    state = {
        "edf_path": None,
        "edf_header": None,
    }

    def on_load_edf():
        path = filedialog.askopenfilename(
            title="Select EDF/BDF file",
            filetypes=[("EDF/BDF files", "*.edf *.bdf"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            header = parse_edf_header(path)
        except Exception as e:
            messagebox.showerror("EDF Parse Error", f"Failed to parse header:\n{e}")
            return

        state["edf_path"] = path
        state["edf_header"] = header

        # Fill entries from header
        total_records = header.num_records if header.num_records >= 0 else (header.computed_num_records or 0)
        entries['Total Records'].delete(0, tk.END)
        entries['Total Records'].insert(0, str(total_records))

        entries['Total Duration (HH:MM:SS)'].delete(0, tk.END)
        entries['Total Duration (HH:MM:SS)'].insert(0, header.total_duration_hhmmss)

        entries['Recording Start Time (HH:MM:SS)'].delete(0, tk.END)
        entries['Recording Start Time (HH:MM:SS)'].insert(0, normalize_hhmmss(header.start_time))

        # Show header in status box
        txt_status.configure(state='normal')
        txt_status.delete("1.0", tk.END)
        txt_status.insert(tk.END, format_header_for_display(header, path))
        txt_status.configure(state='disabled')

        var_selected_file.set(f"Loaded: {path}")

    def on_submit():
        try:
            total_records = int(entries['Total Records'].get())
            total_duration = entries['Total Duration (HH:MM:SS)'].get().strip()
            recording_start = entries['Recording Start Time (HH:MM:SS)'].get().strip()
            target_start = entries['Target Start Time (HH:MM:SS)'].get().strip()
            target_end = entries['Target End Time (HH:MM:SS)'].get().strip()
            pre_offset = int(entries['Pre-Offset (minutes)'].get())
            post_offset = int(entries['Post-Offset (minutes)'].get())

            # Basic normalization
            total_duration = normalize_hhmmss(total_duration)
            recording_start = normalize_hhmmss(recording_start)
            target_start = normalize_hhmmss(target_start)
            target_end = normalize_hhmmss(target_end)

            result = compute_record_indices(
                total_records,
                total_duration,
                recording_start,
                target_start,
                target_end,
                pre_offset,
                post_offset
            )

            messagebox.showinfo("Result", result)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # --- Build GUI ---
    root = tk.Tk()
    root.title("EDF Record Index Calculator + Header Viewer")

    main = tk.Frame(root)
    main.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)

    var_selected_file = tk.StringVar(value="No EDF loaded")

    # Top controls: Load EDF + selected file label
    top = tk.Frame(main)
    top.pack(side=tk.TOP, fill=tk.X)
    btn_load = tk.Button(top, text="Load EDF...", command=on_load_edf)
    btn_load.pack(side=tk.LEFT)
    lbl_file = tk.Label(top, textvariable=var_selected_file, anchor="w")
    lbl_file.pack(side=tk.LEFT, padx=10)

    # Form fields
    fields = [
        'Total Records',
        'Total Duration (HH:MM:SS)',
        'Recording Start Time (HH:MM:SS)',
        'Target Start Time (HH:MM:SS)',
        'Target End Time (HH:MM:SS)',
        'Pre-Offset (minutes)',
        'Post-Offset (minutes)'
    ]
    entries: dict[str, tk.Entry] = {}

    grid = tk.Frame(main)
    grid.pack(side=tk.TOP, fill=tk.X, pady=(10, 6))
    for i, field in enumerate(fields):
        tk.Label(grid, text=field).grid(row=i, column=0, sticky='e', padx=5, pady=4)
        entry = tk.Entry(grid, width=28)
        entry.grid(row=i, column=1, padx=5, pady=4, sticky='we')
        entries[field] = entry
    grid.grid_columnconfigure(1, weight=1)

    # Defaults
    entries['Pre-Offset (minutes)'].insert(0, '30')
    entries['Post-Offset (minutes)'].insert(0, '30')

    # Calculate button
    submit_button = tk.Button(main, text="Calculate", command=on_submit)
    submit_button.pack(side=tk.TOP, pady=8)

    # Status box (header dump)
    box_frame = tk.LabelFrame(main, text="EDF Header (read-only)")
    box_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(8,0))
    txt_status = scrolledtext.ScrolledText(box_frame, height=18, wrap="none", state='disabled')
    txt_status.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    root.minsize(640, 480)
    root.mainloop()

# -----------------------------
# CLI
# -----------------------------

def main():
    parser = argparse.ArgumentParser(description="Calculate record range for a time window in an EDF recording.")
    parser.add_argument("--total_records", type=int, help="Total number of records")
    parser.add_argument("--duration", type=str, help="Total duration in HH:MM:SS")
    parser.add_argument("--start_time", type=str, help="Recording start time in HH:MM:SS")
    parser.add_argument("--target_start", type=str, help="Target window start time in HH:MM:SS")
    parser.add_argument("--target_end", type=str, help="Target window end time in HH:MM:SS")
    parser.add_argument("--pre_offset", type=int, default=30, help="Minutes before target start")
    parser.add_argument("--post_offset", type=int, default=30, help="Minutes after target end")
    parser.add_argument("--edf", type=str, help="Optional EDF/BDF path to parse header and print a summary")

    args = parser.parse_args()

    if args.edf:
        try:
            h = parse_edf_header(args.edf)
        except Exception as e:
            print(f"Failed to parse EDF header: {e}")
            return
        print(format_header_for_display(h, args.edf))

    if all([args.total_records, args.duration, args.start_time, args.target_start, args.target_end]):
        result = compute_record_indices(
            args.total_records,
            normalize_hhmmss(args.duration),
            normalize_hhmmss(args.start_time),
            normalize_hhmmss(args.target_start),
            normalize_hhmmss(args.target_end),
            args.pre_offset,
            args.post_offset
        )
        print(result)
    else:
        run_gui()

if __name__ == "__main__":
    main()
