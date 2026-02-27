import os
import shutil
import argparse
import pandas as pd
from pathlib import Path

# ------------------------------
# Utility function to validate BIDS-style filename
# ------------------------------
def is_bids_filename(filename):
    """
    Checks if the given filename contains the necessary components for BIDS:
    sub-, ses-, task-, and run-
    """
    return all(x in filename for x in ["sub-", "ses-", "task-", "run-"])

# ------------------------------
# Main processing function
# ------------------------------
def process_excel(excel_file, source_dir, dest_dir, dry_run=False):
    # Read the Excel file into a DataFrame
    df = pd.read_excel(excel_file)

    # Iterate over each row in the spreadsheet
    for idx, row in df.iterrows():
        if str(row.get("Filename A","")) == "nan":
            continue
        else:
            print(row.get("Filename A",""))
        
        match_status = row.get("Match Status", "").strip().lower()
        filename_a = str(row.get("Filename A", ""))
        filename_b = str(row.get("Filename B", ""))
        relative_path_b = row.get("File B Relative Path", "")
        
        # Skip rows that aren't a "unique match" or don't follow BIDS format
        if match_status != "unique match" or not is_bids_filename(filename_a):
            continue
        else:
            print("Proceeding...")

        # Resolve full path to file B
        source_file_b_path = Path(source_dir) / Path(relative_path_b)
        print(f"Full path = <{source_file_b_path}>")
        source_folder = source_file_b_path.parent
        base_filename = source_file_b_path.stem  # Remove extension

        # Construct paths to EDF and EDF_PASS
        edf_file = source_folder / (base_filename + ".edf")
        edf_pass_file = source_folder / (base_filename + ".edf_pass")

        # ------------------------------
        # DELETE LOGIC: Remove .edf only if .edf_pass exists
        # ------------------------------
        if edf_file.exists() and edf_pass_file.exists():
            if not dry_run:
                edf_file.unlink()
            print(f"[DELETE] {edf_file}")

        # ------------------------------
        # MOVE LOGIC: Move .edf_pass and other associated files
        # ------------------------------
        # Construct the destination folder path using BIDS-style filename and A's relative path
        bids_base = Path(filename_a).stem  # Strip extension from filename A
        file_a_rel_path = Path(row.get("File A Relative Path", ""))
        
        fold_out = str(file_a_rel_path.parent / bids_base).replace("/","_").replace("\\","_").replace("-","_")

        dest_folder = Path(dest_dir) / fold_out 
        
        
        # Create destination folder if it doesn't exist
        if not dry_run:
            dest_folder.mkdir(parents=True, exist_ok=True)

        # Move all associated files (same base name, non-.edf extension)
        for file in source_folder.glob(base_filename + ".*"):
            if file.suffix.lower() == ".edf":
                continue  # Skip .edf file
            dest_file_path = dest_folder / file.name
            if not dry_run:
                shutil.move(str(file), str(dest_file_path))
            print(f"[MOVE] {file} -> {dest_file_path}")

# ------------------------------
# Argument parsing
# ------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean and move EDF-related files based on Excel match info.")
    parser.add_argument("--excel", required=True, help="Path to the Excel file.")
    parser.add_argument("--source", required=True, help="Base directory for source files.")
    parser.add_argument("--dest", required=True, help="Base destination directory.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without changes.")
    args = parser.parse_args()

    # Execute main logic
    process_excel(args.excel, args.source, args.dest, args.dry_run)
