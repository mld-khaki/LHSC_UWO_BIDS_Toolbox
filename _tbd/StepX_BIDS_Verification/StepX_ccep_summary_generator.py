# -*- coding: utf-8 -*-
"""
CCEP summary JSON generator (v2p3)

Updated to support three versions of event decoding:
  - decode_events_rev1
  - decode_events_rev2
  - decode_events_rev3

Otherwise does exactly what v2p1 does:
- Parses *_events.tsv and *_channels.tsv in a given folder
- Detects CCEP stim events (short < 20 s, non-high-frequency)
- Extracts stim electrode pairs and associated currents
- Aggregates per stim electrode:
    {
        "stim_electrodes": {
            "LPOp1": {
                "reference": ["LPOp2", ...],
                "currents": [1, 3, 5, ...]
            },
            ...
        },
        "evoked_electrodes": [...]
    }
- Saves JSON next to input files with name:
    sub-<subject>_ses-<session>_run-<run>_ccep_summary.json
"""

import os
import re
import json
from typing import Dict, List, Tuple, Any, Optional, Set

import pandas as pd

# Import decoder functions from ccep_lib
from ccep_lib import (
    decode_events_rev1,
    decode_events_rev2,
    decode_events_rev3,
)


# ------------------------------------------------------------
# Utility: parse subject / session / run from filenames
# ------------------------------------------------------------
def build_flat_stim_channel_summary(
    stim_electrodes: Dict[str, Dict[str, Any]]
) -> List[List[Any]]:
    """
    Build a flat, human-readable summary:
    [
        ["LAHc1", [1, 3]],
        ["LPHc3", [1, 3, 5]],
        ...
    ]
    """
    summary = []

    for ch in sorted(stim_electrodes.keys()):
        currents = stim_electrodes[ch].get("currents", [])
        currents_sorted = sorted(float(c) for c in currents)
        summary.append([ch, currents_sorted])

    return summary


def parse_subject_session_run(folder: str) -> Tuple[str, str, int]:
    """
    Robustly parse subject, session, run from filenames in folder.

    Accepts:
      sub-070_ses-001_task-ccep_run-01_events.tsv
      sub-070_ses-0011_task-ccep_run-01_events.tsv
    """
    pattern = re.compile(
        r"sub-([A-Za-z0-9]+)_ses-([A-Za-z0-9]+).*run-(\d+)",
        re.IGNORECASE
    )

    for f in os.listdir(folder):
        m = pattern.search(f)
        if m:
            subject = m.group(1)
            session = m.group(2)
            run = int(m.group(3))
            return subject, f"ses-{session}", run
        print(f"Failed pattern: {f}")
    raise RuntimeError(
        f"Could not parse subject/session/run from filenames in folder:\n  {folder}"
    )



# ------------------------------------------------------------
# Stim / CCEP parsing helpers (kept from v2p1)
# ------------------------------------------------------------

STIM_PATTERN_RELAY = re.compile(r"Closed relay to (\S+) and (\S+)")
STIM_PATTERN_START = re.compile(r"Start Stimulation from (\S+) to (\S+)")

HIGH_FREQ_KEYWORDS = ("high freq", "high frequency")


def is_high_freq_line(text: str) -> bool:
    """Return True if the line indicates high-frequency stimulation (non-CCEP)."""
    tl = text.lower()
    return any(k in tl for k in HIGH_FREQ_KEYWORDS)


def is_stim_command(text: str) -> bool:
    """Return True if the text is a stimulation command line (relay or start)."""
    if not isinstance(text, str):
        return False
    text = text.strip()
    if not text:
        return False
    if STIM_PATTERN_RELAY.match(text):
        return True
    if STIM_PATTERN_START.match(text):
        return True
    return False


def extract_stim_pair(text: str) -> Optional[Tuple[str, str]]:
    """
    Extract stim pair (electrode1, electrode2) from a stim command line.

    Returns None if no valid pair is found.
    """
    if not isinstance(text, str):
        return None
    text = text.strip()
    m = STIM_PATTERN_RELAY.match(text)
    if m:
        return m.group(1), m.group(2)
    m = STIM_PATTERN_START.match(text)
    if m:
        return m.group(1), m.group(2)
    return None


def contains_electrode_pattern(text: str) -> bool:
    """
    Check if a line contains something that looks like an electrode name:
    region abbreviation + contact number, e.g. LPOp1, RHcMic10, etc.

    Pattern: one or more letters followed by one or more digits.
    """
    if not isinstance(text, str):
        return False
    return bool(re.search(r"[A-Za-z]+[0-9]+", text))


def extract_currents_from_line(text: str) -> List[float]:
    """
    Extract numeric values from a line that is presumed to be a current spec.

    Handles:
      - "1"
      - "3"
      - "5"
      - "3 mA"
      - "current 5 mA"
    etc.

    We treat all found numbers as possible current values.
    """
    if not isinstance(text, str):
        return []
    # Find all integer / float tokens (simple pattern)
    nums = re.findall(r"[-+]?\d*\.?\d+", text)
    currents = []
    for n in nums:
        if n.strip() == "":
            continue
        try:
            # Try int first, then float
            if "." in n:
                val = float(n)
            else:
                val = int(n)
            currents.append(val)
        except ValueError:
            continue
    return currents


# ------------------------------------------------------------
# Evoked channels (from *_channels.tsv)
# ------------------------------------------------------------

GENERIC_CHANNEL_PREFIXES = ("C", "DC")  # e.g., C3, C4, DC01
EXCLUDED_EXACT = set()  # placeholder if we add exact names later
EXCLUDED_CONTAINS = ("osat", "trig", "pr", "pleth", "patient", "event","spo","photic")


def is_generic_channel(name: str) -> bool:
    """
    Return True if the channel name is considered generic/non-evoked.

    Rules:
      - Name starting with 'C' followed by digits (C##), case-insensitive
      - Name starting with 'DC' followed by digits
      - Names that contain: 'osat', 'trig', 'pr', 'pleth', 'patient', 'event' (case-insensitive)
    """
    if not isinstance(name, str):
        return True

    n = name.strip()
    if not n:
        return True

    # Excluded exact names if needed
    if n in EXCLUDED_EXACT:
        return True

    # C##, DC## pattern
    # C followed by digits only
    if re.fullmatch(r"[cC]\d+", n):
        return True
    # DC followed by digits
    if re.fullmatch(r"[dD][cC]\d+", n):
        return True

    # Contains excluded substrings
    nl = n.lower()
    if any(nl.startswith(ex) for ex in EXCLUDED_CONTAINS):
        return True

    return False


def parse_evoked_electrodes_from_channels(channels_tsv_path: str) -> List[str]:
    """
    Parse evoked electrodes from *_channels.tsv.

    All channels that are NOT generic are considered evoked.

    Assumes a 'name' column in the TSV.
    """
    df = pd.read_csv(channels_tsv_path, sep="\t")

    if "name" not in df.columns:
        raise RuntimeError(f"'name' column not found in channels file: {channels_tsv_path}")

    evoked: List[str] = []

    for ch in df["name"]:
        if not isinstance(ch, str):
            continue
        if not is_generic_channel(ch):
            evoked.append(ch.strip())

    # Unique + sorted for stability
    evoked_unique = sorted(set(evoked))
    return evoked_unique

def parse_evoked_electrodes_from_channels_prv(channels_tsv_path: str) -> List[str]:
    """
    Parse evoked electrodes from *_channels.tsv.

    All channels that are NOT generic are considered evoked.

    Assumes a 'name' column in the TSV.
    """
    df = pd.read_csv(channels_tsv_path, sep="\t")

    if "name" not in df.columns:
        raise RuntimeError(f"'name' column not found in channels file: {channels_tsv_path}")

    evoked: List[str] = []

    for ch in df["name"]:
        if not isinstance(ch, str):
            continue
        if not is_generic_channel(ch):
            evoked.append(ch.strip())

    # Unique + sorted for stability
    evoked_unique = sorted(set(evoked))
    return evoked_unique


# ------------------------------------------------------------
# Main extraction using ccep_lib decoders
# ------------------------------------------------------------

def extract_ccep_stim_info_with_decoders(events_tsv_path: str) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """
    Extract CCEP stimulation information from events TSV using ccep_lib decoders.

    Tries decoders in order: rev3 -> rev2 -> rev1
    If all decoders fail or return empty, falls back to v2p1's manual parsing.

    Returns
    -------
    stim_electrodes : dict
        {
            "electrode_name": {
                "reference": [list of paired electrodes],
                "currents": [list of currents]
            },
            ...
        }
    meta : dict
        Metadata about the extraction process
    """
    
    # Read events TSV
    df = pd.read_csv(events_tsv_path, sep="\t")
    
    # Check for onset column
    if "onset" not in df.columns:
        raise RuntimeError(f"'onset' column not found in events file: {events_tsv_path}")
    
    onsets = df["onset"].tolist()
    
    # BIDS commonly uses trial_type, sometimes event (handle both like simplified.py)
    if "trial_type" in df.columns:
        events = df["trial_type"].tolist()
    elif "event" in df.columns:
        events = df["event"].tolist()
    else:
        raise RuntimeError(
            f"Neither 'trial_type' nor 'event' column found in events file: {events_tsv_path}\n"
            f"Found columns: {list(df.columns)}"
        )
    
    # Try decoders in order: rev3 -> rev2 -> rev1
    decoder_chain = [
        ("rev3", decode_events_rev3),
        ("rev2", decode_events_rev2),
        ("rev1", decode_events_rev1),
    ]
    
    events_by_pair = None
    decoder_used = None
    decoder_errors = []
    
    for decoder_name, decoder_func in decoder_chain:
        try:
            # Call decoder with only timestamps and labels (as shown in simplified.py)
            result = decoder_func(onsets, events)
            
            # Check if we got valid output
            if result and isinstance(result, dict) and len(result) > 0:
                events_by_pair = result
                decoder_used = decoder_name
                break
            else:
                decoder_errors.append(f"{decoder_name}: returned empty or invalid result")
        except Exception as e:
            decoder_errors.append(f"{decoder_name}: {type(e).__name__}: {e}")
    
    # If decoders failed or returned empty, fall back to v2p1's manual parsing
    if events_by_pair is None or len(events_by_pair) == 0:
        decoder_errors.append("All decoders failed or returned empty - falling back to manual parsing")
        return extract_ccep_stim_info_manual(events_tsv_path)
    
    # Now convert events_by_pair to the v2p1 stim_electrodes format
    stim_electrodes: Dict[str, Dict[str, Any]] = {}
    
    def ensure_stim_entry(electrode: str) -> Dict[str, Any]:
        """Ensure an entry exists for an electrode in stim_electrodes."""
        if electrode not in stim_electrodes:
            stim_electrodes[electrode] = {
                "reference": set(),
                "currents": set()
            }
        return stim_electrodes[electrode]
    
    # Process each pair and its events
    for pair, events_list in events_by_pair.items():
        if "-" not in pair:
            continue
        
        # Extract electrode names from pair (e.g., "LAHc1-LAHc2")
        parts = pair.split("-", 1)
        if len(parts) != 2:
            continue
        
        stim_a, stim_b = parts
        
        # Ensure entries exist for both electrodes
        entry_a = ensure_stim_entry(stim_a)
        entry_b = ensure_stim_entry(stim_b)
        
        # Update references (pairs are detected even without currents)
        entry_a["reference"].add(stim_b)
        entry_b["reference"].add(stim_a)
        
        # Extract currents from events (if available)
        currents_for_pair: Set[float] = set()
        for timestamp, value in events_list:
            # Try to convert value to float (current)
            try:
                current = float(value)
                currents_for_pair.add(current)
            except (ValueError, TypeError):
                # If value is not numeric, that's okay - we still have the pair
                pass
        
        # Update currents if we found any
        if currents_for_pair:
            entry_a["currents"].update(currents_for_pair)
            entry_b["currents"].update(currents_for_pair)
    
    # Convert sets to sorted lists
    for elec, data in stim_electrodes.items():
        refs: Set[str] = data.get("reference", set())
        curs: Set[float] = data.get("currents", set())
        data["reference"] = sorted(refs)
        data["currents"] = sorted(float(c) for c in curs)
    
    # Build metadata
    ccep_stim_events_found = len(stim_electrodes) > 0
    
    # Check for CCEP indicator lines (LFF, etc.)
    indicator_keywords = ("lff", "lff stim", "f = 1 hz", "f=1hz", "1hz")
    indicator_found = False
    for ev in events:
        if not isinstance(ev, str):
            continue
        evl = ev.lower()
        if any(k in evl for k in indicator_keywords):
            indicator_found = True
            break
    
    warnings = []
    if indicator_found and not ccep_stim_events_found:
        warnings.append(
            "CCEP indicator lines (e.g., LFF or F = 1 Hz) were found, but no CCEP stim events "
            "were detected by the decoders."
        )
    if not indicator_found and ccep_stim_events_found:
        warnings.append(
            "CCEP stim events were detected, but no CCEP indicator lines (LFF/LFF STIM/F = 1 Hz) "
            "were found."
        )
    
    meta = {
        "ccep_indicator_lines_found": indicator_found,
        "ccep_stim_events_found": ccep_stim_events_found,
        "decoder_used": decoder_used,
        "decoder_errors": decoder_errors,
        "warnings": warnings
    }
    
    return stim_electrodes, meta


def extract_ccep_stim_info_manual(events_tsv_path: str) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """
    Extract CCEP stimulation information using v2p1's manual parsing logic.
    
    This is a fallback when ccep_lib decoders fail.
    """
    df = pd.read_csv(events_tsv_path, sep="\t")
    
    # Check for onset column
    if "onset" not in df.columns:
        raise RuntimeError(f"'onset' column not found in events file: {events_tsv_path}")
    
    onsets = df["onset"].tolist()
    
    # BIDS commonly uses trial_type, sometimes event
    if "trial_type" in df.columns:
        events = df["trial_type"].tolist()
    elif "event" in df.columns:
        events = df["event"].tolist()
    else:
        raise RuntimeError(
            f"Neither 'trial_type' nor 'event' column found in events file: {events_tsv_path}"
        )

    n_rows = len(df)

    # Track if CCEP indicators present
    indicator_keywords = ("lff", "lff stim", "f = 1 hz", "f=1hz", "ccep")
    indicator_found = False

    stim_electrodes: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []

    # Helper function to ensure entry exists for a stim electrode
    def ensure_stim_entry(electrode: str) -> Dict[str, Any]:
        if electrode not in stim_electrodes:
            stim_electrodes[electrode] = {
                "reference": set(),   # will convert to list later
                "currents": set()     # will convert to list later
            }
        return stim_electrodes[electrode]

    # Detect CCEP indicator lines
    for ev in events:
        if not isinstance(ev, str):
            continue
        evl = ev.lower()
        if any(k in evl for k in indicator_keywords):
            indicator_found = True
            break

    # Iterate rows to find stim lines and assign currents
    for i in range(n_rows - 1):  # up to n-2, so we can compute duration as onset[i+1] - onset[i]
        ev = events[i]
        if not isinstance(ev, str):
            continue
        text = ev.strip()
        if not text:
            continue

        # Skip if this is obviously non-stim
        if not is_stim_command(text):
            continue

        # Exclude high-frequency stim:
        #   - if the line itself contains "high freq"/"high frequency"
        #   - or if the immediately previous line contains these terms
        if is_high_freq_line(text):
            continue
        if i > 0:
            prev_ev = events[i - 1]
            if isinstance(prev_ev, str) and is_high_freq_line(prev_ev):
                # The term appeared right before the stim line -> skip
                continue

        # Compute duration as next_onset - this_onset
        try:
            t0 = float(onsets[i])
            t1 = float(onsets[i + 1])
            duration = t1 - t0
        except Exception:
            # If onsets cannot be parsed, skip this stim
            continue

        # Only keep short stim events (< 20 seconds)
        if duration >= 20.0:
            continue

        # Extract stim pair
        pair = extract_stim_pair(text)
        if pair is None:
            continue
        stim_a, stim_b = pair

        # Collect currents from lines following this stim up to the next stim
        currents_for_this_stim: List[float] = []
        j = i + 1
        while j < n_rows:
            ev_j = events[j]
            if not isinstance(ev_j, str):
                j += 1
                continue

            text_j = ev_j.strip()
            if not text_j:
                j += 1
                continue

            # Stop if we hit another stim command -> next block
            if is_stim_command(text_j):
                break

            # If this line is clearly describing a new electrode (contains electrode-like pattern),
            # we stop collecting currents for the current stim.
            # (We still rely on stim commands for new stim blocks, but this helps avoid
            # misinterpreting electrode lines as current lines.)
            if contains_electrode_pattern(text_j):
                j += 1
                continue

            # Try to extract currents: any numbers in this line
            currents_line = extract_currents_from_line(text_j)
            if currents_line:
                currents_for_this_stim.extend(currents_line)

            # Move on
            j += 1

        # Aggregate into stim_electrodes structure
        if currents_for_this_stim:
            # Ensure entries exist
            entry_a = ensure_stim_entry(stim_a)
            entry_b = ensure_stim_entry(stim_b)

            # Update references
            entry_a["reference"].add(stim_b)
            entry_b["reference"].add(stim_a)

            # Update currents
            for c in currents_for_this_stim:
                entry_a["currents"].add(c)
                entry_b["currents"].add(c)

    # Convert sets to sorted lists
    for elec, data in stim_electrodes.items():
        refs: Set[str] = data.get("reference", set())
        curs: Set[float] = data.get("currents", set())
        data["reference"] = sorted(refs)
        # Sort currents numerically; cast to float for safety
        data["currents"] = sorted(float(c) for c in curs)

    ccep_stim_events_found = len(stim_electrodes) > 0

    if indicator_found and not ccep_stim_events_found:
        warnings.append(
            "CCEP indicator lines (e.g., LFF or F = 1 Hz) were found, but no CCEP stim events "
            "shorter than 20 s were detected."
        )
    if not indicator_found and ccep_stim_events_found:
        warnings.append(
            "CCEP stim events were detected, but no CCEP indicator lines (LFF/LFF STIM/F = 1 Hz) "
            "were found."
        )

    meta = {
        "ccep_indicator_lines_found": indicator_found,
        "ccep_stim_events_found": ccep_stim_events_found,
        "decoder_used": "manual_parsing",
        "decoder_errors": [],
        "warnings": warnings
    }

    return stim_electrodes, meta


# ------------------------------------------------------------
# Main function to build JSON for a folder
# ------------------------------------------------------------

def build_ccep_summary_json(folder: str) -> str:
    """
    Build a CCEP summary JSON for the given folder.

    The folder is expected to contain:
      - exactly one *_events.tsv
      - exactly one *_channels.tsv

    Returns
    -------
    json_path : str
        Full path to the generated JSON file.
    """
    folder = os.path.abspath(folder)

    events_file = None
    channels_file = None

    for f in os.listdir(folder):
        if f.endswith("_events.tsv"):
            events_file = os.path.join(folder, f)
        elif f.endswith("_channels.tsv"):
            channels_file = os.path.join(folder, f)

    if events_file is None:
        raise RuntimeError("Missing *_events.tsv in folder: " + folder)
    if channels_file is None:
        raise RuntimeError("Missing *_channels.tsv in folder: " + folder)

    # Parse subject/session/run
    subject_id, session_id, run = parse_subject_session_run(folder)

    # Extract stim info from events using ccep_lib decoders
    stim_electrodes, meta = extract_ccep_stim_info_with_decoders(events_file)
    
    flat_stim_summary = build_flat_stim_channel_summary(stim_electrodes)


    # Extract evoked electrodes from channels.tsv
    evoked_electrodes = parse_evoked_electrodes_from_channels(channels_file)

    # Build final JSON structure (Option B style with 'reference')
    json_data = {
        "subject": subject_id,
        "session": session_id,
        "run": run,

        # NEW: human-readable flat summary
        "stimulated_channels": flat_stim_summary,

        # existing machine-readable outputs preserved
        "stim_electrodes": stim_electrodes,
        "evoked_electrodes": evoked_electrodes,
        "meta": meta
    }


    # Output filename as: sub-<subject>_ses-<session>_run-<run>_ccep_summary.json
    out_name = f"sub-{subject_id}_{session_id}_run-{run:02d}_ccep_summary.json"
    out_path = os.path.join(folder, out_name)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("{\n")
        f.write(f'  "subject": "{subject_id}",\n')
        f.write(f'  "session": "{session_id}",\n')
        f.write(f'  "run": {run},\n')

        f.write('  "stimulated_channels": ')
        f.write(dump_stimulated_channels_compact(json_data["stimulated_channels"]))
        f.write(",\n")

        # keep the rest pretty-printed
        f.write('  "stim_electrodes": ')
        json.dump(json_data["stim_electrodes"], f, indent=2, ensure_ascii=False)
        f.write(",\n")


        f.write('  "evoked_electrodes": ')
        json.dump(json_data["evoked_electrodes"], f, indent=2, ensure_ascii=False)
        f.write(",\n")

        f.write('  "meta": ')
        json.dump(json_data["meta"], f, indent=2, ensure_ascii=False)
        f.write("\n}")


    return out_path

def dump_stimulated_channels_compact(stimulated_channels):
    """
    Render stimulated_channels as:
    [
      ["LAHc1",[1,3]],
      ["LAHc2",[1,3]],
      ...
    ]
    """
    lines = []
    for ch, currents in stimulated_channels:
        cur_str = ",".join(str(int(c) if c.is_integer() else c) for c in currents)
        lines.append(f'    ["{ch}",[{cur_str}]]')
    return "[\n" + ",\n".join(lines) + "\n  ]"
 
def extract_start_end_from_edf(folder: str):
    """
    Extract start/end datetime from EDF header.
    """
    import pyedflib
    from datetime import timedelta

    edf_files = [f for f in os.listdir(folder) if f.lower().endswith(".edf")]
    if not edf_files:
        return "N/A", "N/A"

    edf_path = os.path.join(folder, edf_files[0])

    with pyedflib.EdfReader(edf_path) as f:
        start_dt = f.getStartdatetime()
        duration_sec = f.getFileDuration()

    end_dt = start_dt + timedelta(seconds=duration_sec)

    return start_dt,end_dt
 
def extract_start_end_from_sidecar(events_tsv_path: str):
    """
    Extract start/end datetime from events.tsv sidecar.
    """
    df = pd.read_csv(events_tsv_path, sep="\t")

    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce").dropna()
        if not ts.empty:
            return ts.iloc[0], ts.iloc[-1]

    if "onset" in df.columns:
        return (
            f"{df['onset'].iloc[0]} s",
            f"{df['onset'].iloc[-1]} s",
        )

    return "N/A", "N/A"
    
from datetime import datetime

def format_excel_row(start_dt, end_dt):
    """
    Format datetimes as:
    YYYY-MM-DD <tab> HH:MM:SS AM <tab> HH:MM:SS PM
    Returns 'N/A' if inputs are not datetimes.
    """
    if not isinstance(start_dt, datetime) or not isinstance(end_dt, datetime):
        return "N/A"

    date_str = start_dt.strftime("%Y-%m-%d")
    start_str = start_dt.strftime("%I:%M:%S %p").lstrip("0")
    end_str = end_dt.strftime("%I:%M:%S %p").lstrip("0")

    return f"{date_str}\t{start_str}\t{end_str}"

 # \n\n {start_dt.strftime("%Y-%m-%d %I:%M:%S %p")}\n{end_dt.strftime("%Y-%m-%d %I:%M:%S %p")}"

    
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title("CCEP Summary Generator")
    root.geometry("500x400")

    def choose_folder():
        folder = filedialog.askdirectory()
        if not folder:
            return
        try:
            
            out = build_ccep_summary_json(folder)

            # locate events sidecar
            events_file = next(
                f for f in os.listdir(folder) if f.endswith("_events.tsv")
            )
            events_path = os.path.join(folder, events_file)

            edf_start, edf_end = extract_start_end_from_edf(folder)
            sc_start, sc_end = extract_start_end_from_sidecar(events_path)

            edf_excel = (
                format_excel_row(edf_start, edf_end)
                if edf_start != "N/A" else "N/A"
            )

            sc_excel = (
                format_excel_row(sc_start, sc_end)
                if sc_start != "N/A" else "N/A"
            )

            info = (
                "EDF header (Excel-ready):\n"
                f"{edf_excel}\n\n"
                "Sidecar events.tsv (Excel-ready):\n"
                f"{sc_excel}\n"
            )

            text_box.delete("1.0", "end")
            text_box.insert("1.0", info)

            
        except Exception as e:
            messagebox.showerror("Error", str(e))

    label = tk.Label(
        root,
        text="Select a folder containing *_events.tsv and *_channels.tsv",
        wraplength=480
    )
    label.pack(pady=20)

    btn = tk.Button(root, text="Select Folder", command=choose_folder, width=20)
    btn.pack(pady=10)
    text_box = tk.Text(root, height=10, width=65)
    text_box.pack(padx=10, pady=10)

    root.mainloop()
   

# ------------------------------------------------------------
# CLI entry point (optional)
# ------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate CCEP stim/evoked summary JSON for a CCEP folder (using ccep_lib decoders)."
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=None,
        help="Path to folder containing *_events.tsv and *_channels.tsv"
    )

    args = parser.parse_args()

    if args.folder is None:
        # No CLI argument → GUI mode
        run_gui()
    else:
        # CLI mode
        json_file = build_ccep_summary_json(args.folder)
        print(f"CCEP summary JSON written to:\n  {json_file}")


