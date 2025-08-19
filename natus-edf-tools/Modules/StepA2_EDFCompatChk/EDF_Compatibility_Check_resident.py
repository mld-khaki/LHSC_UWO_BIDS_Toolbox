import os
import time
import shutil
import re
from EDF_Compatibility_Check_Tool import check_edf_compatibility

EDFBROWSER_PATH = r"c:\_Code\S22_GitHub\EDFbrowser_CompatChecker\edfbrowser.exe"  # UPDATE this path
MAIN_FOLDER = r"o:/_pipeline/_StepB_AutoFLD_NatusInp_StepAOut"         # UPDATE this path

#MAIN_FOLDER    = r'c:\_Code_SortQueue\_temp_BIDS'

SCAN_INTERVAL_SEC = 10

def is_file_locked(filepath):
    try:
        temp_path = filepath.replace(".edf", "_.edf").lower()
        os.rename(filepath, temp_path)
        os.rename(temp_path, filepath)
        return False
    except Exception:
        return True

def process_new_edf_files():
    for entry in os.listdir(MAIN_FOLDER):
        sub_path = MAIN_FOLDER + "/" + entry
        if not os.path.isdir(sub_path):
            #print(f"(sub_path is not correct = <{sub_path}>")
            continue
        if not re.match(r"sub-\d+", entry):
            continue

        edf_files = [f for f in os.listdir(sub_path) if f.lower().endswith('.edf')]
        for edf_file in edf_files:
            #print(f"Checking EDF file <{edf_file}>...")
            edf_path = os.path.join(sub_path, edf_file)
            base, _ = os.path.splitext(edf_path)
            pass_file = base + ".edf_pass"
            fail_file = base + ".edf_fail"

            if os.path.exists(pass_file) or os.path.exists(fail_file):
                #print(f"File already checked/failed = {edf_path}")
                continue

            if is_file_locked(edf_path):
                print(f"[Locked] Skipping in-use file: {edf_path}")
                continue

            print(f"[Processing] Checking: {edf_path}")
            check_edf_compatibility(EDFBROWSER_PATH, edf_path)

def main():
    while True:
        try:
            print(f"Monitoring {MAIN_FOLDER} every {SCAN_INTERVAL_SEC} seconds...")
            process_new_edf_files()
        except Exception as e:
            print(f"[Error] {e}")
        time.sleep(SCAN_INTERVAL_SEC)

if __name__ == "__main__":
    main()
