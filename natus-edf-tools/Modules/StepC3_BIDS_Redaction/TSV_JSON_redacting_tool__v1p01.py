#!/usr/bin/env python3
# TSV_JSON_redacting_tool_optimized.py
# Author: Dr. Milad Khaki (Updated by ChatGPT)
# Date: 2025-08-13
# Description: Optimized script redacts names from TSV and JSON files using caching, combined Aho–Corasick search, and optimized I/O.
# Usage: python TSV_JSON_redacting_tool_optimized.py <csv_path> <folder_path> <backup_folder_org> <backup_folder_upd>
# License: MIT License

import os
import json
import pandas as pd
import shutil
import csv
import re
import time
import argparse
from functools import lru_cache
import ahocorasick  # Requires: pip install pyahocorasick

# Allow separators like space, underscore, dot, comma, pipe, semicolon, dash
SEP_CLASS = r"[ \t_\.,\|;\-]+"
END_BOUND = r"(?=$|[\s\.,;\|\-\]\)})])"
START_BOUND = r"(?:(?<=^)|(?<=[\s:\(\[\{]))"

ignore_list = [
    "obscur","please","clean","leans","polyspik","adjustin","against","covering","fluttering",
    "leaving","technician","LIAN+","max 2","max 3","max 4","max 5","max 6","max 7","max 8",
    "max 9","max 0","max L","Max L","clear","polys","piano","todd's","todds","quivering",
    "ering","POLYSPIK","against","leaves","Todds","Todd's","sparkling","Clear","unpleasant",
    "leading","PLEASE","variant"," IAn","maximum","Maximum","MAXIMUM"," max ","LIAn","automatic",
    "automatically","auto"
]

def load_names_from_csv(csv_path):
    """Load names from a CSV file and generate variations."""
    df = pd.read_csv(csv_path, usecols=["lastname", "firstname"], dtype=str)
    df.dropna(subset=["lastname", "firstname"], inplace=True)

    last_names = set(df["lastname"].str.strip().tolist())
    first_names = set(df["firstname"].str.strip().tolist())

    full_variants = set()
    reverse_full_variants = set()

    seps = ["", "_", ",", ".", "|", ";", "-", "  ", ", ", ": ", " :", ":"]

    for _, row in df.iterrows():
        first = row["firstname"].strip()
        last = row["lastname"].strip()
        if not first or not last:
            continue

        # Core forms
        full_variants.add(f"{first} {last}")
        reverse_full_variants.add(f"{last} {first}")
        reverse_full_variants.add(f"{last}, {first}")
        reverse_full_variants.add(f"{last}, {first[0]}")
        reverse_full_variants.add(f"{last}, {first[0]}.")

        # Separator variations
        for sep in seps:
            full_variants.add(f"{first}{sep}{last}")
            reverse_full_variants.add(f"{last}{sep}{first}")
            # last + first initial
            reverse_full_variants.add(f"{last}{sep}{first[0]}")
            reverse_full_variants.add(f"{last}{sep}{first[0]}.")

    return last_names, first_names, full_variants, reverse_full_variants

def _compile_ignore_pattern():
    if not ignore_list:
        return None
    # \b ... \b on word-like tokens; keep simple (case-insensitive)
    return re.compile(r'\b(?:' + '|'.join(map(re.escape, ignore_list)) + r')\b', re.IGNORECASE)

_IGNORE_RE = _compile_ignore_pattern()

def _strip_ignored(text: str) -> str:
    if not _IGNORE_RE:
        return text
    return _IGNORE_RE.sub(" ", text)

@lru_cache(maxsize=4096)
def compiled_name_pattern(raw_name: str):
    """
    Build a robust regex that matches:
      - First Last  (with flexible separators)
      - Last, First
      - Last, F or Last, F.
      - When given Last, F it will also match Last, FirstName (expanding the initial)
    """
    name = raw_name.strip()

    # Heuristics to detect "Last, First*" pattern (comma form)
    m_comma = re.match(r"^\s*([A-Za-z'`\-]+)\s*,\s*([A-Za-z])(?:\.|\b)?\s*$", name)
    if m_comma:
        last = re.escape(m_comma.group(1))
        first_initial = re.escape(m_comma.group(2))
        # Allow full first name or just the initial (with optional dot)
        pat = (
            START_BOUND
            + rf"{last}\s*,\s*{first_initial}[A-Za-z]*\.?"
            + END_BOUND
        )
        return re.compile(pat, re.IGNORECASE)

    # Full comma form "Last, FirstName"
    m_comma_full = re.match(r"^\s*([A-Za-z'`\-]+)\s*,\s*([A-Za-z]+)\s*$", name)
    if m_comma_full:
        last = re.escape(m_comma_full.group(1))
        first = re.escape(m_comma_full.group(2))
        # Accept full first or its initial (with any tail letters), to cover variants
        pat = (
            START_BOUND
            + rf"{last}\s*,\s*{first[0]}[A-Za-z]*\.?"
            + END_BOUND
        )
        return re.compile(pat, re.IGNORECASE)

    # "First Last" (space/separator flexible). Also allow First M. Last (optional middle initial)
    m_space = re.match(r"^\s*([A-Za-z]+)\s+([A-Za-z'`\-]+)\s*$", name)
    if m_space:
        first = re.escape(m_space.group(1))
        last = re.escape(m_space.group(2))
        pat = (
            START_BOUND
            + rf"{first}(?:{SEP_CLASS}[A-Za-z]\.?)?{SEP_CLASS}{last}"
            + END_BOUND
        )
        return re.compile(pat, re.IGNORECASE)

    # Fallback: escape the raw string but let separators vary a bit
    # Replace obvious separator runs in the raw with the separator class.
    sepified = re.sub(r"[ \t_\.,\|;\-]+", SEP_CLASS, re.escape(name))
    pat = START_BOUND + sepified + END_BOUND
    return re.compile(pat, re.IGNORECASE)

def replace_with_case_preserved(text: str, raw_name: str) -> (str, bool):
    """Replace matched name variants while preserving case; returns (new_text, changed?)."""
    pat = compiled_name_pattern(raw_name)

    def repl(m):
        token = m.group(0)
        return ".X." if (len(token) and token[0].isupper()) else ".x."

    new_text, n = pat.subn(repl, text)
    return new_text, (n > 0)

def build_automaton(names):
    """Build an Aho–Corasick automaton for fast string matching (lowercased)."""
    A = ahocorasick.Automaton()
    for name in names:
        nm = (name or "").strip()
        if not nm:
            continue
        A.add_word(nm.lower(), nm)
    A.make_automaton()
    return A

def find_matches(text, automaton):
    """Find unique name candidates in text; prefer longer, non-overlapping spans."""
    all_matches = []
    s = text.lower()
    for end, original in automaton.iter(s):
        start = end - len(original) + 1
        all_matches.append((start, end, original))

    # Sort by start asc, end desc (longer first at same start)
    all_matches.sort(key=lambda x: (x[0], -x[1]))

    filtered = []
    if all_matches:
        cur = all_matches[0]
        filtered.append(cur)
        for m in all_matches[1:]:
            if m[0] > cur[1]:
                cur = m
                filtered.append(cur)
            elif m[0] == cur[0] and m[1] > cur[1]:
                filtered[-1] = m
                cur = m
    # Return the raw strings (original forms that were added to the automaton)
    return [m[2] for m in filtered]

def prompt_user_for_replacement(line, raw_name, file):
    """
    Ask user before replacing; uses the same compiled pattern that we'll actually apply,
    so we never prompt for something we can't replace.
    """
    pat = compiled_name_pattern(raw_name)
    tmp_line = _strip_ignored(line)

    if not pat.search(tmp_line):
        return False

    print("=" * 80)
    print(f"\nFound match upd: {tmp_line.strip()}, in file = <{file}>")
    print(f"\nFound match: {line.strip()}")
    resp = input(f"Replace '{raw_name}' (incl. full first name if present) with '.X.'? (y or enter/n): ").strip().lower()
    return resp in ("", "y")

def move_to_backup(original_path, input_folder, backup_folder_org):
    """Move the original file to a backup folder while maintaining the structure."""
    rel_path = os.path.relpath(original_path, input_folder)
    backup_path_org = os.path.join(backup_folder_org, rel_path)
    os.makedirs(os.path.dirname(backup_path_org), exist_ok=True)

    # If target exists, timestamp it.
    if os.path.exists(backup_path_org):
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        base, ext = os.path.splitext(backup_path_org)
        backup_path_org = f"{base}_{timestamp}{ext}"

    shutil.move(original_path, backup_path_org)
    return backup_path_org

def process_tsv(file_path, args, automaton):
    """Process and redact TSV files (safe temp + atomic replace)."""
    changed = False
    temp_file_path = file_path + ".tmp"

    with open(file_path, "r", encoding="utf-8", newline="") as infile, \
         open(temp_file_path, "w", encoding="utf-8", newline="") as outfile:
        reader = csv.reader(infile, delimiter="\t")
        writer = csv.writer(outfile, delimiter="\t")

        for row in reader:
            new_row = []
            for cell in row:
                orig = cell
                # get longest-first matches
                matches = sorted(set(find_matches(cell, automaton)), key=len, reverse=True)
                for raw_name in matches:
                    if prompt_user_for_replacement(cell, raw_name, file_path):
                        cell, did = replace_with_case_preserved(cell, raw_name)
                        if did:
                            changed = True
                            # continue to allow multiple different names within the same cell
                new_row.append(cell)
            writer.writerow(new_row)

    if changed:
        # Copy the redacted temp to "upd" backup, move original to "org", then place the redacted file in place.
        rel_path = os.path.relpath(file_path, args.input_folder)
        backup_path_upd = os.path.join(args.backup_folder_upd, rel_path)
        os.makedirs(os.path.dirname(backup_path_upd), exist_ok=True)
        shutil.copyfile(temp_file_path, backup_path_upd)

        backup_path_org = move_to_backup(file_path, args.input_folder, args.backup_folder_org)
        os.replace(temp_file_path, file_path)
        print(f" - Redacted TSV file. Original moved to {backup_path_org}, updated copy saved to {backup_path_upd}")
    else:
        os.remove(temp_file_path)
        print(" - No changes needed in TSV file.")

    return changed

def process_json(file_path, args, automaton):
    """Process and redact JSON files (safe temp + atomic replace, same as TSV)."""
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print(" - Error: Invalid JSON file.")
            return False

    def redact(obj):
        changed = False
        if isinstance(obj, dict):
            new_d = {}
            for k, v in obj.items():
                nv, ch = redact(v)
                new_d[k] = nv
                changed |= ch
            return new_d, changed
        elif isinstance(obj, list):
            new_l = []
            for v in obj:
                nv, ch = redact(v)
                new_l.append(nv)
                changed |= ch
            return new_l, changed
        elif isinstance(obj, str):
            s = obj
            matches = sorted(set(find_matches(s, automaton)), key=len, reverse=True)
            for raw_name in matches:
                if prompt_user_for_replacement(s, raw_name, file_path):
                    s2, did = replace_with_case_preserved(s, raw_name)
                    if did:
                        s = s2
                        changed = True
            return s, changed
        else:
            return obj, False

    modified, changed = redact(data)

    if not changed:
        print(" - No changes needed in JSON file.")
        return False

    # Write to temp
    temp_file_path = file_path + ".tmp.json"
    with open(temp_file_path, "w", encoding="utf-8") as f:
        json.dump(modified, f, indent=4, ensure_ascii=False)

    # Save updated copy, move original to org, replace atomically
    rel_path = os.path.relpath(file_path, args.input_folder)
    backup_path_upd = os.path.join(args.backup_folder_upd, rel_path)
    os.makedirs(os.path.dirname(backup_path_upd), exist_ok=True)
    shutil.copyfile(temp_file_path, backup_path_upd)

    backup_path_org = move_to_backup(file_path, args.input_folder, args.backup_folder_org)
    os.replace(temp_file_path, file_path)
    print(f" - Redacted JSON file. Original moved to {backup_path_org}, updated copy saved to {backup_path_upd}")
    return True

def search_and_process_files(args, automaton):
    """Search for files and process them."""
    file_handlers = {
        ".tsv": process_tsv,
        ".json": process_json,
    }
    total_changed = 0

    for root, _, files in os.walk(args.input_folder):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in file_handlers:
                continue
            path = os.path.join(root, fname)
            print(f"Processing {path}...")
            if file_handlers[ext](path, args, automaton):
                total_changed += 1

    print(f"Total files modified: {total_changed}")

def main():
    parser = argparse.ArgumentParser(description="Redact names from TSV and JSON files.")
    parser.add_argument("csv_path", nargs="?", help="Path to the csv file")
    parser.add_argument("input_folder", nargs="?", help="Folder containing TSV/JSON files")
    parser.add_argument("backup_folder_org", nargs="?", help="Folder to store original files")
    parser.add_argument("backup_folder_upd", nargs="?", help="Folder to store newly generated files")

    args = parser.parse_args()

    # Prompt user if any argument is missing
    if not args.csv_path:
        args.csv_path = input("Enter path to csv file (default: e:/iEEG_Demographics.csv): ") or "e:/iEEG_Demographics.csv"
    if not args.input_folder:
        args.input_folder = input("Enter input folder path (default: c:/tmp/all_tsv/): ") or "c:/tmp/all_tsv/"
    if not args.backup_folder_org:
        args.backup_folder_org = input("Enter backup folder for original files' path (default: c:/tmp/backup/org/): ") or "c:/tmp/backup/org/"
    if not args.backup_folder_upd:
        args.backup_folder_upd = input("Enter backup folder for newly gen files' path (default: c:/tmp/backup2/upd/): ") or "c:/tmp/backup2/upd/"

    start_time = time.time()

    print(f"Loading names from {args.csv_path}...")
    last_names, first_names, full_names, reverse_full_names = load_names_from_csv(args.csv_path)

    # Build automaton from all forms
    names_for_ac = set().union(last_names, first_names, full_names, reverse_full_names)
    automaton = build_automaton(names_for_ac)

    print(f"Scanning {args.input_folder}...")
    search_and_process_files(args, automaton)

    print(f"Total execution time: {time.time() - start_time:.2f} seconds")

if __name__ == "__main__":
    main()
