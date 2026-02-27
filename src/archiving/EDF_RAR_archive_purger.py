import os
import sys
import time
#sys.path.append(os.path.abspath('c:\\Temp\\EDF\\tester\\code\\_lhsc_lib\\'))
#os.environ['PATH'] += os.pathsep + 'c:\\Temp\\EDF\\tester\\code\\_lhsc_lib\\'

cur_path = r'c:\_code'
sys.path.append(os.path.abspath(cur_path))
os.environ['PATH'] += os.pathsep + cur_path
from _lhsc_lib.rar_checksum_tester import rar_checksum_eval

#search_dirs = ["/volume1/seeg_data/ieeg_dataset_a/bids/", "/volume1/seeg_data/ieeg_dataset_b/bids/"]
required_extensions = ['.rar', '.edf']

import logging
import argparse

def setup_logging(main_folder, log_file=None):
    """
    Sets up logging to a specified file inside the main folder.
    If no log file is provided, it creates a default log file with the name of the main folder.
    """
    if log_file is None:
        log_file = os.path.join(main_folder, os.path.basename(main_folder) + ".log")
    
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    return log_file

def process_folder(main_folder, log_file=None):
    """
    Recursively searches for and processes files in the given folder.
    Deletes `.edf` files if corresponding `.edf.rar`, `.equal`, and `.confirm_equal` files exist.
    Logs all operations to the specified log file.
    """
    log_file = setup_logging(main_folder, log_file)
    
    logging.info(f"Starting processing in folder: {main_folder}")
    
    for root, _, files in os.walk(main_folder):
        edf_files = {f for f in files if f.endswith(".edf")}
        rar_files = {f for f in files if f.endswith(".rar")}
        equal_files = {f for f in files if f.endswith(".equal")}
        equal_confirmed_files = {f for f in files if f.endswith(".confirm_equal")}

        for edf_file in edf_files:
            base_name = os.path.splitext(edf_file)[0]
            rar_name = f"{base_name}.edf.rar"
            equal_name = f"{base_name}.equal"
            equal_confirmed_name = f"{base_name}.confirm_equal"

            if rar_name in rar_files and equal_name in equal_files and equal_confirmed_name in equal_confirmed_files:
                try:
                    # Delete the .edf file
                    edf_path = os.path.join(root, edf_file)
                    os.remove(edf_path)
                    logging.info(f"Deleted EDF file: {edf_path}")
                    print(f"Deleted: {edf_path}")

                    # Delete the .equal_confirmed file
                    equal_confirmed_path = os.path.join(root, equal_confirmed_name)
                    os.remove(equal_confirmed_path)
                    logging.info(f"Deleted equal_confirmed file: {equal_confirmed_path}")
                    print(f"Deleted: {equal_confirmed_path}")
                
                except Exception as e:
                    logging.error(f"Error deleting files for {edf_file}: {str(e)}")
                    print(f"Error deleting {edf_file}: {str(e)}")
    
    logging.info(f"Processing completed for folder: {main_folder}")
    print(f"Processing completed. Log file: {log_file}")


def main():
    """
    Parses command-line arguments and starts the processing.
    """
    parser = argparse.ArgumentParser(
        description="""
        This script scans a given folder for .edf files and deletes them if all of the following exist:
        - A corresponding .edf.rar file
        - A corresponding .equal file
        - A corresponding .confirm_equal file
        
        All deletions are logged in a log file inside the main folder unless specified otherwise.
        """,
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        "main_folder", 
        help="Path to the main folder that contains the files to process."
    )
    
    parser.add_argument(
        "--log_file", "-l", 
        help="Path to a specific log file (optional). If not provided, a default log file will be created in the main folder.",
        default=None
    )
    
    args = parser.parse_args()
    process_folder(args.main_folder, args.log_file)


if __name__ == "__main__":
    main()
