
# 📁 Folder/File Name Check Utility

**FolderFile_NameCheck.py** is a lightweight command-line tool for verifying the existence of specific files or folders inside a target directory, based on a list of expected names or wildcard patterns.

This is especially useful in neuroscience research pipelines, such as validating the presence of exported SEEG data, annotations, or processing outputs across structured data folders.

---

## 📌 Summary

This script:
- Takes a `.txt` file containing names or patterns (e.g., `sub-001_edf.edf`, `ses-*`, or `sub-*/`)
- Compares them against the contents of a specified directory
- Returns **which expected files/folders were found** and **which were missing**
- Supports pattern matching via `fnmatch` (similar to shell wildcards)
- Differentiates between files and folders using a trailing backslash (`\`) convention

---

## 🧰 Usage

```bash
python FolderFile_NameCheck.py --list patterns.txt --dir /path/to/folder
```

### `--list`  
Text file with expected names or patterns, one per line  
Append `\` to a line to indicate a folder

### `--dir`  
The directory to check for the presence of those names

---

## 🧪 Example Output

```
=== FOUND ===
sub-001_edf.edf
ses-001/

=== NOT FOUND ===
sub-002_edf.edf
ses-999/
```

---

## ✅ Dependencies

- Python 3.6+
- Standard libraries only (`os`, `argparse`, `fnmatch`)

---

## 👨‍💻 Developed by  
**Dr. Milad Khaki**  
Biomedical Data Scientist, LHSC  
`milad.khaki@lhsc.on.ca`
