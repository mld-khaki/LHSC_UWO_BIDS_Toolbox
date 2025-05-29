import os
import shutil
import subprocess
import time
from datetime import datetime

# Configuration
MAIN_FOLDER = r'V:\_pipeline\_StepA_AutoFLD_NatusInp'
DEST_FOLDER = r'x:\_pipeline\_StepB_AutoFLD_NatusInp_StepAOut'
ARCHIVE_FOLDER = r'x:\_pipeline\_StepA_AutoFLD_NatusArx'
EDFEXPORT_PATH = r'd:\Neuroworks\EDFExport.exe'
CHECK_INTERVAL = 10  # in seconds

def log_provenance(file_path, start_time, end_time, source, destination, folder_name):
    with open(file_path, 'w') as f:
        f.write(f"Task started: {start_time}\n")
        f.write(f"Task ended: {end_time}\n")
        f.write(f"Source folder: {source}\n")
        f.write(f"Destination file: {destination}\n")
        f.write(f"Processed folder: {folder_name}\n")

def run_conversion(input_folder):
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    source_path = os.path.join(MAIN_FOLDER, input_folder)
    edf_output_path = os.path.join(DEST_FOLDER, f"{input_folder}.EDF")
    a_ready_path = os.path.join(source_path, "A_ready_for_conv.txt")
    b_ready_path = os.path.join(source_path, "B_ready_for_anonymization.txt")

    # Execute EDFExport command
    command = [EDFEXPORT_PATH, '-s', source_path, '-t', '', '-o', DEST_FOLDER]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Conversion failed for {input_folder}: {e}")
        return

    # Check if EDF file was created
    if os.path.exists(edf_output_path):
        end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Move the input folder to archive
        archive_path = os.path.join(ARCHIVE_FOLDER, input_folder)
        shutil.move(source_path, archive_path)

        # Rename and log in the archive folder
        new_b_ready_path = os.path.join(archive_path, "B_ready_for_anonymization.txt")
        log_provenance(new_b_ready_path, start_time, end_time, source_path, edf_output_path, input_folder)

        print(f"Processed and archived: {input_folder}")
    else:
        print(f"EDF file not found for {input_folder}")

def main_loop():
    while True:
        for folder in os.listdir(MAIN_FOLDER):
            folder_path = os.path.join(MAIN_FOLDER, folder)
            if os.path.isdir(folder_path):
                #ready_file = os.path.join(folder_path, "A_ready_for_conv.txt")
                if True: #os.path.exists(ready_file):
                    run_conversion(folder)
        time.sleep(CHECK_INTERVAL)

main_loop()
