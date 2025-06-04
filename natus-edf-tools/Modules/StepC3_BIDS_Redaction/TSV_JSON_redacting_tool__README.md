# Redact Names from TSV and JSON Files

## Overview
This script redacts names from TSV and JSON files based on an Excel list of names. The script searches for occurrences of names in the files and replaces them with "X" while preserving case sensitivity.

## Usage
```sh
python redact_names.py <excel_path> <folder_path>
```

### Arguments:
- `excel_path`: Path to the Excel file containing "LastName" and "FirstName" columns.
- `folder_path`: Path to the folder containing TSV and JSON files to process.

## Installation
Ensure you have Python installed and install the required dependencies:
```sh
pip install pandas
```

## Example
```sh
python redact_names.py names.xlsx /path/to/data
```

## Features
- Supports various name formats and separators (_ , . | -).
- Creates backups of modified files.
- Recursively searches for TSV and JSON files.
- Handles large datasets efficiently.

## License
This project is licensed under the MIT License.

