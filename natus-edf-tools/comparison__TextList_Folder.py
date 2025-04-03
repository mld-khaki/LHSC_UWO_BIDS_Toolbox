import os
import argparse

def compare_folders(folder_path, txt_file_path):
    # Read list of folder names from txt file
    with open(txt_file_path, 'r') as f:
        expected_folders = set(line.strip() for line in f if line.strip())

    # Get list of actual subfolders
    actual_folders = set(
        name for name in os.listdir(folder_path)
        if os.path.isdir(os.path.join(folder_path, name))
    )

    # Compute differences
    missing_on_disk = expected_folders - actual_folders
    extras_on_disk = actual_folders - expected_folders

    # Report
    print(f"Total expected from list: {len(expected_folders)}")
    print(f"Total found in folder:   {len(actual_folders)}\n")

    print(f"Missing on disk ({len(missing_on_disk)}):")
    for name in sorted(missing_on_disk):
        print(f"  - {name}")

    print(f"\nExtra folders not in list ({len(extras_on_disk)}):")
    for name in sorted(extras_on_disk):
        print(f"  - {name}")

def main():
    parser = argparse.ArgumentParser(description="Compare a folder with a list of expected folders.")
    parser.add_argument('folder', type=str, help='Path to the parent folder containing subfolders')
    parser.add_argument('txtfile', type=str, help='Path to the .txt file listing expected folder names')

    args = parser.parse_args()
    compare_folders(args.folder, args.txtfile)

if __name__ == '__main__':
    main()
