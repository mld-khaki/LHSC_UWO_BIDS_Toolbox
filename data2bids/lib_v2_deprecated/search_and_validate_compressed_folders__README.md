# Folder Extension Checker and Validator

## Overview
This script recursively searches a specified directory for folders containing files with all required extensions (e.g., `.rar` and `.edf`) and validates the contents using a checksum evaluator.

## Features
- Searches folders recursively for specific file extensions.
- Ensures all required extensions are present in each folder.
- Validates `.rar` files using a checksum evaluator.
- Saves the paths of matching folders to a text file (`matching_folders.txt`).

## Requirements
- Python 3.x
- `_lhsc_lib.rar_checksum_tester` module installed and accessible in the Python environment.
- Access to the directory specified for searching and validation.

## Usage

### 1. Clone or Copy the Script
Save the script in a `.py` file, such as `folder_extension_validator.py`.

### 2. Set Up Required Paths
Modify the following variables in the script to suit your environment:
- `cur_path`: Path to the `_lhsc_lib` directory containing the `rar_checksum_tester` module.
- `search_dir`: Directory to recursively search for folders containing files with the required extensions.

### 3. Run the Script
Execute the script using Python:
```bash
python folder_extension_validator.py
```

### 4. View Results
After execution, the script:
- Prints the paths of all matching folders.
- Saves the matching folder paths in a text file named `matching_folders.txt`.

## Script Details

### Functionality
#### `folder_contains_all_extensions(folder_path, extensions)`
Checks if a folder contains files with all specified extensions.

- **Args**:
  - `folder_path` (str): Path to the folder to check.
  - `extensions` (list of str): List of required file extensions.
- **Returns**: `bool`

#### `search_folders_with_extensions(directory, extensions)`
Recursively searches for folders containing files with all specified extensions and validates `.rar` files.

- **Args**:
  - `directory` (str): Path to the root directory to search.
  - `extensions` (list of str): List of required file extensions.
- **Returns**: `list of str`

#### `main()`
Executes the search and saves the results to a file.

### Example Output
Sample output when matching folders are found:
```text
['/volume1/seeg_data/ieeg_dataset_a/bids/folder1',
 '/volume1/seeg_data/ieeg_dataset_a/bids/folder2']

Found 2 folders with all required extensions. Results saved to 'matching_folders.txt'.
```

## Contributing
Feel free to fork this repository and make pull requests for improvements or additional features.

## License
This script is licensed under the MIT License. See `LICENSE` for details.