import os
import sys
import argparse

# Set the default search directory
default_search_dir = "/volume1/seeg_data/ieeg_dataset_a/bids/"
required_extensions = ['.rar', '.edf']

# Function to check if a folder contains files with all specified extensions
def folder_contains_all_extensions(folder_path, extensions):
    found_extensions = set()
    print(f"Checking {folder_path}")
    for file in os.listdir(folder_path):
        for ext in extensions:
            if file.lower().endswith(ext.lower()):
                found_extensions.add(ext.lower())
                break
    return len(found_extensions) == len(extensions)

# Function to recursively search for folders containing files with all specified extensions
def search_folders_with_extensions(directory, extensions):
    matching_folders = []
    for root, dirs, files in os.walk(directory):
        print(f"Checking {root}")
        if folder_contains_all_extensions(root, extensions):
            matching_folders.append(root)
            print(f"Found all extensions in {root}, validating...")
            rar_checksum_eval(root)

    return matching_folders

# Main execution
def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Search folders for required file extensions.")
    parser.add_argument("-s", "--search", type=str, help="Path to the search directory", default=default_search_dir)
    args = parser.parse_args()

    search_dir = args.search
    
    if not os.path.isdir(search_dir):
        print(f"Error: The specified search directory '{search_dir}' does not exist.")
        sys.exit(1)

    matching_folders = search_folders_with_extensions(search_dir, required_extensions)
    print(matching_folders)

    # Export the results
    if matching_folders:
        with open('matching_folders.txt', 'w') as f:
            for folder in matching_folders:
                f.write(folder + '\n')
        print(f"Found {len(matching_folders)} folders with all required extensions. Results saved to 'matching_folders.txt'.")
    else:
        print("No matching folders found.")

if __name__ == "__main__":
    # Adjust the system path and environment variables for the library
    cur_path = r'/volume1/seeg_data/code/'
    sys.path.append(os.path.abspath(cur_path))
    os.environ['PATH'] += os.pathsep + cur_path
    from _lhsc_lib.rar_checksum_tester import rar_checksum_eval

    main()
