# -*- coding: utf-8 -*-
"""
edf_embedded_annotations_redactor.py

EDF+ tool that can:
  1) Blank (remove) embedded EDF+ annotations (EDF Annotations / BDF Annotations channels)
  2) Optionally anonymize selected patient/recording header sub-fields
  3) Optionally copy signal labels (electrode names) from a reference EDF to a target EDF
     using a strict 1-to-1 index mapping (excluding annotation channels)

This file is designed to be used both:
  - As a library (imported by the GUI)
  - As a CLI script (python edf_embedded_annotations_redactor.py ...)

Notes:
  - "Electrode names" here means the EDF signal label field (16 bytes per signal).
  - Copying labels does NOT change signal data, only the header label strings.
"""

import numpy as np
import re
import logging
import os
import time
import mmap
import traceback
import argparse
from datetime import datetime
import sys

from tqdm import tqdm

# Optional dependency (legacy)
try:
    import ahocorasick  # noqa: F401
except Exception:
    ahocorasick = None  # type: ignore

# Optional: used in verification
try:
    from edflibpy.edfreader import EDFreader
except Exception:
    EDFreader = None  # type: ignore


ANNOTATION_LABELS = {"EDF Annotations", "BDF Annotations"}


# --------------------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------------------
def setup_logging(log_dir="logs", filename="logData_"):
    """Set up detailed logging to both console and file."""
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, filename + f"edf_anonymize_{timestamp}.log")
    redaction_map_file = os.path.join(log_dir, filename + f"redaction_map_{timestamp}.txt")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Remove any existing handlers to avoid duplicate logs in repeated GUI runs
    for h in list(logger.handlers):
        logger.removeHandler(h)

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(levelname)s: %(message)s")
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    redaction_map_handler = logging.FileHandler(redaction_map_file)
    redaction_map_handler.setLevel(logging.INFO)
    redaction_map_formatter = logging.Formatter("%(message)s")
    redaction_map_handler.setFormatter(redaction_map_formatter)

    redaction_logger = logging.getLogger("redaction_map")
    redaction_logger.setLevel(logging.INFO)

    for h in list(redaction_logger.handlers):
        redaction_logger.removeHandler(h)

    redaction_logger.addHandler(redaction_map_handler)

    logger.info(f"Logging initialized. Log file: {log_file}")
    logger.info(f"Redaction map file: {redaction_map_file}")
    return logger


# --------------------------------------------------------------------------------------
# EDF structure parsing (no external libs needed)
# --------------------------------------------------------------------------------------
def _read_bytes_field(b: bytes) -> str:
    return b.decode("ascii", errors="ignore").strip()


def read_edf_structure(edf_path: str):
    """
    Read the essential EDF header pieces needed for:
      - signal label mapping
      - identifying annotation channels
      - validating structure compatibility
      - computing record_size

    Returns:
      dict with keys:
        - header_bytes, data_records, record_duration, num_signals
        - base_header (256 bytes as bytearray)
        - signal_header (num_signals*256 bytes as bytearray)
        - signal_labels (list[str], length num_signals)
        - annot_channels (list[int])
        - samples_per_record (list[int], length num_signals)
        - record_size (int, bytes)
        - signal_header_size (int)
    """
    if not os.path.exists(edf_path):
        raise FileNotFoundError(f"EDF not found: {edf_path}")

    with open(edf_path, "rb") as f:
        base_header = bytearray(f.read(256))
        if len(base_header) != 256:
            raise ValueError(f"File too small to be a valid EDF: {edf_path}")

        header_bytes = int(_read_bytes_field(base_header[184:192]))
        data_records = int(_read_bytes_field(base_header[236:244]))
        record_duration = float(_read_bytes_field(base_header[244:252]))
        num_signals = int(_read_bytes_field(base_header[252:256]))

        signal_header_size = num_signals * 256
        signal_header = bytearray(f.read(signal_header_size))
        if len(signal_header) != signal_header_size:
            raise ValueError(f"Failed to read full signal header from: {edf_path}")

        # Signal labels live in first (num_signals*16) bytes
        signal_labels = [
            signal_header[i * 16 : (i + 1) * 16].decode("ascii", errors="ignore").strip()
            for i in range(num_signals)
        ]
        annot_channels = [i for i, lab in enumerate(signal_labels) if lab.strip() in ANNOTATION_LABELS]

        # Samples-per-record start offset in the "field-wise" signal header layout:
        # offset = num_signals * 216, then 8 bytes per signal.
        samples_per_record = []
        spr_offset = num_signals * 216
        for i in range(num_signals):
            spr_raw = signal_header[spr_offset + i * 8 : spr_offset + (i + 1) * 8]
            spr = int(_read_bytes_field(spr_raw))
            samples_per_record.append(spr)

        bytes_per_sample = 2  # EDF
        record_size = sum(samples_per_record) * bytes_per_sample

        return {
            "header_bytes": header_bytes,
            "data_records": data_records,
            "record_duration": record_duration,
            "num_signals": num_signals,
            "base_header": base_header,
            "signal_header": signal_header,
            "signal_labels": signal_labels,
            "annot_channels": annot_channels,
            "samples_per_record": samples_per_record,
            "record_size": record_size,
            "signal_header_size": signal_header_size,
        }


def _non_annotation_indices(struct_dict):
    annot = set(struct_dict["annot_channels"])
    return [i for i in range(struct_dict["num_signals"]) if i not in annot]


def compare_edf_signal_labels(
    ref_edf_path: str,
    target_edf_path: str,
    *,
    require_strict_structure_match: bool = True,
):
    """
    Compare reference and target EDF signal labels (electrode names), excluding annotation channels.

    Returns a dict with summary + lists:
      - matches: list[str] (one line per matching channel)
      - mismatches: list[str] (one line per mismatching channel)
    """
    ref_s = read_edf_structure(ref_edf_path)
    tgt_s = read_edf_structure(target_edf_path)

    if require_strict_structure_match:
        # Always required
        if ref_struct["num_signals"] != target_struct["num_signals"]:
            raise ValueError(
                f"Structure mismatch: num_signals differs "
                f"(ref={ref_struct['num_signals']}, target={target_struct['num_signals']})"
            )

        if ref_struct["annot_channels"] != target_struct["annot_channels"]:
            raise ValueError(
                f"Structure mismatch: annotation channel indices differ "
                f"(ref={ref_struct['annot_channels']}, target={target_struct['annot_channels']})"
            )

        # Only required if we are NOT doing label-only operations
        if not copy_signal_labels:
            if ref_struct["samples_per_record"] != target_struct["samples_per_record"]:
                raise ValueError(
                    "Structure mismatch: samples_per_record differs "
                    "(required only when modifying signal data)."
                )


    ref_idx = _non_annotation_indices(ref_s)
    tgt_idx = _non_annotation_indices(tgt_s)

    if len(ref_idx) != len(tgt_idx):
        raise ValueError(
            f"Non-annotation channel count mismatch: ref={len(ref_idx)} vs target={len(tgt_idx)}"
        )

    matches = []
    mismatches = []
    for k, (ri, ti) in enumerate(zip(ref_idx, tgt_idx), start=1):
        rlab = ref_s["signal_labels"][ri]
        tlab = tgt_s["signal_labels"][ti]
        if rlab.strip() == tlab.strip():
            matches.append(f"{k:04d} | sig_idx={ti:03d} | {tlab}")
        else:
            mismatches.append(f"{k:04d} | sig_idx={ti:03d} | target='{tlab}'  !=  ref='{rlab}'")

    return {
        "ref_path": ref_edf_path,
        "target_path": target_edf_path,
        "num_signals": tgt_s["num_signals"],
        "annot_channels": tgt_s["annot_channels"],
        "num_non_annot": len(tgt_idx),
        "num_matches": len(matches),
        "num_mismatches": len(mismatches),
        "matches": matches,
        "mismatches": mismatches,
    }


def _encode_signal_label(label: str) -> bytes:
    # EDF label field is 16 bytes, ASCII; truncate/pad with spaces.
    lab = (label or "").encode("ascii", errors="ignore")[:16]
    return lab.ljust(16, b" ")


def copy_signal_labels_from_ref_to_target_signal_header(
    ref_struct: dict,
    target_struct: dict,
    target_signal_header: bytearray,
):
    """
    Modify target_signal_header in-place to copy NON-annotation signal labels from ref to target
    by 1-to-1 mapping in channel order (excluding annotation channels).

    Preconditions:
      - Structure compatibility must already have been checked.
    """
    ref_idx = _non_annotation_indices(ref_struct)
    tgt_idx = _non_annotation_indices(target_struct)

    if len(ref_idx) != len(tgt_idx):
        raise ValueError(
            f"Non-annotation channel count mismatch: ref={len(ref_idx)} vs target={len(tgt_idx)}"
        )

    for ri, ti in zip(ref_idx, tgt_idx):
        new_lab = ref_struct["signal_labels"][ri]
        target_signal_header[ti * 16 : (ti + 1) * 16] = _encode_signal_label(new_lab)

    return target_signal_header


# --------------------------------------------------------------------------------------
# Selective header anonymization
# --------------------------------------------------------------------------------------
def _split_field_tokens(field_str: str):
    # EDF fields are space-separated tokens, but patientname/equipment can have spaces.
    # We'll parse by spec-like heuristics and preserve remaining text.
    return field_str.strip().split()


def _build_patient_field(
    original_patient_field: str,
    *,
    anonymize_patientcode: bool,
    anonymize_gender: bool,
    anonymize_birthdate: bool,
    anonymize_patientname: bool,
) -> str:
    """
    EDF+ patient field format (common):
        patientcode sex birthdate patientname...

    We preserve token count/spacing as best-effort, then pad/truncate to 80 bytes later.
    """
    parts = _split_field_tokens(original_patient_field)
    if len(parts) < 4:
        # Fallback: if not parseable, either wipe whole field if any anonymize requested
        if anonymize_patientcode or anonymize_gender or anonymize_birthdate or anonymize_patientname:
            return "X X X X"
        return original_patient_field.strip()

    patientcode = parts[0]
    sex = parts[1]
    birthdate = parts[2]
    name_parts = parts[3:]

    if anonymize_patientcode:
        patientcode = "X"
    if anonymize_gender:
        sex = "X"
    if anonymize_birthdate:
        birthdate = "X"
    if anonymize_patientname:
        # Replace each token, keep token count similar
        name_parts = ["X" for _ in name_parts] if name_parts else ["X"]

    return " ".join([patientcode, sex, birthdate] + name_parts)


def _build_recording_field(
    original_recording_field: str,
    *,
    anonymize_recording_additional: bool,
    anonymize_admincode: bool,
    anonymize_technician: bool,
    anonymize_equipment: bool,
) -> str:
    """
    EDF+ recording field format (common):
        startdate admincode technician equipment...

    User didn't request startdate as a checkbox; we keep token0 unless the field is not parseable.
    "recording_additional" is interpreted as: wipe everything AFTER the first token (startdate).
    """
    parts = _split_field_tokens(original_recording_field)
    if len(parts) < 1:
        return original_recording_field.strip()

    startdate = parts[0]
    admincode = parts[1] if len(parts) >= 2 else ""
    technician = parts[2] if len(parts) >= 3 else ""
    equipment_parts = parts[3:] if len(parts) >= 4 else []

    if anonymize_recording_additional:
        # wipe everything after startdate
        admincode = "X" if admincode else ""
        technician = "X" if technician else ""
        equipment_parts = ["X"] if equipment_parts else []
    else:
        if anonymize_admincode and admincode:
            admincode = "X"
        if anonymize_technician and technician:
            technician = "X"
        if anonymize_equipment and equipment_parts:
            equipment_parts = ["X" for _ in equipment_parts]

    rebuilt = " ".join([p for p in [startdate, admincode, technician] if p] + equipment_parts)
    return rebuilt.strip() if rebuilt.strip() else original_recording_field.strip()


def anonymize_edf_header_selective(base_header_bytes: bytes, anonymize_options: dict | None):
    """
    Selectively anonymize patient/recording subfields (EDF+ style).
    Fields affected:
      - patient field: bytes 8..88 (80 bytes)
      - recording field: bytes 88..168 (80 bytes)

    If anonymize_options is None -> keep legacy behavior:
      - wipe entire patient field to 'X X X X'
      - leave recording field unchanged
    """
    logger = logging.getLogger("edf_header")
    new_header = bytearray(base_header_bytes)

    patient_field = base_header_bytes[8:88].decode("ascii", errors="ignore").strip()
    recording_field = base_header_bytes[88:168].decode("ascii", errors="ignore").strip()

    if anonymize_options is None:
        # Legacy behavior
        anon_patient = "X X X X"
        new_header[8:88] = anon_patient.ljust(80).encode("ascii", errors="ignore")[:80]
        logger.info(f"Anonymized patient field (legacy): '{patient_field}' -> '{anon_patient}'")
        return new_header

    # Patient options
    anon_patient_str = _build_patient_field(
        patient_field,
        anonymize_patientcode=bool(anonymize_options.get("patientcode", True)),
        anonymize_gender=bool(anonymize_options.get("gender", True)),
        anonymize_birthdate=bool(anonymize_options.get("birthdate", True)),
        anonymize_patientname=bool(anonymize_options.get("patientname", True)),
    )

    # Recording options
    anon_recording_str = _build_recording_field(
        recording_field,
        anonymize_recording_additional=bool(anonymize_options.get("recording_additional", False)),
        anonymize_admincode=bool(anonymize_options.get("admincode", False)),
        anonymize_technician=bool(anonymize_options.get("technician", False)),
        anonymize_equipment=bool(anonymize_options.get("equipment", False)),
    )

    new_header[8:88] = anon_patient_str.ljust(80).encode("ascii", errors="ignore")[:80]
    new_header[88:168] = anon_recording_str.ljust(80).encode("ascii", errors="ignore")[:80]

    logger.info(f"Patient field: '{patient_field}' -> '{anon_patient_str}'")
    logger.info(f"Recording field: '{recording_field}' -> '{anon_recording_str}'")

    return new_header


# --------------------------------------------------------------------------------------
# EDF+ Annotation blanking (kept close to your original implementation)
# --------------------------------------------------------------------------------------
def process_edf_annotations(data_chunk, annot_offsets, annot_sizes, record_size):
    """
    Blank all EDF+ annotations in the chunk by replacing annotation content with spaces (preserving size).
    """
    logger = logging.getLogger("edf_processor")
    redaction_logger = logging.getLogger("redaction_map")
    logger.debug(f"Processing data chunk of size {len(data_chunk)}, with {len(annot_offsets)} annotation signals")

    data_array = np.frombuffer(data_chunk, dtype=np.uint8).copy()

    for r in range(len(data_chunk) // record_size):
        record_start = r * record_size

        for i, offset in enumerate(annot_offsets):
            annot_start = record_start + offset
            annot_end = annot_start + annot_sizes[i]

            if annot_end <= len(data_array):
                annot_data = data_array[annot_start:annot_end]

                try:
                    annot_bytes = annot_data.tobytes()

                    if all(b == 0 for b in annot_bytes):
                        continue

                    pos = 0
                    modified_bytes = bytearray(annot_bytes)

                    while pos < len(annot_bytes):
                        if annot_bytes[pos] == ord("+") or annot_bytes[pos] == ord("-"):
                            tal_end = annot_bytes.find(b"\x00", pos)
                            if tal_end == -1:
                                tal_end = len(annot_bytes) - 1

                            tal_bytes = annot_bytes[pos : tal_end + 1]
                            modified_tal = process_tal_blank(tal_bytes, logger, redaction_logger)

                            modified_bytes[pos : pos + len(tal_bytes)] = modified_tal
                            pos += len(modified_tal)
                        else:
                            pos += 1

                    for j in range(len(modified_bytes)):
                        if annot_start + j < len(data_array):
                            data_array[annot_start + j] = modified_bytes[j]

                except Exception as e:
                    logger.warning(f"Warning: Failed to process annotation in record {r}, offset {offset}: {e}")
                    logger.debug(f"Exception details: {traceback.format_exc()}")

    return data_array.tobytes()


def process_tal_blank(tal_bytes, logger, redaction_logger):
    """
    Process a single TAL by blanking all annotation text segments (keep timestamp).
    """
    try:
        tal = bytearray(tal_bytes)
        onset_end = tal.find(0x14)
        if onset_end == -1:
            return tal

        onset = tal[:onset_end].decode("utf-8", errors="replace")
        annotations_start = onset_end + 1

        current_pos = annotations_start
        modifications_made = 0

        while current_pos < len(tal):
            annotation_end = tal.find(0x14, current_pos)
            if annotation_end == -1:
                break

            if annotation_end > current_pos:
                original_annotation = tal[current_pos:annotation_end].decode("utf-8", errors="replace")
                if original_annotation.strip():
                    redaction_logger.info(f"BLANKED ANNOTATION: '{original_annotation}'")
                    logger.debug(f"Blanked annotation: '{original_annotation}'")
                    modifications_made += 1

                blank_bytes = b""
                tal[current_pos:annotation_end] = blank_bytes.ljust(annotation_end - current_pos, b" ")

            current_pos = annotation_end + 1
            if current_pos < len(tal) and tal[current_pos] == 0:
                break

        logger.debug(f"Processed TAL at timestamp {onset}: {modifications_made} annotations blanked")
        return tal
    except Exception as e:
        logger.warning(f"Error processing TAL: {e}")
        logger.debug(f"TAL processing exception details: {traceback.format_exc()}")
        return tal_bytes


# --------------------------------------------------------------------------------------
# Main processing function (redact header + blank annotations + copy labels)
# --------------------------------------------------------------------------------------
def anonymize_edf_complete(
    input_path,
    output_path,
    buffer_size_mb=64,
    redaction_patterns=None,  # kept for backward compatibility; no longer required
    log_dir="",
    *,
    blank_annotations=True,
    anonymize_options=None,
    ref_edf_path=None,
    copy_signal_labels=False,
    require_strict_structure_match=True,
):
    """
    Create a processed EDF+ file:
      - optional selective header anonymization
      - optional copying of signal labels from ref EDF
      - optional blanking of EDF+ annotations

    Returns:
      bool success
    """
    start_time = time.time()

    if redaction_patterns is None:
        redaction_patterns = []

    if log_dir:
        logger = setup_logging(log_dir, filename=os.path.basename(input_path))
    else:
        logger = logging.getLogger("edf_anonymizer")
        if not logger.handlers:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    logger.info(f"Starting processing of target EDF: {input_path}")
    logger.info(f"Output will be saved to: {output_path}")
    logger.info(f"Buffer size: {buffer_size_mb} MB")
    logger.info(f"Blank annotations: {blank_annotations}")
    logger.info(f"Copy signal labels: {copy_signal_labels} (ref={ref_edf_path})")
    logger.info(f"Selective anonymize options provided: {anonymize_options is not None}")

    try:
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Input file not found: {input_path}")

        input_file_size = os.path.getsize(input_path)
        logger.info(f"Input file size: {input_file_size:,} bytes ({input_file_size / (1024*1024):.2f} MB)")

        # Read target structure (and reference if requested)
        target_struct = read_edf_structure(input_path)
        ref_struct = None

        if copy_signal_labels:
            if not ref_edf_path:
                raise ValueError("copy_signal_labels=True but ref_edf_path is not provided.")
            ref_struct = read_edf_structure(ref_edf_path)

            if require_strict_structure_match:
                if ref_struct["num_signals"] != target_struct["num_signals"]:
                    raise ValueError(
                        f"Structure mismatch: num_signals differs (ref={ref_struct['num_signals']}, target={target_struct['num_signals']})"
                    )
                if ref_struct["annot_channels"] != target_struct["annot_channels"]:
                    raise ValueError(
                        f"Structure mismatch: annotation channel indices differ (ref={ref_struct['annot_channels']}, target={target_struct['annot_channels']})"
                    )
                if ref_struct["samples_per_record"] != target_struct["samples_per_record"]:
                    raise ValueError("Structure mismatch: samples_per_record differs (channel order/layout mismatch).")

        header_bytes = target_struct["header_bytes"]
        data_records = target_struct["data_records"]
        num_signals = target_struct["num_signals"]
        signal_header_size = target_struct["signal_header_size"]
        record_size = target_struct["record_size"]
        samples_per_record = target_struct["samples_per_record"]
        annot_channels = target_struct["annot_channels"]

        logger.info(f"Header size: {header_bytes} bytes")
        logger.info(f"Data records: {data_records}")
        logger.info(f"Number of signals: {num_signals}")
        logger.info(f"Annotation channels: {annot_channels}")
        logger.info(f"Data record size: {record_size} bytes")

        # Compute annotation offsets
        annot_offsets, annot_sizes = [], []
        if blank_annotations and annot_channels:
            offset = 0
            bytes_per_sample = 2
            for i, spr in enumerate(samples_per_record):
                size = spr * bytes_per_sample
                if i in annot_channels:
                    annot_offsets.append(offset)
                    annot_sizes.append(size)
                offset += size

        # Open file using mmap for fast access
        with open(input_path, "rb") as f:
            mmapped_file = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

            # Prepare new base header
            base_header = bytearray(mmapped_file[:256])
            new_base_header = anonymize_edf_header_selective(base_header, anonymize_options)

            # Prepare new signal header (copy from target then optionally map labels)
            signal_header = bytearray(mmapped_file[256 : 256 + signal_header_size])
            if copy_signal_labels and ref_struct is not None:
                signal_header = copy_signal_labels_from_ref_to_target_signal_header(
                    ref_struct, target_struct, signal_header
                )
                logger.info("Copied non-annotation signal labels from reference EDF into target header")

            # Write output file
            logger.info(f"Creating output file: {output_path}")
            with open(output_path, "wb") as out_file:
                out_file.write(new_base_header)
                out_file.write(signal_header)

                buffer_size_bytes = buffer_size_mb * 1024 * 1024
                records_per_chunk = max(1, buffer_size_bytes // record_size)
                chunk_size_bytes = records_per_chunk * record_size

                bytes_remaining = input_file_size - (256 + signal_header_size)
                logger.info(f"Processing records in chunks: {records_per_chunk} records "
                            f"({chunk_size_bytes / (1024*1024):.2f} MB) per chunk")
                logger.info(f"Data bytes to process: {bytes_remaining:,}")

                total_records_processed = 0

                with tqdm(total=data_records, desc="Processing records", unit="records") as pbar:
                    for record_index in range(0, data_records, records_per_chunk):
                        chunk_records = min(records_per_chunk, data_records - record_index)
                        chunk_bytes = min(chunk_size_bytes, bytes_remaining)
                        if chunk_bytes <= 0:
                            break

                        data_chunk = mmapped_file[
                            256 + signal_header_size + record_index * record_size :
                            256 + signal_header_size + record_index * record_size + chunk_bytes
                        ]

                        if blank_annotations and annot_channels:
                            data_chunk = process_edf_annotations(
                                data_chunk,
                                annot_offsets=annot_offsets,
                                annot_sizes=annot_sizes,
                                record_size=record_size,
                            )

                        out_file.write(data_chunk)
                        bytes_remaining -= chunk_bytes
                        total_records_processed += chunk_records
                        pbar.update(chunk_records)

            mmapped_file.close()

        # Ensure output file size matches input
        output_file_size = os.path.getsize(output_path)
        if output_file_size != input_file_size:
            logger.warning(f"Output file size mismatch (input={input_file_size}, output={output_file_size}). Attempting to fix.")
            with open(output_path, "r+b") as fix_file:
                if output_file_size < input_file_size:
                    diff = input_file_size - output_file_size
                    fix_file.seek(0, os.SEEK_END)
                    # pad in chunks
                    chunk = 1024 * 1024
                    while diff > 0:
                        w = min(chunk, diff)
                        fix_file.write(b"\x00" * w)
                        diff -= w
                else:
                    fix_file.truncate(input_file_size)

        elapsed_time = time.time() - start_time
        logger.info(f"Processing completed in {elapsed_time:.2f} seconds")
        logger.info(f"Output EDF saved to: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Error during processing: {e}")
        logger.error(traceback.format_exc())
        return False


# --------------------------------------------------------------------------------------
# Verification (kept; requires edflibpy)
# --------------------------------------------------------------------------------------
def validate_edf_header(file_path, expected_records=None):
    logger = logging.getLogger("edf_validator")
    try:
        with open(file_path, "r+b") as f:
            f.seek(0)
            header = f.read(256)

            data_records_str = header[236:244].decode("ascii", "replace").strip()
            try:
                data_records = int(data_records_str)
                logger.info(f"Header data record count: {data_records}")

                if data_records <= 0 and expected_records is not None:
                    logger.warning(f"Invalid data record count ({data_records}), fixing to {expected_records}")
                    f.seek(236)
                    f.write(f"{expected_records:<8}".encode("ascii"))
                    return True

                return data_records > 0

            except ValueError:
                logger.error(f"Could not parse data record count: '{data_records_str}'")
                if expected_records is not None:
                    logger.warning(f"Setting data record count to {expected_records}")
                    f.seek(236)
                    f.write(f"{expected_records:<8}".encode("ascii"))
                    return True
                return False

    except Exception as e:
        logger.error(f"Error validating EDF header: {e}")
        logger.error(traceback.format_exc())
        return False


def validate_anonymized_file(input_path, output_path):
    logger = logging.getLogger("edf_validator")
    logger.info(f"Starting basic structure validation: {input_path} vs {output_path}")

    try:
        input_size = os.path.getsize(input_path)
        output_size = os.path.getsize(output_path)

        logger.info(f"Original file size: {input_size:,} bytes")
        logger.info(f"Processed file size: {output_size:,} bytes")

        if input_size != output_size:
            logger.warning(f"File size mismatch: Input={input_size}, Output={output_size}, Diff={input_size-output_size}")
            return False

        with open(input_path, "rb") as in_file, open(output_path, "rb") as out_file:
            in_header = in_file.read(256)
            out_header = out_file.read(256)

            if in_header[0:8] != out_header[0:8]:
                logger.warning("Version field mismatch")
                return False

            # Technical fields should match
            if in_header[184:256] != out_header[184:256]:
                logger.warning("Technical header fields mismatch")
                return False

        logger.info("Basic validation passed")
        return True

    except Exception as e:
        logger.error(f"Error during validation: {e}")
        logger.error(traceback.format_exc())
        return False


def verify_edf_signals(input_path, output_path):
    """
    Compare non-annotation signal data between original and processed files.
    Requires edflibpy.
    """
    if EDFreader is None:
        raise RuntimeError("edflibpy is required for verify_edf_signals but could not be imported.")

    logger = logging.getLogger("edf_verifier")
    logger.info(f"Starting detailed signal verification between:\n  - {input_path}\n  - {output_path}")

    results = {
        "total_signals": 0,
        "matching_signals": 0,
        "mismatched_signals": [],
        "error_details": None,
    }

    try:
        original_edf = EDFreader(input_path)
        anon_edf = EDFreader(output_path)

        signal_count = original_edf.getNumSignals()
        signal_labels = [original_edf.getSignalLabel(s).strip() for s in range(signal_count)]
        annot_channels = [i for i, label in enumerate(signal_labels) if label.strip() in ANNOTATION_LABELS]

        data_records = original_edf.getNumDataRecords()

        for signal_idx in range(signal_count):
            if signal_idx in annot_channels:
                continue

            signal_name = signal_labels[signal_idx]
            logger.info(f"Verifying signal: {signal_name} (index {signal_idx})")

            samples_per_record = original_edf.getSampelsPerDataRecord(signal_idx)
            total_samples = samples_per_record * data_records

            chunk_size = min(samples_per_record * 100, total_samples)

            mismatches_for_signal = []

            for offset in range(0, total_samples, chunk_size):
                actual_chunk = min(chunk_size, total_samples - offset)

                original_data = np.zeros(actual_chunk, dtype=np.float64)
                anon_data = np.zeros(actual_chunk, dtype=np.float64)

                original_edf.fseek(signal_idx, offset, original_edf.EDFSEEK_SET)
                anon_edf.fseek(signal_idx, offset, anon_edf.EDFSEEK_SET)

                samples_read_orig = original_edf.readSamples(signal_idx, original_data, actual_chunk)
                samples_read_anon = anon_edf.readSamples(signal_idx, anon_data, actual_chunk)

                if samples_read_orig != actual_chunk or samples_read_anon != actual_chunk:
                    logger.warning(f"Failed to read expected samples for signal {signal_name}")
                    continue

                if not np.array_equal(original_data, anon_data):
                    if np.allclose(original_data, anon_data, rtol=1e-10, atol=1e-10):
                        logger.info(f"Minor precision differences within tolerance for {signal_name}")
                    else:
                        diff = original_data - anon_data
                        nz = diff[diff != 0]
                        if len(nz) > 0:
                            diff_stats = {
                                "mean_diff": float(np.mean(nz)),
                                "max_diff": float(np.max(np.abs(nz))),
                                "diff_count": int(len(nz)),
                                "diff_percent": float(100 * len(nz) / len(diff)),
                                "chunk_start": int(offset),
                                "chunk_size": int(actual_chunk),
                            }
                            mismatches_for_signal.append(diff_stats)
                            if diff_stats["diff_percent"] > 1.0:
                                break

            if mismatches_for_signal:
                total_diffs = sum(m["diff_count"] for m in mismatches_for_signal)
                overall_diff_percent = 100 * total_diffs / total_samples
                results["mismatched_signals"].append(
                    {
                        "signal_name": signal_name,
                        "signal_idx": signal_idx,
                        "total_samples": total_samples,
                        "total_differences": total_diffs,
                        "diff_percent": overall_diff_percent,
                        "chunk_details": mismatches_for_signal,
                    }
                )
            else:
                results["matching_signals"] += 1

        results["total_signals"] = signal_count - len(annot_channels)

        original_edf.close()
        anon_edf.close()

        success = (results["mismatched_signals"] == [] and results["error_details"] is None)
        return success, results

    except Exception as e:
        results["error_details"] = str(e)
        logger.error(f"Error during signal verification: {e}")
        logger.error(traceback.format_exc())
        return False, results


def run_verification(input_path, output_path):
    logger = logging.getLogger("edf_verifier")
    logger.info("Starting comprehensive EDF verification...")

    structure_ok = validate_anonymized_file(input_path, output_path)
    if not structure_ok:
        logger.error("File structure validation failed")
        return False

    signals_ok, results = verify_edf_signals(input_path, output_path)

    logger.info("=== Verification Summary ===")
    if signals_ok:
        logger.info(f"Signal verification PASSED: All {results['total_signals']} signals match")
    else:
        logger.error(f"Signal verification FAILED: {len(results['mismatched_signals'])} of {results['total_signals']} signals mismatched")

    return signals_ok and structure_ok


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def build_default_output_path(target_path: str) -> str:
    p = os.path.abspath(target_path)
    folder = os.path.dirname(p)
    stem, ext = os.path.splitext(os.path.basename(p))
    return os.path.join(folder, f"{stem}__redacted__labelsFromRef{ext}")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Process EDF+ file: blank annotations, optionally anonymize header fields, optionally copy labels from reference EDF."
    )

    parser.add_argument("target_path", type=str, help="Path to the TARGET EDF file (the one you want to write a new output for).")
    parser.add_argument("--ref_path", type=str, default=None, help="Path to the REFERENCE EDF file (source of signal labels).")

    parser.add_argument("--output_path", type=str, default=None, help="Output EDF path (default: targetname__redacted__labelsFromRef.edf in same folder).")

    parser.add_argument("--buffer_size_mb", type=int, default=64, help="Buffer size in MB for chunk processing (default: 64).")

    parser.add_argument("--copy_labels", action="store_true", help="Copy non-annotation signal labels from --ref_path to target.")
    parser.add_argument("--blank_annotations", action="store_true", help="Blank all embedded EDF+ annotations in output.")
    parser.add_argument("--no_blank_annotations", action="store_true", help="Disable annotation blanking.")

    parser.add_argument("--verify", action="store_true", help="Verify signal data integrity after processing (requires edflibpy).")
    parser.add_argument("--verify_level", choices=["basic", "thorough"], default="thorough",
                        help="Verification level: basic structure vs thorough signal comparison.")

    parser.add_argument("--log_dir", type=str, default="logs", help="Directory to store log files")
    parser.add_argument("--log_level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Logging level")

    # Selective header anonymization flags
    parser.add_argument("--anonymize_patientname", action="store_true", help="Anonymize patient name (EDF+ patient field).")
    parser.add_argument("--anonymize_patientcode", action="store_true", help="Anonymize patient code (EDF+ patient field).")
    parser.add_argument("--anonymize_birthdate", action="store_true", help="Anonymize birthdate (EDF+ patient field).")
    parser.add_argument("--anonymize_gender", action="store_true", help="Anonymize gender/sex (EDF+ patient field).")

    parser.add_argument("--anonymize_recording_additional", action="store_true", help="Wipe everything after startdate in recording field.")
    parser.add_argument("--anonymize_admincode", action="store_true", help="Anonymize admincode in recording field.")
    parser.add_argument("--anonymize_technician", action="store_true", help="Anonymize technician in recording field.")
    parser.add_argument("--anonymize_equipment", action="store_true", help="Anonymize equipment in recording field.")

    parser.add_argument("--yes", action="store_true", help="Skip interactive confirmation prompt.")

    return parser.parse_args()


def _cli_print_preflight(stats: dict):
    print("\n=== Preflight: Label Similarity (excluding annotation channels) ===")
    print(f"Target: {stats['target_path']}")
    print(f"Ref   : {stats['ref_path']}")
    print(f"Signals: {stats['num_signals']} (non-annot={stats['num_non_annot']}, annot_idx={stats['annot_channels']})")
    print(f"Matches   : {stats['num_matches']}")
    print(f"Mismatches: {stats['num_mismatches']}\n")

    print("Matching channels:")
    for line in stats["matches"]:
        print("  " + line)

    if stats["mismatches"]:
        print("\nMismatching channels:")
        for line in stats["mismatches"]:
            print("  " + line)
    print("")


def main_cli():
    args = parse_arguments()

    # Setup logging
    logger = setup_logging(args.log_dir)
    log_level = getattr(logging, args.log_level)
    logger.setLevel(log_level)

    target_path = args.target_path
    ref_path = args.ref_path
    output_path = args.output_path or build_default_output_path(target_path)

    blank_annotations = True
    if args.no_blank_annotations:
        blank_annotations = False
    elif args.blank_annotations:
        blank_annotations = True  # explicit

    # Build anonymize_options only if any flag is set; otherwise keep None (legacy behavior)
    any_anon_flag = any([
        args.anonymize_patientname,
        args.anonymize_patientcode,
        args.anonymize_birthdate,
        args.anonymize_gender,
        args.anonymize_recording_additional,
        args.anonymize_admincode,
        args.anonymize_technician,
        args.anonymize_equipment,
    ])

    anonymize_options = None
    if any_anon_flag:
        anonymize_options = {
            "patientname": args.anonymize_patientname,
            "patientcode": args.anonymize_patientcode,
            "birthdate": args.anonymize_birthdate,
            "gender": args.anonymize_gender,
            "recording_additional": args.anonymize_recording_additional,
            "admincode": args.anonymize_admincode,
            "technician": args.anonymize_technician,
            "equipment": args.anonymize_equipment,
        }

    # If copying labels, do preflight + confirmation
    if args.copy_labels:
        if not ref_path:
            logger.error("--copy_labels requires --ref_path")
            print("ERROR: --copy_labels requires --ref_path")
            sys.exit(2)

        stats = compare_edf_signal_labels(ref_path, target_path, require_strict_structure_match=True)
        _cli_print_preflight(stats)

        if not args.yes:
            resp = input("Proceed with processing (and label copy)? [y/N]: ").strip().lower()
            if resp not in ("y", "yes"):
                print("Canceled.")
                sys.exit(0)

    else:
        # If ref provided, still show preflight stats (optional)
        if ref_path:
            stats = compare_edf_signal_labels(ref_path, target_path, require_strict_structure_match=True)
            _cli_print_preflight(stats)
            if not args.yes:
                resp = input("Proceed with processing (no label copy)? [y/N]: ").strip().lower()
                if resp not in ("y", "yes"):
                    print("Canceled.")
                    sys.exit(0)

    # Run processing
    logger.info("=== EDF Processing Tool ===")
    logger.info(f"Target file: {target_path}")
    logger.info(f"Ref file   : {ref_path}")
    logger.info(f"Output     : {output_path}")
    logger.info(f"Blank annotations: {blank_annotations}")
    logger.info(f"Copy labels: {args.copy_labels}")
    logger.info(f"Selective anonymize: {anonymize_options}")

    ok = anonymize_edf_complete(
        target_path,
        output_path,
        buffer_size_mb=args.buffer_size_mb,
        log_dir=args.log_dir,
        blank_annotations=blank_annotations,
        anonymize_options=anonymize_options,
        ref_edf_path=ref_path,
        copy_signal_labels=args.copy_labels,
        require_strict_structure_match=True,
    )

    if not ok:
        print("ERROR: Processing failed. Check logs for details.")
        sys.exit(1)

    print(f"OK: Wrote output: {output_path}")

    # Optional verification
    if args.verify:
        if args.verify_level == "thorough":
            v_ok = run_verification(target_path, output_path)
        else:
            v_ok = validate_anonymized_file(target_path, output_path)

        if v_ok:
            print("OK: Verification PASSED")
        else:
            print("WARNING: Verification FAILED (see logs)")


if __name__ == "__main__":
    main_cli()
