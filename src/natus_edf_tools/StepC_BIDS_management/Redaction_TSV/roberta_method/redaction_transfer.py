import csv
import shutil
from pathlib import Path

# -------------------------
# Configuration
# -------------------------
csv_file = r"o:\phi_redactor_index.csv"
base_folder = Path(r"o:\ieeg_dataset_z")
output_folder = Path(r"c:\ieeg_dataset_z_org")

# Create output folder if it doesn't exist
output_folder.mkdir(parents=True, exist_ok=True)

# -------------------------
# Process CSV
# -------------------------
with open(csv_file, newline='', encoding="utf-8") as f:
    reader = csv.DictReader(f)

    for row in reader:
        status = row.get("status", "").strip().lower()

        if status == "processed":
            rel_path = row.get("rel_path", "").strip()

            if not rel_path:
                print("Skipping row with empty rel_path")
                continue

            source_file = base_folder / rel_path
            destination_file = output_folder / rel_path

            try:
                # create destination directory
                destination_file.parent.mkdir(parents=True, exist_ok=True)

                shutil.copy2(source_file, destination_file)
                print(f"Copied: {source_file} -> {destination_file}")

            except FileNotFoundError:
                print(f"Source file not found: {source_file}")
            except Exception as e:
                print(f"Error copying {source_file}: {e}")

print("Done.")