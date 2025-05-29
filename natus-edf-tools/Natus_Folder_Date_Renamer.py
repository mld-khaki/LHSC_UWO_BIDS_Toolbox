import os
import datetime
from collections import Counter
import argparse

def get_earliest_timestamp(path):
    stat = os.stat(path)
    created = stat.st_ctime
    modified = stat.st_mtime
    earliest = min(created, modified)
    return datetime.datetime.fromtimestamp(earliest).astimezone().date()

def process_subfolder(subfolder_path, interactive):
    date_counter = Counter()
    all_files = []

    for root, _, files in os.walk(subfolder_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                file_date = get_earliest_timestamp(file_path)
                date_counter[file_date] += 1
                all_files.append(file_path)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")

    total_files = len(all_files)
    if total_files == 0:
        print(f"No files found in {subfolder_path}")
        return

    most_common_date, count = date_counter.most_common(1)[0]
    percentage = count / total_files * 100

    folder_name = os.path.basename(subfolder_path)
    parent_dir = os.path.dirname(subfolder_path)

    if percentage >= 90:
        new_folder_name = f"{most_common_date.strftime('%Y_%m_%d')}__{folder_name}"
        new_folder_path = os.path.join(parent_dir, new_folder_name)

        if os.path.exists(new_folder_path):
            print(f"Target folder name already exists: {new_folder_path}")
        else:
            os.rename(subfolder_path, new_folder_path)
            print(f"Renamed: {subfolder_path} -> {new_folder_path}")
    else:
        print(f"\nFolder: {subfolder_path}")
        print("File date distribution (based on earliest of created/modified):")
        for date, count in sorted(date_counter.items()):
            print(f"  {date}: {count} file(s)")

        if interactive:
            print("Options:")
            print("  1. Rename using one of the above dates")
            print("  2. Skip renaming")

            choice = input("Enter your choice (1/2): ").strip()
            if choice == '1':
                chosen_date = input("Enter the date (YYYY-MM-DD) from above to use: ").strip()
                try:
                    parsed_date = datetime.datetime.strptime(chosen_date, "%Y-%m-%d").date()
                    new_folder_name = f"{parsed_date.strftime('%Y_%m_%d')}__{folder_name}"
                    new_folder_path = os.path.join(parent_dir, new_folder_name)

                    if os.path.exists(new_folder_path):
                        print(f"Target folder name already exists: {new_folder_path}")
                    else:
                        os.rename(subfolder_path, new_folder_path)
                        print(f"Renamed: {subfolder_path} -> {new_folder_path}")
                except ValueError:
                    print("Invalid date format. Skipping.")
            else:
                print("Skipped.")
        else:
            print("Skipped due to non-interactive mode.")

def scan_and_process_folder(root_folder, interactive):
    for entry in os.scandir(root_folder):
        if entry.is_dir():
            process_subfolder(entry.path, interactive)

def main():
    parser = argparse.ArgumentParser(description="Rename subfolders based on file date uniformity.")
    parser.add_argument("root", help="Root folder to scan")
    parser.add_argument("--interactive", action="store_true", help="Enable interactive prompts for non-uniform folders")

    args = parser.parse_args()

    if not os.path.isdir(args.root):
        print("Invalid path.")
    else:
        scan_and_process_folder(args.root, args.interactive)

if __name__ == "__main__":
    main()
