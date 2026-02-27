#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EDF/BDF Metadata Comparator GUI (Tkinter, no external EDF libs)

Features:
- Two panes (LEFT and RIGHT), each with its own Load button directly above its pane.
- Shows file name + full path.
- In-depth comparison:
  1) Summary fields (file size, header bytes, records, computed records, duration/record, total duration, bytes/record, num signals, start date/time, EDF+/BDF flags, IDs)
  2) Per-signal comparison table (by signal index): label, transducer, physical dimension, physical/digital min/max, prefilter, samples/record, reserved
  3) Raw header dump (human-readable) for each file
- Highlights mismatches in red (row-level highlighting).
- Delete button per file; requires confirmation; deletes only that file and clears the pane.

Based on the EDF header parser pattern in the user's provided EDF_time_calculator_GUI.py.
"""

import os
import re
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import scrolledtext
from pathlib import Path

# -----------------------------
# EDF/BDF header parsing (from your provided style)
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
    path: str
    version: str
    patient_id: str
    recording_id: str
    start_date: str
    start_time: str
    header_bytes: int
    reserved: str
    num_records: int
    duration_of_record: float
    num_signals: int
    signals: list
    file_size: int
    bytes_per_record: int
    computed_num_records: int | None
    total_duration_seconds: float
    total_duration_hhmmss: str
    is_bdf: bool
    is_edf_plus: bool
    start_time_hhmmss_colon: str

def _read_ascii(b: bytes) -> str:
    return b.decode("ascii", errors="ignore").strip(" \x00")

def _chunked_read(f, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise IOError(f"Unexpected EOF while reading {n} bytes, got {len(data)}")
    return data

def _read_grouped_fields(f, n_signals: int, field_len: int) -> list[str]:
    raw = _chunked_read(f, n_signals * field_len)
    out = []
    for i in range(n_signals):
        out.append(_read_ascii(raw[i * field_len:(i + 1) * field_len]))
    return out

def seconds_to_hhmmss(seconds: float | int) -> str:
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def normalize_hhmmss(s: str) -> str:
    s = s.strip().replace('.', ':')
    parts = [p.zfill(2) for p in s.split(':')]
    if len(parts) != 3:
        raise ValueError(f"Invalid time string: {s}")
    return ":".join(parts)

def parse_edf_header(path: str) -> EdfHeader:
    size = os.path.getsize(path)

    with open(path, 'rb') as f:
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
            num_records = -1
        duration_of_record = float(_read_ascii(_chunked_read(f, 8)) or "0")
        num_signals   = int(_read_ascii(_chunked_read(f, 4)) or "0")

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

    signals = []
    spr_ints = []
    for i in range(num_signals):
        spr_s = samples_per_record[i].strip() or "0"
        try:
            spr_i = int(float(spr_s))
        except ValueError:
            spr_i = 0
        spr_ints.append(spr_i)
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

    total_samples_per_record = sum(spr_ints)
    is_bdf = "24BIT" in reserved.upper()
    bytes_per_sample = 3 if is_bdf else 2

    bytes_per_record = total_samples_per_record * bytes_per_sample
    data_bytes = max(size - header_bytes, 0)

    computed_num_records = None
    if bytes_per_record > 0:
        computed_num_records = data_bytes // bytes_per_record

    effective_records = num_records
    if effective_records <= 0 and computed_num_records is not None:
        effective_records = computed_num_records

    total_duration_seconds = effective_records * duration_of_record
    total_duration_hhmmss = seconds_to_hhmmss(total_duration_seconds)

    try:
        start_time_norm = normalize_hhmmss(start_time)
    except Exception:
        start_time_norm = "00:00:00"

    is_edf_plus = ("EDF+" in version.upper()) or ("EDF+" in recording_id.upper())

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
        start_time_hhmmss_colon=start_time_norm,
    )

def format_header_for_display(h: EdfHeader) -> str:
    lines = []
    lines.append("=== EDF/BDF Header Summary ===")
    lines.append(f"File                 : {h.path}")
    lines.append(f"File size            : {h.file_size} bytes")
    lines.append(f"Version              : {h.version}")
    lines.append(f"Patient ID           : {h.patient_id}")
    lines.append(f"Recording ID         : {h.recording_id}")
    lines.append(f"Start Date           : {h.start_date}")
    lines.append(f"Start time (raw)     : {h.start_time}")
    lines.append(f"Start time (HH:MM:SS): {h.start_time_hhmmss_colon}")
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
        hdr = (
            f"{'Idx':>3}  {'Label':<16}  {'Dim':<8}  {'PhysMin':>8}  {'PhysMax':>8}  "
            f"{'DigMin':>8}  {'DigMax':>8}  {'Samp/Rec':>8}  {'Prefilter':<30}"
        )
        lines.append(hdr)
        lines.append("-" * len(hdr))
        for i, s in enumerate(h.signals):
            lines.append(
                f"{i:>3}  {s.label:<16}  {s.physical_dimension:<8}  {s.physical_min:>8}  {s.physical_max:>8}  "
                f"{s.digital_min:>8}  {s.digital_max:>8}  {s.samples_per_record:>8}  {s.prefiltering[:30]:<30}"
            )
    return "\n".join(lines)

# -----------------------------
# GUI
# -----------------------------

class Pane:
    def __init__(self):
        self.header: EdfHeader | None = None
        self.last_dir: str | None = None
        self.path_var: tk.StringVar | None = None

class EDFComparatorApp:
    SUMMARY_FIELDS = [
        ("File name", "file_basename"),
        ("Full path", "path"),
        ("File size (bytes)", "file_size"),
        ("Header bytes", "header_bytes"),
        ("Version", "version"),
        ("Patient ID", "patient_id"),
        ("Recording ID", "recording_id"),
        ("Start date", "start_date"),
        ("Start time (raw)", "start_time"),
        ("Start time (HH:MM:SS)", "start_time_hhmmss_colon"),
        ("EDF+ flag", "is_edf_plus"),
        ("BDF 24-bit flag", "is_bdf"),
        ("Num signals", "num_signals"),
        ("Duration/record (s)", "duration_of_record"),
        ("Header num records", "num_records"),
        ("Computed num records", "computed_num_records"),
        ("Bytes/record", "bytes_per_record"),
        ("Total duration (s)", "total_duration_seconds"),
        ("Total duration (HH:MM:SS)", "total_duration_hhmmss"),
    ]

    SIGNAL_COLS = [
        ("Idx", "idx"),
        ("Label", "label"),
        ("Transducer", "transducer_type"),
        ("PhysDim", "physical_dimension"),
        ("PhysMin", "physical_min"),
        ("PhysMax", "physical_max"),
        ("DigMin", "digital_min"),
        ("DigMax", "digital_max"),
        ("Prefilter", "prefiltering"),
        ("Samp/Rec", "samples_per_record"),
        ("Reserved", "reserved"),
    ]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("EDF/BDF In-Depth Metadata Comparator")

        self.left = Pane()
        self.right = Pane()

        self._build_ui()
        self._refresh_all()

    def _build_ui(self):
        self.root.geometry("1400x820")

        # Main container
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=10, pady=10)

        # Two columns
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        self.left_frame = ttk.Frame(main)
        self.right_frame = ttk.Frame(main)
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.right_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self._build_pane(self.left_frame, side="LEFT")
        self._build_pane(self.right_frame, side="RIGHT")

        # Global compare hint
        hint = ttk.Label(self.root, text="Rows highlighted red indicate differences between LEFT and RIGHT.")
        hint.pack(anchor="w", padx=12, pady=(0, 8))

    def _build_pane(self, parent: ttk.Frame, side: str):
        # -----------------------------
        # Top controls
        # -----------------------------
        top = ttk.Frame(parent)
        top.pack(fill="x", pady=(0, 8))

        pane = self.left if side == "LEFT" else self.right

        load_btn = ttk.Button(
            top,
            text=f"Load {side} EDF/BDF",
            command=(self._load_left if side == "LEFT" else self._load_right)
        )
        load_btn.pack(side="left")

        # LEFT-only: BIDS navigation
        move_btn = None
        if side == "LEFT":
            move_btn = ttk.Button(
                top,
                text="Move to next →",
                command=self._move_left_to_next
            )
            move_btn.pack(side="left", padx=6)

        pane.path_var = tk.StringVar(value="")
        path_entry = ttk.Entry(top, textvariable=pane.path_var)
        path_entry.pack(side="left", padx=8, fill="x", expand=True)

        # Manual entry + Enter
        path_entry.bind(
            "<Return>",
            lambda e, s=side: self._load_from_path(s)
        )

        # RIGHT-only: find corresponding file from LEFT
        if side == "RIGHT":
            find_btn = ttk.Button(
                top,
                text="Find corresponding file ← LEFT",
                command=self._find_corresponding_in_right
            )
            find_btn.pack(side="left", padx=6)

        # -----------------------------
        # Notebook
        # -----------------------------
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True)

        tab_summary = ttk.Frame(nb)
        tab_signals = ttk.Frame(nb)
        tab_raw = ttk.Frame(nb)

        nb.add(tab_summary, text="Summary")
        nb.add(tab_signals, text="Signals")
        nb.add(tab_raw, text="Raw header")

        # -----------------------------
        # Summary table
        # -----------------------------
        summary_tree = ttk.Treeview(tab_summary, columns=("field", "value"), show="headings")
        summary_tree.heading("field", text="Field")
        summary_tree.heading("value", text="Value")
        summary_tree.column("field", width=220, anchor="w", stretch=False)
        summary_tree.column("value", width=520, anchor="w", stretch=True)

        vs = ttk.Scrollbar(tab_summary, orient="vertical", command=summary_tree.yview)
        summary_tree.configure(yscrollcommand=vs.set)

        summary_tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        summary_tree.tag_configure("diff", background="#ffcccc")

        # -----------------------------
        # Signals table
        # -----------------------------
        sig_cols = [c[0] for c in self.SIGNAL_COLS]
        signals_tree = ttk.Treeview(tab_signals, columns=sig_cols, show="headings")

        for c in sig_cols:
            signals_tree.heading(c, text=c)
            signals_tree.column(c, width=120, anchor="w", stretch=True)

        vs2 = ttk.Scrollbar(tab_signals, orient="vertical", command=signals_tree.yview)
        hs2 = ttk.Scrollbar(tab_signals, orient="horizontal", command=signals_tree.xview)
        signals_tree.configure(yscrollcommand=vs2.set, xscrollcommand=hs2.set)

        signals_tree.grid(row=0, column=0, sticky="nsew")
        vs2.grid(row=0, column=1, sticky="ns")
        hs2.grid(row=1, column=0, sticky="ew")

        tab_signals.rowconfigure(0, weight=1)
        tab_signals.columnconfigure(0, weight=1)
        signals_tree.tag_configure("diff", background="#ffcccc")

        # -----------------------------
        # Raw header
        # -----------------------------
        raw_txt = scrolledtext.ScrolledText(tab_raw, wrap="none", height=20)
        raw_txt.pack(fill="both", expand=True)
        raw_txt.configure(state="disabled")

        # -----------------------------
        # Delete button
        # -----------------------------
        bottom = ttk.Frame(parent)
        bottom.pack(fill="x", pady=(8, 0))

        del_btn = ttk.Button(
            bottom,
            text=f"Delete {side} file…",
            command=(self._delete_left if side == "LEFT" else self._delete_right)
        )
        del_btn.pack(side="left")

        ttk.Label(bottom, text="(Requires confirmation)", foreground="red").pack(side="left", padx=8)

        # Save references
        if side == "LEFT":
            self.left_summary_tree = summary_tree
            self.left_signals_tree = signals_tree
            self.left_raw_txt = raw_txt
            self.left_delete_btn = del_btn
            self.left_move_btn = move_btn
        else:
            self.right_summary_tree = summary_tree
            self.right_signals_tree = signals_tree
            self.right_raw_txt = raw_txt
            self.right_delete_btn = del_btn


    def _check_internal_consistency(self, h: EdfHeader | None) -> tuple[bool, str]:
        """
        Strict EDF structural consistency check.

        Rules:
        - If header num_records == -1, duration-based quantities are NOT independent.
        - In that case, the ONLY physical truth is file size.
        - Any non-trivial EDF must have a self-consistent size → samples → records relation.
        """

        if h is None:
            return True, ""

        issues = []

        # -----------------------------
        # Sanity: bytes_per_record must be > 0
        # -----------------------------
        if h.bytes_per_record <= 0:
            return False, "Invalid bytes_per_record (≤ 0)"

        # -----------------------------
        # Size-implied record count
        # -----------------------------
        data_bytes = h.file_size - h.header_bytes
        if data_bytes <= 0:
            return False, "File size smaller than header"

        size_records = data_bytes / h.bytes_per_record

        # -----------------------------
        # Case 1: Header explicitly defines record count
        # -----------------------------
        if h.num_records > 0:
            if abs(size_records - h.num_records) > 1:
                issues.append(
                    f"Header vs size mismatch "
                    f"(header={h.num_records}, size≈{size_records:.1f})"
                )

        # -----------------------------
        # Case 2: Header record count UNKNOWN → this is NOT benign
        # -----------------------------
        else:
            # EDF+ allows -1, but ONLY if duration & size are still coherent.
            # In our parser, duration is derived → NOT independent → flag.
            issues.append(
                "Header num_records is -1 and duration is derived; "
                "file cannot be independently validated"
            )

            # Extra hard check: record count is absurd for file size
            if size_records < 1e5:
                issues.append(
                    f"Implied record count from size is suspiciously low "
                    f"(≈{size_records:.1f})"
                )

        if issues:
            return False, " | ".join(issues)

        return True, "OK"

    def _find_corresponding_in_right(self):
        # LEFT must be a loaded file
        if not self.left.header:
            messagebox.showerror(
                "No LEFT file",
                "Load an EDF/BDF file in the LEFT pane first."
            )
            return

        # RIGHT must be a directory
        right_path = self.right.path_var.get().strip()
        if not os.path.isdir(right_path):
            dir_path = os.path.dirname(right_path)
            if os.path.isdir(dir_path):
                right_path = dir_path
            else:
                if not right_path or not os.path.isdir(right_path):
                    messagebox.showerror(
                        "Invalid RIGHT directory",
                        "The RIGHT pane must contain a directory path."
                    )
                    return

        left_size = self.left.header.file_size
        matches = []

        for fname in os.listdir(right_path):
            if not fname.lower().endswith((".edf", ".bdf")):
                continue
            full = os.path.join(right_path, fname)
            if not os.path.isfile(full):
                continue
            try:
                if os.path.getsize(full) == left_size:
                    matches.append(full)
            except OSError:
                continue

        if not matches:
            messagebox.showinfo(
                "No match found",
                "No EDF/BDF file with identical size was found in:\n\n" + right_path
            )
            return

        # If multiple matches → user selects
        if len(matches) > 1:
            sel = self._select_from_list(
                title="Multiple matching files",
                prompt="Multiple files match the LEFT file by size.\nSelect one to load:",
                options=matches
            )
            if not sel:
                return
            path = sel
        else:
            path = matches[0]

        self._load_from_explicit_path(self.right, path)

    def _select_from_list(self, title: str, prompt: str, options: list[str]) -> str | None:
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.geometry("700x400")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text=prompt).pack(anchor="w", padx=10, pady=6)

        frame = ttk.Frame(dlg)
        frame.pack(fill="both", expand=True, padx=10)

        lb = tk.Listbox(frame)
        sb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)

        for opt in options:
            lb.insert(tk.END, opt)

        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        result = {"value": None}

        def on_ok():
            sel = lb.curselection()
            if sel:
                result["value"] = options[sel[0]]
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.pack(pady=8)

        ttk.Button(btns, text="Load", command=on_ok).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=on_cancel).pack(side="left", padx=6)

        dlg.wait_window()
        return result["value"]

    # -----------------------------
    # Load / delete
    # -----------------------------

    def _pick_file(self, pane: Pane) -> str | None:
        initial_dir = pane.last_dir if pane.last_dir and os.path.isdir(pane.last_dir) else None

        path = filedialog.askopenfilename(
            title="Select EDF/BDF file",
            initialdir=initial_dir,
            filetypes=[("EDF/BDF files", "*.edf *.bdf"), ("All files", "*.*")]
        )
        return path or None

    def _load_left(self):
        path = self._pick_file(self.left)
        if not path:
            return
        self._load_from_explicit_path(self.left, path)

    def _load_right(self):
        path = self._pick_file(self.right)
        if not path:
            return
        self._load_from_explicit_path(self.right, path)

    def _confirm_delete(self, path: str) -> bool:
        return messagebox.askyesno(
            "Confirm deletion",
            "This will permanently delete the file from disk:\n\n"
            f"{path}\n\n"
            "Are you sure?"
        )

    def _load_from_path(self, side: str):
        pane = self.left if side == "LEFT" else self.right
        path = pane.path_var.get().strip()

        if not path:
            return

        if not os.path.isfile(path):
            messagebox.showerror("Invalid path", f"File does not exist:\n{path}")
            return

        self._load_from_explicit_path(pane, path)

    def _load_from_explicit_path(self, pane: Pane, path: str):
        try:
            pane.header = parse_edf_header(path)
        except Exception as e:
            messagebox.showerror("Parse error", str(e))
            pane.header = None
            return

        pane.last_dir = os.path.dirname(path)
        pane.path_var.set(path)

        self._refresh_all()

    def _delete_left(self):
        h = self.left.header
        if not h:
            return
        if not os.path.exists(h.path):
            messagebox.showerror("Delete error", "File does not exist on disk anymore.")
            self.left.header = None
            self._refresh_all()
            return
        if self._confirm_delete(h.path):
            try:
                os.remove(h.path)
            except Exception as e:
                messagebox.showerror("Delete error (LEFT)", str(e))
                return
            self.left.header = None
            self._refresh_all()

    def _delete_right(self):
        h = self.right.header
        if not h:
            return
        if not os.path.exists(h.path):
            messagebox.showerror("Delete error", "File does not exist on disk anymore.")
            self.right.header = None
            self._refresh_all()
            return
        if self._confirm_delete(h.path):
            try:
                os.remove(h.path)
            except Exception as e:
                messagebox.showerror("Delete error (RIGHT)", str(e))
                return
            self.right.header = None
            self._refresh_all()


    # -----------------------------
    # BIDS navigation (LEFT)
    # -----------------------------

    def _natural_key(self, s: str):
        # Natural sort: "run-2" < "run-10"
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

    def _session_sort_key(self, p: Path):
        m = re.match(r"^ses-(\d+)$", p.name, flags=re.IGNORECASE)
        if m:
            return (int(m.group(1)), p.name.lower())
        return (10**9, p.name.lower())

    def _list_ieeg_files(self, ieeg_dir: Path) -> list[Path]:
        if not ieeg_dir.is_dir():
            return []
        files = [
            p for p in ieeg_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (".edf", ".bdf")
        ]
        return sorted(files, key=lambda x: self._natural_key(x.name))

    def _find_session_dir_for_file(self, file_path: Path) -> Path | None:
        # file_path is expected to be a file (or a directory). We locate the closest parent "ses-###".
        for parent in file_path.parents:
            if parent.is_dir() and parent.name.lower().startswith("ses-"):
                return parent
        return None

    def _compute_next_path_bids(self, current_path: str) -> str | None:
        p = Path(current_path)

        if not p.exists():
            return None

        # If user provides a directory, attempt to start from the first EDF/BDF in it (BIDS aware)
        if p.is_dir():
            # If this is a ses-### directory, jump into ieeg
            if p.name.lower().startswith("ses-"):
                files = self._list_ieeg_files(p / "ieeg")
                return str(files[0]) if files else None

            # If this is an ieeg directory, use it directly
            if p.name.lower() == "ieeg":
                files = self._list_ieeg_files(p)
                return str(files[0]) if files else None

            # Otherwise: find ses-### children and pick first session with EDF/BDF
            ses_dirs = [d for d in p.iterdir() if d.is_dir() and d.name.lower().startswith("ses-")]
            for ses in sorted(ses_dirs, key=self._session_sort_key):
                files = self._list_ieeg_files(ses / "ieeg")
                if files:
                    return str(files[0])
            return None

        # File: locate containing session
        session_dir = self._find_session_dir_for_file(p)
        if session_dir is None:
            return None

        subject_dir = session_dir.parent
        if not subject_dir.is_dir():
            return None

        # List sessions for this subject (ses-###)
        ses_dirs = [d for d in subject_dir.iterdir() if d.is_dir() and d.name.lower().startswith("ses-")]
        ses_dirs = sorted(ses_dirs, key=self._session_sort_key)

        # Current session EDF/BDF files
        cur_files = self._list_ieeg_files(session_dir / "ieeg")

        # Find current file index within session list
        try:
            cur_res = p.resolve()
        except Exception:
            cur_res = p

        idx_in_session = None
        for i, fp in enumerate(cur_files):
            try:
                if fp.resolve() == cur_res:
                    idx_in_session = i
                    break
            except Exception:
                if fp == p:
                    idx_in_session = i
                    break

        # 1) Next file in same session
        if idx_in_session is not None and idx_in_session + 1 < len(cur_files):
            return str(cur_files[idx_in_session + 1])

        # 2) Otherwise, move to the next session with at least one EDF/BDF
        cur_session_idx = None
        for i, sd in enumerate(ses_dirs):
            try:
                if sd.resolve() == session_dir.resolve():
                    cur_session_idx = i
                    break
            except Exception:
                if sd == session_dir:
                    cur_session_idx = i
                    break

        if cur_session_idx is None:
            for i, sd in enumerate(ses_dirs):
                if sd.name == session_dir.name:
                    cur_session_idx = i
                    break

        if cur_session_idx is None:
            return None

        for sd in ses_dirs[cur_session_idx + 1:]:
            files = self._list_ieeg_files(sd / "ieeg")
            if files:
                return str(files[0])

        return None

    def _compute_next_path_same_folder(self, current_path: str) -> str | None:
        p = Path(current_path)
        if not p.exists():
            return None

        if p.is_dir():
            files = self._list_ieeg_files(p)
            return str(files[0]) if files else None

        folder = p.parent
        files = self._list_ieeg_files(folder)
        if not files:
            return None

        try:
            cur_res = p.resolve()
        except Exception:
            cur_res = p

        for i, fp in enumerate(files):
            try:
                if fp.resolve() == cur_res:
                    return str(files[i + 1]) if i + 1 < len(files) else None
            except Exception:
                if fp == p:
                    return str(files[i + 1]) if i + 1 < len(files) else None

        # If current not found, start at the first
        return str(files[0])

    def _move_left_to_next(self):
        # Prefer the loaded file; otherwise use whatever is in the LEFT path box.
        cur = self.left.header.path if self.left.header else (self.left.path_var.get().strip() if self.left.path_var else "")
        if not cur:
            messagebox.showinfo("No LEFT file", "Load an EDF/BDF file in the LEFT pane first.")
            return

        if not os.path.exists(cur):
            messagebox.showerror("Path not found", f"Path does not exist:\n{cur}")
            return

        # Primary: BIDS-style navigation (ses-###/ieeg). Fallback: same folder.
        next_path = self._compute_next_path_bids(cur)
        if not next_path:
            next_path = self._compute_next_path_same_folder(cur)

        if not next_path:
            messagebox.showinfo("End reached", "No next EDF/BDF file found.")
            return

        self._load_from_explicit_path(self.left, next_path)

    # -----------------------------
    # Refresh UI
    # -----------------------------

    def _get_summary_value(self, h: EdfHeader | None, key: str):
        if h is None:
            return ""
        if key == "file_basename":
            return os.path.basename(h.path)
        v = getattr(h, key, "")
        # normalize common types for display
        if isinstance(v, bool):
            return "True" if v else "False"
        if v is None:
            return ""
        if isinstance(v, float):
            # keep durations readable but stable
            return f"{v:.6g}"
        return str(v)

    def _clear_tree(self, tree: ttk.Treeview):
        for iid in tree.get_children():
            tree.delete(iid)

    def _set_raw_text(self, txt: scrolledtext.ScrolledText, content: str):
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.insert("1.0", content)
        txt.configure(state="disabled")

    def _refresh_all(self):
        # ---- Update editable path boxes ----
        if self.left.header:
            self.left.path_var.set(self.left.header.path)
        #else:
            #self.left.path_var.set("")

        if self.right.header:
            self.right.path_var.set(self.right.header.path)
        #else:
            #self.right.path_var.set("")

        # ---- Enable / disable delete buttons ----
        self.left_delete_btn.configure(state=("normal" if self.left.header else "disabled"))
        self.right_delete_btn.configure(state=("normal" if self.right.header else "disabled"))

        # ---- Enable / disable navigation button ----
        if hasattr(self, "left_move_btn") and self.left_move_btn is not None:
            self.left_move_btn.configure(state=("normal" if self.left.header else "disabled"))

        # ---- Refresh tables ----
        self._refresh_summary_tables()
        self._refresh_signal_tables()
        self._refresh_raw_tabs()

    def _refresh_summary_tables(self):
        self._clear_tree(self.left_summary_tree)
        self._clear_tree(self.right_summary_tree)

        # --- Internal consistency row (LEFT / RIGHT independently) ---
        left_ok, left_msg = self._check_internal_consistency(self.left.header)
        right_ok, right_msg = self._check_internal_consistency(self.right.header)

        # LEFT
        self.left_summary_tree.insert(
            "",
            "end",
            values=(
                "⚠ Consistency check",
                "OK" if left_ok else left_msg
            ),
            tags=(() if left_ok else ("diff",))
        )

        # RIGHT
        self.right_summary_tree.insert(
            "",
            "end",
            values=(
                "⚠ Consistency check",
                "OK" if right_ok else right_msg
            ),
            tags=(() if right_ok else ("diff",))
        )

        # --- Normal summary fields ---
        for (label, key) in self.SUMMARY_FIELDS:
            lv = self._get_summary_value(self.left.header, key)
            rv = self._get_summary_value(self.right.header, key)

            diff = (
                self.left.header is not None
                and self.right.header is not None
                and lv != rv
            )

            self.left_summary_tree.insert(
                "",
                "end",
                values=(label, lv),
                tags=(("diff",) if diff else ())
            )

            self.right_summary_tree.insert(
                "",
                "end",
                values=(label, rv),
                tags=(("diff",) if diff else ())
            )

    def _signal_to_row(self, idx: int, s: EdfSignal | None):
        if s is None:
            return {
                "idx": idx,
                "label": "",
                "transducer_type": "",
                "physical_dimension": "",
                "physical_min": "",
                "physical_max": "",
                "digital_min": "",
                "digital_max": "",
                "prefiltering": "",
                "samples_per_record": "",
                "reserved": "",
            }
        return {
            "idx": idx,
            "label": s.label,
            "transducer_type": s.transducer_type,
            "physical_dimension": s.physical_dimension,
            "physical_min": s.physical_min,
            "physical_max": s.physical_max,
            "digital_min": s.digital_min,
            "digital_max": s.digital_max,
            "prefiltering": s.prefiltering,
            "samples_per_record": s.samples_per_record,
            "reserved": s.reserved,
        }

    def _refresh_signal_tables(self):
        self._clear_tree(self.left_signals_tree)
        self._clear_tree(self.right_signals_tree)

        lh = self.left.header
        rh = self.right.header

        lsignals = lh.signals if lh else []
        rsignals = rh.signals if rh else []

        max_n = max(len(lsignals), len(rsignals))

        for i in range(max_n):
            ls = lsignals[i] if i < len(lsignals) else None
            rs = rsignals[i] if i < len(rsignals) else None

            lrow = self._signal_to_row(i, ls)
            rrow = self._signal_to_row(i, rs)

            # Compare by index: if any field differs => diff
            diff = False
            if lh is not None and rh is not None:
                for _, key in self.SIGNAL_COLS:
                    if str(lrow.get(key, "")) != str(rrow.get(key, "")):
                        diff = True
                        break

            ltags = ("diff",) if diff else ()
            rtags = ("diff",) if diff else ()

            lvals = [str(lrow.get(key, "")) for _, key in self.SIGNAL_COLS]
            rvals = [str(rrow.get(key, "")) for _, key in self.SIGNAL_COLS]

            self.left_signals_tree.insert("", "end", values=lvals, tags=ltags)
            self.right_signals_tree.insert("", "end", values=rvals, tags=rtags)

    def _refresh_raw_tabs(self):
        if self.left.header:
            self._set_raw_text(self.left_raw_txt, format_header_for_display(self.left.header))
        else:
            self._set_raw_text(self.left_raw_txt, "")

        if self.right.header:
            self._set_raw_text(self.right_raw_txt, format_header_for_display(self.right.header))
        else:
            self._set_raw_text(self.right_raw_txt, "")

# -----------------------------
# Run
# -----------------------------

def main():
    root = tk.Tk()
    app = EDFComparatorApp(root)
    root.minsize(1100, 650)
    root.mainloop()

if __name__ == "__main__":
    main()
