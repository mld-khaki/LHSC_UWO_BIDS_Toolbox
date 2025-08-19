#!/usr/bin/env python3
import os
import sys
import csv
import argparse
from pathlib import Path
from datetime import datetime

# --- Import your EDF reader (relative two levels up, like your GUI script) ---
current_script_dir = os.path.dirname(os.path.abspath(__file__))
two_levels_up_path = os.path.abspath(os.path.join(current_script_dir, "..", ".."))
sys.path.append(two_levels_up_path)
from _lhsc_lib.EDF_reader_mld import EDFreader  # noqa: E402


# ------------------------------- ANSI helpers -------------------------------

class Ansi:
    GREEN = "\033[92m"
    ORANGE = "\033[33m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def colorize(s: str, enabled: bool, color: str) -> str:
    return f"{color}{s}{Ansi.RESET}" if enabled else s


# ------------------------------- EDF metadata -------------------------------

def read_edf_metadata(path: Path):
    """
    Returns (size_bytes:int, start_iso:str 'YYYY-MM-DDTHH:MM:SS', duration_sec:float)
    Raises on error.
    """
    size_bytes = path.stat().st_size
    reader = EDFreader(str(path), read_annotations=False)
    try:
        start_dt = reader.getStartDateTime()  # datetime
        dur_sec = float(reader.getFileDuration())  # seconds (float)
    finally:
        reader.close()
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
    return size_bytes, start_iso, dur_sec


def edf_key(size_bytes: int, start_iso: str, dur_sec: float):
    """
    Strict equality key:
      - size in bytes
      - start time to the second (ISO string)
      - duration seconds rounded to 3 decimals (to mirror your TSV convention)
    """
    return (int(size_bytes), start_iso, f"{dur_sec:.3f}")


def edf_pass_path(edf_path: Path) -> Path:
    """
    "test.edf" -> "test.edf_pass" sidecar in the same directory.
    """
    return edf_path.with_suffix(edf_path.suffix + "_pass")


# ------------------------------- Scanning -----------------------------------

def iter_edf_files(root: Path):
    for p in root.rglob("*.edf"):
        if p.is_file():
            yield p


def scan_tree(root: Path, color_enabled: bool):
    """
    Scan a tree for EDFs and return:
      meta_by_path: {Path: (size_bytes, start_iso, dur_str3)}
      key_to_paths: {(size, start, dur3): [Path, ...]}
      errors: [(Path, error_str)]
    """
    meta_by_path, key_to_paths, errors = {}, {}, []
    for p in iter_edf_files(root):
        try:
            size_b, start_iso, dur_s = read_edf_metadata(p)
            key = edf_key(size_b, start_iso, dur_s)
            meta_by_path[p] = (size_b, start_iso, f"{dur_s:.3f}")
            key_to_paths.setdefault(key, []).append(p)
        except Exception as e:
            errors.append((p, str(e)))
    if errors:
        print(colorize(f"[!] {len(errors)} EDF read errors under {root}", color_enabled, Ansi.RED))
        for path, err in errors[:20]:
            print(colorize(f"    {path} :: {err}", color_enabled, Ansi.RED))
        if len(errors) > 20:
            print(colorize(f"    ... and {len(errors)-20} more", color_enabled, Ansi.RED))
    return meta_by_path, key_to_paths, errors


# ------------------------------- Comparison ---------------------------------

def compare_stepc_stepb(stepc_root: Path, stepb_root: Path, color_enabled: bool, csv_out: Path | None):
    print(colorize(f"\nScanning StepC (BIDS): {stepc_root}", color_enabled, Ansi.CYAN))
    c_meta, c_keys, c_errs = scan_tree(stepc_root, color_enabled)

    print(colorize(f"\nScanning StepB (raw):  {stepb_root}", color_enabled, Ansi.CYAN))
    b_meta, b_keys, b_errs = scan_tree(stepb_root, color_enabled)

    common_keys = set(c_keys.keys()) & set(b_keys.keys())

    compliant = []  # (b_path, c_path, key)
    warnings = []   # (b_path, c_path, key, reason)
    b_missing_sidecars = []  # all StepB EDFs missing .edf_pass (orphan list)

    # cache sidecar existence for all StepB EDFs
    b_sidecar_exists = {}
    for b_path in b_meta.keys():
        sidecar = edf_pass_path(b_path)
        ok = sidecar.exists()
        b_sidecar_exists[b_path] = ok
        if not ok:
            b_missing_sidecars.append(b_path)

    # Build duplicate lists
    for key in sorted(common_keys):
        b_paths = b_keys[key]
        c_paths = c_keys[key]
        for bp in b_paths:
            for cp in c_paths:
                if b_sidecar_exists.get(bp, False):
                    compliant.append((bp, cp, key))
                else:
                    warnings.append((bp, cp, key, "Missing .edf_pass sidecar"))

    # ---------- Reporting ----------
    print(colorize("\n=== DUPLICATES & COMPLIANCE ===", color_enabled, Ansi.BOLD))
    print(colorize(f"Unique duplicate keys: {len(common_keys)}", color_enabled, Ansi.BOLD))

    # Compliant section
    print(colorize(f"\n[OK] Compliant duplicates: {len(compliant)}", color_enabled, Ansi.GREEN))
    for bp, cp, key in compliant[:100]:
        size_b, start_iso, dur3 = key
        print(colorize(f"\r\n\r\n  B: {bp}", color_enabled, Ansi.GREEN))
        print(colorize(f"     C: {cp} | size={size_b}, start={start_iso}, dur={dur3}s", color_enabled, Ansi.GREEN))
    if len(compliant) > 100:
        print(colorize(f"  ... and {len(compliant)-100} more", color_enabled, Ansi.GREEN))

    # Warnings (duplicates but missing sidecar)
    print(colorize(f"\n[WARN] Duplicates missing .edf_pass: {len(warnings)}", color_enabled, Ansi.ORANGE))
    for bp, cp, key, why in warnings[:100]:
        size_b, start_iso, dur3 = key
        print(colorize(f"  B: {bp}", color_enabled, Ansi.ORANGE))
        print(colorize(f"     C: {cp} | size={size_b}, start={start_iso}, dur={dur3}s -> {why}", color_enabled, Ansi.ORANGE))
    if len(warnings) > 100:
        print(colorize(f"  ... and {len(warnings)-100} more", color_enabled, Ansi.ORANGE))

    # Orphan missing-sidecar (StepB files without duplicates but still missing sidecar)
    print(colorize(f"\n[WARN] StepB EDFs missing .edf_pass (total): {len(b_missing_sidecars)}", color_enabled, Ansi.ORANGE))
    for p in b_missing_sidecars[:100]:
        print(colorize(f"  {p}", color_enabled, Ansi.ORANGE))
    if len(b_missing_sidecars) > 100:
        print(colorize(f"  ... and {len(b_missing_sidecars)-100} more", color_enabled, Ansi.ORANGE))

    # Summary
    print(colorize("\n=== SUMMARY ===", color_enabled, Ansi.BOLD))
    print(f"StepC EDFs read: {len(c_meta)}  (errors: {len(c_errs)})")
    print(f"StepB EDFs read: {len(b_meta)}  (errors: {len(b_errs)})")
    print(f"Duplicate keys: {len(common_keys)}")
    print(f"Compliant duplicates: {len(compliant)}")
    print(f"Warning duplicates (missing sidecar): {len(warnings)}")
    print(f"StepB EDFs missing sidecar (total): {len(b_missing_sidecars)}")

    # Optional CSV
    if csv_out:
        write_csv_report(csv_out, compliant, warnings, b_missing_sidecars)
        print(colorize(f"\nCSV report written to: {csv_out}", color_enabled, Ansi.CYAN))


def write_csv_report(csv_path: Path, compliant, warnings, orphans):
    """
    CSV columns:
      status, stepb_path, stepc_path, size_bytes, start_iso, duration_sec_3dp, note
      - 'compliant' rows include both paths
      - 'warning_dup' rows include both paths + note
      - 'warning_no_sidecar' rows include only stepb_path
    """
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["status", "stepb_path", "stepc_path", "size_bytes", "start_iso", "duration_sec_3dp", "note"])
        for bp, cp, key in compliant:
            size_b, start_iso, dur3 = key
            w.writerow(["compliant", str(bp), str(cp), size_b, start_iso, dur3, ""])
        for bp, cp, key, why in warnings:
            size_b, start_iso, dur3 = key
            w.writerow(["warning_dup", str(bp), str(cp), size_b, start_iso, dur3, why])
        for bp in orphans:
            w.writerow(["warning_no_sidecar", str(bp), "", "", "", "", "missing .edf_pass"])


# --------------------------------- CLI --------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=(
            "Compare StepC (BIDS) vs StepB (raw EDFs) and report duplicates.\n"
            "Duplicate = same size, same start time (sec), same duration (sec, 3dp).\n"
            "A duplicate is 'compliant to remove' if the StepB file has a .edf_pass sidecar."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    ap.add_argument("--stepc", required=True, help="Path to StepC (BIDS) subject root (contains ses-XXX folders).")
    ap.add_argument("--stepb", required=True, help="Path to StepB raw EDF root (will be scanned recursively).")
    ap.add_argument("--csv", help="Optional CSV report output path.")
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI colors in console output.")
    args = ap.parse_args()

    stepc = Path(args.stepc).resolve()
    stepb = Path(args.stepb).resolve()
    if not stepc.is_dir():
        print(f"ERROR: StepC path not found or not a directory: {stepc}")
        sys.exit(2)
    if not stepb.is_dir():
        print(f"ERROR: StepB path not found or not a directory: {stepb}")
        sys.exit(2)

    color_enabled = not args.no_color and sys.stdout.isatty()
    t0 = datetime.now()
    compare_stepc_stepb(stepc, stepb, color_enabled, Path(args.csv).resolve() if args.csv else None)
    dt = (datetime.now() - t0).total_seconds()
    print(f"\nDone in {dt:.2f}s.")


if __name__ == "__main__":
    main()
