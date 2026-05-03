# -*- coding: utf-8 -*-
"""
remediate_annotation_phi.py
----------------------------
Batch remediation tool for EDF/BDF files inside .rar archives where the
EDF Annotations channel was not properly blanked during anonymization.

Reads the JSON output from EDF_Anonymization_Verifier and re-processes
all FAIL entries by:
  1. Extracting the full EDF from the .rar archive to a temp directory
  2. Blanking annotation segments in-place using _blank_tal_annotations()
  3. Repacking the fixed EDF back into a new .rar (replacing the original)
  4. Verifying the repacked file passes the anonymization check

Usage:
    python remediate_annotation_phi.py results.json
    python remediate_annotation_phi.py results.json --dry-run
    python remediate_annotation_phi.py results.json --log-dir C:/logs --backup-dir C:/backups
    python remediate_annotation_phi.py results.json --rar-tool "C:/Program Files/WinRAR/WinRAR.exe"

Notes:
  - A .rar backup of each original archive is written to --backup-dir before
    any modification (default: a "_phi_remediation_backups" sibling folder).
  - The script is safe to re-run; already-clean files are skipped.
  - Requires WinRAR or the "rar" CLI for repacking.
    For extraction, rarfile (pip install rarfile) or unrar/WinRAR on PATH is used.

Author: Dr. Milad Khaki (LHSC / Western University)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Resolve imports -- support both running from repo root and from this folder
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_SRC  = _HERE.parents[2]   # BIDS_Verification -> StepC_BIDS_management -> natus_edf_tools -> src
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from common_libs.anonymization.edf_anonymizer import (
        parse_edf_structure,
        verify_edf_anonymized,
        _blank_tal_annotations,          # internal helper -- intentional import
    )
except ImportError as exc:
    sys.exit(
        f"[ERROR] Cannot import edf_anonymizer: {exc}\n"
        f"  Make sure '{_SRC}' is on PYTHONPATH."
    )


# =============================================================================
#  Constants
# =============================================================================

_WINRAR_CANDIDATES = [
    r"C:\Program Files\WinRAR\WinRAR.exe",
    r"C:\Program Files\WinRAR\rar.exe",
    r"C:\Program Files (x86)\WinRAR\WinRAR.exe",
    r"C:\Program Files (x86)\WinRAR\rar.exe",
    "rar",
    "WinRAR",
]

_UNRAR_CANDIDATES = [
    r"C:\Program Files\WinRAR\UnRAR.exe",
    r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
    "unrar",
    "UnRAR",
] + _WINRAR_CANDIDATES


# =============================================================================
#  Logging
# =============================================================================

def _setup_logger(log_dir: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger("remediate_annotation_phi")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(ch)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(log_dir, f"remediate_{ts}.log")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
        logger.addHandler(fh)
        logger.info(f"Log file: {log_path}")

    return logger


# =============================================================================
#  Result dataclass
# =============================================================================

@dataclass
class RemediationResult:
    path: str
    status: str          # "dry_run" | "ok" | "failed" | "skipped"
    message: str = ""
    elapsed_s: float = 0.0


# =============================================================================
#  Tool discovery
# =============================================================================

def _find_tool(candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if not c:
            continue
        if os.path.isfile(c):
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


def _subprocess_kw() -> dict:
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kw


# =============================================================================
#  RAR extraction
# =============================================================================

def extract_edf_from_rar(
    rar_path: str,
    dest_dir: str,
    unrar_tool: Optional[str] = None,
) -> str:
    """
    Extract the single EDF/BDF from *rar_path* into *dest_dir*.
    Returns the path to the extracted EDF file.
    """
    tool = _find_tool(([unrar_tool] if unrar_tool else []) + _UNRAR_CANDIDATES)

    # Strategy 1: CLI (unrar / WinRAR)
    if tool:
        res = subprocess.run(
            [tool, "e", "-inul", "-y", rar_path, dest_dir],
            capture_output=True, timeout=300,
            **_subprocess_kw()
        )
        # find the extracted file even if return code is non-zero (unrar can warn)
        for fn in os.listdir(dest_dir):
            if Path(fn).suffix.lower() in (".edf", ".bdf"):
                return os.path.join(dest_dir, fn)

    # Strategy 2: rarfile package
    try:
        import rarfile
        with rarfile.RarFile(rar_path) as rf:
            members = [m for m in rf.namelist()
                       if Path(m).suffix.lower() in (".edf", ".bdf")]
            if not members:
                raise RuntimeError(f"No EDF/BDF found inside {rar_path}")
            rf.extract(members[0], dest_dir)
            candidate = os.path.join(dest_dir, Path(members[0]).name)
            if os.path.exists(candidate):
                return candidate
            # Walk in case rarfile created subdirs
            for root, _, files in os.walk(dest_dir):
                for fn in files:
                    if Path(fn).suffix.lower() in (".edf", ".bdf"):
                        return os.path.join(root, fn)
    except ImportError:
        pass

    raise RuntimeError(
        f"Could not extract EDF from {rar_path}.\n"
        "Install WinRAR/unrar on PATH, or: pip install rarfile"
    )


# =============================================================================
#  RAR repacking
# =============================================================================

def repack_edf_into_rar(
    edf_path: str,
    output_rar: str,
    rar_tool: Optional[str] = None,
) -> None:
    """Create a new RAR archive at *output_rar* containing *edf_path*."""
    tool = _find_tool(([rar_tool] if rar_tool else []) + _WINRAR_CANDIDATES)
    if not tool:
        raise RuntimeError(
            "No RAR creation tool found.\n"
            "Install WinRAR and ensure WinRAR.exe or rar.exe is on PATH,\n"
            "or pass --rar-tool <path>."
        )

    edf_dir  = os.path.dirname(os.path.abspath(edf_path))
    edf_name = os.path.basename(edf_path)
    out_abs  = os.path.abspath(output_rar)

    if os.path.exists(out_abs):
        os.remove(out_abs)

    res = subprocess.run(
        [tool, "a", "-ep", "-inul", out_abs, edf_name],
        cwd=edf_dir,
        capture_output=True,
        timeout=300,
        **_subprocess_kw()
    )
    if res.returncode not in (0, 1):
        stderr = res.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"RAR creation failed (exit {res.returncode}): {stderr}")
    if not os.path.exists(out_abs):
        raise RuntimeError(f"RAR tool ran but output not found: {out_abs}")


# =============================================================================
#  Core: blank annotation segments in-place
# =============================================================================

def blank_annotations_inplace(edf_path: str, logger: logging.Logger) -> int:
    """
    Open *edf_path* in read-write mode and blank all TAL annotation text across
    every data record. Returns the number of records processed.
    """
    st = parse_edf_structure(edf_path, logger=logger)
    annot_segs = st.annotation_segments()

    if not annot_segs:
        logger.debug("  No annotation channels found -- nothing to blank.")
        return 0

    record_bytes = st.record_bytes
    if record_bytes <= 0:
        raise ValueError(f"record_bytes <= 0 for {edf_path}")

    count = 0
    with open(edf_path, "r+b") as f:
        f.seek(st.header_bytes)
        while True:
            rec_start = f.tell()
            chunk = f.read(record_bytes)
            if not chunk:
                break
            if len(chunk) != record_bytes:
                logger.warning(f"  Partial record at end ({len(chunk)}/{record_bytes} bytes) -- skipping.")
                break

            b = bytearray(chunk)
            for off, sz in annot_segs:
                if sz > 0 and off + sz <= len(b):
                    _blank_tal_annotations(b, off, sz)

            f.seek(rec_start)
            f.write(bytes(b))
            count += 1

    return count


# =============================================================================
#  Verify a RAR-wrapped EDF
# =============================================================================

def verify_rar(
    rar_path: str,
    unrar_tool: Optional[str],
    logger: logging.Logger,
) -> bool:
    """Extract the EDF from the RAR and run verify_edf_anonymized on it."""
    with tempfile.TemporaryDirectory(prefix="_phi_verify_") as tmpd:
        try:
            edf = extract_edf_from_rar(rar_path, tmpd, unrar_tool)
        except Exception as e:
            logger.error(f"  Verify-extract failed: {e}")
            return False

        result = verify_edf_anonymized(edf, require_blank_annotations=True)

    ok = (
        result.get("header_ok") is True
        and result.get("annotations_blank_ok") is True
    )
    if not ok:
        logger.debug(
            f"  Verify: header_ok={result.get('header_ok')} "
            f"annotations_blank_ok={result.get('annotations_blank_ok')} "
            f"n_records_with_phi={result.get('n_records_with_phi')} "
            f"non_blank_bytes={result.get('non_blank_byte_count')}"
        )
    return ok


# =============================================================================
#  Single-file remediation
# =============================================================================

def remediate_one(
    rar_path: str,
    *,
    backup_dir: Optional[str],
    rar_tool: Optional[str],
    unrar_tool: Optional[str],
    dry_run: bool,
    logger: logging.Logger,
) -> RemediationResult:
    t0 = time.perf_counter()

    # Dry-run: report intent without touching anything
    if dry_run:
        exists = os.path.exists(rar_path)
        note = "(file present)" if exists else "(WARNING: file not found on disk)"
        return RemediationResult(
            path=rar_path, status="dry_run",
            message=f"Would remediate {note}",
            elapsed_s=time.perf_counter() - t0,
        )

    if not os.path.exists(rar_path):
        return RemediationResult(
            path=rar_path, status="failed",
            message="File not found on disk",
            elapsed_s=time.perf_counter() - t0,
        )

    with tempfile.TemporaryDirectory(prefix="_phi_remed_") as tmpd:
        try:
            # 1. Extract
            logger.debug("  Extracting EDF from RAR ...")
            edf_path = extract_edf_from_rar(rar_path, tmpd, unrar_tool)
            logger.debug(f"  Extracted: {os.path.basename(edf_path)}")

            # 2. Blank annotation segments in-place
            logger.debug("  Blanking annotation segments ...")
            n_records = blank_annotations_inplace(edf_path, logger)
            logger.debug(f"  Records processed: {n_records}")

            # 3. Pre-repack sanity check
            pre = verify_edf_anonymized(edf_path, require_blank_annotations=True)
            if pre.get("annotations_blank_ok") is not True:
                return RemediationResult(
                    path=rar_path, status="failed",
                    message=(
                        f"Blanking incomplete (non_blank_byte_count="
                        f"{pre.get('non_blank_byte_count')}). File unchanged."
                    ),
                    elapsed_s=time.perf_counter() - t0,
                )

            # 4. Backup original
            if backup_dir:
                os.makedirs(backup_dir, exist_ok=True)
                parts = Path(rar_path).parts
                safe_name = "__".join(parts[-3:]).replace("\\", "_").replace("/", "_")
                shutil.copy2(rar_path, os.path.join(backup_dir, safe_name))
                logger.debug(f"  Backup saved.")

            # 5. Repack
            new_rar = os.path.join(tmpd, "fixed.rar")
            logger.debug("  Repacking ...")
            repack_edf_into_rar(edf_path, new_rar, rar_tool)

            # 6. Replace original
            shutil.move(new_rar, rar_path)
            logger.debug("  Original replaced.")

        except Exception as e:
            return RemediationResult(
                path=rar_path, status="failed",
                message=str(e),
                elapsed_s=time.perf_counter() - t0,
            )

    # 7. Post-replace verification (re-extracts from the final file on disk)
    if verify_rar(rar_path, unrar_tool, logger):
        return RemediationResult(
            path=rar_path, status="ok",
            message=f"Annotations blanked and verified ({n_records} records)",
            elapsed_s=time.perf_counter() - t0,
        )
    return RemediationResult(
        path=rar_path, status="failed",
        message="Post-repack verification failed. Backup retained if --backup-dir was set.",
        elapsed_s=time.perf_counter() - t0,
    )


# =============================================================================
#  Main
# =============================================================================

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Remediate annotation PHI in EDF/.rar files flagged by the verifier.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("json_path",
                    help="Path to the EDF_Anonymization_Verifier JSON results file.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be done without modifying any files.")
    ap.add_argument("--log-dir", default=None,
                    help="Directory for log file output.")
    ap.add_argument("--backup-dir", default=None,
                    help="Directory for RAR backups before modification. "
                         "Defaults to '_phi_remediation_backups' next to the JSON.")
    ap.add_argument("--rar-tool", default=None,
                    help="Path to WinRAR/rar executable for repacking.")
    ap.add_argument("--unrar-tool", default=None,
                    help="Path to UnRAR/unrar executable for extraction.")
    ap.add_argument("--no-backup", action="store_true",
                    help="Skip backup step (not recommended).")

    args = ap.parse_args(argv)
    logger = _setup_logger(args.log_dir)

    # Load JSON
    json_path = os.path.abspath(args.json_path)
    if not os.path.exists(json_path):
        logger.error(f"JSON file not found: {json_path}")
        return 1

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    results = data.get("results", [])
    fail_rars = [
        r for r in results
        if r.get("status") == "FAIL" and r.get("type", "").lower() == "rar"
    ]

    if not fail_rars:
        logger.info("No FAIL RAR entries in JSON -- nothing to do.")
        return 0

    logger.info(f"Found {len(fail_rars)} FAIL RAR file(s) to remediate.")
    if args.dry_run:
        logger.info("DRY-RUN mode: no files will be modified.")

    # Backup dir
    backup_dir: Optional[str] = None
    if not args.no_backup and not args.dry_run:
        backup_dir = args.backup_dir or os.path.join(
            os.path.dirname(json_path), "_phi_remediation_backups"
        )
        logger.info(f"Backups -> {backup_dir}")

    # Tool discovery
    rar_tool   = _find_tool(([args.rar_tool]   if args.rar_tool   else []) + _WINRAR_CANDIDATES)
    unrar_tool = _find_tool(([args.unrar_tool] if args.unrar_tool else []) + _UNRAR_CANDIDATES)

    if not args.dry_run:
        if not rar_tool:
            logger.error(
                "No RAR creation tool found. Install WinRAR or 'rar', "
                "or pass --rar-tool <path>."
            )
            return 1
        logger.info(f"RAR tool  : {rar_tool}")
        logger.info(f"Unrar tool: {unrar_tool or '(rarfile package fallback)'}")

    # Process files
    remediation_results: List[RemediationResult] = []
    n = len(fail_rars)
    icons: Dict[str, str] = {"ok": "v", "failed": "x", "dry_run": "~", "skipped": "-"}

    for i, entry in enumerate(fail_rars, 1):
        rar_path = entry["path"]
        logger.info(f"[{i}/{n}] {Path(rar_path).name}")
        result = remediate_one(
            rar_path,
            backup_dir=backup_dir,
            rar_tool=rar_tool,
            unrar_tool=unrar_tool,
            dry_run=args.dry_run,
            logger=logger,
        )
        remediation_results.append(result)
        icon = icons.get(result.status, "?")
        logger.info(f"  [{icon}] {result.status.upper()} -- {result.message} ({result.elapsed_s:.1f}s)")

    # Summary
    counts: Dict[str, int] = {}
    for r in remediation_results:
        counts[r.status] = counts.get(r.status, 0) + 1

    logger.info("")
    logger.info("=" * 58)
    logger.info("REMEDIATION SUMMARY")
    logger.info("=" * 58)
    for status, count in sorted(counts.items()):
        logger.info(f"  {status.upper():12s}: {count}")
    logger.info(f"  {'TOTAL':12s}: {n}")

    failed = [r for r in remediation_results if r.status == "failed"]
    if failed:
        logger.info("")
        logger.info("Failed files:")
        for r in failed:
            logger.info(f"  {r.path}")
            logger.info(f"    -> {r.message}")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
