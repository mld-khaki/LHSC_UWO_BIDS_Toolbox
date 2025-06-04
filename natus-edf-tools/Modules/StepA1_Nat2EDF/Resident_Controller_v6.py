import os
import shutil
import subprocess
import time
import re
from datetime import datetime

# Configuration
MAIN_FOLDER = r'V:\_pipeline\_StepA_AutoFLD_NatusInp'
DEST_FOLDER = r'V:\_pipeline\_StepB_AutoFLD_NatusInp_StepAOut'
ARCHIVE_FOLDER = r'V:\_pipeline\_StepA_AutoFLD_NatusArx'
EDFEXPORT_PATH = r'"d:\Neuroworks\EDFExport.exe"'
EDFTEMPLATE_PATH = r'"D:\Neuroworks\Settings\quantum_milad_c.exp"'
PROCESSED_LIST_FILE = r'V:\_pipeline\stepA_processed_list.txt'
CHECK_INTERVAL = 10  # in seconds

# Sub‐folders under ARCHIVE_FOLDER
SKIP_DIR = os.path.join(ARCHIVE_FOLDER, 'skipped sessions')
COMPLETE_DIR = os.path.join(ARCHIVE_FOLDER, 'completed')
ERROR_DIR = os.path.join(ARCHIVE_FOLDER, 'errors')

# Make sure archive subdirs exist
for d in (SKIP_DIR, COMPLETE_DIR, ERROR_DIR):
    os.makedirs(d, exist_ok=True)

def read_processed_list():
    if not os.path.exists(PROCESSED_LIST_FILE):
        return set()
    with open(PROCESSED_LIST_FILE, 'r') as f:
        return set(line.strip() for line in f if line.strip())

def append_to_processed_list(folder_name):
    with open(PROCESSED_LIST_FILE, 'a') as f:
        f.write(f"{folder_name}\n")

def log_provenance(log_path, start_time, end_time, source_folder, edf_match, folder_name):
    with open(log_path, 'w') as f:
        f.write(f"Task started:   {start_time}\n")
        f.write(f"Task ended:     {end_time}\n")
        f.write(f"Source folder:  {source_folder}\n")
        f.write(f"EDF matched:    {edf_match}\n")
        f.write(f"Folder name:    {folder_name}\n")

def base_from_folder(folder_name):
    """
    If name is yyyy_mm_dd__X~ X_rest, strip the date prefix;
    else return the full name.
    """
    m = re.match(r'^\d{4}_\d{2}_\d{2}__(.+)$', folder_name)
    return m.group(1) if m else folder_name

def find_matching_edf(base_name):
    """
    Case‐insensitive search in DEST_FOLDER for any .edf
    whose basename starts with base_name + '.'
    """
    for fname in os.listdir(DEST_FOLDER):
        if fname.lower().endswith('.edf'):
            if fname.lower().startswith(base_name.lower() + '.'):
                return fname
    return None

def archive_folder(src_path, dest_root, folder_name):
    dest = os.path.join(dest_root, folder_name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        shutil.move(src_path, dest)
    except Exception:
        # if move fails, create an empty dir so user can see it
        os.makedirs(dest, exist_ok=True)
    return dest

def run_conversion(folder_name, processed):
    if folder_name in processed:
        return  # already handled

    source_path = os.path.join(MAIN_FOLDER, folder_name)
    if not os.path.isdir(source_path):
        return

    base = base_from_folder(folder_name)
    edf_match = find_matching_edf(base)

    # 1) SKIP if EDF already exists
    if edf_match:
        print(f"SKIP: Found existing EDF '{edf_match}' for '{folder_name}'")
        archive_folder(source_path, SKIP_DIR, folder_name)
        append_to_processed_list(folder_name)
        return

    # 2) TRY conversion
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cmd = [EDFEXPORT_PATH, '-s', source_path, '-t', EDFTEMPLATE_PATH, '-o', DEST_FOLDER]

    try:
        subprocess.run(cmd, check=True)
        # after success, look again for match
        edf_match = find_matching_edf(base)
        if not edf_match:
            raise FileNotFoundError(f"No EDF output for base '{base}'")

        # COMPLETED
        end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        archive_dest = archive_folder(source_path, COMPLETE_DIR, folder_name)

        # write provenance log
        log_name = os.path.join(
            archive_dest,
            f"conversion_provenance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        log_provenance(log_name, start_time, end_time, source_path, edf_match, folder_name)

        append_to_processed_list(folder_name)
        print(f"COMPLETED: '{folder_name}' → archived under 'completed'")

    except Exception as e:
        # ERROR
        print(f"ERROR processing '{folder_name}': {e}")
        err_dest = archive_folder(source_path, ERROR_DIR, folder_name)

        # write error log
        err_log = os.path.join(
            err_dest,
            f"conversion_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        with open(err_log, 'w') as f:
            f.write(f"Error: {e}\n")
        # no need to append to processed_list since folder’s gone
        return

def main_loop():
    while True:
        processed = read_processed_list()
        for folder in os.listdir(MAIN_FOLDER):
            run_conversion(folder, processed)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main_loop()
