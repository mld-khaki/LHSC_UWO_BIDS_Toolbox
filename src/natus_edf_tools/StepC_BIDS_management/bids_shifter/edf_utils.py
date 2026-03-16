# -*- coding: utf-8 -*-
"""
EDF file utilities for BIDS Shifter GUI.
Handles EDF file reading and metadata extraction.
"""

import os
import sys
import glob
import csv
from .config import EXCEPTION_DEBUG, DEFAULT_TSV_COLUMNS
from .utils import iso_fmt_T, log_line, is_zipped_edf


# Try to import EDFreader from various locations
_EDFreader = None
_import_error_msg = None

def _init_edfreader():
    """Initialize EDFreader on first use."""
    global _EDFreader, _import_error_msg
    
    if _EDFreader is not None:
        return _EDFreader
    
    # Try multiple import strategies
    import_attempts = []
    
    # Strategy 1: Direct import (if edfreader_mld2.py is in Python path)
    try:
        from edfreader_mld2 import EDFreader
        _EDFreader = EDFreader
        return _EDFreader
    except ImportError as e:
        import_attempts.append(f"Direct import: {e}")
    
    # Strategy 2: Import from parent directory (common case)
    try:
        # Add parent directory to path temporarily
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        
        from edfreader_mld2 import EDFreader
        _EDFreader = EDFreader
        return _EDFreader
    except ImportError as e:
        import_attempts.append(f"Parent dir import: {e}")
    
    # Strategy 3: Try common_libs path (legacy)
    try:
        from common_libs.edflib_fork_mld.edfreader_mld2 import EDFreader
        _EDFreader = EDFreader
        return _EDFreader
    except ImportError as e:
        import_attempts.append(f"common_libs import: {e}")
    
    # All strategies failed
    _EDFreader = False
    _import_error_msg = "\n".join(import_attempts)
    return _EDFreader


def is_edfreader_available():
    """Check if EDFreader is available."""
    reader = _init_edfreader()
    return reader is not False and reader is not None


def get_edfreader_error():
    """Get the error message if EDFreader import failed."""
    global _import_error_msg
    _init_edfreader()  # Ensure we've tried to import
    return _import_error_msg


def read_edf_metadata(filepath, log_path=None):
    """
    Read metadata from an EDF file.
    
    Args:
        filepath: Path to EDF file
        log_path: Optional log file path
    
    Returns:
        Dict with:
            - acq_time: ISO formatted acquisition time
            - duration: Duration in hours (3 decimal places)
            - edf_type: EDF type string
        Or None if reading failed
    """
    EDFreader = _init_edfreader()
    
    if not EDFreader:
        log_line(log_path, f"ERROR: EDFreader not available. {_import_error_msg}")
        return None
    
    try:
        reader = EDFreader(filepath, read_annotations=False)
        start_dt = reader.getStartDateTime()
        dur_sec = reader.getFileDuration()
        reader.close()
        
        acq_time = iso_fmt_T(start_dt)
        dur_hours = float(dur_sec) / (3600.0 * 1e7)
        
        return {
            "acq_time": acq_time,
            "duration": f"{dur_hours:.3f}",
            "edf_type": "EDF+C"
        }
    
    except Exception as e:
        log_line(log_path, f"ERROR reading EDF {filepath}: {e}")
        if EXCEPTION_DEBUG:
            raise e
        return None


# ---------------------------------------------------------------------------
# Session-level TSV helpers (used for zipped EDF metadata lookup)
# ---------------------------------------------------------------------------

def find_session_tsv(session_path):
    """
    Find the per-session scans TSV inside a session folder.

    Looks for a file matching ``*_scans.tsv`` directly inside
    ``session_path`` (e.g. ``ses-001/sub-167_ses-001_scans.tsv``).

    Args:
        session_path: Full path to the session folder (e.g. /data/sub-167/ses-001)

    Returns:
        Full path to the TSV file, or None if not found.
    """
    if not session_path or not os.path.isdir(session_path):
        return None
    candidates = glob.glob(os.path.join(session_path, "*_scans.tsv"))
    return candidates[0] if candidates else None


def read_metadata_from_session_tsv(session_tsv_path, rel_path):
    """
    Look up metadata for a specific file in a session-level scans TSV.

    Matching is attempted first on the full relative path stored in the
    ``filename`` column, then on the bare basename only, to accommodate
    minor path-format differences.

    Args:
        session_tsv_path: Full path to the ``*_scans.tsv`` file.
        rel_path: Relative path of the archive as it will appear in the
                  subject-level TSV (e.g. ``ses-001/ieeg/sub-167_ses-001_ieeg.edf.zip``).

    Returns:
        Dict of all columns from the matching row, or None if not found.
    """
    if not session_tsv_path or not os.path.exists(session_tsv_path):
        return None

    target_basename = os.path.basename(rel_path)

    try:
        with open(session_tsv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                fn = row.get("filename", "")
                # Full relative path match (preferred)
                if fn == rel_path:
                    return dict(row)
                # Basename-only fallback
                if os.path.basename(fn) == target_basename:
                    return dict(row)
    except Exception as e:
        log_line(None, f"ERROR reading session TSV {session_tsv_path}: {e}")
        if EXCEPTION_DEBUG:
            raise e

    return None


# ---------------------------------------------------------------------------
# Session TSV generation from subject-level TSV
# ---------------------------------------------------------------------------

def _write_session_tsv(path, header, rows):
    """
    Write rows to a new session-level TSV file.

    Args:
        path  : Full destination path for the TSV.
        header: List of column names (fieldnames).
        rows  : List of row dicts to write.
    """
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=header, delimiter="\t",
            lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _check_session_tsv_match(ses_tsv_path, subject_rows, log_path=None):
    """
    Compare an existing session TSV against the expected rows from the
    subject-level TSV.

    Comparison is order-insensitive and uses a (filename, acq_time, duration)
    key so that irrelevant extra columns do not cause false mismatches.

    Args:
        ses_tsv_path : Full path to the existing session TSV.
        subject_rows : List of row dicts for this session from the subject TSV.
        log_path     : Optional log file path.

    Returns:
        None if the files agree, or a human-readable error string if they differ.
    """
    try:
        with open(ses_tsv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            ses_rows = list(reader)
    except Exception as e:
        return f"Could not read existing session TSV: {e}"

    def row_key(r):
        return (
            r.get("filename", "").strip(),
            r.get("acq_time", "").strip(),
            r.get("duration", "").strip(),
        )

    subject_keys = {row_key(r) for r in subject_rows}
    session_keys = {row_key(r) for r in ses_rows}

    only_in_subject = subject_keys - session_keys
    only_in_session = session_keys - subject_keys

    if only_in_subject or only_in_session:
        parts = []
        if only_in_subject:
            parts.append(
                f"{len(only_in_subject)} row(s) present in subject TSV but missing from session TSV"
            )
        if only_in_session:
            parts.append(
                f"{len(only_in_session)} row(s) present in session TSV but not in subject TSV"
            )
        return "; ".join(parts)

    return None


def generate_session_tsvs_from_subject_tsv(root_dir, subject_tsv_path, log_path=None):
    """
    Generate per-session scans TSV files from the subject-level scans TSV.

    For every session folder that contains at least one zipped EDF archive,
    this function splits the relevant rows out of the subject-level TSV and
    writes a session-level ``sub-###_ses-###_scans.tsv`` file inside the
    session folder -- but only if that file does not already exist.

    If a session TSV already exists, its rows are compared against the
    subject-level TSV using a (filename, acq_time, duration) key.  Any
    discrepancy is treated as a blocking error: the file is NOT overwritten,
    the mismatch is logged, and the error is returned to the caller so the
    GUI can alert the user before proceeding.

    Rows that are present in the subject TSV but have no corresponding entry
    (i.e. the archive is listed in the subject TSV but the row is absent)
    produce a WARNING only -- they do not block the operation.

    Args:
        root_dir          : Subject root directory (e.g. ``/data/sub-167``).
        subject_tsv_path  : Path to the subject-level ``sub-###_scans.tsv``.
        log_path          : Optional log file path.

    Returns:
        Tuple of ``(success, generated, errors)`` where:
            - ``success``   : False if any mismatch errors were found.
            - ``generated`` : List of session TSV paths that were newly created.
            - ``errors``    : List of human-readable blocking error strings.
    """
    from .utils import extract_session_from_filename

    generated = []
    errors = []

    if not subject_tsv_path or not os.path.exists(subject_tsv_path):
        log_line(log_path,
                 "WARNING: Subject-level TSV not found -- cannot generate session TSVs")
        return True, generated, errors

    # Derive subject name from root_dir for the session TSV filename
    subject_name = os.path.basename(os.path.normpath(root_dir))

    # Read subject TSV
    try:
        with open(subject_tsv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            header = list(reader.fieldnames) if reader.fieldnames else list(DEFAULT_TSV_COLUMNS)
            all_rows = list(reader)
    except Exception as e:
        msg = f"WARNING: Could not read subject TSV ({subject_tsv_path}): {e}"
        log_line(log_path, msg)
        # Non-blocking: return True so scanning can still continue
        return True, generated, errors

    if not all_rows:
        log_line(log_path, "WARNING: Subject TSV is empty -- no session TSVs will be generated")
        return True, generated, errors

    # Group rows by session using the first path segment of the filename column
    session_rows = {}
    for row in all_rows:
        ses = extract_session_from_filename(row.get("filename", ""))
        if ses:
            session_rows.setdefault(ses, []).append(row)
        # Rows with no recognisable session are silently ignored here

    log_line(log_path,
             f"Subject TSV contains {len(all_rows)} rows across "
             f"{len(session_rows)} session(s)")

    for ses, rows in sorted(session_rows.items()):
        session_path = os.path.join(root_dir, ses)

        if not os.path.isdir(session_path):
            log_line(log_path, f"  Skipping {ses}: folder not found on disk")
            continue

        # Only act on sessions that actually contain zipped EDFs
        has_zipped = False
        for dirpath, _dirs, files in os.walk(session_path):
            if any(is_zipped_edf(f) for f in files):
                has_zipped = True
                break

        if not has_zipped:
            log_line(log_path, f"  Skipping {ses}: no zipped EDF files found")
            continue

        ses_tsv_name = f"{subject_name}_{ses}_scans.tsv"
        ses_tsv_path = os.path.join(session_path, ses_tsv_name)

        if os.path.exists(ses_tsv_path):
            # --- Existing session TSV: validate it matches the subject TSV ---
            mismatch = _check_session_tsv_match(ses_tsv_path, rows, log_path)
            if mismatch:
                msg = (
                    f"Session TSV mismatch for {ses} -- {mismatch}. "
                    f"File: {ses_tsv_path}"
                )
                log_line(log_path, f"ERROR: {msg}")
                errors.append(msg)
            else:
                log_line(log_path,
                         f"  {ses}: existing session TSV matches subject TSV ({len(rows)} rows) -- OK")

        else:
            # --- No session TSV: generate it from the subject TSV rows ---
            try:
                _write_session_tsv(ses_tsv_path, header, rows)
                log_line(log_path,
                         f"  {ses}: generated session TSV -- {ses_tsv_name} ({len(rows)} rows)")
                generated.append(ses_tsv_path)
            except Exception as e:
                # Write failure is a warning, not a blocking error
                log_line(log_path,
                         f"  WARNING: Could not write session TSV {ses_tsv_path}: {e}")

    if generated or errors:
        log_line(
            log_path,
            f"Session TSV generation summary: "
            f"{len(generated)} created, {len(errors)} mismatch error(s)"
        )

    return len(errors) == 0, generated, errors


def generate_tsv_records(root_dir, log_path=None, subject_tsv_path=None):
    """
    Generate TSV records from all EDF files (plain or zipped) in a directory.

    If ``subject_tsv_path`` is provided, ``generate_session_tsvs_from_subject_tsv``
    is called first.  If that step finds a mismatch between an existing session
    TSV and the subject TSV, this function returns immediately with an empty
    records list and the blocking errors so the caller (GUI layer) can alert
    the user without proceeding.

    For plain ``.edf`` files metadata is read directly via EDFreader.
    For zipped EDF archives (``.edf.zip``, ``.edf.rar``, ``.edf.7z``,
    ``.edf.gz``) the function looks up the matching session-level TSV first.
    If no TSV or no matching row is found, the record is flagged with
    ``metadata_source="manual_required"`` for the GUI to handle.

    Args:
        root_dir          : Root subject directory (e.g. ``/data/sub-167``).
        log_path          : Optional log file path.
        subject_tsv_path  : Optional path to the subject-level scans TSV.
                            When supplied, per-session TSVs are auto-generated
                            for sessions that contain zipped EDFs and do not
                            yet have one.

    Returns:
        Tuple of ``(records, errors)`` where:
            - ``records`` : List of dicts (empty if blocking errors occurred).
                            Each dict contains:
                            - ``filename``       : relative path (forward slashes)
                            - ``acq_time``       : ISO-8601 string, or ``""``
                            - ``duration``       : hours as 3 d.p. string, or ``""``
                            - ``edf_type``       : EDF type string
                            - ``metadata_source``: ``"edf"`` | ``"session_tsv"``
                                                   | ``"manual_required"``
                            Sorted by ``acq_time`` (empty strings sort first).
            - ``errors``  : List of human-readable blocking error strings.
                            Empty list means no errors.

    Note:
        **Breaking change**: now returns a ``(records, errors)`` tuple instead
        of a plain list, and ``records`` items are dicts instead of 4-tuples.
        Update all GUI callers accordingly.
    """
    records = []
    errors = []
    n_plain = 0
    n_archive_tsv = 0
    n_manual = 0

    # ------------------------------------------------------------------
    # Step 1: auto-generate per-session TSVs from subject TSV if needed
    # ------------------------------------------------------------------
    if subject_tsv_path:
        ok, generated, gen_errors = generate_session_tsvs_from_subject_tsv(
            root_dir, subject_tsv_path, log_path
        )
        if not ok:
            # Mismatch errors are blocking -- do not proceed with scanning
            return [], gen_errors

    # ------------------------------------------------------------------
    # Step 2: scan for EDFs
    # ------------------------------------------------------------------
    if not is_edfreader_available():
        log_line(log_path, "WARNING: EDFreader not available -- plain EDF metadata cannot be read")
        log_line(log_path, f"  Import errors: {_import_error_msg}")

    for root, dirs, files in os.walk(root_dir):
        for fn in files:
            lower_fn = fn.lower()

            is_plain = lower_fn.endswith(".edf") and not is_zipped_edf(fn)
            is_archive = is_zipped_edf(fn)

            if not is_plain and not is_archive:
                continue

            full_path = os.path.join(root, fn)
            rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")

            # ------------------------------------------------------------------
            # Plain EDF -- read metadata directly
            # ------------------------------------------------------------------
            if is_plain:
                if not is_edfreader_available():
                    log_line(log_path, f"  SKIPPED (no EDFreader): {rel_path}")
                    continue

                metadata = read_edf_metadata(full_path, log_path)
                if metadata:
                    records.append({
                        "filename": rel_path,
                        "acq_time": metadata["acq_time"],
                        "duration": metadata["duration"],
                        "edf_type": metadata["edf_type"],
                        "metadata_source": "edf",
                    })
                    n_plain += 1

            # ------------------------------------------------------------------
            # Zipped EDF -- look up session-level TSV, else flag manual input
            # ------------------------------------------------------------------
            elif is_archive:
                ses_segment = rel_path.split("/")[0]
                session_path = os.path.join(root_dir, ses_segment)
                session_tsv = find_session_tsv(session_path)

                metadata_row = None
                if session_tsv:
                    metadata_row = read_metadata_from_session_tsv(session_tsv, rel_path)

                if metadata_row:
                    record = {
                        "filename": rel_path,
                        "acq_time": metadata_row.get("acq_time", ""),
                        "duration": metadata_row.get("duration", ""),
                        "edf_type": metadata_row.get("edf_type", "EDF+C"),
                        "metadata_source": "session_tsv",
                    }
                    # Carry through any extra columns present in the session TSV
                    for k, v in metadata_row.items():
                        if k not in record:
                            record[k] = v
                    records.append(record)
                    log_line(log_path, f"  Metadata from session TSV: {rel_path}")
                    n_archive_tsv += 1

                else:
                    records.append({
                        "filename": rel_path,
                        "acq_time": "",
                        "duration": "",
                        "edf_type": "EDF+C",
                        "metadata_source": "manual_required",
                    })
                    if not session_tsv:
                        log_line(log_path, f"  No session TSV found for: {rel_path}")
                    else:
                        log_line(log_path, f"  No matching row in session TSV for: {rel_path}")
                    n_manual += 1

    # Sort by acquisition time; empty strings sort before dated records
    records.sort(key=lambda r: r.get("acq_time", "") or "")

    log_line(
        log_path,
        f"Generated {len(records)} TSV records "
        f"({n_plain} plain EDF, {n_archive_tsv} from session TSV, "
        f"{n_manual} need manual input)"
    )

    return records, errors
