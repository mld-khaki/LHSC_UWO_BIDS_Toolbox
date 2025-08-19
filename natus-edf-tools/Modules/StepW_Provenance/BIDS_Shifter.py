import os
import sys
import argparse
import re
import shutil

def rename_sessions(base_dir, start_from, end_from, start_to, end_to):
    if (end_from - start_from) != (end_to - start_to):
        print("❌ Error: The from-range and to-range must have the same length.")
        sys.exit(1)

    offset = start_to - start_from
    session_pattern = re.compile(r"(ses-)(\d+)(\b|_)")

    for ses_num in range(end_from, start_from - 1, -1):  # reverse to avoid overwriting
        old_ses_str = f"ses-{ses_num:03d}"
        new_ses_str = f"ses-{ses_num + offset:03d}"

        old_ses_path = os.path.join(base_dir, old_ses_str)
        new_ses_path = os.path.join(base_dir, new_ses_str)

        if not os.path.exists(old_ses_path):
            print(f"⚠ Skipping {old_ses_str} (folder not found)")
            continue

        # Rename files inside folder
        for root, dirs, files in os.walk(old_ses_path):
            for filename in files:
                new_filename = session_pattern.sub(
                    lambda m: f"{m.group(1)}{int(m.group(2)) + offset:03d}{m.group(3)}",
                    filename
                )
                if filename != new_filename:
                    old_file_path = os.path.join(root, filename)
                    new_file_path = os.path.join(root, new_filename)
                    os.rename(old_file_path, new_file_path)
                    print(f"   Renamed file: {filename} -> {new_filename}")

        # Rename folder last
        os.rename(old_ses_path, new_ses_path)
        print(f"✅ Renamed folder: {old_ses_str} -> {new_ses_str}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rename session folders and files within a range.")
    parser.add_argument("--change-ses-from", required=True, help="Range to rename from, e.g. 108-112")
    parser.add_argument("--change-ses-to", required=True, help="Range to rename to, e.g. 109-113")
    parser.add_argument("--base-dir", default=".", help="Base directory containing session folders (default: current directory)")

    args = parser.parse_args()

    try:
        start_from, end_from = map(int, args.change_ses_from.split("-"))
        start_to, end_to = map(int, args.change_ses_to.split("-"))
    except ValueError:
        print("❌ Error: Please provide ranges in the format NNN-NNN (e.g., 108-112).")
        sys.exit(1)

    rename_sessions(args.base_dir, start_from, end_from, start_to, end_to)
