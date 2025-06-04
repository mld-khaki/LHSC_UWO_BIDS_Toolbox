
# 📁 Natus Info Server Scraper

The **Natus_InfoServerScraper.py** script is designed to extract structured metadata from `.eeg` files located in folder hierarchies exported from Natus EEG systems. It enables batch scanning of multiple subject directories using folder name pattern matching and generates detailed Excel summaries of clinical EEG file metadata.

---

## 📌 Summary

This tool recursively scans `.eeg` files matching a folder name pattern, extracting:
- Recording metadata (start time, duration, machine ID)
- Clinical and file-level annotations
- Folder-level statistics: total size, number of files, EEG file count
- All timestamp and duration fields in a structured format

It is tailored for **automated export auditing**, **research preparation**, and **data pipeline validation** in SEEG and EEG recording environments.

---

## 🚀 Usage

```bash
python Natus_InfoServerScraper.py <input_dir> [-o output.xlsx] [-p pattern]
```

### Arguments:
- `input_dir`: Root directory containing subject folders
- `-o, --output`: (Optional) Excel output file name (default: `eeg_metadata.xlsx`)
- `-p, --pattern`: String pattern to match folder names (e.g., "SUB-" or "sub_")

---

## 🔍 Features

- ✅ Excel-style timestamp conversion to readable format
- ✅ Recursive metadata parsing with nested field support
- ✅ Folder-level statistics and logging
- ✅ Lightweight and dependency-minimal
- ✅ Error-tolerant and silent-fail-safe for missing fields

---

## 🧪 Example

```bash
python Natus_InfoServerScraper.py /mnt/data/exports --pattern SUB- --output Server_Metadata.xlsx
```

---

## 📦 Output

- Excel spreadsheet containing:
  - Study and folder identifiers
  - File size summaries
  - Duration and timing info
  - Full flattened metadata for downstream search/indexing

---

## ✅ Dependencies

- Python 3.7+
- `pandas`
- `openpyxl`

Install with:

```bash
pip install pandas openpyxl
```

---

## 👨‍⚕️ Developed by  
**Dr. Milad Khaki**  
Biomedical Data Scientist, LHSC  
`milad.khaki@lhsc.on.ca`
