
# ⏱️ EDF Time Calculator

The **EDF Time Calculator** is a utility tool designed to determine the precise record range within an EDF file corresponding to a specific time window. It supports both command-line and GUI-based operation and is especially useful for clipping EEG/SEEG recordings with exact temporal boundaries for downstream analysis or anonymization.

---

## 🧩 Summary

This tool calculates the **start and end record indices** based on:
- Total number of records in the EDF
- Total recording duration
- Actual recording start time
- Target window of interest (start and end times)
- Optional pre/post padding (default 30 minutes)

It is frequently used in SEEG data pipelines where accurate subsetting of long recordings is essential for segment extraction or exporting clean clips for review or research.

---

## 🧰 Usage

### CLI Mode

```bash
python EDF_time_calculator.py --total_records 36000 \
    --duration 01:00:00 \
    --start_time 12:00:00 \
    --target_start 12:20:00 \
    --target_end 12:30:00 \
    --pre_offset 15 --post_offset 10
```

### GUI Mode

Simply run without arguments:

```bash
python EDF_time_calculator.py
```

A simple Tkinter interface will prompt you for the required parameters and display the resulting record range.

---

## 💡 Output Example

```
Adjusted Start Time: 12:05:00 -> Record #9000
Adjusted End Time:   12:40:00 -> Record #18000
```

---

## ✅ Dependencies

- Python 3.6+
- Standard libraries only: `argparse`, `datetime`, `tkinter`

---

## 👨‍⚕️ Developed by  
**Dr. Milad Khaki**  
Biomedical Data Scientist, LHSC  
`milad.khaki@lhsc.on.ca`
