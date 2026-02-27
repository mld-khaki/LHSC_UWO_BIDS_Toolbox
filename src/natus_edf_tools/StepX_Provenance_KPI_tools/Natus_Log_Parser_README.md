
# 📄 Natus Log Parser

The **Natus_Log_Parser.py** script extracts anonymization mappings from standard log files generated during batch EDF anonymization runs. It identifies and records the relationship between input EDF filenames and their corresponding anonymized output filenames — essential for tracking, auditing, and verifying de-identification workflows.

---

## 📌 Summary

This tool reads line-by-line through a Natus anonymization log file to:
- Identify original `.EDF` files being anonymized
- Extract the corresponding anonymized output filenames
- Match and store the input-output pairs
- Export results to CSV for further tracking or compliance review

---

## 🚀 Usage

```bash
python Natus_Log_Parser.py anonymization_log.txt --output_csv mappings.csv
```

### Arguments:
- `log_file`: Path to a `.log` or `.txt` file from the anonymization tool
- `--output_csv`: (Optional) Output file path for saving the input-output mappings in CSV format

---

## 🧪 Example Output

| input               | output                  |
|---------------------|--------------------------|
| EEG01_001_EDF.EDF   | sub-001_ses-001_ieeg.edf |
| EEG02_002_EDF.EDF   | sub-002_ses-001_ieeg.edf |

---

## ✅ Dependencies

- Python 3.6+
- `pandas`
- `re`, `argparse`, `os` (standard libraries)

Install pandas if not already installed:

```bash
pip install pandas
```

---

## 👨‍⚕️ Developed by  
**Dr. Milad Khaki**  
Biomedical Data Scientist, LHSC  
`milad.khaki@lhsc.on.ca`
