#!/usr/bin/env python3

import os
import sys
import time
import argparse
import logging
import hashlib
import rarfile
import subprocess
import shutil
from datetime import datetime

# Adjust this import according to your environment.
# E.g., if "redaction.py" is in the same directory, do `from redaction import redaction`.
# Here we'll assume it's in a subfolder called sub_process_path:
try:
    sys.path.append(os.path.join(os.path.dirname(__file__), 'sub_process_path'))
    from redaction import redaction
except ImportError:
    # If you have a different path or name for the redaction script, adjust accordingly.
    # For demonstration, we just define a placeholder function.
    def redaction(input_file, output_file):
        """
        Placeholder redaction function.
        Replace this with a real import from your actual 'redaction.py'.
        """
        # Example only: copy input to output (NO real redaction!)
        shutil.copy2(input_file, output_file)

###############################################################################
# HELPER FUNCTIONS
###############################################################################

def setup_logger(provenance_root):
    """
    Sets up a logger that writes to both console and a timestamped log file
    in the root of the provenance folder.
    """
    # Ensure the provenance root exists, then create a log file name
    os.makedirs(provenance_root, exist_ok=True)
    log_filename = datetime.now().strftime("process_log_%Y%m%d_%H%M%S.log")
    full_log_path = os.path.join(provenance_root, log_filename)

    logger = logging.getLogger("RAR_EDF_Processor")
    logger.setLevel(logging.DEBUG)

    # Clear existing handlers if re-running
    logger.handlers = []

    # File handler (INFO level and above)
    fh = logging.FileHandler(full_log_path, encoding="utf-8")
    fh.setLevel(logging.INFO)
    file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh.setFormatter(file_formatter)
    logger.addHandler(fh)

    # Console handler (DEBUG level and above, so user sees everything)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch.setFormatter(console_formatter)
    logger.addHandler(ch)

    logger.info(f"Logging initialized. Writing log to: {full_log_path}")
    return logger

def compute_md5(file_path, buffer_size=65536):
    """
    Compute the MD5 of the given file and return it as a hex string.
    """
    md5_hash = hashlib.md5()
    total_size = os.path.getsize(file_path)
    processed_size = 0
    with open(file_path, "rb") as f:
        while True:
            data = f.read(buffer_size)
            if not data:
                break
            md5_hash.update(data)
            processed_size += len(data)
    return md5_hash.hexdigest()

def create_rar(rar_path, file_to_add, logger):
    """
    Create or update a RAR archive containing the specified file.
    Calls the 'rar' or 'winrar' command line tool via subprocess.
    """
    # For example, to create a RAR on Windows:
    #   rar a test-v2.edf.rar test-v2.edf
    #
    # The user environment must have 'rar' on the PATH.
    cmd = ["rar", "a", rar_path, file_to_add]
    logger.info(f"Creating RAR archive: {rar_path} with {file_to_add}")
    logger.debug(f"Running command: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed creating RAR. Command: {cmd}. Error: {e}")
        raise e

def extract_rar(rar_path, extract_to_dir, logger):
    """
    Extract all contents of rar_path into extract_to_dir using rarfile.
    Returns a list of extracted file names (just the basenames).
    """
    extracted_files = []
    logger.debug(f"Extracting from RAR: {rar_path} to {extract_to_dir}")
    with rarfile.RarFile(rar_path) as rf:
        rf.extractall(path=extract_to_dir)
        extracted_files = rf.namelist()
    return extracted_files

def ensure_md5_exists(edf_path, logger):
    """
    If an .md5 file doesn't exist for `edf_path`, compute and create it.
    Return the path to the .md5 file.
    """
    md5_file_path = edf_path + ".md5"
    if not os.path.isfile(md5_file_path):
        logger.info(f"No MD5 found for {edf_path}; generating it now.")
        md5val = compute_md5(edf_path)
        with open(md5_file_path, "w") as f:
            f.write(md5val)
    return md5_file_path

def move_with_subfolders(src_path, start_folder, provenance_folder, logger):
    """
    Move `src_path` into `provenance_folder`, preserving the subfolder structure
    relative to `start_folder`.
    Example:
       src_path = /my/data/sub1/sub2/test.edf
       start_folder = /my/data
       provenance_folder = /my/provenance
     => new path: /my/provenance/sub1/sub2/test.edf
    Creates subfolders if needed.
    """
    rel = os.path.relpath(os.path.dirname(src_path), start_folder)
    dest_dir = os.path.join(provenance_folder, rel)
    os.makedirs(dest_dir, exist_ok=True)
    dest_file = os.path.join(dest_dir, os.path.basename(src_path))

    logger.info(f"Moving {src_path} => {dest_file}")
    shutil.move(src_path, dest_file)

###############################################################################
# CORE PROCESS
###############################################################################

def process_single_rar(rar_path, start_folder, provenance_folder, logger):
    """
    Process one .rar that should contain exactly one .edf.
    Follows the steps:
      - Check if there's exactly one .edf inside
      - Extract the .edf, ensure we have its MD5
      - Compare MD5
      - Redact => test-v2.edf
      - Generate MD5 => test-v2.edf.md5
      - Re-pack => test-v2.edf.rar
      - Extract => temp.edf => compute MD5 => compare
      - If match => test-v2.equal, else => test-v2.diff
      - Move final and original files to the provenance folder
    """
    try:
        logger.info(f"Examining RAR: {rar_path}")

        with rarfile.RarFile(rar_path) as rf:
            edf_members = [m for m in rf.namelist() if m.lower().endswith(".edf")]

            if len(edf_members) == 0:
                logger.warning(f"No .edf found in {rar_path}. Skipping.")
                return
            if len(edf_members) > 1:
                logger.error(f"Multiple .edf files in {rar_path}; skipping per instructions.")
                return

            # The single EDF filename inside the RAR
            edf_in_rar = edf_members[0]
            logger.info(f"RAR {rar_path} contains exactly one EDF: {edf_in_rar}")

        # Create a temporary directory to do extraction and re-packing
        tmp_work_dir = os.path.join(os.path.dirname(rar_path), "tmp_extract_" + str(int(time.time())))
        os.makedirs(tmp_work_dir, exist_ok=True)

        # Extract the EDF
        extract_rar(rar_path, tmp_work_dir, logger)  # extracts all
        extracted_edf_path = os.path.join(tmp_work_dir, edf_in_rar)

        # 2.1) We have test.edf in extracted_edf_path
        if not os.path.isfile(extracted_edf_path):
            logger.error(f"After extraction, {extracted_edf_path} was not found. Skipping.")
            shutil.rmtree(tmp_work_dir, ignore_errors=True)
            return

        # 2.2) Check if there's a .md5 for the EDF, else create one
        # Let's call the original name "test.edf", for example
        original_name = os.path.basename(extracted_edf_path)  # e.g. test.edf
        base_no_ext, ext = os.path.splitext(original_name)    # base_no_ext="test", ext=".edf"
        parent_dir = os.path.dirname(rar_path)

        possible_md5 = os.path.join(parent_dir, f"{base_no_ext}.edf.md5")
        if not os.path.isfile(possible_md5):
            # Could also check "test.edf.rar.md5", "test.edf.md5", etc. 
            # But per your instructions, if not found, generate it:
            logger.info(f"MD5 file not found for {original_name}, generating one now.")
            # We'll store it in the same folder as the .rar
            md5_val = compute_md5(extracted_edf_path)
            with open(possible_md5, "w") as f:
                f.write(md5_val)

        # Now read the original's MD5
        with open(possible_md5, "r") as f:
            original_md5 = f.read().strip()

        actual_md5_extracted = compute_md5(extracted_edf_path)
        logger.info(f"Extracted EDF path: {extracted_edf_path}")
        logger.info(f"MD5 of extracted: {actual_md5_extracted}, MD5 from file: {original_md5}")

        # 2.2.1) If mismatch here, we still continue. The instructions say to compare,
        # but not to abort. We'll just log it.
        if actual_md5_extracted != original_md5:
            logger.warning(f"Extracted EDF MD5 mismatch from provided MD5. (Got {actual_md5_extracted}, expected {original_md5})")

        # 2.2.2) Apply redaction => test-v2.edf
        redacted_name = f"{base_no_ext}-v2.edf"
        redacted_path = os.path.join(tmp_work_dir, redacted_name)
        logger.info(f"Running redaction({extracted_edf_path}, {redacted_path})")
        redaction(extracted_edf_path, redacted_path)  # The user's function or your real method

        if not os.path.isfile(redacted_path):
            logger.error(f"Redaction step did not produce {redacted_path}. Cannot continue.")
            shutil.rmtree(tmp_work_dir, ignore_errors=True)
            return

        # 2.2.3) Calculate MD5 => test-v2.edf.md5
        redacted_md5 = compute_md5(redacted_path)
        with open(redacted_path + ".md5", "w") as f:
            f.write(redacted_md5)
        logger.info(f"Redacted file MD5: {redacted_md5}")

        # 2.2.4) Repack => test-v2.edf.rar
        redacted_rar = os.path.join(tmp_work_dir, f"{base_no_ext}-v2.edf.rar")
        create_rar(redacted_rar, redacted_path, logger)

        if not os.path.isfile(redacted_rar):
            logger.error(f"Could not create {redacted_rar}. Stopping process.")
            shutil.rmtree(tmp_work_dir, ignore_errors=True)
            return

        # 2.2.5) Extract it from the new RAR => temp.edf
        temp_extract_dir = os.path.join(tmp_work_dir, "temp_repack_check")
        os.makedirs(temp_extract_dir, exist_ok=True)
        extract_rar(redacted_rar, temp_extract_dir, logger)
        # We expect to find test-v2.edf in there
        temp_extracted_path = os.path.join(temp_extract_dir, redacted_name)
        if not os.path.isfile(temp_extracted_path):
            logger.error(f"Temp extraction did not produce {temp_extracted_path}. Stopping.")
            shutil.rmtree(tmp_work_dir, ignore_errors=True)
            return

        # 2.2.6) Calculate MD5 => temp.edf.md5
        temp_md5 = compute_md5(temp_extracted_path)
        logger.info(f"MD5 of re-extracted redacted file: {temp_md5}")

        # 2.2.7) Compare
        equal_or_diff = ".equal" if (temp_md5 == redacted_md5) else ".diff"
        result_file_name = f"{base_no_ext}-v2{equal_or_diff}"
        result_file_path = os.path.join(parent_dir, result_file_name)
        with open(result_file_path, "w") as rf:
            rf.write(f"md5({redacted_name}) = {redacted_md5}, md5(extracted temp-v2.edf) = {temp_md5}")
        logger.info(f"Created {result_file_path} with MD5 comparison results.")

        # If they match => 2.2.7.1) we do the moves
        if temp_md5 == redacted_md5:
            # 2.2.7.1.1) Move the edf file (test-v2.edf) to provenance
            move_with_subfolders(redacted_path, start_folder, provenance_folder, logger)
            # 2.2.7.1.2) Move original edf file (test.edf) to provenance
            move_with_subfolders(extracted_edf_path, start_folder, provenance_folder, logger)
            # 2.2.7.1.3) Move original edf.rar file to provenance
            move_with_subfolders(rar_path, start_folder, provenance_folder, logger)
            # 2.2.7.1.4) Move any original md5 or .equal files to provenance
            # Specifically:
            #  - test.edf.md5 (if it exists)
            #  - test.edf.rar.md5 (if it exists)
            #  - test.equal or test-v2.equal, etc. – basically any related files
            #    that start with the same base
            base_search = base_no_ext + ".edf"
            possible_extras = [
                f"{base_search}.md5",
                f"{base_search}.rar.md5",
                f"{base_search}.equal",
                f"{base_search}-v2.equal",
                f"{base_search}.diff",
                f"{base_search}-v2.diff",
            ]
            for extra in possible_extras:
                full_extra_path = os.path.join(parent_dir, extra)
                if os.path.isfile(full_extra_path):
                    move_with_subfolders(full_extra_path, start_folder, provenance_folder, logger)

        else:
            logger.warning(f"MD5 mismatch for redacted vs. re-extracted. Created .diff file: {result_file_path}")

        # Clean up our temp working directory
        shutil.rmtree(tmp_work_dir, ignore_errors=True)

    except Exception as exc:
        logger.error(f"Error processing {rar_path}: {exc}")
        # Continue; do not raise, so we can move on to next file.

###############################################################################
# MAIN SCRIPT
###############################################################################

def main():
    parser = argparse.ArgumentParser(
        description="Recursively processes RAR archives containing EDF files. "
                    "Redacts, repacks, and verifies MD5 checks, then moves results "
                    "to a provenance folder."
    )
    parser.add_argument("start_folder", help="Path to the folder to scan recursively.")
    parser.add_argument("provenance_folder", help="Path to the root provenance folder.")
    args = parser.parse_args()

    start_folder = os.path.abspath(args.start_folder)
    provenance_folder = os.path.abspath(args.provenance_folder)

    # Set up logging to a single file in the provenance folder + console
    logger = setup_logger(provenance_folder)
    logger.info("Beginning search for .rar files in: " + start_folder)

    # Ensure rarfile can find unrar/WinRAR if needed
    # If needed on Windows:
    # rarfile.UNRAR_TOOL = r"C:\Path\To\UnRAR.exe"
    # On Linux, might be '/usr/bin/unrar' or so.
    # Adjust if needed:
    # rarfile.UNRAR_TOOL = "unrar"

    # Walk the directory tree
    for root, dirs, files in os.walk(start_folder):
        # We only care about .rar files
        rar_files = [f for f in files if f.lower().endswith(".rar")]
        for rarf in rar_files:
            rar_path = os.path.join(root, rarf)
            process_single_rar(rar_path, start_folder, provenance_folder, logger)

    logger.info("All done! Exiting script.")

if __name__ == "__main__":
    main()
