import argparse
import subprocess
import time
from datetime import datetime
import os
import sys
import threading
import itertools
import sys

def spinner_task(stop_event):
    spinner = itertools.cycle(['|', '/', '-', '\\'])
    while not stop_event.is_set():
        sys.stdout.write(f"\rChecking... {next(spinner)}")
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write("\rDone.           \n")
    sys.stdout.flush()

def check_edf_compatibility(edfbrowser_path, edf_file_path):
    # Skip if already processed
    base_name = os.path.basename(edf_file_path)
    dir_path = os.path.dirname(edf_file_path)
    base_no_ext = os.path.splitext(base_name)[0]

    pass_file = os.path.join(dir_path, base_no_ext + ".edf_pass")
    fail_file = os.path.join(dir_path, base_no_ext + ".edf_fail")

    if os.path.exists(pass_file) or os.path.exists(fail_file):
        print(f"Skipping (already processed): {edf_file_path}")
        return

    start_time = time.time()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    output_file_temp = "output_temp.txt"

    command = [
        edfbrowser_path,
        "--check-compatibility",
        edf_file_path
    ]

    stop_event = threading.Event()
    spinner_thread = threading.Thread(target=spinner_task, args=(stop_event,))
    #spinner_thread.start()

    try:
        with open(output_file_temp, "w", encoding='utf-8') as outfile:
            result = subprocess.run(command, stdout=outfile, stderr=subprocess.STDOUT)
    except Exception as e:
        #stop_event.set()
        #spinner_thread.join()
        print(f"Fail! Error running edfbrowser: {e}")
        return





def find_edf_files(folder, recursive=False):
    edf_files = []
    cnt = 0
    line_end = 0
    if recursive:
        for root, _, files in os.walk(folder):            
            for f in files:
                cnt += 1
                if cnt > 1000:
                    print(".",end="",flush=True)
                    line_end += 1
                    cnt = 0
                    if line_end > 80:
                        print("\r\n")
                        line_end = 0
                        
                if f.lower().endswith(".edf"):
                    edf_files.append(os.path.join(root, f))
    else:
        for f in os.listdir(folder):
            full_path = os.path.join(folder, f)
            if os.path.isfile(full_path) and f.lower().endswith(".edf"):
                edf_files.append(full_path)
    return edf_files

def main():
    parser = argparse.ArgumentParser(description="Check EDF file compatibility using EDFbrowser.")
    parser.add_argument('--edfbrowser', required=True, help='Full path to edfbrowser.exe')
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--edf', help='Full path to a single EDF file')
    group.add_argument('--folder', help='Folder to search for EDF files')

    parser.add_argument('--recursive', action='store_true', help='Search folders recursively if --folder is used')

    args = parser.parse_args()

    if not os.path.isfile(args.edfbrowser):
        print(f"[X] edfbrowser.exe not found: {args.edfbrowser}")
        sys.exit(1)

    if args.edf:
        if not os.path.isfile(args.edf):
            print(f"[X] EDF file not found: {args.edf}")
            sys.exit(1)
        check_edf_compatibility(args.edfbrowser, args.edf)

    elif args.folder:
        if not os.path.isdir(args.folder):
            print(f"[X] Folder not found: {args.folder}")
            sys.exit(1)
        
        edf_files = find_edf_files(args.folder, args.recursive)
        if not edf_files:
            print("[!] No EDF files found.")
            return
        
        for edf_file in edf_files:
            print(f"Checking file: {edf_file}")
            check_edf_compatibility(args.edfbrowser, edf_file)

if __name__ == "__main__":
    main()
