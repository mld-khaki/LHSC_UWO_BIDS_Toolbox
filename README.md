# EEG Data Tools Suite – Comprehensive Repository Summary

This GitHub repository provides a suite of Python tools for processing, analyzing, redacting, and managing EEG data files, primarily focused on EDF and Natus EEG formats. The tools are designed for researchers and clinicians working with large EEG datasets. A centralized GUI script (`_MK_EDF_handler.py`) facilitates launching each tool with the appropriate arguments.

---

## 🧰 Tool Summary

### 1. `_MK_EDF_handler.py`
- A **graphical user interface (GUI)** launcher built with `PySimpleGUI`.
- Supports selecting and running any of the included tools by dynamically presenting required inputs.
- Displays script output within the interface and handles execution errors.

---

### 2. `EDF_dir_scanner.py`
- Recursively scans directories for `.edf` files and **extracts rich metadata**.
- Outputs metadata in `.xlsx`, `.csv`, `.json`, or `.txt` format.
- **Metadata includes** subject info, recording equipment, timestamps, and signal properties.
- Efficiently handles **large datasets**.
- Requires `pandas`, `openpyxl`, and `EDF_reader_mld`.

**Usage Example**:
```
python EDF_dir_scanner.py /path/to/edf/files --output metadata.xlsx
```

---

### 3. `FolderAnalysis.py`
- Counts the number of subdirectories in a given folder **excluding the `code/` folder**.
- Simple and lightweight; no external dependencies.
- Outputs structured folder count.

**Usage Example**:
```
python FolderAnalysis.py
```

---

### 4. `Natus_InfoExtractor.py` & `Natus_InfoServerScraper.py`
- Extracts **deep nested metadata** from Natus `.eeg` files using pattern matching.
- Handles **Excel-style timestamps**, nested key-value trees, and folder statistics (size, # of files, EEG count).
- Saves metadata in Excel for analysis.
- Includes date filtering (`--pattern`) and logging.

**Usage Example**:
```
python Natus_InfoServerScraper.py /path/to/natus/files -o metadata.xlsx -p SUBJECT_
```

**Usage Help Output**:
```
usage: Natus_InfoServerScraper.py [-h] [-o OUTPUT] [-p PATTERN] input_dir
Natus_InfoServerScraper.py: error: the following arguments are required: input_dir
```

---

### 5. `NatusExportList_Generator.py`
- Scans for EEG session folders matching a **strict naming pattern** (1 tilde, 1 underscore, 4 dashes).
- Creates a structured text list of EEG files paired with a **constant configuration path**.
- Useful for **batch exports** with Natus NeuroWorks software.
- No extra dependencies required.

**Usage Example**:
```
python NatusExportList_Generator.py /data/eeg output_list.txt D:\Neuroworks\Settings\quantum_new.exp
```

**Usage Help Output**:
```
Usage: NatusExportList_Generator.py <main_folder> <output_file> [constant_path]
```

---

### 6. `TSV_dates_checker.py`
- Analyzes a TSV file with EEG session data to:
  - Identify **missing days**.
  - Detect **days with insufficient (<23h) recording time**.
  - List **days with multiple sessions**.
- Outputs results to a **log file** with timestamps.
- Useful for **quality control and compliance checks**.

**Usage Example**:
```
python TSV_dates_checker.py sessions.tsv log.txt
```

**Usage Help Output**:
```
usage: TSV_dates_checker.py [-h] tsv_file log_file

Check if daily recording duration meets minimum requirements.

positional arguments:
  tsv_file    Path to the TSV file containing session information
  log_file    Path to the log file (appends logs, does not overwrite)

options:
  -h, --help  show this help message and exit
```

---

### 7. `TSV_JSON_redacting_tool.py`
- Redacts personal identifiers (first/last names) from **TSV and JSON** files.
- Uses a provided Excel list of names.
- Supports multiple name separators and formats.
- Creates **backups** of modified files.
- Processes folders **recursively**.

**Usage Example**:
```
python TSV_JSON_redacting_tool.py names.xlsx /data/files backup_original backup_updated
```

**Usage Help Output**:
```
usage: TSV_JSON_redacting_tool.py [-h] [excel_path] [input_folder] [backup_folder_org] [backup_folder_upd]

Redact names from TSV and JSON files.

positional arguments:
  excel_path         Path to the Excel file
  input_folder       Folder containing TSV/JSON files
  backup_folder_org  Folder to store original files
  backup_folder_upd  Folder2 to store newly generated files

options:
  -h, --help         show this help message and exit
```

---

### 8. `TSV_Participant_Merger.py`
- Merges two TSV files **row-wise** and saves the combined data.
- Ideal for unifying participant metadata from multiple sources.

**Usage Example**:
```
python TSV_Participant_Merger.py file1.tsv file2.tsv merged.tsv
```

**Usage Help Output**:
```
usage: TSV_Participant_Merger.py [-h] file1 file2 output_file

Merge two TSV files row-wise.

positional arguments:
  file1        Path to the first TSV file.
  file2        Path to the second TSV file.
  output_file  Path to save the merged TSV file.

options:
  -h, --help   show this help message and exit
```

---

## ✅ Key Features

- Rich metadata extraction for EDF and Natus EEG formats.
- Redaction of identifiable information.
- File list generation for structured exports.
- Quality control tools for verifying EEG duration coverage.
- Modular CLI tools with a centralized launcher GUI.
- Efficient handling of **large datasets**.
- Licensed under the **MIT License**.

---

## 🧪 Requirements

- Python 3.x
- Dependencies (varies per script): `pandas`, `openpyxl`, `PySimpleGUI`

---

## 🧭 Example Workflows

1. **Scan EDF files** → `EDF_dir_scanner.py`
2. **Extract nested Natus metadata** → `Natus_InfoServerScraper.py`
3. **Redact personal data before sharing** → `TSV_JSON_redacting_tool.py`
4. **Check data coverage over multiple days** → `TSV_dates_checker.py`
5. **Create export list for Natus** → `NatusExportList_Generator.py`
6. **Merge participant info** → `TSV_Participant_Merger.py`

---

## 🔒 License
All scripts are released under the **MIT License**, allowing flexible reuse with attribution.
