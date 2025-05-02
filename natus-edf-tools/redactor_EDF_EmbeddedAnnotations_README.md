
# 🔐 EDF Embedded Annotation Redactor

**redactor_EDF_EmbeddedAnnotations.py** is an advanced, high-precision tool for anonymizing EDF/EDF+ files by redacting patient-identifiable information embedded in both the file header and the annotation channels.

This tool is designed to ensure compliance with research data protection protocols by rewriting headers, scanning time-stamped annotation lists (TALs), and rewriting EDF files with bit-exact data structure matching — preserving compatibility with downstream clinical and research software.

---

## 📌 Summary

This tool:
- Extracts and anonymizes patient metadata from the EDF header (bytes 8–88)
- Parses and redacts personally identifiable strings inside EDF+ annotation channels
- Applies multiple levels of **pattern-based redaction**
- Supports **chunked processing** for large files using memory-mapped I/O
- Preserves signal integrity and data record alignment
- Offers full **verification mode** to compare signal integrity between input and output

---

## 🚀 Usage

### Basic Anonymization

```bash
python redactor_EDF_EmbeddedAnnotations.py input.edf output.edf
```

### With Verification

```bash
python redactor_EDF_EmbeddedAnnotations.py input.edf output.edf --verify --verify_level thorough
```

---

## 🔍 Features

- ✔️ Multi-pass anonymization (header + embedded annotations)
- ✔️ Chunked processing for large EDF files
- ✔️ Structured logging with automatic log file generation
- ✔️ Signal-level comparison verification (optional)
- ✔️ TAL processing to remove names, hospital IDs, patient descriptors

---

## 🧪 Output

- An anonymized EDF file identical in size and structure to the input
- Log files detailing redaction actions and any mismatches found
- (Optional) CSV reports of header/annotation redactions and mismatches

---

## ✅ Dependencies

- Python 3.7+
- `numpy`
- `tqdm`
- `edflibpy`

Install with:

```bash
pip install numpy tqdm edflibpy
```

---

## 👨‍⚕️ Developed by  
**Dr. Milad Khaki**  
Biomedical Data Scientist, LHSC  
`milad.khaki@lhsc.on.ca`
