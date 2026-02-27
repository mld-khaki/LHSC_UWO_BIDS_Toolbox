# MD5 Checksum Generator for SEEG Data Files

This script recursively searches for files with specified extensions (e.g., `.edf`, `.edfz`, `.rar`) in a directory, calculates their MD5 checksums, and writes the checksum to a file. It ensures that files already processed or in use are skipped.

## Features
- **File Filtering**: Processes files with specific extensions (`.edf`, `.edfz`, `.rar`, `.RAR`).
- **Checksum Calculation**: Generates MD5 checksums for files.
- **Progress Display**: Optionally displays progress while calculating the checksum for large files.
- **File Skipping**: Skips files if:
  - A checksum file already exists.
  - The file is in use by another process.
- **Batch Processing**: Processes multiple subdirectories using a loop.

## Requirements
- **Operating System**: Linux is recommended for this script. Ensure appropriate permissions for file access.
- **Python Libraries**: Uses standard Python libraries (`os`, `hashlib`, `errno`).

## Usage
1. Update the `start_directory_path` variable to the base directory containing the files to process.
2. Adjust the `subs` list to reflect the range of subdirectories to process.
3. Run the script:
   ```bash
   python md5_checksum_generator.py
   ```
4. Check the generated `.md5` files in the same directory as the processed files.

## Notes
- **Windows Alternative**: On Windows, consider using tools like `WinMD5` or similar for manual checksum calculation.
- **File Overwriting**: The script will not overwrite existing `.md5` files.
- **Subdirectory Range**: The script processes subdirectories numbered in the format `sub-###` (e.g., `sub-001`, `sub-002`).

## Example Directory Structure
Before processing:
```
/volume1/seeg_data/ieeg_dataset_a/bids/sub-001/
├── file1.edf
├── file2.rar
```

After processing:
```
/volume1/seeg_data/ieeg_dataset_a/bids/sub-001/
├── file1.edf
├── file1.edf.md5
├── file2.rar
├── file2.rar.md5
```

## License
This script is provided \"as is\" without any warranty. Use at your own risk.

