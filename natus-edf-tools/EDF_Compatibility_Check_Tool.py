import argparse
import subprocess
import time
from datetime import datetime
import os
import sys

def check_edf_compatibility(edfbrowser_path, edf_file_path):
    start_time = time.time()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    output_file_temp = "output.txt"
    
    # Build the command
    command = [
        edfbrowser_path,
        "--check-compatibility",
        edf_file_path
    ]

    # Run the command and redirect stdout/stderr to file
    with open(output_file_temp, "w", encoding='utf-8') as outfile:
        result = subprocess.run(command, stdout=outfile, stderr=subprocess.STDOUT)

    elapsed = time.time() - start_time

    # Read the output
    with open(output_file_temp, "r", encoding='utf-8') as f:
        output_content = f.read()

    # Determine output extension
    if "NOT a valid EDF" in output_content:
        result_ext = ".edf_fail"
    else:
        result_ext = ".edf_compat"

    # Construct output filename
    base_name = os.path.basename(edf_file_path)
    out_filename = os.path.splitext(base_name)[0] + result_ext
    out_fullpath = os.path.join(os.path.dirname(edf_file_path), out_filename)

    # Write result
    with open(out_fullpath, "w", encoding='utf-8') as f:
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"File: {edf_file_path}\n")
        f.write(f"Elapsed Time: {elapsed:.2f} seconds\n\n")
        f.write("Output:\n")
        f.write(output_content)

    # Cleanup temp
    os.remove(output_file_temp)

    print(f"Done! Result saved to: {out_fullpath}")

def main():
    parser = argparse.ArgumentParser(description="Check EDF file compatibility using EDFbrowser.")
    parser.add_argument('--edfbrowser', required=True, help='Full path to edfbrowser.exe')
    parser.add_argument('--edf', required=True, help='Full path to EDF file')

    args = parser.parse_args()

    if not os.path.isfile(args.edfbrowser):
        print(f"[X] edfbrowser.exe not found: {args.edfbrowser}")
        sys.exit(1)

    if not os.path.isfile(args.edf):
        print(f"[X] EDF file not found: {args.edf}")
        sys.exit(1)

    check_edf_compatibility(args.edfbrowser, args.edf)

if __name__ == "__main__":
    main()
