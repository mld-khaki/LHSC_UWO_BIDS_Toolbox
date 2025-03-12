import sys
import os
import hashlib
import rarfile
from common_libs.checksum_lib import mld_calculate_md5, write_checksum, is_file_in_use
import logging
import time
import tempfile
import shutil

# only enable this option in windows machine
rarfile.UNRAR_TOOL = "c:\\_Codes\\=lhsc_lib\\UnRAR.exe"
# rarfile.UNRAR_TOOL = "f:\\ieeg_dataset_b\\code\\S03_incomplete_task_finder\\_lhsc_lib\\UnRAR.exe"


temp_dir_org = "./tmp_dir/"

slash_char = "/" # "\\"

debug = 1

# Configure logging
logging.basicConfig(filename='process.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

def process_archive(rar_path, edf_name, md5_checksum, folder_path, buffer_size=32 * 1024 * 1024, temp_dir = temp_dir_org):
    try:
        with rarfile.RarFile(rar_path) as rf:
            logging.info(f"Working on file <{rar_path}>")
            print(f"working on file <{rar_path}>")
            
            if edf_name in rf.namelist():
                # Create a temporary directory to extract the file
                print(f"Temp dir = {temp_dir}")
                temp_file_path = os.path.join(temp_dir, edf_name)
                
                # Extract the file to the temporary directory
                rf.extract(edf_name, path=temp_dir)
                logging.info(f"Extracted {edf_name} to {temp_file_path}")

                # Calculate the MD5 of the extracted file
                calculated_md5 = mld_calculate_md5(temp_file_path, buffer_size=buffer_size)
                logging.info(f"Calculated MD5 for {edf_name} in {rar_path}: {calculated_md5}")
                logging.info(f"Original MD5 from .md5 file: {md5_checksum}")

                # Compare checksums
                print(f"Before equal/diff, calc_md5 = {calculated_md5}, saved_md5 = {md5_checksum}")
                if calculated_md5 == md5_checksum:
                    state = "equal"
                    log_state = "match"
                else:
                    state = "diff"
                    log_state = "mismatch"
                    
                fid = open(os.path.join(folder_path, f"{os.path.splitext(edf_name)[0]}." + state), 'w')
                fid.write(f"MD5 calculated after extracting from RAR = {calculated_md5}, Original md5 calculated from uncompressed file = {md5_checksum}")
                fid.close()
                logging.info(f"Checksums {log_state} for {edf_name} in {rar_path}.")
                os.remove(temp_file_path)

                if state == "equal":
                    fid = open(os.path.join(folder_path, f"{os.path.splitext(edf_name)[0]}.confirm_equal"), 'w')
                    fid.write(f"MD5 Calc = {calculated_md5}, Saved = {md5_checksum}")
                    fid.close()
                
                #else:
                 #   open(os.path.join(folder_path, f"{os.path.splitext(edf_name)[0]}.diff"), 'w').close()
                  #  logging.error(f"Checksum mismatch for {edf_name} in {rar_path}. Expected: {md5_checksum}, Found: {calculated_md5}")
            else:
                logging.error(f"{edf_name} not found in {rar_path}.")
    except Exception as e:
        if debug == 1:
            raise(e)
        logging.error(f"Error processing {rar_path}: {str(e)}")

def process_folder(folder_path,tmp_dir = temp_dir_org):
    for root, dirs, files in os.walk(folder_path):
        edf_files = [f for f in files if f.casefold().endswith('.edf')]
        rar_files = [f for f in files if f.casefold().endswith('.rar')]
        md5_files = [f for f in files if f.casefold().endswith('.md5') and f.find(".rar.md5") == -1]
        print(root)
        print(edf_files)
        print(rar_files)
        
        for edf_file in edf_files:
            full_path = root + slash_char + edf_file
            if is_file_in_use(full_path) == True:
                print(f"File <{full_path}> is being used, skipping...")
                continue
            
            base_name = os.path.splitext(edf_file)[0]
            rar_file = next((f for f in rar_files if f.startswith(base_name)), None)
            md5_file = next((f for f in md5_files if f.startswith(base_name)), None)
            
            if md5_file == None:
                print(f"calculating checksum md5 {full_path}")
                checksum = mld_calculate_md5(full_path,display_progress=True)
                write_checksum(full_path, checksum)
                md5_files = [f for f in files if f.endswith('.md5')]
                md5_file = next((f for f in md5_files if f.startswith(base_name)), None)
            
            if rar_file and md5_file:
                md5_file_path = os.path.join(root, md5_file)
                with open(md5_file_path, 'r') as mf:
                    md5_checksum = mf.read().strip()

                rar_path = os.path.join(root, rar_file)

                try:
                    # If RAR archive contains more than one EDF file, skip and log
                    with rarfile.RarFile(rar_path) as rf:
                        edf_files_in_rar = [f for f in rf.namelist() if f.endswith('.edf')]
                        if len(edf_files_in_rar) > 1:
                            logging.error(f"Multiple EDF files found in {rar_path}. Skipping.")
                            continue
                except Exception as e:
                    if debug == 1:
                        raise(e)
                    logging.error(f"Error in opening rar file: {rar_path}. {str(e)}. Skipping.")
                    os.
                    raise(e)
                    continue

                process_archive(rar_path, edf_file, md5_checksum, root,temp_dir = tmp_dir)
                

def rar_checksum_eval(folder_to_process, tmp_dir):
    process_folder(folder_to_process, tmp_dir = tmp_dir)

if __name__ == "__main__":
    pass
