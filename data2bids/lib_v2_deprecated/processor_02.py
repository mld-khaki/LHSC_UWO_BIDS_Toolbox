import os
import hashlib
import shutil
import logging
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    filename='checksum_copy.log', 
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.info("Script started.")

# Function to calculate MD5 checksum
def calculate_md5(file_path):
    try:
        with open(file_path, 'rb') as f:
            hash_md5 = hashlib.md5()
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        logging.error(f"Error calculating MD5 for {file_path}: {e}")
        return None

# Function to get all files in a directory
def get_all_files(directory):
    file_list = []
    for root, _, files in os.walk(directory):
        for file in files:
            file_list.append(os.path.join(root, file))
    return file_list

# Function to copy a file with error handling
def copy_file(source, destination):
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(source, destination)
        logging.info(f"Copied: {source} to {destination}")
    except Exception as e:
        logging.error(f"Error copying {source} to {destination}: {e}")

# Main function
def main():
    source_dir = "/mnt/newdrive"
    dest_dir = "/volume1/seeg_data/new_drive"

    # Get list of files
    logging.info("Gathering file lists.")
    source_files = get_all_files(source_dir)
    dest_files = get_all_files(dest_dir)

    # Create dictionaries for checksums
    source_checksums = {}
    dest_checksums = {}

    logging.info("Calculating source checksums.")
    for file in tqdm(source_files, desc="Calculating source checksums", unit="file"):
        relative_path = os.path.relpath(file, source_dir)
        source_checksums[relative_path] = calculate_md5(file)
        tqdm.write(f"Processed file: {file} (Relative Path: {relative_path})")

    logging.info("Calculating destination checksums.")
    for file in tqdm(dest_files, desc="Calculating destination checksums", unit="file"):
        relative_path = os.path.relpath(file, dest_dir)
        dest_checksums[relative_path] = calculate_md5(file)
        tqdm.write(f"Processed file: {file} (Relative Path: {relative_path})")

    # Compare checksums and copy missing/mismatched files
    logging.info("Comparing checksums and copying files.")
    for relative_path, source_checksum in tqdm(source_checksums.items(), desc="Copying mismatched or missing files", unit="file"):
        dest_path = os.path.join(dest_dir, relative_path)

        if relative_path not in dest_checksums:
            logging.info(f"File missing in destination: {relative_path}")
            tqdm.write(f"Missing file: {relative_path}")
            copy_file(os.path.join(source_dir, relative_path), dest_path)
        elif dest_checksums[relative_path] != source_checksum:
            logging.info(f"Checksum mismatch for file: {relative_path}")
            tqdm.write(f"Checksum mismatch: {relative_path}")
            copy_file(os.path.join(source_dir, relative_path), dest_path)

    logging.info("Script completed.")

if __name__ == "__main__":
    main()
