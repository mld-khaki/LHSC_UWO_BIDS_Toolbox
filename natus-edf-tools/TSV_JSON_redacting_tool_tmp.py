## TSV_JSON_redacting_tool_optimized.py
# Author: Dr. Milad Khaki (Updated by ChatGPT)
# Date: 2025-02-24
# Description: Optimized script redacts names from TSV and JSON files using caching, combined Aho–Corasick search, and optimized I/O.
# Usage: python TSV_JSON_redacting_tool_optimized.py <excel_path> <folder_path> <backup_folder>
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

SEPARATORS = r"[ _\.,\|;\-]+"  # Extended regex pattern for names with separators

ignore_list = ["obscur", "please", "clean", "leans", "polyspik", "adjustin", "against", 
    "covering", "fluttering", "leaving", "technician", "LIAN+", "max 2", "max 3", "max 4",
    "max 5", "max 6", "max 7", "max 8", "max 9", "max 0", "max L", "Max L", "clear", 
    "polys", "piano", "todd's", "todds","quivering","ering","POLYSPIK","leaves",
    "Todds","Todd's","sparkling","Clear","unpleasant","leading","PLEASE","variant"," IAn",
    "maximum","Maximum","MAXIMUM", " max "]

def load_names_from_excel(excel_path):
    """Load names from an Excel file and generate variations."""
    df = pd.read_excel(excel_path, usecols=["LastName", "FirstName"], dtype=str)
    df.dropna(subset=["LastName", "FirstName"], inplace=True)

    last_names = set(df["LastName"].str.strip().tolist())
    first_names = set(df["FirstName"].str.strip().tolist())

    full_names = set()
    reverse_full_names = set()

    for _, row in df.iterrows():
        first, last = row["FirstName"].strip(), row["LastName"].strip()
        full_names.add(f"{first} {last}")
        reverse_full_names.add(f"{last} {first}")

        for sep in ["_", ",", ".", "|", ";", "-", "  "]:
            full_names.add(f"{first}{sep}{last}")
            reverse_full_names.add(f"{last}{sep}{first}")

    return last_names, first_names, full_names, reverse_full_names

def prompt_user_for_replacement(line, name, file):
    pattern = re.compile(r'\b(?:' + '|'.join(map(re.escape, ignore_list)) + r')\b', re.IGNORECASE)
    tmp_line = pattern.sub(" ", line)
    if not any(name.lower() in word for word in tmp_line.lower().split()):
        return False

    print(f"\nFound match: {line.strip()} in file = <{file}>")
    response = input(f"Replace '{name}' with 'X'? (y or enter/n): ").strip().lower()
    return response in ["y", ""]

@lru_cache(maxsize=1024)
def get_compiled_pattern(name):
    """Cache compiled regex pattern for a name."""
    return re.compile(rf"\b{re.escape(name)}\b|{re.escape(name).replace(' ', SEPARATORS)}", re.IGNORECASE)

def replace_with_case_preserved(text, name):
    """Replace whole word occurrences while preserving case."""
    def replacement(match):
        return ".X." if match.group(0).istitle() else ".x."
    
    pattern = get_compiled_pattern(name)
    return pattern.sub(replacement, text)

def build_automaton(names):
    """Build an Aho–Corasick automaton for fast string matching."""
    A = ahocorasick.Automaton()
    for name in names:
        A.add_word(name.lower(), name)
    A.make_automaton()
    return A

def find_matches(text, automaton):
    """Find all unique name matches in text."""
    matches = set()
    lower_text = text.lower()
    for _, original in automaton.iter(lower_text):
        matches.add(original)
    return matches

def move_to_backup(original_path, input_folder, backup_folder_org):
    """Move the original file to a backup folder while maintaining the structure."""
    rel_path = os.path.relpath(original_path, input_folder)
    backup_path_org = os.path.join(backup_folder_org, rel_path)
    if os.path.exists(backup_path_org):
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path_org = f"{backup_path_org}_{timestamp}"
    os.makedirs(os.path.dirname(backup_path_org), exist_ok=True)
    shutil.move(original_path, backup_path_org)
    return backup_path_org

def process_tsv(file_path, args, automaton):
    """Process and redact TSV files."""
    changed = False
    temp_file_path = file_path + ".tmp"

    with open(file_path, "r", encoding="utf-8") as infile, open(temp_file_path, "w", encoding="utf-8", newline='') as outfile:
        reader = csv.reader(infile, delimiter='\t')
        writer = csv.writer(outfile, delimiter='\t')

        for row in reader:
            new_row = [replace_with_case_preserved(cell, name) if name in find_matches(cell, automaton) else cell for cell in row]
            writer.writerow(new_row)
            changed |= new_row != row

    if changed:
        shutil.copy2(file_path, args.backup_folder_upd)
        move_to_backup(file_path, args.input_folder, args.backup_folder_org)
        os.replace(temp_file_path, file_path)
        print(f" - Redacted TSV file: {file_path}")
    else:
        os.remove(temp_file_path)

    return changed

def main():
    parser = argparse.ArgumentParser(description="Redact names from TSV and JSON files.")
    parser.add_argument("excel_path", help="Path to the Excel file")
    parser.add_argument("folder_path", help="Folder containing TSV/JSON files")
    parser.add_argument("backup_folder_org", help="Folder to store original files")
    parser.add_argument("backup_folder_upd", help="Folder to store updated files")
    args = parser.parse_args()
    
    last_names, first_names, full_names, reverse_full_names = load_names_from_excel(args.excel_path)
    automaton = build_automaton(set().union(last_names, first_names, full_names, reverse_full_names))
    search_and_process_files(args, automaton)
    
if __name__ == "__main__":
    main()
