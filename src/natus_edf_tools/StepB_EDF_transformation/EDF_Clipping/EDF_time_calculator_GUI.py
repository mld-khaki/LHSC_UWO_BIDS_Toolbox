#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import messagebox, filedialog
from tkinter import scrolledtext

# ============================================================
# Time utilities
# ============================================================

def normalize_hhmmss(s: str) -> str:
    s = s.strip().replace('.', ':')
    parts = s.split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid time format: {s}")
    return ":".join(p.zfill(2) for p in parts)

def hms_to_seconds(hms: str) -> int:
    h, m, s = map(int, normalize_hhmmss(hms).split(':'))
    return h * 3600 + m * 60 + s

def seconds_to_hhmmss(seconds: int) -> str:
    seconds = int(max(seconds, 0))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

# ============================================================
# EDF header parsing (UNCHANGED)
# ============================================================
def _read_ascii(b: bytes) -> str:
    """Decode bytes to ASCII, strip trailing spaces and nulls."""
    return b.decode("ascii", errors="ignore").strip(" \x00")

def _chunked_read(f, n: int) -> bytes:
    """Read exactly n bytes or raise IOError."""
    data = f.read(n)
    if len(data) != n:
        raise IOError(f"Unexpected EOF while reading {n} bytes, got {len(data)}")
    return data

def _chunked_read(f, n: int) -> bytes:
    """Read exactly n bytes or raise IOError."""
    data = f.read(n)
    if len(data) != n:
        raise IOError(f"Unexpected EOF while reading {n} bytes, got {len(data)}")
    return data
    
    
def _read_grouped_fields(f, n_signals: int, field_len: int) -> list[str]:
    """
    EDF/BDF packs each signal field as n_signals * field_len bytes.
    We read the whole block then slice.
    """
    raw = _chunked_read(f, n_signals * field_len)
    out = []
    for i in range(n_signals):
        out.append(_read_ascii(raw[i * field_len:(i + 1) * field_len]))
    return out


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
    path: str
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
    start_time_hhmmss: str  # normalized with colons
    total_records: int


def parse_edf_header(path: str) -> EdfHeader:
    """
    Minimal EDF/EDF+/BDF header parser that:
    - Reads main header + signal headers.
    - Distinguishes BDF (24-bit) via "24BIT" in reserved field or heuristics.
    - Computes number of records from file size if header gives -1/invalid.
    """
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

    # Total samples per record (for all signals)
    total_samples_per_record = sum(samples_per_record_int)

    # Very small heuristic to detect BDF: reserved often contains "24BIT"
    is_bdf = "24BIT" in reserved.upper()
    if is_bdf:
        bytes_per_sample = 3
    else:
        # Classic EDF = 2 bytes/sample
        bytes_per_sample = 2

    bytes_per_record = total_samples_per_record * bytes_per_sample
    data_bytes = max(size - header_bytes, 0)

    # EDF+ may have -1 or 0 for unknown number of records
    if bytes_per_record > 0:
        computed_num_records = data_bytes // bytes_per_record
    else:
        computed_num_records = None

    # Choose an "effective" record count
    effective_records = num_records
    if effective_records <= 0 and computed_num_records is not None:
        effective_records = computed_num_records

    total_duration_seconds = effective_records * duration_of_record
    total_duration_hhmmss = seconds_to_hhmmss(total_duration_seconds)

    # Normalize start time to HH:MM:SS in case it uses dots
    try:
        start_time_norm = normalize_hhmmss(start_time)
    except Exception:
        start_time_norm = "00:00:00"

    is_edf_plus = "EDF+" in version.upper() or "EDF+" in recording_id.upper()

    return EdfHeader(
        path=path,
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
        start_time_hhmmss=start_time_norm,
        total_records=effective_records,
    )

# ============================================================
# CORE FIXED COMPUTATION
# ============================================================

def compute_record_indices(
    total_records: int,
    total_duration_seconds: int,
    recording_start_datetime: datetime,
    target_start_hms: str,
    target_end_hms: str,
    day_offset_hms: str,
    pre_offset_min: int,
    post_offset_min: int
) -> str:

    warnings = []

    records_per_second = total_records / total_duration_seconds

    # FIXED:
    day_offset_sec = hms_to_seconds(day_offset_hms)

    # Parse target times as seconds from midnight
    target_start_sec_from_midnight = hms_to_seconds(target_start_hms)
    target_end_sec_from_midnight = hms_to_seconds(target_end_hms)

    # Calculate recording start time in seconds from midnight
    rec_start_sec_from_midnight = (recording_start_datetime.hour * 3600 + 
                                    recording_start_datetime.minute * 60 + 
                                    recording_start_datetime.second)

    # Calculate absolute time in seconds from midnight (with day offset)
    target_start_abs = target_start_sec_from_midnight + day_offset_sec
    target_end_abs = target_end_sec_from_midnight + day_offset_sec

    # Convert to seconds relative to recording start
    target_start_sec = target_start_abs - rec_start_sec_from_midnight
    target_end_sec = target_end_abs - rec_start_sec_from_midnight
    if target_end_sec <= target_start_sec:
        raise ValueError("Target end must be after target start.")

    adjusted_start = target_start_sec - pre_offset_min * 60
    adjusted_end = target_end_sec + post_offset_min * 60

    if adjusted_start < 0:
        adjusted_start = 0
        warnings.append("Adjusted start clipped to file start.")

    if adjusted_end > total_duration_seconds:
        adjusted_end = total_duration_seconds
        warnings.append("Adjusted end clipped to file end.")

    start_record = int(adjusted_start * records_per_second)
    end_record = int(adjusted_end * records_per_second) - 1

    start_record = max(start_record, 0)
    end_record = min(end_record, total_records - 1)

    abs_start_dt = recording_start_datetime + timedelta(seconds=adjusted_start)
    abs_end_dt = recording_start_datetime + timedelta(seconds=adjusted_end)

    rel_start = seconds_to_hhmmss(adjusted_start)
    rel_end = seconds_to_hhmmss(adjusted_end)

    result = (
        f"Adjusted Start:\n"
        f"  Absolute : {abs_start_dt}\n"
        f"  Relative : +{rel_start}\n"
        f"  Record   : #{start_record}\n\n"
        f"Adjusted End:\n"
        f"  Absolute : {abs_end_dt}\n"
        f"  Relative : +{rel_end}\n"
        f"  Record   : #{end_record}"
    )

    if warnings:
        result += "\n\nWarnings:\n" + "\n".join(f"- {w}" for w in warnings)

    return result

# ============================================================
# GUI
# ============================================================

def run_gui():
    root = tk.Tk()
    root.title("EDF Record Index Calculator (Robust Time Model)")

    header_state = {"header": None}

    def load_edf():
        path = filedialog.askopenfilename(filetypes=[("EDF files", "*.edf")])
        if not path:
            return
            
        h = parse_edf_header(path)
        try:
            h = parse_edf_header(path)
        except Exception as e:
            messagebox.showerror("EDF Error", str(e))
            #return

        header_state["header"] = h

        entries["Total Records"].delete(0, tk.END)
        entries["Total Records"].insert(0, str(h.total_records))

        entries["Total Duration (HH:MM:SS)"].delete(0, tk.END)
        entries["Total Duration (HH:MM:SS)"].insert(0, h.total_duration_hhmmss)

        entries["Recording Start Time (HH:MM:SS)"].delete(0, tk.END)
        entries["Recording Start Time (HH:MM:SS)"].insert(0, h.start_time_hhmmss)

        status.configure(state="normal")
        status.delete("1.0", tk.END)
        status.insert(tk.END, f"Loaded EDF: {path}\nStart date: {h.start_date}")
        status.configure(state="disabled")

    def calculate():
        try:
            h = header_state["header"]
            if h is None:
                raise ValueError("No EDF loaded.")

            rec_start_dt = datetime.strptime(
                f"{h.start_date} {h.start_time_hhmmss}",
                "%d.%m.%y %H:%M:%S"
            )

            result = compute_record_indices(
                total_records=int(entries["Total Records"].get()),
                total_duration_seconds=h.total_duration_seconds,
                recording_start_datetime=rec_start_dt,
                target_start_hms=entries["Target Start Time (HH:MM:SS)"].get(),
                target_end_hms=entries["Target End Time (HH:MM:SS)"].get(),
                day_offset_hms=entries["Day Offset (HH:MM:SS)"].get(),
                pre_offset_min=int(entries["Pre-Offset (minutes)"].get()),
                post_offset_min=int(entries["Post-Offset (minutes)"].get())
            )

            messagebox.showinfo("Result", result)

        except Exception as e:
            messagebox.showerror("Error", str(e))

    fields = [
        "Total Records",
        "Total Duration (HH:MM:SS)",
        "Recording Start Time (HH:MM:SS)",
        "Target Start Time (HH:MM:SS)",
        "Target End Time (HH:MM:SS)",
        "Day Offset (HH:MM:SS)",
        "Pre-Offset (minutes)",
        "Post-Offset (minutes)"
    ]

    entries = {}

    frame = tk.Frame(root)
    frame.pack(padx=10, pady=10)

    for i, f in enumerate(fields):
        tk.Label(frame, text=f).grid(row=i, column=0, sticky="e", padx=5, pady=3)
        e = tk.Entry(frame, width=25)
        e.grid(row=i, column=1, pady=3)
        entries[f] = e

    entries["Day Offset (HH:MM:SS)"].insert(0, "00:00:00")
    entries["Pre-Offset (minutes)"].insert(0, "30")
    entries["Post-Offset (minutes)"].insert(0, "30")

    tk.Button(frame, text="Load EDF", command=load_edf).grid(row=len(fields), column=0, pady=10)
    tk.Button(frame, text="Calculate", command=calculate).grid(row=len(fields), column=1)

    status = scrolledtext.ScrolledText(root, height=5, state="disabled")
    status.pack(fill="both", padx=10, pady=10)

    root.mainloop()

# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    run_gui()
