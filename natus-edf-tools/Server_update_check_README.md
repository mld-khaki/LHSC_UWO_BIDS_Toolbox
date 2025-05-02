
# 🔄 Server Update Checker

**Server_update_check.py** is a lightweight file and folder comparison utility for checking updates between two mirrored directory structures. It is ideal for verifying data synchronization between primary and backup research servers, storage volumes, or project directories.

---

## 📌 Summary

This tool compares the contents of two folders (`inpA` vs `inpB`) and:
- Detects missing folders or files in the second path
- Reports updated files based on file size or modification time (1s threshold)
- Ignores specified file extensions (e.g., `.tmp`) if needed
- Outputs a plain text report logging all differences found

It is particularly useful in **clinical research** or **large data server environments** to audit whether mirrored data folders are up to date.

---

## 🚀 Usage

```bash
python Server_update_check.py <original_folder> <compare_folder> --output log.txt --ignore_ext .tmp
```

### Arguments:
- `original_folder`: Path to the source/original directory (`inpA`)
- `compare_folder`: Path to the backup/secondary directory (`inpB`)
- `--output`: (Optional) File to save comparison log (default: `differences.txt`)
- `--ignore_ext`: (Optional) File extension to exclude from comparison

---

## 🧪 Example

```bash
python Server_update_check.py /mnt/serverA/EEG /mnt/serverB/EEG --output diff_log.txt --ignore_ext .log
```

---

## 💡 Output

A text file listing:
- Missing files or folders
- Modified files with size and timestamp differences

---

## ✅ Dependencies

- Python 3.6+
- No third-party libraries required (uses `os`, `time`, `datetime`, `argparse`)

---

## 👨‍💻 Developed by  
**Dr. Milad Khaki**  
Biomedical Data Scientist, LHSC  
`milad.khaki@lhsc.on.ca`
