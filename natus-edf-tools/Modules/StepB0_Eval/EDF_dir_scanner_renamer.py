import os
import argparse
import sys
from datetime import datetime
from pathlib import Path
import re

# Try to import edflibpy, but make annotations check optional if not available
#try:
 #   from edflibpy.edfreader import EDFreader
  #  EDFLIBPY_AVAILABLE = True
#except ImportError:
 #   EDFLIBPY_AVAILABLE = False

cur_path = r'../../'
sys.path.append(os.path.abspath(cur_path))
os.environ['PATH'] += os.pathsep + cur_path

from _lhsc_lib.EDF_reader_mld import EDFreader

def get_start_date_string(edf_path):
    try:
        reader = EDFreader(edf_path, read_annotations = False)
        start_time = reader.getStartDateTime()
        reader.close()
        print(start_time)
        return start_time.strftime('%Y_%m_%d')
    except Exception as e:
        raise(e)
        print(f"Failed to get start time from {edf_path}: {e}")
        return None

def rename_files_with_prefix(base_file_path, date_prefix):
    folder = base_file_path.parent
    # Get the base filename without extension
    base_name = base_file_path.stem
    
    # Create pattern to match files with the same base name
    # Using regex pattern to match exact base name with optional suffix
    pattern = re.compile(f"^{re.escape(base_name)}(.*?)$")
    
    print(f"Looking for files matching pattern: {base_name}*")
    
    renamed_files = []
    for file in os.listdir(folder):
        file_path = folder / file
        
        # Use regex match to properly identify related files
        match = pattern.match(file)
        if match:
            suffix = match.group(1)  # Get the suffix part
            new_file_name = f"{date_prefix}_{base_name}{suffix}"
            new_file_path = folder / new_file_name
            
            print(f"Found match: {file} -> {new_file_name}")
            
            try:
                # Uncomment to actually perform renaming
                os.rename(file_path, new_file_path)
                renamed_files.append((str(file), new_file_name))
            except Exception as e:
                print(f"Failed to rename {file_path} to {new_file_path}: {e}")
    
    return renamed_files


def scan_and_rename(folder):
    renamed_all = []

    for root, _, files in os.walk(folder):
        for file in files:
            if file.lower().endswith(".edf"):
                full_path = Path(root) / file
                date_prefix = get_start_date_string(full_path)
                if date_prefix:
                    renamed = rename_files_with_prefix(full_path, date_prefix)
                    renamed_all.extend(renamed)

    if renamed_all:
        print("\nRenaming Summary:")
        for old, new in renamed_all:
            print(f"{old} -> {new}")
    else:
        print("No files were renamed.")

def main():
    parser = argparse.ArgumentParser(description="Rename EDF files and their associated files with date prefix based on EDF start time.")
    parser.add_argument("folder", type=str, help="Folder to scan for EDF files.")
    args = parser.parse_args()

    scan_and_rename(args.folder)

if __name__ == "__main__":
    main()
