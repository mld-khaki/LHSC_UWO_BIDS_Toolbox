import os
import sys
import csv

def check_tsv_file_references(tsv_path, base_dir="."):
    """
    Checks if all files listed in the 'filename' column of a TSV file exist,
    and reports the line number in the TSV for any missing file.
    
    Parameters:
        tsv_path (str): Path to the TSV file.
        base_dir (str): Base directory where the files are located (default: current directory).
    """
    missing_files = []
    
    # Open TSV with tab delimiter
    with open(tsv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        
        if 'filename' not in reader.fieldnames:
            raise ValueError(f"TSV file '{tsv_path}' does not contain a 'filename' column.")
        
        for line_number, row in enumerate(reader, start=2):  # Start at 2 because line 1 is header
            file_path = os.path.join(base_dir, row['filename'])
            if not os.path.isfile(file_path):
                missing_files.append((line_number, file_path))
    
    if missing_files:
        print("❌ Error: The following files are missing:")
        for line_num, mf in missing_files:
            print(f"\r\n  Line {line_num}: {mf}")
            
        print(f"\n{len(missing_files)} file(s) referenced in '{tsv_path}' do not exist.")
        
    else:
        print("✅ All files exist.")

if __name__ == "__main__":
    if os.name == 'nt':  # Check if the operating system is Windows
        os.system('cls')
    else:  # Assume Linux or macOS
        os.system('clear')
        
    if len(sys.argv) < 2:
        print(f"Usage: python {os.path.basename(__file__)} <tsv_file> [base_dir]")
        sys.exit(1)
    
    tsv_file = sys.argv[1]
    base_directory = sys.argv[2] if len(sys.argv) > 2 else "."
    
    check_tsv_file_references(tsv_file, base_directory)
