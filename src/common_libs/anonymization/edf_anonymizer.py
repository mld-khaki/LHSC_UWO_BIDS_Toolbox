# -*- coding: utf-8 -*-
"""
EDF Anonymizer (Header scrub + optional embedded annotation blanking)

Design goals:
- No legacy dependencies (no ahocorasick/tqdm/numpy)
- Safe defaults: scrub header patient/recording fields
- Optional: blank EDF+/BDF+ embedded TAL/annotations at the binary level
- Stream copy: preserves file structure and size

Notes:
- This module does NOT attempt "string replacement redaction" inside TAL.
  It is designed for the policy: blank all annotation content (PHI-safe).
- For EDF: 2 bytes/sample (int16). For BDF: 3 bytes/sample (24-bit).
"""

from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any


# -----------------------------
# Helpers / constants
# -----------------------------

EDF_FIXED_HEADER_BYTES = 256
SIG_HEADER_BYTES_PER_SIGNAL = 256

ANNOTATION_LABELS = {
    "EDF Annotations",
    "BDF Annotations",
    "EDF+ Annotations",
    "BDF+ Annotations",
}


def _setup_logger(log_dir: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger("edf_anonymizer")
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    fmt = logging.Formatter("%(levelname)s: %(message)s")
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(os.path.join(log_dir, "edf_anonymizer.log"), encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(fh)

    return logger


def _padtrim_ascii(text: str, length: int) -> bytes:
    # EDF header fields are ASCII, space-padded.
    b = (text or "").encode("ascii", errors="ignore")[:length]
    return b + (b" " * (length - len(b)))


def _safe_int_from_ascii(field_bytes: bytes) -> Optional[int]:
    s = field_bytes.decode("ascii", errors="ignore").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        # Some writers use non-standard; keep None
        return None


def _safe_float_from_ascii(field_bytes: bytes) -> Optional[float]:
    s = field_bytes.decode("ascii", errors="ignore").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _looks_like_bdf(path: str, header_reserved: bytes) -> bool:
    # Most robust: extension
    ext = os.path.splitext(path)[1].lower()
    if ext == ".bdf":
        return True
    # Heuristic: sometimes reserved contains "BDF" or "24BIT"
    r = header_reserved.decode("ascii", errors="ignore").upper()
    if "BDF" in r or "24BIT" in r or "24-BIT" in r:
        return True
    return False


@dataclass
class EDFStructure:
    header_bytes: int
    n_signals: int
    n_records: Optional[int]
    record_duration: Optional[float]
    bytes_per_sample: int
    samples_per_signal: List[int]
    labels: List[str]

    @property
    def record_bytes(self) -> int:
        return sum(self.samples_per_signal) * self.bytes_per_sample

    def annotation_signal_indices(self) -> List[int]:
        out = []
        for i, lbl in enumerate(self.labels):
            if lbl.strip() in ANNOTATION_LABELS:
                out.append(i)
        return out

    def annotation_segments(self) -> List[Tuple[int, int]]:
        """
        Returns list of (offset_bytes, size_bytes) inside each data record.
        """
        segs: List[Tuple[int, int]] = []
        offset = 0
        for i, n_samp in enumerate(self.samples_per_signal):
            size = n_samp * self.bytes_per_sample
            if self.labels[i].strip() in ANNOTATION_LABELS:
                segs.append((offset, size))
            offset += size
        return segs


def parse_edf_structure(file_path: str, logger: Optional[logging.Logger] = None) -> EDFStructure:
    logger = logger or _setup_logger(None)

    with open(file_path, "rb") as f:
        fixed = f.read(EDF_FIXED_HEADER_BYTES)
        if len(fixed) != EDF_FIXED_HEADER_BYTES:
            raise ValueError(f"Not a valid EDF/BDF file (header too short): {file_path}")

        header_bytes = _safe_int_from_ascii(fixed[184:192])
        n_records = _safe_int_from_ascii(fixed[236:244])
        record_duration = _safe_float_from_ascii(fixed[244:252])
        n_signals = _safe_int_from_ascii(fixed[252:256])

        if header_bytes is None or n_signals is None:
            raise ValueError(f"Cannot parse EDF header_bytes or n_signals: {file_path}")

        # Reserved field used for heuristics
        reserved = fixed[192:236]
        bytes_per_sample = 3 if _looks_like_bdf(file_path, reserved) else 2

        # Read full header to parse per-signal fields
        f.seek(0)
        header = f.read(header_bytes)
        if len(header) != header_bytes:
            #Bug raise ValueError(f"Header truncated: expected {header_bytes}, got {len(header_bytes)}")
            raise ValueError(f"Header truncated: expected {header_bytes}, got {len(header)}")


        # Per-signal header blocks are "column-wise" fields.
        # Offsets within the full header:
        # fixed (256) then arrays:
        # label (16*ns), transducer (80*ns), physdim (8*ns),
        # physmin (8*ns), physmax (8*ns), digmin (8*ns), digmax (8*ns),
        # prefilter (80*ns), samples (8*ns), reserved (32*ns)
        base = EDF_FIXED_HEADER_BYTES
        ns = n_signals

        def read_field(field_len: int) -> List[bytes]:
            nonlocal base
            chunk = header[base: base + field_len * ns]
            base += field_len * ns
            return [chunk[i * field_len:(i + 1) * field_len] for i in range(ns)]

        labels_b = read_field(16)
        _ = read_field(80)  # transducer
        _ = read_field(8)   # physdim
        _ = read_field(8)   # physmin
        _ = read_field(8)   # physmax
        _ = read_field(8)   # digmin
        _ = read_field(8)   # digmax
        _ = read_field(80)  # prefilter
        samples_b = read_field(8)
        _ = read_field(32)  # reserved

        labels = [b.decode("ascii", errors="ignore").strip() for b in labels_b]
        samples_per_signal: List[int] = []
        for sb in samples_b:
            v = _safe_int_from_ascii(sb)
            samples_per_signal.append(v if v is not None else 0)

        return EDFStructure(
            header_bytes=header_bytes,
            n_signals=ns,
            n_records=n_records,
            record_duration=record_duration,
            bytes_per_sample=bytes_per_sample,
            samples_per_signal=samples_per_signal,
            labels=labels,
        )


# -----------------------------
# Header scrub
# -----------------------------

def scrub_header_bytes(
    header: bytes,
    patient_field: str = "X X X X",
    recording_field: str = "Startdate X X X X",
) -> bytes:
    """
    Returns a modified header bytes buffer with patient/recording overwritten.
    Works for both EDF and BDF since header layout is the same.
    """
    if len(header) < EDF_FIXED_HEADER_BYTES:
        raise ValueError("Header buffer too short.")

    out = bytearray(header)
    out[8:88] = _padtrim_ascii(patient_field, 80)
    out[88:168] = _padtrim_ascii(recording_field, 80)
    return bytes(out)


def scrub_header_in_place(
    edf_path: str,
    patient_field: str = "X X X X",
    recording_field: str = "Startdate X X X X",
) -> None:
    """
    Scrub patient/recording header fields in-place.
    Does NOT modify annotations (data records).
    """
    logger = _setup_logger(None)
    with open(edf_path, "r+b") as f:
        fixed = f.read(EDF_FIXED_HEADER_BYTES)
        if len(fixed) != EDF_FIXED_HEADER_BYTES:
            raise ValueError(f"Not a valid EDF/BDF (header too short): {edf_path}")
        header_bytes = _safe_int_from_ascii(fixed[184:192])
        if header_bytes is None:
            raise ValueError(f"Cannot parse header length: {edf_path}")

        f.seek(0)
        header = f.read(header_bytes)
        if len(header) != header_bytes:
            raise ValueError(f"Header truncated: {edf_path}")

        new_header = scrub_header_bytes(header, patient_field=patient_field, recording_field=recording_field)

        f.seek(0)
        f.write(new_header)

    logger.info(f"Scrubbed EDF/BDF header in-place: {edf_path}")


# -----------------------------
# Full-file anonymization
# -----------------------------

def _blank_tal_annotations(chunk: bytearray, off: int, sz: int) -> None:
    """
    Blank annotation text within a TAL block while preserving timing structure.
    Replaces annotation text (after 0x14 separators) with spaces,
    keeping timestamps and structural bytes intact.
    """
    end = off + sz
    pos = off
    data = chunk

    while pos < end:
        # Find start of TAL: must begin with + or -
        if data[pos] in (ord('+'), ord('-')):
            # Find first 0x14 (end of onset timestamp)
            sep1 = data.find(0x14, pos, end)
            if sep1 == -1:
                break
            # Find null terminator of this TAL
            null_pos = data.find(0x00, sep1, end)
            if null_pos == -1:
                null_pos = end

            # Blank everything between the first 0x14 and the null,
            # but preserve the 0x14 bytes themselves
            cursor = sep1 + 1
            while cursor < null_pos:
                next_sep = data.find(0x14, cursor, null_pos)
                if next_sep == -1:
                    # Blank from cursor to null terminator
                    for i in range(cursor, null_pos):
                        data[i] = ord(' ')
                    break
                else:
                    # Blank text segment between separators
                    for i in range(cursor, next_sep):
                        data[i] = ord(' ')
                    cursor = next_sep + 1

            pos = null_pos + 1
        else:
            pos += 1

def anonymize_edf_file(
    src_path: str,
    dst_path: str,
    *,
    patient_field: str = "X X X X",
    recording_field: str = "Startdate X X X X",
    blank_annotations: bool = True,
    buffer_mb: int = 64,
    log_dir: Optional[str] = None,
) -> bool:
    """
    Copy src EDF/BDF to dst with anonymized header, and optionally blank embedded annotations.

    Returns True on success, False on failure.
    """
    logger = _setup_logger(log_dir)

    try:
        st = parse_edf_structure(src_path, logger=logger)
        header_bytes = st.header_bytes
        record_bytes = st.record_bytes
        annot_segs = st.annotation_segments() if blank_annotations else []

        if record_bytes <= 0:
            raise ValueError(f"Computed record_bytes <= 0 (bad header?): {src_path}")

        buf_size = max(1024 * 1024, int(buffer_mb * 1024 * 1024))

        with open(src_path, "rb") as fin, open(dst_path, "wb") as fout:
            header = fin.read(header_bytes)
            if len(header) != header_bytes:
                raise ValueError(f"Header truncated: {src_path}")

            fout.write(scrub_header_bytes(header, patient_field=patient_field, recording_field=recording_field))

            # Now stream-copy data records
            # Prefer record-by-record handling so we can safely blank exact segments.
            # If n_records is unknown/invalid, we copy until EOF, but in record-sized reads.
            rec_count = 0
            while True:
                chunk = fin.read(record_bytes)
                if not chunk:
                    break
                if len(chunk) != record_bytes:
                    # Partial record at end -> write as-is (rare corruption). Still safe to scrub header.
                    fout.write(chunk)
                    break

                if annot_segs:
                    b = bytearray(chunk)
                    for off, sz in annot_segs:
                        if sz <= 0:
                            continue
                        end = off + sz
                        if end <= len(b):
                            # blank with zeros (PHI-safe, preserves size)
                            #found the bug! #b[off:end] = b"\x00" * sz
                            # FIXED:
                            _blank_tal_annotations(b, off, sz)
                            
                    fout.write(bytes(b))
                else:
                    fout.write(chunk)

                rec_count += 1

        # Basic sanity check
        src_sz = os.path.getsize(src_path)
        dst_sz = os.path.getsize(dst_path)
        if src_sz != dst_sz:
            logger.warning(f"Size mismatch after anonymization: src={src_sz} dst={dst_sz} ({src_path})")

        logger.info(
            f"Anonymized EDF/BDF: {os.path.basename(src_path)} -> {os.path.basename(dst_path)} "
            f"(records_copied={rec_count}, blank_annotations={blank_annotations})"
        )
        return True

    except Exception as e:
        logger.error(f"Anonymization failed for {src_path}: {e}")
        return False


# -----------------------------
# Verification (for StepB)
# -----------------------------

def verify_edf_anonymized(
    edf_path: str,
    *,
    expected_patient_field: str = "X X X X",
    expected_recording_field_prefix: str = "Startdate",
    require_blank_annotations: bool = False,
    max_records_to_check: int = 3,
) -> Dict[str, Any]:
    """
    Verify (without exposing PHI) whether:
    - patient/recording fields look scrubbed
    - (optional) annotation bytes are blank in the first N records

    Returns dict with booleans and reasons (no raw PHI).
    """
    logger = _setup_logger(None)

    result: Dict[str, Any] = {
        "path": os.path.abspath(edf_path),
        "header_patient_ok": False,
        "header_recording_ok": False,
        "header_ok": False,
        "annotation_channels_present": False,
        "annotations_blank_ok": None,
        "notes": [],
    }

    try:
        st = parse_edf_structure(edf_path, logger=logger)
        annot_segs = st.annotation_segments()
        result["annotation_channels_present"] = len(annot_segs) > 0

        with open(edf_path, "rb") as f:
            fixed = f.read(EDF_FIXED_HEADER_BYTES)
            if len(fixed) != EDF_FIXED_HEADER_BYTES:
                result["notes"].append("Header too short.")
                return result

            patient = fixed[8:88].decode("ascii", errors="ignore").strip()
            rec = fixed[88:168].decode("ascii", errors="ignore").strip()

            # Patient check: exact match to expected
            result["header_patient_ok"] = (patient == expected_patient_field)

            # Recording check: must start with expected prefix (to allow small variations)
            result["header_recording_ok"] = rec.startswith(expected_recording_field_prefix)

            result["header_ok"] = result["header_patient_ok"] and result["header_recording_ok"]

            if require_blank_annotations:
                if not annot_segs:
                    result["annotations_blank_ok"] = True
                    result["notes"].append("No annotation channels detected.")
                    return result

                header_bytes = st.header_bytes
                rec_bytes = st.record_bytes

                f.seek(header_bytes)
                ok = True
                for _i in range(max_records_to_check):
                    recbuf = f.read(rec_bytes)
                    if not recbuf:
                        break
                    if len(recbuf) != rec_bytes:
                        break

                    for off, sz in annot_segs:
                        seg = recbuf[off:off + sz]
                        # Accept fully zeroed (our policy) or fully space-padded.
                        if not (all(b == 0 for b in seg) or all(b == 32 for b in seg)):
                            ok = False
                            break
                    if not ok:
                        break

                result["annotations_blank_ok"] = ok

        return result

    except Exception as e:
        result["notes"].append(f"verify exception: {e}")
        return result