import os
import time
import re
from EDF_Compatibility_Check_Tool import check_edf_compatibility

EDFBROWSER_PATH = r"c:\_Code\S22_GitHub\EDFbrowser_CompatChecker\edfbrowser.exe"  # UPDATE this path
MAIN_FOLDER = "k:/_pipeline/"  # UPDATE this path

SCAN_INTERVAL_SEC = 10
SUBDIR_RE = re.compile(r"sub-\d+", re.IGNORECASE)

def is_file_locked(filepath: str) -> bool:
    """
    Try an atomic rename out and back. Avoid lowercasing paths (can be problematic on Windows shares).
    """
    base, ext = os.path.splitext(filepath)
    tmp = f"{base}.__lockcheck__{ext}"
    try:
        # rename out, then back
        os.replace(filepath, tmp)
        os.replace(tmp, filepath)
        return False
    except Exception:
        # best-effort revert if first rename succeeded but second failed
        if os.path.exists(tmp) and not os.path.exists(filepath):
            try:
                os.replace(tmp, filepath)
            except Exception:
                pass
        return True

def process_new_edf_files():
    # Only descend into top-level sub-### folders, but process ALL depths beneath them.
    for root, dirs, files in os.walk(MAIN_FOLDER, topdown=True):
        if os.path.normpath(root) == os.path.normpath(MAIN_FOLDER):
            # prune traversal to subject folders at the top level
            dirs[:] = [d for d in dirs if SUBDIR_RE.fullmatch(d)]
        # From here down, process every level (ses-*, ieeg, etc.)
        for name in files:
            print("Checking file <{name}>")
            if not name.lower().endswith(".edf"):
                continue
            edf_path = os.path.join(root, name)
            base, _ = os.path.splitext(edf_path)
            pass_file = base + ".edf_pass"
            fail_file = base + ".edf_fail"

            if os.path.exists(pass_file) or os.path.exists(fail_file):
                continue

            if is_file_locked(edf_path):
                print(f"[Locked] Skipping in-use file: {edf_path}")
                continue

            print(f"[Processing] Checking: {edf_path}")
            check_edf_compatibility(EDFBROWSER_PATH, edf_path)

def main():
    while True:
        try:
            print(f"Monitoring {MAIN_FOLDER} recursively every {SCAN_INTERVAL_SEC} seconds...")
            process_new_edf_files()
        except Exception as e:
            print(f"[Error] {e}")
        time.sleep(SCAN_INTERVAL_SEC)

if __name__ == "__main__":
    main()
