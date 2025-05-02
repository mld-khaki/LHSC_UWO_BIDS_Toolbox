
# 🧠 _MK_EDF_handler: Generalized SEEG Data Tool Launcher

This GUI-based script launcher is designed to help researchers and engineers working with SEEG (stereo-electroencephalography) data easily run and manage a wide variety of Python tools, including anonymization, format checking, session parsing, and EDF conversion.

It is part of a broader infrastructure project supporting LHSC's Epilepsy Monitoring Unit (EMU), aimed at improving reproducibility, privacy, and long-term research storage for intracranial EEG recordings.

---

## 🔧 Key Features

- Unified interface for running over 20 Python-based tools via **PySimpleGUI**
- Auto-loads argument structure from `_MK_EDF_handler_data.py`
- Smart input rendering (file/folder/checkboxes for flags)
- Default arguments pulled from `_MK_EDF_defaults.py`
- Dynamic command preview & clipboard copy
- Load/save configuration as JSON
- Optional output saving for audit logs
- Simple execution wrapper for scripts with stdout capture

---

## 🚀 How to Run

```bash
python _MK_EDF_handler.py
```

---

## 🧰 Required Files

- `_MK_EDF_handler.py` — main launcher GUI  
- `_MK_EDF_handler_data.py` — defines the tools, argument structure, and usage info  
- `_MK_EDF_defaults.py` — optional file for preloading default paths per tool  

---

## 🗂 Supported Tools

Examples of integrated tools include:

- `EDF_Anonymization_Scanner` — scans EDF files for embedded patient data
- `EDF_Compatibility_Check_Tool` — checks EDF files using `edfbrowser.exe`
- `Natus_InfoExtractor` — extracts metadata from Natus-exported EEG data
- `TSV_JSON_redacting_tool` — redacts personal names from structured data
- `EDF_time_calculator` — calculates EDF clip boundaries
- `comparison_two_massive_files` — compares large datasets line-by-line

> View all available tools and their arguments in `_MK_EDF_handler_data.py`.

---

## 🧩 Usage Workflow

1. Launch the GUI.
2. Select a tool from the list.
3. Required arguments will be shown with appropriate UI elements (file/folder pickers, flags).
4. Review the auto-generated command preview.
5. Click `Run` to execute the script.
6. Optionally, save the output or configuration for reproducibility.

---

## 💾 Save & Load Configurations

You can save your selected tool, arguments, and optionally the output to a `.json` configuration file for later reuse.

---

## 📁 Example Default Config (_MK_EDF_defaults.py)

```python
default_args = {
    "EDF_dir_scanner": {
        1: "C:/my/default/edf/folder"
    },
    "Natus_InfoExtractor": {
        1: "D:/input/folder",
        0: "results/output.json"
    },
    "EDF_Compatibility_Check_Tool": {
        0: "C:/Tools/EDFbrowser/edfbrowser.exe"
    }
}
```

---

## ✅ Dependencies

- Python 3.7+
- `PySimpleGUI`
- Your analysis tools/scripts should exist in the same folder or a configured location.

Install GUI dependency if needed:

```bash
pip install PySimpleGUI
```

---

## 📬 Contact

Developed by **Dr. Milad Khaki**  
Biomedical Data Scientist, LHSC  
`milad.khaki@lhsc.on.ca`

---
