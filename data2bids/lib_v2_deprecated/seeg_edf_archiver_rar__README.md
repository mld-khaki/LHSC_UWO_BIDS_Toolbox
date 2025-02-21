# EDF Archiver Script

This script is designed to locate `.edf` files within a specified directory and create `.rar` archives for them using Python's `rarfile` module. It automates the process of archiving `.edf` files, ensuring that each file is compressed and stored as a `.rar` archive in the same directory.

## Key Features
- **Recursive Search**: The script scans the specified directory and all its subdirectories for `.edf` files.
- **RAR Archiving**: Each `.edf` file is archived using the `.rar` format.
- **Logging**: All operations, including success and error messages, are logged to `archive_log.txt`.

## Requirements
- **Operating System**: This script is intended for use on **Linux** systems. The `rarfile` module relies on the `rar` or `unrar` utility, which must be installed and accessible in the system's PATH.
- **Python Modules**: The following Python libraries are required:
  - `os`
  - `rarfile`
  - `logging`
  - `datetime`

## Usage
1. Ensure the `rar` or `unrar` utility is installed on your Linux system.
   ```bash
   sudo apt install rar unrar
   ```
2. Update the `search_dir` variable in the script to the directory containing your `.edf` files.
3. Run the script:
   ```bash
   python edf_archiver.py
   ```
4. Check `archive_log.txt` for details about the archiving process.

## Notes
- **Windows Alternative**: If running on a Windows system, it is recommended to use **WinRAR** for archiving. Configure filters to ensure only `.edf` files are included in the archive.
- **Archive Location**: The `.rar` files are created in the same directory as the original `.edf` files, with the `.rar` extension appended to the original file name.

## Limitations
- **File Type**: Only `.edf` files are processed.
- **Existing Archives**: If a `.rar` archive already exists for a file, the script skips the archiving process.
- **Temp Directory**: The `temp_dir` variable is currently defined but not used.

## Example Directory Structure
Before archiving:
```
/volume1/seeg_data/ieeg_dataset_a/bids/sub-137/
├── file1.edf
├── file2.edf
```

After archiving:
```
/volume1/seeg_data/ieeg_dataset_a/bids/sub-137/
├── file1.edf
├── file1.edf.rar
├── file2.edf
├── file2.edf.rar
```

## License
This script is provided \"as is\" without any warranty. Use at your own risk.
