import os
import hashlib
import errno

debug = 1

def is_file_in_use(file_path):
    """
    Check if a file is currently being used by another process.
    
    Args:
        file_path (str): Path to the file to check.
    
    Returns:
        bool: True if the file is in use, False otherwise.
    """
    try:
        # Attempt to open the file in exclusive mode
        fd = os.open(file_path, os.O_RDWR | os.O_EXCL)
        os.close(fd)
        return False  # File is not in use
    except OSError as e:
        # Check for specific errors indicating the file is in use
        if e.errno in {errno.EBUSY, errno.EACCES}:
            return True  # File is in use
        else:
            raise(OSError)
        return False  # Other errors indicate the file is not in use
    except Exception as e:
        if debug == 1:
            raise(e)
    

def mld_calculate_md5(file_path, display_progress=True):
    """
    Calculate the MD5 checksum of a file, with an optional progress display.
    
    Args:
        file_path (str): Path to the file to calculate the checksum for.
        display_progress (bool): Whether to display progress during calculation.
    
    Returns:
        str: The calculated MD5 checksum of the file.
    """
    hash_md5 = hashlib.md5()
    total_size = os.path.getsize(file_path)
    processed_size = 0

    with open(file_path, "rb") as f:
        # Read the file in chunks to avoid memory issues with large files
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
            processed_size += len(chunk)
            if display_progress:
                progress_percentage = (processed_size / total_size) * 100
                print(f"\rCalculating MD5 for {os.path.basename(file_path)}: {progress_percentage:.2f}%", end='', flush=True)

    if display_progress:
        print()  # Print a newline after progress is complete

    return hash_md5.hexdigest()

def write_checksum(file_path, checksum):
    """
    Write the calculated checksum to a file.
    
    Args:
        file_path (str): Path of the original file.
        checksum (str): The calculated checksum to write.
    """
    if checksum:  # Ensure checksum is not None before writing
        checksum_file_path = f"{file_path}.md5"
        with open(checksum_file_path, "w") as f:
            f.write(checksum)

def find_and_process_files(start_path, extensions=['.edf', '.edfz', '.rar', '.RAR']):
    """
    Locate files with specific extensions and generate MD5 checksums if not already processed.
    
    Args:
        start_path (str): The root directory to begin the search.
        extensions (list): A list of file extensions to filter for.
    """
    files_found = 0
    files_skipped = 0

    for root, dirs, files in os.walk(start_path):
        for file in files:
            # Process files with the specified extensions
            if any(file.endswith(ext) for ext in extensions):
                full_path = os.path.join(root, file)
                checksum_file_path = f"{full_path}.md5"

                # Skip if checksum file already exists
                if os.path.exists(checksum_file_path):
                    print(f"{full_path}, checksum already exists, skipping!")
                    files_skipped += 1
                    continue

                # Skip if file is in use by another process
                if is_file_in_use(full_path):
                    print(f"{full_path} is currently in use by another process, skipping!")
                    files_skipped += 1
                    continue

                print(f"Processing {full_path}")
                checksum = mld_calculate_md5(full_path, display_progress=True)
                write_checksum(full_path, checksum)
                files_found += 1

    # Print summary of results
    if files_found == 0 and files_skipped == 0:
        print("No files found with the specified extensions.")
    else:
        print(f"Processed {files_found} files, skipped {files_skipped} files.")

# Main script to iterate over subdirectories and process files
start_directory_path = "/volume1/seeg_data/ieeg_dataset_a/bids/sub-"
subs = list(range(1, 500))  # Range of subdirectories to process

for qctr in subs:
    cur_start_path = start_directory_path
