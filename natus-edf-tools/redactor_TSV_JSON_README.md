
# 🧾 TSV & JSON Name Redactor

The **redactor_TSV_JSON.py** script is a highly optimized and interactive tool designed to scan TSV and JSON files for names and redact them to protect patient privacy. It is intended for use in clinical neuroscience workflows, especially those involving sensitive annotation or metadata files alongside EEG/SEEG recordings.

---

## 📌 Summary

This tool:
- Loads lists of first and last names from an Excel or CSV demographic file
- Builds a powerful **Aho–Corasick automaton** for high-performance multi-pattern matching
- Scans TSV and JSON files for names, prompting the user for interactive replacement decisions
- Preserves formatting and structure of the original files
- Creates backups of both original and redacted files to specified directories

It is an essential tool for validating and safeguarding sensitive patient identifiers in BIDS-compatible research datasets or any structured clinical file exports.

---

## 🚀 Usage

```bash
python redactor_TSV_JSON.py <excel_path> <input_folder> <backup_folder_org> <backup_folder_upd>
```

### Arguments:
- `excel_path`: CSV/Excel file with "FirstName" and "LastName" columns
- `input_folder`: Folder to recursively scan for `.tsv` and `.json` files
- `backup_folder_org`: Backup folder for original (unmodified) files
- `backup_folder_upd`: Folder for updated redacted copies

---

## 🔍 Features

- 🔁 Supports both `.tsv` and `.json` formats  
- ⚡ Uses **Aho–Corasick automaton** for rapid string matching  
- 👤 Prompts user interactively to confirm redaction per match  
- 💾 Maintains complete backups of all changes  
- 🧠 Case-preserving replacements (.X. vs .x.)  
- ⛔ Ignores common false positives via a smart ignore list

---

## 🧪 Example

```bash
python redactor_TSV_JSON.py ieeg_demographics.csv ./data ./backup/original ./backup/updated
```

---

## ✅ Dependencies

- Python 3.6+
- `pandas`
- `pyahocorasick`
- `csv`, `json`, `argparse`, `re`, `shutil`, `os`

Install missing dependencies:

```bash
pip install pandas pyahocorasick
```

---

## 👨‍⚕️ Developed by  
**Dr. Milad Khaki**  
Biomedical Data Scientist, LHSC  
`milad.khaki@lhsc.on.ca`
