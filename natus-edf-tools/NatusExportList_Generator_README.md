
# 📤 Natus Export List Generator

The **NatusExportList_Generator.py** script is a utility for automating the generation of EEG export batch lists. It cross-references a list of expected patient session folders with a main directory and verifies that corresponding `.eeg` files exist. If valid, it outputs a line for each matched file including a constant path (e.g., for Natus export scripts or batch jobs).

---

## 📌 Summary

This tool is especially useful in pre-processing pipelines where:
- EEG sessions need to be batch-exported from the Natus system
- Researchers or EEG techs maintain a folder list for sessions to include
- Each EEG file must be matched with a fixed `.exp` configuration path for export scripting

---

## 🚀 Usage

```bash
python NatusExportList_Generator.py --main_folder D:/NatusExports --folder_list folders.txt --output export_list.txt --constant_path D:\Neuroworks\Settings\quant_new_256_with_photic.exp
```

### Arguments:
- `--main_folder`: Root directory containing EEG session folders  
- `--folder_list`: Text file listing session folder names (one per line)  
- `--output`: Output file to write matching EEG paths + constant path  
- `--constant_path`: Fixed export script path to append per file (default included)

---

## 🧪 Output Example

```
D:\NatusExports\PAT~TEST_2024-04-18-12-00-00\PAT~TEST_2024-04-18-12-00-00.eeg, D:\Neuroworks\Settings\quant_new_256_with_photic.exp
```

---

## ✅ Dependencies

- Python 3.6+
- Uses only standard libraries: `os`, `argparse`, `re`

---

## 👨‍⚕️ Developed by  
**Dr. Milad Khaki**  
Biomedical Data Scientist, LHSC  
`milad.khaki@lhsc.on.ca`
