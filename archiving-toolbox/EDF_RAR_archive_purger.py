import os
import sys
import logging

def setup_logging(main_folder, log_file=None):
    """Sets up logging to a specified file inside the main folder."""
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
    """Recursively searches for and processes files in the given folder."""
    log_file = setup_logging(main_folder, log_file)
    
    logging.info(f"Starting processing in folder: {main_folder}")
    
    for root, _, files in os.walk(main_folder):
        edf_files = {f for f in files if f.endswith(".edf")}
        rar_files = {f for f in files if f.endswith(".rar")}
        equal_files = {f for f in files if f.endswith(".equal")}
        equal_confirmed_files = {f for f in files if f.endswith(".confirm_equal")}

        for edf_file in edf_files:
            print(edf_file)
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

                    # Delete the .equal_confirmed file
                    equal_confirmed_path = os.path.join(root, equal_confirmed_name)
                    os.remove(equal_confirmed_path)
                    logging.info(f"Deleted equal_confirmed file: {equal_confirmed_path}")

                except Exception as e:
                    logging.error(f"Error deleting files for {edf_file}: {str(e)}")

    logging.info(f"Processing completed for folder: {main_folder}")
    print(f"Processing completed. Log file: {log_file}")

if __name__ == "__main__":
    if 0:#len(sys.argv) < 2:
        print("Usage: python script.py <main_folder> [log_file]")
        sys.exit(1)
    # print(sys.argv[1])
    main_folder = "e:\\EEG_Sessions\\" #sys.argv[1]
    log_name = os.path.basename(os.path.dirname(main_folder))
    log_path = os.path.join(main_folder,log_name + '.log')

    log_file = sys.argv[2] if len(sys.argv) > 2 else log_path
    
    process_folder(main_folder, log_file)
