import os
import hashlib
import errno

def is_file_in_use(file_path):
    """Check if a file is being used by another process."""
    try:
        # Try to open the file in exclusive mode
        fd = os.open(file_path, os.O_RDWR | os.O_EXCL)
        os.close(fd)
        return False  # File is not in use
    except OSError as e:
        if e.errno == errno.EBUSY or e.errno == errno.EACCES:
            return True  # File is in use by another process
        return False  # Other errors indicate it's not in use

def mld_calculate_md5(file_path, display_progress=True, buffer_size = 32*1024*1024):
    """Calculate the MD5 checksum of a file, optionally displaying progress."""
    hash_md5 = hashlib.md5()
    total_size = os.path.getsize(file_path)
    processed_size = 0

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(buffer_size), b""):
            hash_md5.update(chunk)
            processed_size += len(chunk)
            if display_progress:
                progress_percentage = (processed_size / total_size) * 100
                print(f"\rCalculating MD5 for {os.path.basename(file_path)}: {progress_percentage:.2f}%", end='', flush=True)

    if display_progress:
        print()  # Move to the next line after progress is complete

    return hash_md5.hexdigest()

def write_checksum(file_path, checksum):
    """Write the checksum to a file."""
    if checksum:  # Only write if checksum is not None
        checksum_file_path = f"{file_path}.md5"
        with open(checksum_file_path, "w") as f:
            f.write(checksum)

def find_and_process_files(start_path, extensions=['.edf', '.edfz','.rar','.RAR']):
    """Find files with given extensions and calculate/write their MD5 checksums only if they haven't been processed before."""
    files_found = 0
    files_skipped = 0
    for root, dirs, files in os.walk(start_path):
        for file in files:
            if any(file.endswith(ext) for ext in extensions):
                full_path = os.path.join(root, file)
                checksum_file_path = f"{full_path}.md5"
                
                # Check if checksum file already exists
                if os.path.exists(checksum_file_path):
                    print(f"{full_path}, checksum already exists, skipping!")
                    files_skipped += 1
                    continue

                # Check if the file is in use by another process
                if is_file_in_use(full_path):
                    print(f"{full_path} is currently in use by another process, skipping!")
                    files_skipped += 1
                    continue

                print(f"Processing {full_path}")
                checksum = mld_calculate_md5(full_path, display_progress=True)
                write_checksum(full_path, checksum)
                files_found += 1

    if files_found == 0 and files_skipped == 0:
        print("No files found with the specified extensions.")
    else:
        print(f"Processed {files_found} files, skipped {files_skipped} files.")

# Replace 'start_directory_path' with the path of the directory you want to start the search from
#start_directory_path = "/volume1/seeg_data/ieeg_dataset_a/bids/sub-"

#subs = list(range(1, 500))

#for qctr in subs:
#    cur_start_path = start_directory_path + f"{qctr:03.0f}/"
#    find_and_process_files(cur_start_path)
if __name__ == "__main__":
    pass
