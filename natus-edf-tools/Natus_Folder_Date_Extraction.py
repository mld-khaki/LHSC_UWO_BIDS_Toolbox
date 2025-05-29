import os
import datetime
from collections import Counter
import argparse
import csv

def get_earliest_timestamp(path):
    stat = os.stat(path)
    created = stat.st_ctime
    modified = stat.st_mtime
    return datetime.datetime.fromtimestamp(min(created, modified)).date()

def get_folder_stats(subfolder_path):
    date_counter = Counter()
    total_size = 0
    total_files = 0

    for root, _, files in os.walk(subfolder_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                date = get_earliest_timestamp(file_path)
                date_counter[date] += 1
                total_files += 1
                total_size += os.path.getsize(file_path)
            except Exception as e:
                print(f"Error reading file {file_path}: {e}")

    if total_files == 0:
        return None

    common_dates = date_counter.most_common(2)
    most_date, most_count = common_dates[0]
    second_date, second_count = common_dates[1] if len(common_dates) > 1 else (None, 0)

    return {
        "folder": os.path.basename(subfolder_path),
        "most_date": most_date.strftime('%Y-%m-%d'),
        "most_count": most_count,
        "second_date": second_date.strftime('%Y-%m-%d') if second_date else '',
        "second_count": second_count,
        "total_files": total_files,
        "total_size": total_size
    }

def scan_and_log(root_folder, prefix, output_csv):
    results = []

    for entry in os.scandir(root_folder):
        if entry.is_dir() and entry.name.startswith(prefix):
            stats = get_folder_stats(entry.path)
            if stats:
                results.append(stats)

    with open(output_csv, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "folder", "most_date", "most_count", "second_date", "second_count",
            "total_files", "total_size"
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"Report written to: {output_csv}")

def main():
    parser = argparse.ArgumentParser(description="Scan folders and report file date distributions.")
    parser.add_argument("root", help="Root folder to scan")
    parser.add_argument("--prefix", default="", help="Only include subfolders starting with this prefix")
    parser.add_argument("--output", default="folder_date_report.csv", help="Output CSV file name")

    args = parser.parse_args()

    if not os.path.isdir(args.root):
        print("Invalid root path.")
        return

    scan_and_log(args.root, args.prefix, args.output)

if __name__ == "__main__":
    main()
