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
EDFEXPORT_PATH = r'd:\Neuroworks\EDFExport.exe'
EDFTEMPLATE_PATH = r'd:\Neuroworks\Settings\quant_new_256_with_photic.exp'
PROCESSED_LIST_FILE = r'V:\_pipeline\stepA_processed_list.txt'
CHECK_INTERVAL = 10  # in seconds

# Sub‐folders under ARCHIVE_FOLDER
SKIP_DIR = os.path.join(ARCHIVE_FOLDER, 'skipped sessions')
COMPLETE_DIR = os.path.join(ARCHIVE_FOLDER, 'completed')
ERROR_DIR = os.path.join(ARCHIVE_FOLDER, 'errors')



import psutil

def monitor_output_file(file_path, proc, timeout_mb_per_min=10, check_interval_sec=15):
    prev_size = 0
    stagnant_time = 0  # seconds of low activity
    threshold_bytes = timeout_mb_per_min * 1024 * 1024 / 60 * check_interval_sec

    while proc.poll() is None:  # while still running
        time.sleep(check_interval_sec)
        if not os.path.exists(file_path):
            continue
        new_size = os.path.getsize(file_path)
        delta = new_size - prev_size
        prev_size = new_size

        if delta < threshold_bytes:
            stagnant_time += check_interval_sec
            if stagnant_time >= 60:  # total low activity for 1 minute
                print(f"Low activity on {file_path}. Terminating process.")
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return False  # not completed
        else:
            stagnant_time = 0  # reset if activity seen
    return True  # completed normally



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
    Extract the UUID part of the folder name.
    Example: sub-080_X~ X_1d395e3c-11ea-4b8f-ba48-3b8dc56c8151
    → 1d395e3c-11ea-4b8f-ba48-3b8dc56c8151
    """
    match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', folder_name, re.IGNORECASE)
    return match.group(1) if match else folder_name  # fallback to full name

def find_matching_edf(uuid_part):
    for fname in os.listdir(DEST_FOLDER):
        if fname.lower().endswith('.edf') and uuid_part.lower() in fname.lower():

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
    print(f"[DEBUG] Extracted UUID from folder: {base}")

    edf_match = find_matching_edf(base)

    print(f"[DEBUG] Looking for EDF match for base: {base}")
    for fname in os.listdir(DEST_FOLDER):
        if fname.lower().endswith('.edf'):
            print(f"[DEBUG] Checking against: {fname}")
    # 1) SKIP if EDF already exists
    if edf_match:
        print(f"SKIP: Found existing EDF '{edf_match}' for '{folder_name}'")
        archive_folder(source_path, SKIP_DIR, folder_name)
        append_to_processed_list(folder_name)
        return

    # 2) TRY conversion
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cmd = [EDFEXPORT_PATH, '-s', source_path , '-t', EDFTEMPLATE_PATH, '-o', DEST_FOLDER]
    print(f"Running: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(cmd, shell=True)
        expected_edf_path = os.path.join(DEST_FOLDER, base + ".EDF")  # crude guess
        completed = monitor_output_file(expected_edf_path, proc)

        if not completed:
            raise RuntimeError(f"EDFExport stalled for '{folder_name}'")

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

        return


def main_loop():
    while True:
        processed = read_processed_list()
        for folder in os.listdir(MAIN_FOLDER):
            run_conversion(folder, processed)
        time.sleep(CHECK_INTERVAL)
        print(f"Cheking MAIN_FOLDER = {MAIN_FOLDER}....")

if __name__ == "__main__":
    main_loop()
