import os
import json
import pandas as pd
import shutil
import csv
import argparse
import re

# Extended regex pattern to allow separators like _ , . | -
SEPARATORS = r"[ _\.,\|;\-]+"

def load_names_from_excel(excel_path):
    """Load last and first names, and their variations from an Excel file."""
    df = pd.read_excel(excel_path, usecols=["LastName", "FirstName"], dtype=str)
    df = df.dropna(subset=["LastName", "FirstName"])  # Ensure no NaN values

    last_names = set(df["LastName"].str.strip().tolist())
    first_names = set(df["FirstName"].str.strip().tolist())

    # Generate name variations
    full_names = set()
    reverse_full_names = set()
    
    for _, row in df.iterrows():
        first = row.FirstName.strip()
        last = row.LastName.strip()
        full_names.add(f"{first} {last}")  # Standard
        reverse_full_names.add(f"{last} {first}")  # Last First

        # Variants with common delimiters
        for sep in ["_", ",", ".", "|", ";", "-", "  "]:  # Double space for handling multiple spaces
            full_names.add(f"{first}{sep}{last}")
            reverse_full_names.add(f"{last}{sep}{first}")

    return last_names, first_names, full_names, reverse_full_names

def prompt_user_for_replacement(line, name):
    """Prompt user to confirm name replacement."""
    print(f"Found match: {line.strip()}")
    response = input(f"Replace '{name}' with 'X'? (y or enter/n): ").strip().lower()
    return response in ["y", ""]

def replace_with_case_preserved(text, name):
    """Replace whole word occurrences of `name` with 'X' while preserving the case of the matched text."""
    def replacement(match):
        return "X" if match.group(0)[0].isupper() else "x"
    
    # Updated regex pattern to handle word separations
    pattern = re.compile(rf"\b{re.escape(name)}\b|{re.escape(name).replace(' ', SEPARATORS)}", re.IGNORECASE)
    return pattern.sub(replacement, text)

def process_tsv(file_path, last_names, first_names, full_names, reverse_full_names):
    """Read and redact names in a TSV file."""
    modified_lines = []
    changed = False
    
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter='\t')
        for row in reader:
            new_row = []
            for item in row:
                original_item = item
                for name_set in [last_names, first_names, full_names, reverse_full_names]:
                    for name in name_set:
                        if re.search(rf"\b{re.escape(name)}\b|{re.escape(name).replace(' ', SEPARATORS)}", item, re.IGNORECASE):
                            if prompt_user_for_replacement(item, name):
                                item = replace_with_case_preserved(item, name)
                                changed = True
                new_row.append(item)
            modified_lines.append(new_row)
    
    if changed:
        backup_path = file_path + ".bak"
        shutil.copy(file_path, backup_path)
        
        with open(file_path, "w", encoding="utf-8", newline='') as f:
            writer = csv.writer(f, delimiter='\t')
            writer.writerows(modified_lines)

def process_json(file_path, last_names, first_names, full_names, reverse_full_names):
    """Read and redact names in a JSON file."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    def redact(obj):
        changed = False
        if isinstance(obj, dict):
            return {k: redact(v)[0] for k, v in obj.items()}, changed
        elif isinstance(obj, list):
            return [redact(v)[0] for v in obj], changed
        elif isinstance(obj, str):
            original_obj = obj
            for name_set in [last_names, first_names, full_names, reverse_full_names]:
                for name in name_set:
                    if re.search(rf"\b{re.escape(name)}\b|{re.escape(name).replace(' ', SEPARATORS)}", obj, re.IGNORECASE):
                        if prompt_user_for_replacement(obj, name):
                            obj = replace_with_case_preserved(obj, name)
                            changed = True
            return obj, changed or (obj != original_obj)
        return obj, changed
    
    modified_data, changed = redact(data)
    
    if changed:
        backup_path = file_path + ".bak"
        shutil.copy(file_path, backup_path)
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(modified_data, f, indent=4, ensure_ascii=False)

def search_and_process_files(directory, last_names, first_names, full_names, reverse_full_names):
    """Recursively search for TSV and JSON files and process them."""
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            if file.endswith(".tsv"):
                print(f"Processing file <{file}>", end="")
                process_tsv(file_path, last_names, first_names, full_names, reverse_full_names)
                print("done!")
            elif file.endswith(".json"):
                print(f"Processing file <{file}>", end="")
                process_json(file_path, last_names, first_names, full_names, reverse_full_names)
                print("done!")
            
def main():
    """Main function to parse arguments and execute the script."""
    parser = argparse.ArgumentParser(description="Redact names from TSV and JSON files based on an Excel list.")
    parser.add_argument("excel_path", help="Path to the Excel file containing 'LastName' and 'FirstName' columns.")
    parser.add_argument("folder_path", help="Folder to scan for TSV and JSON files.")
    args = parser.parse_args()
    
    if not os.path.exists(args.excel_path):
        print("Error: Excel file not found.")
        return
    if not os.path.exists(args.folder_path):
        print("Error: Folder not found.")
        return
    
    last_names, first_names, full_names, reverse_full_names = load_names_from_excel(args.excel_path)
    search_and_process_files(args.folder_path, last_names, first_names, full_names, reverse_full_names)
    print("Processing complete.")

if __name__ == "__main__":
    main()
