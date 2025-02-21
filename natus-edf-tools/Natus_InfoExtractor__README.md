# Extract EEG Metadata

## Overview
This script extracts metadata from Natus EEG files by parsing key-tree formatted content and saves the extracted data to an Excel file.

## Usage
```sh
python extract_eeg_metadata.py <input_dir> [-o output.xlsx]
```

### Arguments:
- `input_dir`: Path to the directory containing `.eeg` files.
- `-o, --output`: (Optional) Output Excel file name. Defaults to `eeg_metadata.xlsx`.

## Installation
Ensure you have Python installed and the required dependencies:
```sh
pip install pandas
```

## Example
```sh
python extract_eeg_metadata.py /data/eeg_files -o metadata_output.xlsx
```

## Features
- Extracts nested key-tree metadata from `.eeg` files.
- Saves results in an Excel file for easy analysis.
- Handles large datasets efficiently.
- Provides error handling and logging.

## License
This project is licensed under the MIT License.

