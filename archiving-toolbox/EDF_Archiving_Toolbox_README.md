
# 🗃️ EDF Archiving and Validation Toolbox

This toolbox provides a suite of command-line tools designed to automate the anonymization, compression, verification, and purging of SEEG/EEG `.edf` files. These tools support secure, reproducible, and storage-efficient data workflows for large-scale neuroscience research archives.

---

## 📌 Tools Summary

### 1. **EDF_RAR_archive_purger.py**
Deletes `.edf` files from archive folders **only if**:
- A `.edf.rar` archive exists
- `.equal` and `.confirm_equal` verification files are present  
Also deletes `.confirm_equal` as part of cleanup. Logs actions.

```bash
python EDF_RAR_archive_purger.py /data/edf_folders
```

---

### 2. **search_and_validate_compressed_folders.py**
Continuously monitors folders for new `.edf` + `.rar` pairs.
- Validates RAR integrity using checksum
- Appends valid folders to a report
- Designed for daemon-like execution (auto-loop every 60 seconds)

```bash
python search_and_validate_compressed_folders.py /exports
```

---

### 3. **search_validate_update_of__compressed_folders.py**
Full processing pipeline:
- Extracts `.edf` from `.rar`
- Redacts using provided function
- Re-compresses and verifies new `.rar`
- Compares MD5s, outputs `.equal` or `.diff`
- Moves confirmed files to a provenance folder

```bash
python search_validate_update_of__compressed_folders.py <input_dir> <provenance_dir>
```

---

## ✅ Features

- 🔐 Ensures anonymization of compressed archives
- 💾 Reduces storage by deleting verified raw EDFs
- ♻️ Guarantees reproducibility via hash matching
- 📦 Organizes clean output into structured provenance directories
- 🧪 Compatible with large-batch archival processing

---

## 🧰 Dependencies

- Python 3.7+
- `rarfile`, `hashlib`, `tqdm`, `logging`
- External: `rar`/`unrar` CLI tools must be available in PATH

Install required Python libs:

```bash
pip install rarfile tqdm
```

---

## 👨‍⚕️ Developed by  
**Dr. Milad Khaki**  
Biomedical Data Scientist, LHSC  
`milad.khaki@lhsc.on.ca`
