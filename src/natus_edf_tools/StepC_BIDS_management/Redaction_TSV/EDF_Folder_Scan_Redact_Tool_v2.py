#!/usr/bin/env python3
"""
EDF/BDF Folder Scanner + Redactor (CLI + GUI)

What it does
------------
1) Scan a folder recursively for EDF/BDF files and detect whether each file contains
   any *non-blank* embedded annotations (EDF+/BDF+ annotation TAL strings).
   - "Blank" means: missing/empty/whitespace-only annotation text.
   - Special "blankish" tokens: ".", "-", "NA" (case-insensitive). These are treated as blank,
     but are reported as WARNINGS with a sample token.
   - Scan stops at the first true non-blank annotation for each file (fast path).

2) Export scan results to a JSON file including:
   - filename, folder, parent folders (1/2/3 levels up)
   - file size (bytes)
   - file duration (seconds)
   - ALL header info (main header + per-signal headers) as provided by pyedflib
     plus a raw EDF header parse (for completeness / troubleshooting)
   - a sample non-blank annotation (if present), and warnings (if any)

3) Redact files listed in a JSON scan file (or scan-and-redact directly):
   - Never overwrites sources.
   - Writes to an output folder, preserving the relative folder structure.
   - Two independent operations (selectable):
       (a) Blank embedded annotations
       (b) Header anonymization (selectable sub-fields)
   - Uses the *existing redaction backend* (aux_EDF_Cleaner_Redactor.anonymize_edf_complete)
     for writing/blanking/anonymizing.

Usage
-----
GUI mode (no args):
    python EDF_Folder_Scan_Redact_Tool.py

CLI scan:
    python EDF_Folder_Scan_Redact_Tool.py scan --input-folder /data --output-json scan.json

CLI redact using a scan JSON:
    python EDF_Folder_Scan_Redact_Tool.py redact --input-json scan.json --output-folder /out \
        --blank-annotations --anonymize-header --anon-patientname --anon-patientcode --anon-birthdate --anon-gender

CLI scan+redact in one step:
    python EDF_Folder_Scan_Redact_Tool.py scan-redact --input-folder /data --output-folder /out \
        --blank-annotations --anonymize-header

Dependencies
------------
- Python 3.8+
- tkinter (usually included with Python)
- pyedflib (for header extraction; scan detection uses a lightweight TAL parser)
- Existing backend import:
    natus_edf_tools.StepB_EDF_transformation.LabelCopy_Redaction.aux_EDF_Cleaner_Redactor

Notes
-----
- "PyPDFLib" is a PDF library; for EDF/BDF we use pyedflib. (You mentioned "PyPDFLib" but the EDF library
  that reads EDF headers/annotations is pyedflib.)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------
# Optional deps
# ---------------------------

try:
    import common_libs.edflib_fork_mld as pyedflib  # type: ignore
except Exception:  # pragma: no cover
    pyedflib = None

try:
    from tqdm import tqdm  # type: ignore
except Exception:  # pragma: no cover
    tqdm = None

# ---------------------------
# Existing backend (required for redaction)
# ---------------------------

_BACKEND_IMPORT_ERROR = None
try:
    from natus_edf_tools.StepB_EDF_transformation.LabelCopy_Redaction.aux_EDF_Cleaner_Redactor import (
        anonymize_edf_complete,
        build_default_output_path,  # may not be used, but keep import parity
        validate_anonymized_file,
        run_verification,
    )
except Exception as e:  # pragma: no cover
    anonymize_edf_complete = None  # type: ignore
    validate_anonymized_file = None  # type: ignore
    run_verification = None  # type: ignore
    build_default_output_path = None  # type: ignore
    _BACKEND_IMPORT_ERROR = e

# ---------------------------
# Constants / helpers
# ---------------------------

DEFAULT_EXTS = {".edf", ".bdf"}
DEFAULT_ANNOTATION_LABELS = {
    "edf annotations",
    "bdf annotations",
    "annotations",
    "patient event",
    "patient events",
}
BLANKISH_TOKENS = {".", "-", "NA"}  # "NA" is case-insensitive

LOG = logging.getLogger("edf_folder_tool")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _is_visible_blank(s: str) -> bool:
    # "Blank" means no visible characters after trimming whitespace and nulls.
    return s.replace("\x00", "").strip() == ""


def _is_blankish_token(s: str) -> bool:
    t = s.replace("\x00", "").strip()
    if t == "":
        return False
    if t in {".", "-"}:
        return True
    if t.upper() == "NA":
        return True
    return False


def _safe_json(obj: Any) -> Any:
    """Convert to JSON-serializable where possible."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe_json(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    # pyedflib can return numpy types; stringify fallback
    try:
        import numpy as np  # type: ignore
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    return str(obj)


def _rel_parents(path: Path, root: Path) -> Tuple[str, str, str, str]:
    """
    Return (folder, parent1, parent2, parent3) relative names (not full paths)
    based on a file path and root.
    """
    rel = path.relative_to(root)
    parent = rel.parent
    folder = str(parent) if str(parent) not in ("", ".") else "."
    parts = parent.parts
    p1 = parts[-1] if len(parts) >= 1 else ""
    p2 = parts[-2] if len(parts) >= 2 else ""
    p3 = parts[-3] if len(parts) >= 3 else ""
    return folder, p1, p2, p3


# ---------------------------
# EDF header parsing (raw)
# ---------------------------

def _read_ascii(fh, n: int) -> str:
    b = fh.read(n)
    try:
        return b.decode("ascii", errors="replace")
    except Exception:
        return b.decode(errors="replace")


def parse_edf_header_raw(file_path: Path) -> Dict[str, Any]:
    """
    Minimal EDF/BDF header parser that returns the core header fields + per-signal arrays.
    Used primarily for completeness and for TAL scan offsets.
    """
    with file_path.open("rb") as fh:
        version = _read_ascii(fh, 8)
        patient_id = _read_ascii(fh, 80)
        recording_id = _read_ascii(fh, 80)
        startdate = _read_ascii(fh, 8)
        starttime = _read_ascii(fh, 8)
        header_bytes = _read_ascii(fh, 8)
        reserved = _read_ascii(fh, 44)
        num_records = _read_ascii(fh, 8)
        record_duration = _read_ascii(fh, 8)
        num_signals = _read_ascii(fh, 4)

        def _to_int(x: str, default: int = 0) -> int:
            try:
                return int(x.strip() or default)
            except Exception:
                return default

        def _to_float(x: str, default: float = 0.0) -> float:
            try:
                return float(x.strip() or default)
            except Exception:
                return default

        hb = _to_int(header_bytes, 0)
        nrec = _to_int(num_records, -1)
        dur = _to_float(record_duration, 0.0)
        ns = _to_int(num_signals, 0)

        # Per-signal arrays
        def _read_arr(width: int) -> List[str]:
            return [_read_ascii(fh, width) for _ in range(ns)]

        labels = _read_arr(16)
        transducers = _read_arr(80)
        phys_dims = _read_arr(8)
        phys_mins = _read_arr(8)
        phys_maxs = _read_arr(8)
        dig_mins = _read_arr(8)
        dig_maxs = _read_arr(8)
        prefilters = _read_arr(80)
        samples_per_record = _read_arr(8)
        sig_reserved = _read_arr(32)

        def _strip_list(lst: List[str]) -> List[str]:
            return [s.rstrip(" \x00") for s in lst]

        def _int_list(lst: List[str]) -> List[int]:
            out: List[int] = []
            for s in lst:
                try:
                    out.append(int(s.strip()))
                except Exception:
                    out.append(0)
            return out

        header = {
            "version": version.rstrip(" \x00"),
            "patient_id": patient_id.rstrip(" \x00"),
            "recording_id": recording_id.rstrip(" \x00"),
            "startdate": startdate.rstrip(" \x00"),
            "starttime": starttime.rstrip(" \x00"),
            "header_bytes": hb,
            "reserved": reserved.rstrip(" \x00"),
            "num_data_records": nrec,
            "data_record_duration_sec": dur,
            "num_signals": ns,
            "signals": {
                "label": _strip_list(labels),
                "transducer": _strip_list(transducers),
                "physical_dimension": _strip_list(phys_dims),
                "physical_min": _strip_list(phys_mins),
                "physical_max": _strip_list(phys_maxs),
                "digital_min": _strip_list(dig_mins),
                "digital_max": _strip_list(dig_maxs),
                "prefiltering": _strip_list(prefilters),
                "samples_per_record": _int_list(samples_per_record),
                "reserved": _strip_list(sig_reserved),
            },
        }
        return header


# ---------------------------
# TAL scanning (fast stop)
# ---------------------------

def _bytes_per_sample(file_path: Path, raw_header: Dict[str, Any]) -> int:
    # EDF is 2 bytes. BDF is 3 bytes. We use extension as the most reliable quick heuristic here.
    ext = file_path.suffix.lower()
    if ext == ".bdf":
        return 3
    # Some BDF files may be named .edf; if reserved has "24BIT" or "bdf", treat as 3 bytes.
    res = str(raw_header.get("reserved", "")).lower()
    if "24bit" in res or "bdf" in res or "biosemi" in res:
        return 3
    return 2


def _extract_ascii_from_samples(raw: bytes, bps: int) -> bytes:
    if bps <= 1:
        return raw
    # Take the least-significant byte from each sample
    return raw[0::bps]


def _find_annotation_channel_indices(raw_header: Dict[str, Any],
                                    extra_labels: Optional[List[str]] = None) -> List[int]:
    labels = raw_header.get("signals", {}).get("label", []) or []
    labels_norm = [str(x).strip().lower() for x in labels]
    targets = set(DEFAULT_ANNOTATION_LABELS)
    if extra_labels:
        targets |= {s.strip().lower() for s in extra_labels if s.strip()}

    idxs = [i for i, lab in enumerate(labels_norm) if lab in targets or "annotations" in lab]
    # Some systems use "Patient Event" exactly; included in targets.
    return idxs


def _scan_file_for_nonblank_annotation(file_path: Path,
                                       raw_header: Dict[str, Any],
                                       annotation_labels: Optional[List[str]] = None,
                                       max_records: Optional[int] = None) -> Tuple[bool, Optional[Dict[str, Any]], List[str]]:
    """
    Returns:
      has_nonblank, sample_annotation_dict, warnings
    """
    warnings: List[str] = []
    ann_sample: Optional[Dict[str, Any]] = None

    ns = int(raw_header.get("num_signals", 0) or 0)
    if ns <= 0:
        return False, None, warnings

    ann_idxs = _find_annotation_channel_indices(raw_header, annotation_labels)
    if not ann_idxs:
        return False, None, warnings

    samples_per_record = raw_header.get("signals", {}).get("samples_per_record", [])
    if not samples_per_record or len(samples_per_record) != ns:
        return False, None, warnings

    hb = int(raw_header.get("header_bytes", 0) or 0)
    nrec = int(raw_header.get("num_data_records", -1))
    if nrec < 0:
        # unknown; scan until EOF
        nrec = 10**9

    if max_records is not None:
        nrec = min(nrec, max_records)

    dur = float(raw_header.get("data_record_duration_sec", 0.0) or 0.0)
    bps = _bytes_per_sample(file_path, raw_header)

    # Compute per-channel byte spans inside each data record
    ch_bytes = [int(spr) * bps for spr in samples_per_record]
    record_bytes = sum(ch_bytes)
    if record_bytes <= 0:
        return False, None, warnings

    # Precompute offsets for each channel inside a record
    offsets = [0] * ns
    cur = 0
    for i in range(ns):
        offsets[i] = cur
        cur += ch_bytes[i]

    def parse_tal(text: str) -> Tuple[Optional[Dict[str, Any]], List[str], bool]:
        """
        Parse TAL-ish string and find first nonblank annotation text.
        Returns (sample, warnings, found_nonblank)
        """
        local_warnings: List[str] = []
        # Split records by field separator 0x14
        for field in text.split("\x14"):
            if not field:
                continue
            # 0x15 separates onset/duration from annotation texts
            if "\x15" not in field:
                continue
            parts = field.split("\x15")
            onset_dur = parts[0].replace("\x00", "").strip()
            for ann_text in parts[1:]:
                cleaned = ann_text.replace("\x00", "").strip()
                if cleaned == "":
                    continue
                if _is_blankish_token(cleaned):
                    local_warnings.append(f'Blankish annotation token found: "{cleaned}" (treated as blank).')
                    # continue searching for real text
                    continue
                # Real nonblank annotation found
                return {
                    "text": cleaned,
                    "onset_duration_raw": onset_dur,
                }, local_warnings, True
        return None, local_warnings, False

    # Read record-by-record and stop early
    with file_path.open("rb") as fh:
        fh.seek(hb, os.SEEK_SET)
        for rec_i in range(nrec):
            buf = fh.read(record_bytes)
            if not buf or len(buf) < record_bytes:
                break

            for ch in ann_idxs:
                start = offsets[ch]
                end = start + ch_bytes[ch]
                raw = buf[start:end]
                ascii_bytes = _extract_ascii_from_samples(raw, bps)
                # Decode as latin-1 to preserve byte values
                tal = ascii_bytes.decode("latin-1", errors="ignore")
                # Quick skip if no separator present
                if "\x15" not in tal:
                    continue

                sample, local_warnings, found = parse_tal(tal)
                warnings.extend(local_warnings)
                if found and sample is not None:
                    ann_sample = sample
                    return True, ann_sample, warnings

    return False, ann_sample, warnings


# ---------------------------
# Scan dataclasses
# ---------------------------

@dataclass
class ScanFileEntry:
    abs_path: str
    rel_path: str
    file_name: str
    folder_rel: str
    folder_name: str
    parent1: str
    parent2: str
    parent3: str
    size_bytes: int
    duration_sec: Optional[float]
    has_nonblank_annotation: bool
    sample_annotation: Optional[Dict[str, Any]]
    warnings: List[str]
    pyedflib_header: Optional[Dict[str, Any]]
    pyedflib_signal_headers: Optional[List[Dict[str, Any]]]
    raw_header: Optional[Dict[str, Any]]
    selected: bool = False


@dataclass
class ScanResult:
    tool: str
    created_at: str
    source_root: str
    file_count: int
    entries: List[ScanFileEntry]


# ---------------------------
# pyedflib header extraction
# ---------------------------

def _pyedflib_headers(file_path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]], Optional[float]]:
    """
    Returns (main_header_dict, signal_headers_list, duration_sec)
    """
    if pyedflib is None:
        raise RuntimeError("pyedflib is not installed. Install with: pip install pyedflib")

    reader = pyedflib.EdfReader(str(file_path))
    try:
        header = reader.getHeader()  # dict
        sig_headers = reader.getSignalHeaders()  # list[dict]
        # pyedflib exposes file_duration for EDF/BDF
        duration = None
        try:
            duration = float(getattr(reader, "file_duration"))
        except Exception:
            # fallback: compute from records * record_duration
            try:
                duration = float(reader.datarecords_in_file) * float(reader.datarecord_duration)
            except Exception:
                duration = None
        return _safe_json(header), _safe_json(sig_headers), duration
    finally:
        try:
            reader.close()
        except Exception:
            pass


# ---------------------------
# Folder scanning
# ---------------------------

def iter_edf_files(root: Path, exts: Optional[set] = None) -> List[Path]:
    exts = exts or DEFAULT_EXTS
    files: List[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            files.append(p)
    return sorted(files)


def scan_folder(
    input_folder: Path,
    annotation_labels: Optional[List[str]] = None,
    include_all_files: bool = True,
    max_records_per_file: Optional[int] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> ScanResult:
    if not input_folder.exists() or not input_folder.is_dir():
        raise ValueError(f"Input folder does not exist or is not a folder: {input_folder}")

    def _emit(ev: Dict[str, Any]) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(ev)
        except Exception:
            # Never let UI callback break scanning
            return

    _emit({"phase": "scan", "stage": "enumerating", "root": str(input_folder)})

    edf_files = iter_edf_files(input_folder)
    total = len(edf_files)

    _emit({"phase": "scan", "stage": "start", "root": str(input_folder), "total": total})

    entries: List[ScanFileEntry] = []

    use_tqdm = (tqdm is not None) and (progress_cb is None)
    iterator = edf_files
    pbar = None
    if use_tqdm:
        pbar = tqdm(edf_files, desc="Scanning EDF/BDF", unit="file")  # type: ignore
        iterator = pbar  # type: ignore

    for i, fpath in enumerate(iterator):
        # per-file info that can be computed cheaply for progress display
        try:
            rel_path = str(fpath.relative_to(input_folder))
        except Exception:
            rel_path = str(fpath)

        _emit({
            "phase": "scan",
            "stage": "file_start",
            "index": i + 1,
            "done": i,
            "total": total,
            "path": str(fpath),
            "rel_path": rel_path,
        })

        if pbar is not None:
            # show a hint of current file in CLI mode
            try:
                pbar.set_postfix_str(rel_path[-60:])
            except Exception:
                pass

        try:
            try:
                size_bytes = fpath.stat().st_size
            except Exception:
                size_bytes = -1

            folder_rel, p1, p2, p3 = _rel_parents(fpath, input_folder)
            folder_name = Path(folder_rel).name if folder_rel not in ("", ".") else "."
            file_name = fpath.name

            # Raw header (also needed for TAL scan)
            raw_header = None
            try:
                raw_header = parse_edf_header_raw(fpath)
            except Exception as e:
                LOG.warning("Failed raw header parse for %s: %s", fpath, e)
                raw_header = None

            has_nonblank = False
            sample_ann = None
            warnings: List[str] = []

            if raw_header is not None:
                try:
                    has_nonblank, sample_ann, warnings = _scan_file_for_nonblank_annotation(
                        fpath,
                        raw_header,
                        annotation_labels=annotation_labels,
                        max_records=max_records_per_file,
                    )
                except Exception as e:
                    warnings.append(f"Annotation scan failed: {e}")

            # pyedflib headers
            py_hdr = None
            py_sig_hdrs = None
            duration_sec = None
            try:
                py_hdr, py_sig_hdrs, duration_sec = _pyedflib_headers(fpath)
            except Exception as e:
                warnings.append(f"pyedflib header read failed: {e}")

            # If user wants include_all_files=False, keep only those with nonblank
            if (not include_all_files) and (not has_nonblank):
                continue

            entry = ScanFileEntry(
                abs_path=str(fpath.resolve()),
                rel_path=rel_path,
                file_name=file_name,
                folder_rel=folder_rel,
                folder_name=folder_name,
                parent1=p1,
                parent2=p2,
                parent3=p3,
                size_bytes=int(size_bytes),
                duration_sec=duration_sec,
                has_nonblank_annotation=bool(has_nonblank),
                sample_annotation=sample_ann,
                warnings=warnings,
                pyedflib_header=py_hdr,
                pyedflib_signal_headers=py_sig_hdrs,
                raw_header=_safe_json(raw_header),
                selected=bool(has_nonblank),  # default selection: redact those with real nonblank annotations
            )
            entries.append(entry)
        finally:
            _emit({
                "phase": "scan",
                "stage": "file_done",
                "index": i + 1,
                "done": i + 1,
                "total": total,
                "path": str(fpath),
                "rel_path": rel_path,
            })

    result = ScanResult(
        tool="EDF_Folder_Scan_Redact_Tool",
        created_at=_now_iso(),
        source_root=str(input_folder.resolve()),
        file_count=len(entries),
        entries=entries,
    )

    _emit({"phase": "scan", "stage": "done", "total": total, "kept": len(entries)})

    return result
def save_scan_json(scan: ScanResult, out_json: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tool": scan.tool,
        "created_at": scan.created_at,
        "source_root": scan.source_root,
        "file_count": scan.file_count,
        "entries": [asdict(e) for e in scan.entries],
    }
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_scan_json(in_json: Path) -> ScanResult:
    data = json.loads(in_json.read_text(encoding="utf-8"))
    entries = []
    for e in data.get("entries", []):
        entries.append(ScanFileEntry(**e))
    return ScanResult(
        tool=data.get("tool", ""),
        created_at=data.get("created_at", ""),
        source_root=data.get("source_root", ""),
        file_count=int(data.get("file_count", len(entries))),
        entries=entries,
    )


# ---------------------------
# Redaction
# ---------------------------

def _require_backend() -> None:
    if anonymize_edf_complete is None:
        raise RuntimeError(
            "Could not import redaction backend (aux_EDF_Cleaner_Redactor). "
            f"Import error: {_BACKEND_IMPORT_ERROR}"
        )


def build_anonymize_options(
    anonymize_header: bool,
    anon_patientname: bool,
    anon_patientcode: bool,
    anon_birthdate: bool,
    anon_gender: bool,
    anon_recording_additional: bool,
    anon_admincode: bool,
    anon_technician: bool,
    anon_equipment: bool,
) -> Dict[str, bool]:
    if not anonymize_header:
        return {
            "patientname": False,
            "patientcode": False,
            "birthdate": False,
            "gender": False,
            "recording_additional": False,
            "admincode": False,
            "technician": False,
            "equipment": False,
        }
    return {
        "patientname": bool(anon_patientname),
        "patientcode": bool(anon_patientcode),
        "birthdate": bool(anon_birthdate),
        "gender": bool(anon_gender),
        "recording_additional": bool(anon_recording_additional),
        "admincode": bool(anon_admincode),
        "technician": bool(anon_technician),
        "equipment": bool(anon_equipment),
    }


def _resolve_input_path(entry: ScanFileEntry, source_root: Path) -> Path:
    p = Path(entry.abs_path)
    if p.exists():
        return p
    # fallback: relative to source root (in case moved machines)
    rel = Path(entry.rel_path)
    candidate = source_root / rel
    return candidate


def redact_from_scan(
    scan: ScanResult,
    output_folder: Path,
    blank_annotations: bool,
    anonymize_header: bool,
    anonymize_options: Dict[str, bool],
    buffer_size_mb: int = 64,
    log_dir: Optional[Path] = None,
    verify: bool = False,
    verify_level: str = "thorough",
    only_selected: bool = True,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """
    Redact based on scan result. Returns summary dict.
    """
    _require_backend()

    def _emit(ev: Dict[str, Any]) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(ev)
        except Exception:
            return

    output_folder.mkdir(parents=True, exist_ok=True)

    source_root = Path(scan.source_root)
    if not source_root.exists():
        # still allow processing if abs paths are valid; but warn
        LOG.warning("Source root from JSON does not exist: %s", source_root)

    if not blank_annotations and not anonymize_header:
        raise ValueError("Nothing to do: both 'blank_annotations' and 'anonymize_header' are False.")

    if log_dir is None:
        log_dir = output_folder / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    skipped = 0
    failed: List[Dict[str, Any]] = []

    entries_all = scan.entries
    if only_selected:
        skipped = sum(1 for e in entries_all if not e.selected)
        entries = [e for e in entries_all if e.selected]
    else:
        entries = list(entries_all)

    total = len(entries)
    _emit({"phase": "redact", "stage": "start", "total": total, "output_folder": str(output_folder)})

    use_tqdm = (tqdm is not None) and (progress_cb is None)
    iterator = entries
    pbar = None
    if use_tqdm:
        pbar = tqdm(entries, desc="Redacting", unit="file")  # type: ignore
        iterator = pbar  # type: ignore

    for i, entry in enumerate(iterator):
        rel_path = entry.rel_path
        _emit({
            "phase": "redact",
            "stage": "file_start",
            "index": i + 1,
            "done": i,
            "total": total,
            "rel_path": rel_path,
            "path": entry.abs_path,
        })

        if pbar is not None:
            try:
                pbar.set_postfix_str(rel_path[-60:])
            except Exception:
                pass

        try:
            in_path = _resolve_input_path(entry, source_root)
            if not in_path.exists():
                failed.append({"path": entry.abs_path, "reason": "Input file missing"})
                continue

            out_path = output_folder / Path(entry.rel_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)

            ok = anonymize_edf_complete(
                str(in_path),
                str(out_path),
                buffer_size_mb=int(buffer_size_mb),
                log_dir=str(log_dir),
                blank_annotations=bool(blank_annotations),
                anonymize_options=dict(anonymize_options),
                ref_edf_path=None,
                copy_signal_labels=False,
                require_strict_structure_match=False,
            )
            if not ok:
                failed.append({"path": str(in_path), "reason": "Backend returned ok=False"})
                continue

            if verify and (validate_anonymized_file is not None or run_verification is not None):
                try:
                    if verify_level.lower() == "basic" and validate_anonymized_file is not None:
                        v_ok = validate_anonymized_file(str(in_path), str(out_path))
                    elif run_verification is not None:
                        v_ok = run_verification(str(in_path), str(out_path))
                    else:
                        v_ok = True
                    if not v_ok:
                        failed.append({"path": str(in_path), "reason": "Verification failed"})
                        continue
                except Exception as e:
                    failed.append({"path": str(in_path), "reason": f"Verification exception: {e}"})
                    continue

            processed += 1

        except Exception as e:
            failed.append({"path": str(entry.abs_path), "reason": str(e)})

        finally:
            _emit({
                "phase": "redact",
                "stage": "file_done",
                "index": i + 1,
                "done": i + 1,
                "total": total,
                "rel_path": rel_path,
                "path": entry.abs_path,
            })

    _emit({"phase": "redact", "stage": "done", "total": total})

    return {
        "processed": processed,
        "skipped": skipped,
        "failed_count": len(failed),
        "failed": failed,
        "output_folder": str(output_folder.resolve()),
        "log_dir": str(log_dir.resolve()),
    }
def run_gui() -> None:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from tkinter import scrolledtext

    class TextHandler(logging.Handler):
        def __init__(self, widget: tk.Text):
            super().__init__()
            self.widget = widget
            self.q = queue.Queue()

        def emit(self, record):
            self.q.put(self.format(record))

        def poll(self):
            try:
                while True:
                    msg = self.q.get_nowait()
                    self.widget.configure(state="normal")
                    self.widget.insert(tk.END, msg + "\n")
                    self.widget.see(tk.END)
                    self.widget.configure(state="disabled")
            except queue.Empty:
                pass

    root = tk.Tk()
    root.title("EDF/BDF Folder Scanner + Redactor")
    root.geometry("1200x860")
    root.minsize(950, 650)

    # State vars
    src_folder = tk.StringVar()
    out_folder = tk.StringVar()

    json_path_var = tk.StringVar()

    include_all = tk.BooleanVar(value=True)

    blank_annotations_var = tk.BooleanVar(value=True)
    anonymize_header_var = tk.BooleanVar(value=True)

    anon_patientname = tk.BooleanVar(value=True)
    anon_patientcode = tk.BooleanVar(value=True)
    anon_birthdate = tk.BooleanVar(value=True)
    anon_gender = tk.BooleanVar(value=True)
    anon_recording_additional = tk.BooleanVar(value=False)
    anon_admincode = tk.BooleanVar(value=False)
    anon_technician = tk.BooleanVar(value=False)
    anon_equipment = tk.BooleanVar(value=False)

    buffer_mb_var = tk.IntVar(value=64)

    verify_var = tk.BooleanVar(value=False)
    verify_level_var = tk.StringVar(value="thorough")

    # scan data
    current_scan: Optional[ScanResult] = None

    # Layout
    root.columnconfigure(0, weight=1)
    root.rowconfigure(3, weight=1)

    main = ttk.Frame(root, padding=10)
    main.grid(row=0, column=0, sticky="nsew")
    main.columnconfigure(0, weight=1)
    main.rowconfigure(3, weight=1)

    # Top: folders
    folders = ttk.LabelFrame(main, text="Folders / JSON", padding=8)
    folders.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    folders.columnconfigure(1, weight=1)

    def browse_src():
        d = filedialog.askdirectory(title="Select source folder to scan")
        if d:
            src_folder.set(d)

    def browse_out():
        d = filedialog.askdirectory(title="Select output folder for redacted EDFs")
        if d:
            out_folder.set(d)

    def browse_json_save():
        p = filedialog.asksaveasfilename(
            title="Save scan JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if p:
            json_path_var.set(p)

    def browse_json_open():
        p = filedialog.askopenfilename(
            title="Open scan JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if p:
            json_path_var.set(p)

    ttk.Label(folders, text="Source folder").grid(row=0, column=0, sticky="w", padx=4, pady=2)
    ttk.Entry(folders, textvariable=src_folder).grid(row=0, column=1, sticky="ew", padx=4, pady=2)
    ttk.Button(folders, text="Browse", command=browse_src).grid(row=0, column=2, padx=4, pady=2)

    ttk.Label(folders, text="Output folder").grid(row=1, column=0, sticky="w", padx=4, pady=2)
    ttk.Entry(folders, textvariable=out_folder).grid(row=1, column=1, sticky="ew", padx=4, pady=2)
    ttk.Button(folders, text="Browse", command=browse_out).grid(row=1, column=2, padx=4, pady=2)

    ttk.Label(folders, text="Scan JSON").grid(row=2, column=0, sticky="w", padx=4, pady=2)
    ttk.Entry(folders, textvariable=json_path_var).grid(row=2, column=1, sticky="ew", padx=4, pady=2)
    btns = ttk.Frame(folders)
    btns.grid(row=2, column=2, sticky="e", padx=4, pady=2)
    ttk.Button(btns, text="Open", command=browse_json_open).grid(row=0, column=0, padx=2)
    ttk.Button(btns, text="Save As", command=browse_json_save).grid(row=0, column=1, padx=2)

    ttk.Checkbutton(
        folders,
        text="Include all files in scan JSON (otherwise only non-blank annotations)",
        variable=include_all
    ).grid(row=3, column=0, columnspan=3, sticky="w", padx=4, pady=(6, 2))

    # Options
    opts = ttk.LabelFrame(main, text="Redaction Options", padding=8)
    opts.grid(row=1, column=0, sticky="ew", pady=(0, 8))
    opts.columnconfigure(10, weight=1)

    ttk.Checkbutton(opts, text="Blank embedded annotations", variable=blank_annotations_var)\
        .grid(row=0, column=0, sticky="w", padx=4, pady=2)
    ttk.Checkbutton(opts, text="Anonymize header", variable=anonymize_header_var)\
        .grid(row=0, column=1, sticky="w", padx=12, pady=2)

    ttk.Label(opts, text="Buffer (MB)").grid(row=0, column=2, sticky="w", padx=(12, 2))
    ttk.Spinbox(opts, from_=16, to=512, width=6, textvariable=buffer_mb_var)\
        .grid(row=0, column=3, sticky="w", padx=(0, 12))

    ttk.Checkbutton(opts, text="Verify outputs", variable=verify_var)\
        .grid(row=0, column=4, sticky="w", padx=4)
    ttk.Label(opts, text="Verify level").grid(row=0, column=5, sticky="w", padx=(12, 2))
    ttk.Combobox(opts, textvariable=verify_level_var, values=["basic", "thorough"], width=10, state="readonly")\
        .grid(row=0, column=6, sticky="w", padx=(0, 12))

    # Anon sub-fields
    anon = ttk.LabelFrame(main, text="Header anonymization fields", padding=8)
    anon.grid(row=2, column=0, sticky="ew", pady=(0, 8))
    anon.columnconfigure((0, 1, 2, 3), weight=1)

    checks = [
        ("patientname", anon_patientname),
        ("patientcode", anon_patientcode),
        ("birthdate", anon_birthdate),
        ("gender", anon_gender),
        ("recording_additional", anon_recording_additional),
        ("admincode", anon_admincode),
        ("technician", anon_technician),
        ("equipment", anon_equipment),
    ]
    for i, (label, var) in enumerate(checks):
        ttk.Checkbutton(anon, text=label, variable=var)\
            .grid(row=i // 4, column=i % 4, sticky="w", padx=6, pady=2)

    # Middle: file table + details
    mid = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
    mid.grid(row=3, column=0, sticky="nsew")
    main.rowconfigure(3, weight=1)

    left = ttk.Frame(mid, padding=6)
    right = ttk.Frame(mid, padding=6)
    mid.add(left, weight=3)
    mid.add(right, weight=2)

    # Treeview
    columns = ("selected", "rel_path", "nonblank", "size", "duration", "sample", "warnings")
    tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="extended")
    tree.heading("selected", text="Redact?")
    tree.heading("rel_path", text="Relative Path")
    tree.heading("nonblank", text="Non-blank ann?")
    tree.heading("size", text="Bytes")
    tree.heading("duration", text="Duration (s)")
    tree.heading("sample", text="Sample annotation")
    tree.heading("warnings", text="Warnings")

    tree.column("selected", width=70, anchor="center")
    tree.column("rel_path", width=420, anchor="w")
    tree.column("nonblank", width=100, anchor="center")
    tree.column("size", width=90, anchor="e")
    tree.column("duration", width=100, anchor="e")
    tree.column("sample", width=240, anchor="w")
    tree.column("warnings", width=260, anchor="w")

    vsb = ttk.Scrollbar(left, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(left, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    left.rowconfigure(0, weight=1)
    left.columnconfigure(0, weight=1)

    # Right: details box
    right.rowconfigure(1, weight=1)
    ttk.Label(right, text="Selected file details").grid(row=0, column=0, sticky="w")
    details = scrolledtext.ScrolledText(right, wrap=tk.WORD)
    details.grid(row=1, column=0, sticky="nsew")
    details.configure(state="disabled")

    # Bottom: actions + log
    bottom = ttk.Frame(main)
    bottom.grid(row=4, column=0, sticky="ew")
    bottom.columnconfigure(0, weight=1)

    actions = ttk.Frame(bottom)
    actions.grid(row=0, column=0, sticky="w")

    # Progress + status (shows current file, counts, elapsed, ETA)
    progress = ttk.Progressbar(bottom, mode="indeterminate", length=260)
    progress.grid(row=0, column=1, sticky="e", padx=(10, 0))

    status_var = tk.StringVar(value="")
    file_var = tk.StringVar(value="")
    eta_var = tk.StringVar(value="")

    status_frame = ttk.Frame(bottom)
    status_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    status_frame.columnconfigure(0, weight=1)

    ttk.Label(status_frame, textvariable=status_var).grid(row=0, column=0, sticky="w")
    ttk.Label(status_frame, textvariable=file_var).grid(row=1, column=0, sticky="w")
    ttk.Label(status_frame, textvariable=eta_var).grid(row=2, column=0, sticky="w")
    log_frame = ttk.LabelFrame(main, text="Log", padding=8)
    log_frame.grid(row=5, column=0, sticky="nsew", pady=(8, 0))
    main.rowconfigure(5, weight=0)

    log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap=tk.WORD)
    log_text.pack(fill=tk.BOTH, expand=True)
    log_text.configure(state="disabled")

    # Logging setup
    handler = TextHandler(log_text)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logging.getLogger().handlers[:] = []
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    def log(msg: str, level: int = logging.INFO):
        logging.getLogger().log(level, msg)

    # Helpers to update table
    def clear_tree():
        for iid in tree.get_children():
            tree.delete(iid)

    def populate_tree(scan: ScanResult):
        clear_tree()
        for idx, e in enumerate(scan.entries):
            sel = "YES" if e.selected else "NO"
            nb = "YES" if e.has_nonblank_annotation else "NO"
            samp = ""
            if e.sample_annotation and isinstance(e.sample_annotation, dict):
                samp = str(e.sample_annotation.get("text", ""))[:180]
            warn = "; ".join(e.warnings)[:250] if e.warnings else ""
            dur = "" if e.duration_sec is None else f"{e.duration_sec:.3f}"
            tree.insert("", "end", iid=str(idx), values=(
                sel,
                e.rel_path,
                nb,
                e.size_bytes,
                dur,
                samp,
                warn
            ))

    def show_details_for_index(idx: int):
        nonlocal current_scan
        if current_scan is None:
            return
        if idx < 0 or idx >= len(current_scan.entries):
            return
        e = current_scan.entries[idx]
        payload = asdict(e)
        details.configure(state="normal")
        details.delete("1.0", tk.END)
        details.insert(tk.END, json.dumps(payload, indent=2, ensure_ascii=False))
        details.configure(state="disabled")

    def on_tree_select(event=None):
        sel = tree.selection()
        if not sel:
            return
        # show first selected
        try:
            idx = int(sel[0])
            show_details_for_index(idx)
        except Exception:
            pass

    tree.bind("<<TreeviewSelect>>", on_tree_select)

    def toggle_selected_for_iids(iids: List[str], value: Optional[bool] = None):
        nonlocal current_scan
        if current_scan is None:
            return
        for iid in iids:
            try:
                idx = int(iid)
                e = current_scan.entries[idx]
                if value is None:
                    e.selected = not e.selected
                else:
                    e.selected = bool(value)
            except Exception:
                continue
        populate_tree(current_scan)

    def on_double_click(event):
        iid = tree.identify_row(event.y)
        if iid:
            toggle_selected_for_iids([iid], value=None)

    tree.bind("<Double-1>", on_double_click)

    def select_nonblank():
        nonlocal current_scan
        if current_scan is None:
            return
        for e in current_scan.entries:
            e.selected = bool(e.has_nonblank_annotation)
        populate_tree(current_scan)

    def select_all():
        nonlocal current_scan
        if current_scan is None:
            return
        for e in current_scan.entries:
            e.selected = True
        populate_tree(current_scan)

    def clear_all():
        nonlocal current_scan
        if current_scan is None:
            return
        for e in current_scan.entries:
            e.selected = False
        populate_tree(current_scan)

    def export_json():
        nonlocal current_scan
        if current_scan is None:
            messagebox.showwarning("No scan data", "Scan or import a JSON first.")
            return
        p = json_path_var.get().strip()
        if not p:
            messagebox.showwarning("Missing path", "Choose a JSON path (Save As) first.")
            return
        try:
            save_scan_json(current_scan, Path(p))
            log(f"Saved scan JSON: {p}")
            messagebox.showinfo("Saved", f"Saved scan JSON:\n{p}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def import_json():
        nonlocal current_scan
        p = json_path_var.get().strip()
        if not p:
            messagebox.showwarning("Missing path", "Choose a JSON path (Open) first.")
            return
        try:
            current_scan = load_scan_json(Path(p))
            src_folder.set(current_scan.source_root)
            populate_tree(current_scan)
            log(f"Loaded scan JSON: {p}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # Background worker
    worker_thread = None
    stop_flag = False
    # Progress event queue (worker thread -> UI thread)
    progress_q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
    task_state = {
        "phase": "",
        "start_ts": 0.0,
        "total": 0,
        "done": 0,
        "current_file": "",
    }

    def _shorten_middle(s: str, max_len: int = 160) -> str:
        s = str(s)
        if len(s) <= max_len:
            return s
        keep_front = max_len // 2 - 10
        keep_back = max_len - keep_front - 3
        return s[:keep_front] + "..." + s[-keep_back:]

    def _fmt_hms(seconds: Optional[float]) -> str:
        if seconds is None or seconds != seconds or seconds < 0:
            return "?"
        seconds_i = int(round(seconds))
        h = seconds_i // 3600
        m = (seconds_i % 3600) // 60
        s = seconds_i % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _set_status(phase: str, done: int, total: int, current_file: str = "") -> None:
        phase_disp = phase.capitalize() if phase else "Working"
        total = int(total) if total is not None else 0
        done = int(done) if done is not None else 0
        done = max(0, min(done, total if total > 0 else done))

        task_state["phase"] = phase
        task_state["total"] = total
        task_state["done"] = done
        if current_file:
            task_state["current_file"] = current_file

        elapsed = max(0.0, time.time() - float(task_state.get("start_ts", 0.0) or 0.0))
        rate = (done / elapsed) if (elapsed > 0 and done > 0) else 0.0
        left = (total - done) if total >= done else 0
        eta = (left / rate) if rate > 0 else None
        pct = (100.0 * done / total) if total > 0 else 0.0

        status_var.set(
            f"{phase_disp}: {done}/{total} ({pct:.1f}%) • left {left} • {rate:.2f} files/s"
            if total > 0 else f"{phase_disp}: {done} files"
        )
        file_var.set(f"Current: {_shorten_middle(task_state.get('current_file',''), 180)}" if task_state.get("current_file") else "")
        eta_var.set(f"Elapsed {_fmt_hms(elapsed)} • ETA {_fmt_hms(eta)}" if eta is not None else f"Elapsed {_fmt_hms(elapsed)}")

        # Update progress bar
        if total > 0:
            # switch to determinate
            try:
                progress.stop()
            except Exception:
                pass
            try:
                progress.configure(mode="determinate", maximum=max(1, total))
            except Exception:
                pass
            try:
                progress["value"] = done
            except Exception:
                pass

    def _reset_progress_ui(phase: str) -> None:
        task_state["phase"] = phase
        task_state["start_ts"] = time.time()
        task_state["total"] = 0
        task_state["done"] = 0
        task_state["current_file"] = ""
        status_var.set(f"{phase.capitalize() if phase else 'Working'}: preparing...")
        file_var.set("")
        eta_var.set("")
        try:
            progress.configure(mode="indeterminate", maximum=100)
            progress["value"] = 0
            progress.start(10)
        except Exception:
            pass

    def _handle_progress_event(ev: Dict[str, Any]) -> None:
        phase = str(ev.get("phase", "") or "")
        stage = str(ev.get("stage", "") or "")

        if stage == "enumerating":
            _reset_progress_ui(phase or "scan")
            status_var.set("Scanning: enumerating files...")
            return

        if stage == "start":
            # total is now known
            total = int(ev.get("total", 0) or 0)
            if not task_state.get("start_ts"):
                task_state["start_ts"] = time.time()
            task_state["phase"] = phase
            task_state["total"] = total
            task_state["done"] = 0
            task_state["current_file"] = ""
            _set_status(phase or "working", 0, total, "")
            return

        if stage == "file_start":
            total = int(ev.get("total", task_state.get("total", 0)) or 0)
            done = int(ev.get("done", task_state.get("done", 0)) or 0)
            cur = ev.get("rel_path") or ev.get("path") or ""
            _set_status(phase or task_state.get("phase", ""), done, total, str(cur))
            return

        if stage == "file_done":
            total = int(ev.get("total", task_state.get("total", 0)) or 0)
            done = int(ev.get("done", task_state.get("done", 0)) or 0)
            cur = ev.get("rel_path") or ev.get("path") or task_state.get("current_file", "")
            _set_status(phase or task_state.get("phase", ""), done, total, str(cur))
            return

        if stage == "done":
            total = int(ev.get("total", task_state.get("total", 0)) or 0)
            done = int(ev.get("done", total) or total)
            _set_status(phase or task_state.get("phase", ""), done, total, task_state.get("current_file", ""))
            phase_disp = (phase or task_state.get("phase", "")).capitalize() or "Work"
            eta_var.set(f"{phase_disp} completed in {_fmt_hms(time.time() - float(task_state.get('start_ts', 0.0) or 0.0))}")
            try:
                progress.stop()
            except Exception:
                pass
            return

    def _drain_progress_events() -> None:
        try:
            while True:
                ev = progress_q.get_nowait()
                if isinstance(ev, dict):
                    _handle_progress_event(ev)
        except queue.Empty:
            pass

    def run_in_thread(fn, on_done=None, phase: str = "working"):
        nonlocal worker_thread, stop_flag
        if worker_thread and worker_thread.is_alive():
            messagebox.showwarning("Busy", "A task is already running.")
            return
        stop_flag = False

        # Reset progress UI immediately
        _reset_progress_ui(phase)

        def _target():
            try:
                result = fn()
                if on_done:
                    root.after(0, lambda: on_done(result, None))
            except Exception as e:
                if on_done:
                    root.after(0, lambda: on_done(None, e))
            finally:
                # If worker didn't emit a final "done", stop the spinner anyway
                root.after(0, lambda: progress.stop())

        worker_thread = threading.Thread(target=_target, daemon=True)
        worker_thread.start()
    def do_scan():
        nonlocal current_scan
        if pyedflib is None:
            messagebox.showerror("Missing dependency", "pyedflib is required for full header export.\n\nInstall with:\n  pip install pyedflib")
            return
        s = src_folder.get().strip()
        if not s:
            messagebox.showwarning("Missing source folder", "Select a source folder.")
            return

        def _work():
            log(f"Scanning folder: {s}")
            scan = scan_folder(Path(s), include_all_files=include_all.get(), progress_cb=lambda ev: progress_q.put(ev))
            return scan

        def _done(scan, err):
            nonlocal current_scan
            if err:
                messagebox.showerror("Scan failed", str(err))
                log(f"Scan failed: {err}", logging.ERROR)
                return
            current_scan = scan
            populate_tree(current_scan)
            log(f"Scan completed. Files in table: {len(current_scan.entries)}")
            # Auto-fill JSON path if empty
            if not json_path_var.get().strip():
                json_path_var.set(str(Path(s) / "edf_scan.json"))

        run_in_thread(_work, _done, phase='scan')

    def do_redact():
        nonlocal current_scan
        if current_scan is None:
            messagebox.showwarning("No scan data", "Scan a folder or import a JSON first.")
            return

        if anonymize_edf_complete is None:
            messagebox.showerror(
                "Backend import error",
                f"Could not import redaction backend:\n{_BACKEND_IMPORT_ERROR}\n\n"
                "Fix the import path or ensure natus_edf_tools is available."
            )
            return

        out = out_folder.get().strip()
        if not out:
            messagebox.showwarning("Missing output folder", "Select an output folder.")
            return

        if (not blank_annotations_var.get()) and (not anonymize_header_var.get()):
            messagebox.showwarning("Nothing selected", "Enable at least one operation: blank annotations and/or anonymize header.")
            return

        anon_opts = build_anonymize_options(
            anonymize_header=anonymize_header_var.get(),
            anon_patientname=anon_patientname.get(),
            anon_patientcode=anon_patientcode.get(),
            anon_birthdate=anon_birthdate.get(),
            anon_gender=anon_gender.get(),
            anon_recording_additional=anon_recording_additional.get(),
            anon_admincode=anon_admincode.get(),
            anon_technician=anon_technician.get(),
            anon_equipment=anon_equipment.get(),
        )

        def _work():
            log(f"Redacting into: {out}")
            summary = redact_from_scan(
                current_scan,
                output_folder=Path(out),
                blank_annotations=blank_annotations_var.get(),
                anonymize_header=anonymize_header_var.get(),
                anonymize_options=anon_opts,
                buffer_size_mb=int(buffer_mb_var.get()),
                verify=verify_var.get(),
                verify_level=verify_level_var.get(),
                only_selected=True,
                progress_cb=lambda ev: progress_q.put(ev),
            )
            return summary

        def _done(summary, err):
            if err:
                messagebox.showerror("Redaction failed", str(err))
                log(f"Redaction failed: {err}", logging.ERROR)
                return
            log("Redaction summary:\n" + json.dumps(summary, indent=2))
            messagebox.showinfo(
                "Done",
                f"Processed: {summary.get('processed')}\n"
                f"Skipped: {summary.get('skipped')}\n"
                f"Failed: {summary.get('failed_count')}\n\n"
                f"Output: {summary.get('output_folder')}\n"
                f"Logs: {summary.get('log_dir')}"
            )

        run_in_thread(_work, _done, phase='redact')

    # Action buttons
    ttk.Button(actions, text="Scan Folder", command=do_scan).grid(row=0, column=0, padx=3, pady=2)
    ttk.Button(actions, text="Import JSON", command=import_json).grid(row=0, column=1, padx=3, pady=2)
    ttk.Button(actions, text="Export JSON", command=export_json).grid(row=0, column=2, padx=3, pady=2)

    ttk.Separator(actions, orient="vertical").grid(row=0, column=3, sticky="ns", padx=8)

    ttk.Button(actions, text="Select Non-blank", command=select_nonblank).grid(row=0, column=4, padx=3, pady=2)
    ttk.Button(actions, text="Select All", command=select_all).grid(row=0, column=5, padx=3, pady=2)
    ttk.Button(actions, text="Clear All", command=clear_all).grid(row=0, column=6, padx=3, pady=2)

    ttk.Separator(actions, orient="vertical").grid(row=0, column=7, sticky="ns", padx=8)

    ttk.Button(actions, text="Process Selected", command=do_redact).grid(row=0, column=8, padx=3, pady=2)

    # Poll log handler
    def poll():
        handler.poll()
        _drain_progress_events()
        root.after(100, poll)

    poll()
    root.mainloop()


# ---------------------------
# CLI
# ---------------------------

def _setup_cli_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")


def cli_scan(args: argparse.Namespace) -> int:
    if pyedflib is None:
        LOG.error("pyedflib is required for full header export. Install with: pip install pyedflib")
        return 2

    scan = scan_folder(
        Path(args.input_folder),
        annotation_labels=args.annotation_label,
        include_all_files=bool(args.include_all),
        max_records_per_file=args.max_records,
    )
    save_scan_json(scan, Path(args.output_json))
    LOG.info("Scan saved to: %s", args.output_json)
    LOG.info("Entries: %d", len(scan.entries))
    # Report quick stats
    nonblank = sum(1 for e in scan.entries if e.has_nonblank_annotation)
    LOG.info("Files with non-blank annotations: %d", nonblank)
    return 0


def cli_redact(args: argparse.Namespace) -> int:
    _require_backend()

    scan = load_scan_json(Path(args.input_json))
    out = Path(args.output_folder)

    anonymize_opts = build_anonymize_options(
        anonymize_header=bool(args.anonymize_header),
        anon_patientname=bool(args.anon_patientname),
        anon_patientcode=bool(args.anon_patientcode),
        anon_birthdate=bool(args.anon_birthdate),
        anon_gender=bool(args.anon_gender),
        anon_recording_additional=bool(args.anon_recording_additional),
        anon_admincode=bool(args.anon_admincode),
        anon_technician=bool(args.anon_technician),
        anon_equipment=bool(args.anon_equipment),
    )

    summary = redact_from_scan(
        scan,
        output_folder=out,
        blank_annotations=bool(args.blank_annotations),
        anonymize_header=bool(args.anonymize_header),
        anonymize_options=anonymize_opts,
        buffer_size_mb=int(args.buffer_mb),
        verify=bool(args.verify),
        verify_level=str(args.verify_level),
        only_selected=not bool(args.process_all),
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("failed_count", 0) == 0 else 1


def cli_scan_redact(args: argparse.Namespace) -> int:
    if pyedflib is None:
        LOG.error("pyedflib is required for full header export. Install with: pip install pyedflib")
        return 2
    _require_backend()

    scan = scan_folder(
        Path(args.input_folder),
        annotation_labels=args.annotation_label,
        include_all_files=True,
        max_records_per_file=args.max_records,
    )

    # Optionally save scan JSON
    if args.output_json:
        save_scan_json(scan, Path(args.output_json))
        LOG.info("Scan saved to: %s", args.output_json)

    anonymize_opts = build_anonymize_options(
        anonymize_header=bool(args.anonymize_header),
        anon_patientname=bool(args.anon_patientname),
        anon_patientcode=bool(args.anon_patientcode),
        anon_birthdate=bool(args.anon_birthdate),
        anon_gender=bool(args.anon_gender),
        anon_recording_additional=bool(args.anon_recording_additional),
        anon_admincode=bool(args.anon_admincode),
        anon_technician=bool(args.anon_technician),
        anon_equipment=bool(args.anon_equipment),
    )

    # By default, redact only those with nonblank annotations (selected=True)
    # But if --process-all is set, redact everything.
    if bool(args.process_all):
        for e in scan.entries:
            e.selected = True

    summary = redact_from_scan(
        scan,
        output_folder=Path(args.output_folder),
        blank_annotations=bool(args.blank_annotations),
        anonymize_header=bool(args.anonymize_header),
        anonymize_options=anonymize_opts,
        buffer_size_mb=int(args.buffer_mb),
        verify=bool(args.verify),
        verify_level=str(args.verify_level),
        only_selected=True,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("failed_count", 0) == 0 else 1


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="EDF_Folder_Scan_Redact_Tool",
        description="Scan EDF/BDF folders for non-blank annotations, export JSON, and redact via existing backend.",
    )
    p.add_argument("--verbose", action="store_true", help="Verbose logging.")
    p.add_argument("--gui", action="store_true", help="Force GUI mode.")

    sub = p.add_subparsers(dest="cmd")

    # scan
    ps = sub.add_parser("scan", help="Scan a folder and export JSON.")
    ps.add_argument("--input-folder", required=True, help="Folder to scan recursively.")
    ps.add_argument("--output-json", required=True, help="Output JSON path.")
    ps.add_argument("--include-all", action="store_true", help="Include all EDF/BDF files in JSON (default false for CLI scan).")
    ps.add_argument("--annotation-label", action="append", default=[], help="Extra annotation channel labels to match (repeatable).")
    ps.add_argument("--max-records", type=int, default=None, help="Optional maximum data records to scan per file (debug/perf).")
    ps.set_defaults(func=cli_scan)

    # redact
    pr = sub.add_parser("redact", help="Redact files described in a scan JSON.")
    pr.add_argument("--input-json", required=True, help="Scan JSON path.")
    pr.add_argument("--output-folder", required=True, help="Destination folder (will preserve relative paths).")
    pr.add_argument("--blank-annotations", action="store_true", help="Blank embedded annotations.")
    pr.add_argument("--anonymize-header", action="store_true", help="Anonymize header fields (see --anon-* flags).")
    pr.add_argument("--buffer-mb", type=int, default=64, help="Buffer size in MB for backend processing.")
    pr.add_argument("--verify", action="store_true", help="Run backend verification after processing.")
    pr.add_argument("--verify-level", choices=["basic", "thorough"], default="thorough", help="Verification level.")
    pr.add_argument("--process-all", action="store_true", help="Ignore selection flags in JSON and process all files.")
    # anon fields
    pr.add_argument("--anon-patientname", action="store_true", help="Anonymize patientname.")
    pr.add_argument("--anon-patientcode", action="store_true", help="Anonymize patientcode.")
    pr.add_argument("--anon-birthdate", action="store_true", help="Anonymize birthdate.")
    pr.add_argument("--anon-gender", action="store_true", help="Anonymize gender.")
    pr.add_argument("--anon-recording-additional", action="store_true", help="Anonymize recording_additional.")
    pr.add_argument("--anon-admincode", action="store_true", help="Anonymize admincode.")
    pr.add_argument("--anon-technician", action="store_true", help="Anonymize technician.")
    pr.add_argument("--anon-equipment", action="store_true", help="Anonymize equipment.")
    pr.set_defaults(func=cli_redact)

    # scan-redact
    psr = sub.add_parser("scan-redact", help="Scan a folder then redact (optionally save scan JSON).")
    psr.add_argument("--input-folder", required=True, help="Folder to scan recursively.")
    psr.add_argument("--output-folder", required=True, help="Destination folder (will preserve relative paths).")
    psr.add_argument("--output-json", default=None, help="Optional: also save scan JSON to this path.")
    psr.add_argument("--annotation-label", action="append", default=[], help="Extra annotation channel labels to match (repeatable).")
    psr.add_argument("--max-records", type=int, default=None, help="Optional maximum data records to scan per file (debug/perf).")
    psr.add_argument("--blank-annotations", action="store_true", help="Blank embedded annotations.")
    psr.add_argument("--anonymize-header", action="store_true", help="Anonymize header fields (see --anon-* flags).")
    psr.add_argument("--buffer-mb", type=int, default=64, help="Buffer size in MB for backend processing.")
    psr.add_argument("--verify", action="store_true", help="Run backend verification after processing.")
    psr.add_argument("--verify-level", choices=["basic", "thorough"], default="thorough", help="Verification level.")
    psr.add_argument("--process-all", action="store_true", help="Process all scanned files (default is only those with non-blank annotations).")
    # anon fields
    psr.add_argument("--anon-patientname", action="store_true", help="Anonymize patientname.")
    psr.add_argument("--anon-patientcode", action="store_true", help="Anonymize patientcode.")
    psr.add_argument("--anon-birthdate", action="store_true", help="Anonymize birthdate.")
    psr.add_argument("--anon-gender", action="store_true", help="Anonymize gender.")
    psr.add_argument("--anon-recording-additional", action="store_true", help="Anonymize recording_additional.")
    psr.add_argument("--anon-admincode", action="store_true", help="Anonymize admincode.")
    psr.add_argument("--anon-technician", action="store_true", help="Anonymize technician.")
    psr.add_argument("--anon-equipment", action="store_true", help="Anonymize equipment.")
    psr.set_defaults(func=cli_scan_redact)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # No args => GUI
    if len(argv) == 0:
        run_gui()
        return 0

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    _setup_cli_logging(verbose=bool(getattr(args, "verbose", False)))

    if getattr(args, "gui", False):
        run_gui()
        return 0

    if not getattr(args, "cmd", None):
        parser.print_help()
        return 2

    # CLI default: scan includes only nonblank unless --include-all is set.
    if args.cmd == "scan" and not getattr(args, "include_all", False):
        # keep behavior explicit: default is only non-blank in CLI scan
        # (GUI has its own checkbox default true)
        pass

    return int(args.func(args))  # type: ignore


if __name__ == "__main__":
    raise SystemExit(main())
