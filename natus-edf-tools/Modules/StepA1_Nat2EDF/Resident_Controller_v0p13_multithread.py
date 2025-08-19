import threading
import os
import shutil
import subprocess
import time
import re
from datetime import datetime

replication_issue_flag = threading.Event()


# Configuration
MAIN_FOLDER = r'V:\_pipeline\_StepA_AutoFLD_NatusInp'
DEST_FOLDER = r'V:\_pipeline\_StepB_AutoFLD_NatusInp_StepAOut'
ARCHIVE_FOLDER = r'V:\_pipeline\_StepA_AutoFLD_NatusArx'
EDFEXPORT_PATH = r'd:\Neuroworks\EDFExport.exe'

# EDFTEMPLATE_PATH = r'd:\Neuroworks\Settings\quant_new_256_with_photic.exp'
EDFTEMPLATE_PATH = r'V:\_pipeline\_StepA_AutoFLD_NatusTemplates\elec_001_to_132_padded_edf_plus.exp'
PROCESSED_LIST_FILE = r'V:\_pipeline\stepA_processed_list.txt'
CHECK_INTERVAL = 10  # in seconds

# Sub‐folders under ARCHIVE_FOLDER
SKIP_DIR = os.path.join(ARCHIVE_FOLDER, 'skipped sessions')
COMPLETE_DIR = os.path.join(ARCHIVE_FOLDER, 'completed')
ERROR_DIR = os.path.join(ARCHIVE_FOLDER, 'errors_semimanual')



import psutil

def kill_edfexport_processes(target_cmdline_fragment=None):
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            if proc.info['name'] and 'EDFExport.exe' in proc.info['name']:
                if target_cmdline_fragment:
                    if not any(target_cmdline_fragment in part for part in proc.info['cmdline']):
                        continue  # skip if cmdline doesn't match
                print(f"[Cleanup] Killing stuck EDFExport process: PID {proc.pid}", flush=True)
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

def wait_for_folder_release(folder_path, timeout=60):
    """
    Wait up to `timeout` seconds for the folder to be released (e.g. by EDFExport.exe).
    Returns True if the folder becomes available, False if not.
    """
    start = time.time()
    probe = os.path.join(folder_path, '__probe__.tmp')
    while time.time() - start < timeout:
        try:
            with open(probe, 'w') as f:
                f.write('probe')
            os.remove(probe)
            return True
        except Exception:
            time.sleep(1)
    return False


def detect_replication_issue(base_name, stop_event):
    pattern = re.compile(r'.*' + re.escape(base_name) + r'\(\d+\)\.edf$', re.IGNORECASE)
    while not stop_event.is_set():
        print(f"[Monitor] Checking for replication of '{base_name}'", flush=True)
        for fname in os.listdir(DEST_FOLDER):
            if pattern.match(fname):
                replication_issue_flag.set()
                print(f"[Monitor] Replication issue detected: '{fname}'", flush=True)
                return
        time.sleep(10)



def monitor_output_file(file_path, proc, folder_name, timeout_mb_per_min=10, check_interval_sec=15):
    prev_size = 0
    stagnant_time = 0  # seconds of low activity
    threshold_bytes = timeout_mb_per_min * 1024 * 1024 / 60 * check_interval_sec

    while proc.poll() is None:  # while still running
        time.sleep(check_interval_sec)

        # Stop immediately if replication is detected
        if replication_issue_flag.is_set():
            print("[Monitor] Replication flag detected inside monitor — terminating process.", flush=True)
            kill_edfexport_processes(target_cmdline_fragment=folder_name)
            return False

        if not os.path.exists(file_path):
            continue
        new_size = os.path.getsize(file_path)
        delta = new_size - prev_size
        prev_size = new_size

        if delta < threshold_bytes:
            stagnant_time += check_interval_sec
            if stagnant_time >= 60:
                print(f"Low activity on {file_path}. Terminating process.")
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return False
        else:
            stagnant_time = 0
    return True



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
        return

    source_path = os.path.join(MAIN_FOLDER, folder_name)
    if not os.path.isdir(source_path):
        return

    base = base_from_folder(folder_name)
    edf_match = find_matching_edf(base)

    if edf_match:
        print(f"SKIP: Found existing EDF '{edf_match}' for '{folder_name}'")
        archive_folder(source_path, SKIP_DIR, folder_name)
        append_to_processed_list(folder_name)
        return

    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cmd = [EDFEXPORT_PATH, "-s", source_path, "-t", EDFTEMPLATE_PATH, "-o", DEST_FOLDER]
    print(f"Running: {' '.join(cmd)}")

    expected_edf_path = os.path.join(DEST_FOLDER, base + ".edf")

    replication_issue_flag.clear()
    stop_monitor = threading.Event()
    monitor_thread = threading.Thread(
        target=detect_replication_issue,
        args=(base, stop_monitor),
        daemon=True
    )

    try:
        proc = subprocess.Popen(cmd, shell=True)
        print(f"[Main] Monitoring base name for EDF: {base}", flush=True)
        monitor_thread.start()

        completed = monitor_output_file(expected_edf_path, proc, folder_name=folder_name)

        stop_monitor.set()
        monitor_thread.join()

        if replication_issue_flag.is_set():
            print(f"[Main] REPLICATION ISSUE: duplicate EDFs for '{folder_name}'")

            if os.path.exists(expected_edf_path):
                new_name = expected_edf_path.replace(".edf", "_replication_issue.edf")
                os.rename(expected_edf_path, new_name)

            print(f"[Main] Waiting for folder release: {source_path}", flush=True)
            if wait_for_folder_release(source_path):
                print(f"[Main] Folder is free. Proceeding to move: {source_path}", flush=True)
            else:
                print(f"[Main] Timeout waiting for folder release: {source_path}", flush=True)

            kill_edfexport_processes(target_cmdline_fragment=folder_name)

            err_dest = archive_folder(source_path, ERROR_DIR, folder_name)
            err_log = os.path.join(
                err_dest,
                f"replication_issue_{datetime.now():%Y%m%d_%H%M%S}.txt"
            )
            with open(err_log, "w") as f:
                f.write("Replication issue detected: multiple EDF files found.\n")

            append_to_processed_list(folder_name)
            return  # prevent continuing to success logic



        if not completed:
            print(f"[Main] Export stalled for '{folder_name}'")
            err_dest = archive_folder(source_path, ERROR_DIR, folder_name)
            err_log = os.path.join(
                err_dest,
                f"stalled_export_{datetime.now():%Y%m%d_%H%M%S}.txt"
            )
            with open(err_log, "w") as f:
                f.write("Export process stalled with low activity or interruption.\n")
            append_to_processed_list(folder_name)
            return

        edf_match = find_matching_edf(base)
        if not edf_match:
            print(f"[Main] Exported but EDF file not found for '{folder_name}'")
            err_dest = archive_folder(source_path, ERROR_DIR, folder_name)
            err_log = os.path.join(
                err_dest,
                f"missing_edf_{datetime.now():%Y%m%d_%H%M%S}.txt"
            )
            with open(err_log, "w") as f:
                f.write("EDF file not found after export process completed.\n")
            append_to_processed_list(folder_name)
            return

        end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        archive_dest = archive_folder(source_path, COMPLETE_DIR, folder_name)

        log_name = os.path.join(
            archive_dest,
            f"conversion_provenance_{datetime.now():%Y%m%d_%H%M%S}.txt"
        )
        log_provenance(log_name, start_time, end_time, source_path, edf_match, folder_name)

        append_to_processed_list(folder_name)
        print(f"COMPLETED: '{folder_name}' archived in 'completed'")

    except Exception as e:
        print(f"[Main] UNEXPECTED ERROR for '{folder_name}': {e}")
        err_dest = archive_folder(source_path, ERROR_DIR, folder_name)
        err_log = os.path.join(
            err_dest,
            f"exception_error_{datetime.now():%Y%m%d_%H%M%S}.txt"
        )
        with open(err_log, "w") as f:
            f.write(f"Unexpected error: {e}\n")
        append_to_processed_list(folder_name)




def main_loop():
    while True:
        processed = read_processed_list()
        for folder in os.listdir(MAIN_FOLDER):
            run_conversion(folder, processed)
        time.sleep(CHECK_INTERVAL)
        print(f"Cheking MAIN_FOLDER = {MAIN_FOLDER}....")

if __name__ == "__main__":
    main_loop()
