# EEG Pipeline Generator

This Python script generates a pipeline file for EEG processing based on folders and their associated `.eeg` files. It validates folder names, ensures the required `.eeg` files exist, and creates a text file with the pipeline output.

## Features

- **Folder Validation**:
  - Ensures the input folder exists and contains only valid subfolders.
  - Validates folder names against a specific pattern.
- **File Verification**:
  - Checks for the presence of corresponding `.eeg` files in each subfolder.
- **Pipeline Generation**:
  - Produces a `pipeline_output.txt` file with paths to `.eeg` files and associated settings.

## Folder Naming Pattern

The script expects folder names in the format:

```
<word>~<word>_<hex_number>-<hex_number>-<hex_number>-<hex_number>-<hex_number>
```

### Example
```
John~Doe_4cb8685c-ac32-4cf8-8beb-1d7604f61661
```

## Usage

### Command-Line Execution

Run the script with the folder path as an argument:

```
python generate_pipeline.py \"path/to/folder\"
```

### Interactive Mode

If no folder path is provided as an argument, the script will prompt you to enter a folder path or use the current directory:

```
python generate_pipeline.py
```

## Output

The script creates a `pipeline_output.txt` file in the input folder. Each line of the file follows this format:

```
<folder_path>\\<folder_name>.eeg, D:\\Neuroworks\\Settings\\quantum_new.exp
```

### Example
```
C:\\Data\\John~Doe_4cb8685c-ac32-4cf8-8beb-1d7604f61661\\John~Doe_4cb8685c-ac32-4cf8-8beb-1d7604f61661.eeg, D:\\Neuroworks\\Settings\\quantum_new.exp
```

## Requirements

- Python 3.x

## Error Handling

The script raises detailed errors for the following scenarios:

- Invalid or non-existent input folder.
- Presence of files instead of folders in the input directory.
- Missing `.eeg` files in subfolders.
- Subfolders not matching the required naming pattern.

## Example Folder Structure

```
input_folder/
├── John~Doe_4cb8685c-ac32-4cf8-8beb-1d7604f61661/
│   └── John~Doe_4cb8685c-ac32-4cf8-8beb-1d7604f61661.eeg
├── ...
```

## Contributing

Contributions are welcome! Feel free to submit issues or pull requests.

## License

This project is licensed under the MIT License.
