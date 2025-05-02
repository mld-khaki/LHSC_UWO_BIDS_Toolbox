
# 🛡️ EDF Anonymization Scanner

The **EDF Anonymization Scanner** is a robust Python tool designed to recursively inspect EEG recordings in EDF/EDF+ format to ensure that both the file headers and embedded annotations are free from sensitive personal information. It is part of a larger anonymization and data governance framework supporting clinical neuroscience research infrastructure.

---

## 🔍 Summary

This tool automates privacy validation across thousands of SEEG files by:
- Checking the **EDF header** for patient names, IDs, and dates using regex heuristics.
- Scanning **annotation channels** for names, emails, phone numbers, SSNs, and other identifiable terms.
- Logging every scan, issue, and error to file-based logs and structured CSV output.
- Using **parallel processing** to speed up large-scale directory scans.

If `edflibpy` is installed, it provides deeper inspection of EDF annotation text; otherwise, header-only mode ensures compatibility across environments.

---

## 🧰 Usage

```bash
python EDF_Anonymization_Scanner.py <directory_to_scan> [--output results.csv] [--log_dir logs] [--log_level INFO] [--max_workers 4] [--skip_annotations]
```

### Example:

```bash
python EDF_Anonymization_Scanner.py /mnt/data/edf_sessions --output scan_report.csv --log_level DEBUG
```

---

## 💡 Key Features

- Memory-efficient header scanning using `mmap`
- Annotation inspection with optional `edflibpy` support
- Customizable logging and output structure
- Parallel file processing with progress bars (`tqdm`)
- Outputs CSV report with detailed issue breakdowns

---

## 📦 Output

- **CSV file** listing each non-anonymized file and issue
- **Log files** saved in the `logs/` directory
- Console summary at completion

---

## ✅ Dependencies

- Python 3.7+
- `numpy`
- `tqdm`
- `edflibpy` *(optional, recommended)*
- `concurrent.futures` (standard lib)

Install dependencies:

```bash
pip install numpy tqdm edflibpy
```

---

## 👨‍⚕️ Developed by  
**Dr. Milad Khaki**  
Biomedical Data Scientist, LHSC  
`milad.khaki@lhsc.on.ca`

