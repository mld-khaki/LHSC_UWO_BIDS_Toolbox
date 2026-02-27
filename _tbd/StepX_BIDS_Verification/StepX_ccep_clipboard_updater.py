import json
import pandas as pd
import pyperclip
import sys
import os
import re
from typing import Dict, List, Set, Optional

# ---------------- GUI imports (only used if no args) ----------------
import tkinter as tk
from tkinter import filedialog, messagebox

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

CHECK_MARK = "✓"
EMPTY_CELL = ""

ELECTRODE_PATTERN = re.compile(r"^[A-Za-z]+[A-Za-z0-9]*\d+$")

# ------------------------------------------------------------
# Clipboard electrode parsing
# ------------------------------------------------------------

def try_read_clipboard_electrode_order() -> Optional[List[str]]:
    try:
        clip_text = pyperclip.paste()
    except Exception as e:
        messagebox.showerror("Error", str(e))
        return None

    if not clip_text or not clip_text.strip():
        return None

    lines = [l for l in clip_text.splitlines() if l.strip()]
    if not lines:
        return None

    # Case 1: single header row
    if len(lines) == 1:
        header_cols = [c.strip() for c in lines[0].split("\t")]
        electrodes = [c for c in header_cols if ELECTRODE_PATTERN.match(c)]
        return electrodes if electrodes else None

    # Case 2: first column list
    electrodes = [line.split("\t")[0].strip() for line in lines]

    if electrodes and electrodes[0].lower() in ("electrode", "channel", "name"):
        electrodes = electrodes[1:]

    if not electrodes:
        return None

    if any(not ELECTRODE_PATTERN.match(e) for e in electrodes):
        return None

    return electrodes


def fallback_electrode_order(stim_map: Dict[str, Set[float]]) -> List[str]:
    return sorted(stim_map.keys())


# ------------------------------------------------------------
# JSON loading
# ------------------------------------------------------------

def load_stimulated_channels(json_path: str) -> Dict[str, Set[float]]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "stimulated_channels" not in data:
        raise RuntimeError("JSON does not contain 'stimulated_channels'")

    stim_map: Dict[str, Set[float]] = {}
    for ch, currents in data["stimulated_channels"]:
        stim_map[ch] = {c for c in currents}

    return stim_map


# ------------------------------------------------------------
# Table construction
# ------------------------------------------------------------

def build_wide_table(
    electrode_order: List[str],
    stim_map: Dict[str, Set[float]]
) -> pd.DataFrame:

    all_currents = sorted({c for v in stim_map.values() for c in v})
    columns = ["Electrode"] + [f"{c} mA" for c in all_currents]

    rows = []
    for elec in electrode_order:
        row = {"Electrode": elec}
        currents = stim_map.get(elec, set())
        for c in all_currents:
            row[f"{c} mA"] = CHECK_MARK if c in currents else EMPTY_CELL
        rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def transpose_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    df_t = df.set_index("Electrode").T
    df_t.reset_index(inplace=True)
    df_t.rename(columns={"index": "Current"}, inplace=True)
    return df_t


def merge_clipboard_with_stimulated(
    clipboard_order: List[str],
    stim_map: Dict[str, Set[float]]
) -> List[str]:

    stim_electrodes = set(stim_map.keys())
    ordered, seen = [], set()

    for e in clipboard_order:
        if e not in seen:
            ordered.append(e)
            seen.add(e)

    for e in sorted(stim_electrodes):
        if e not in seen:
            ordered.append(e)
            seen.add(e)

    return ordered


# ------------------------------------------------------------
# Core execution logic (shared by CLI + GUI)
# ------------------------------------------------------------

def run_pipeline(json_path: str) -> str:
    stim_map = load_stimulated_channels(json_path)

    clipboard_order = try_read_clipboard_electrode_order()

    if clipboard_order is None:
        electrode_order = fallback_electrode_order(stim_map)
    else:
        electrode_order = merge_clipboard_with_stimulated(
            clipboard_order,
            stim_map
        )

    df = build_wide_table(electrode_order, stim_map)
    df = transpose_for_excel(df)

    tsv_text = df.to_csv(sep="\t", index=False)
    pyperclip.copy(tsv_text)

    return tsv_text


# ------------------------------------------------------------
# GUI
# ------------------------------------------------------------

def launch_gui():
    root = tk.Tk()
    root.withdraw()

    messagebox.showinfo(
        "Stim JSON → Excel Table",
        "Select the stimulation summary JSON file.\n\n"
        "Result will be copied to clipboard."
    )

    json_path = filedialog.askopenfilename(
        title="Select stimulation summary JSON",
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
    )

    if not json_path:
        return

    try:
        tsv = run_pipeline(json_path)
        messagebox.showinfo(
            "Success",
            "Table copied to clipboard.\n\n"
            "You can now paste directly into Excel / OneDrive."
        )
    except Exception as e:
        messagebox.showerror("Error", str(e))


# ------------------------------------------------------------
# Entry point
# ------------------------------------------------------------

def main():
    if len(sys.argv) == 1:
        # No arguments → GUI
        launch_gui()
    elif len(sys.argv) == 2:
        # CLI
        json_path = sys.argv[1]
        if not os.path.exists(json_path):
            print(f"ERROR: File not found: {json_path}")
            sys.exit(1)

        tsv = run_pipeline(json_path)
        print(tsv)
        print("\n✔ Table copied to clipboard")
    else:
        print("Usage:")
        print("  python stim_json_to_excel_table.py <input_summary.json>")
        print("  python stim_json_to_excel_table.py   (GUI mode)")
        sys.exit(1)


if __name__ == "__main__":
    main()
