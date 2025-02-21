import os
import sys
import time

# Add the library path dynamically
cur_path = r'/volume1/seeg_data/code/'
sys.path.append(os.path.abspath(cur_path))
cur_path = r'y:\\code\\'
sys.path.append(os.path.abspath(cur_path))
os.environ['PATH'] += os.pathsep + cur_path

from _lhsc_lib.rar_checksum_tester import rar_checksum_eval

# Default search directories
DEFAULT_SEARCH_DIRS = [
    "/volume1/seeg_data/ieeg_dataset_a/bids/",
    "/volume1/seeg_data/ieeg_dataset_b/bids/"
]

required_extensions = ['.rar', '.edf']

def folder_contains_all_extensions(folder_path, extensions):
    found_extensions = set()
    print(f"Checking {folder_path}")
    for file in os.listdir(folder_path):
        for ext in extensions:
            low_ext = ext.lower()
            if file.lower().endswith(low_ext):
                found_extensions.add(low_ext)
                break
    return len(found_extensions) == len(extensions)

def search_folders_with_extensions(directory, extensions):
    matching_folders = []
    for root, dirs, files in os.walk(directory):
        print(f"Checking {root}")
        if folder_contains_all_extensions(root, extensions):
            matching_folders.append(root)
            print(f"Found all extensions in {root}, validating...")
            rar_checksum_eval(root, tmp_dir=cur_path)
    return matching_folders

def scanner(search_dir, required_extensions):
    matching_folders = search_folders_with_extensions(search_dir, required_extensions)
    print(matching_folders)
    if matching_folders:
        with open('matching_folders.txt', 'w') as f:
            for folder in matching_folders:
                f.write(folder + '\n')
        print(f"Found {len(matching_folders)} folders with all required extensions. Results saved to 'matching_folders.txt'.")
    else:
        print("No matching folders found.")

if __name__ == "__main__":
    # Get search directories from arguments or use defaults
    search_dirs = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_SEARCH_DIRS
    
    while True:
        for search_dir in search_dirs:
            scanner(search_dir, required_extensions)
            print("Task is done, waiting for one minute and repeating!")
        time.sleep(60)
