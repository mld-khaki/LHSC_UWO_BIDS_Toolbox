# NatusExportList_Generator

## Overview
This script scans a main folder for EEG subdirectories that match a specific naming pattern and generates a text file listing the valid EEG files along with a constant path.

## Usage
```sh
python generate_eeg_list.py <main_folder> <output_file> [constant_path]
```

### Arguments:
- `main_folder`: Path to the main folder containing subdirectories.
- `output_file`: Path to the output text file.
- `constant_path` (optional): A constant path to append to each line in the output file. Defaults to `D:\Neuroworks\Settings\quantum_new.exp`.

## Installation
Ensure you have Python installed. No additional dependencies are required.

## Example
```sh
python generate_eeg_list.py /data/eeg output_list.txt
```

## Features
- Detects subdirectories with EEG files matching a predefined naming pattern.
- Supports customizable constant paths.
- Generates a structured text output listing valid EEG file paths.

## License
This project is licensed under the MIT License.

