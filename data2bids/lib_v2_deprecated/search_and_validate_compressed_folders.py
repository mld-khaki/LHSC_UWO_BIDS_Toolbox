import os
import sys

# Add the required directory to the system path and update the environment variable
cur_path = r'/volume1/seeg_data/code/'
sys.path.append(os.path.abspath(cur_path))
os.environ['PATH'] += os.pathsep + cur_path

from _lhsc_lib.rar_checksum_tester import rar_checksum_eval

# Define the directory to search and the list of required extensions
search_dir = "/volume1/seeg_data/ieeg_dataset_a/bids/"
required_extensions = ['.rar', '.edf']

def folder_contains_all_extensions(folder_path, extensions):
    """
    Check if a folder contains files with all specified extensions.

    Args:
        folder_path (str): Path to the folder to check.
        extensions (list of str): List of required file extensions.

    Returns:
        bool: True if the folder contains files with all extensions, False otherwise.
    """
    found_extensions = set()
    print(f"Checking {folder_path}")
    for file in os.listdir(folder_path):
        for ext in extensions:
            if file.lower().endswith(ext.lower()):
                found_extensions.add(ext.lower())
                break  # Stop checking other extensions for this file
    return len(found_extensions) == len(extensions)

def search_folders_with_extensions(directory, extensions):
    """
    Recursively search for folders containing files with all specified extensions.

    Args:
        directory (str): Path to the root directory to search.
        extensions (list of str): List of required file extensions.

    Returns:
        list of str: List of folder paths containing files with all specified extensions.
    """
    matching_folders = []
    for root, dirs, files in os.walk(directory):
        print(f"Checking {root}")
        if folder_contains_all_extensions(root, extensions):
            matching_folders.append(root)
            print(f"Found all extensions in {root}, validating with checksum...")
            rar_checksum_eval(root)  # Validate the folder's content using the checksum evaluator
    return matching_folders

def main():
    """
    Main function to execute the folder search and export the results.
    """
    matching_folders = search_folders_with_extensions(search_dir, required_extensions)
    print(matching_folders)

    # Export the results to a text file
    if matching_folders:
        with open('matching_folders.txt', 'w') as f:
            for folder in matching_folders:
                f.write(folder + '\n')
        print(f"Found {len(matching_folders)} folders with all required extensions. "
              f"Results saved to 'matching_folders.txt'.")
    else:
        print("No matching folders found.")

if __name__ == "__main__":
    main()
