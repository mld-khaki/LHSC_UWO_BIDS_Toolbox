"""
EDF Directory Scanner

Author: Dr. Milad Khaki
Created on: Dec 16, 2024

Description:
This script scans a folder recursively for EDF (European Data Format) files and extracts their metadata using the `EDF_reader_mld` library. The extracted information is saved in the specified output format (`.xlsx`, `.csv`, `.json`, `.txt`).

Usage:
    python EDF_dir_scanner.py <folder> --output <output_file>

Arguments:
    folder: The directory to scan for EDF files.
    --output: (Optional) The output file with a supported format.
              Defaults to 'edf_data.xlsx'.

Supported Output Formats:
    - Excel (`.xlsx`, `.xls`)
    - CSV (`.csv`)
    - JSON (`.json`)
    - Tab-separated text (`.txt`)

Requirements:
    - Python 3.x
    - pandas
    - openpyxl (for Excel support)
    - EDF_reader_mld (custom library for reading EDF files)

License:
This project is licensed under the MIT License.
"""

import os
import json
import argparse
import pandas as pd
from pathlib import Path
from openpyxl import Workbook
import sys

# Update system path to include custom EDF reader library
cur_path = r'y:/code/'
sys.path.append(os.path.abspath(cur_path))
os.environ['PATH'] += os.pathsep + cur_path

from _lhsc_lib.EDF_reader_mld import EDFreader

def extract_edf_info(file_path):
    """
    Extracts metadata from an EDF file without reading annotations.
    Extracted fields:
    - Subject Name, Patient Code, Gender, Birth Date, Patient Additional Info
    - Session Start Date, Recording Technician, Equipment Used, Administration Code
    - File Duration (Seconds), Number of Signals, Number of Data Records, Data Record Duration
    - Signal Labels, Sampling Rates, Physical Dimensions
    - Transducer Types, Pre-Filtering Descriptions, Reserved Signal Fields
    - Physical Minimum & Maximum Values, Digital Minimum & Maximum Values
    - Reserved Data Field from EDF Header
    - File Size (Bytes)
    """
    try:
        print(f"Checking file <{file_path}>")
        metadata = {}
        
        reader = EDFreader(file_path, read_annotations=False)

        # General metadata
        metadata["subject_name"] = reader.getPatientName()
        metadata["patient_code"] = reader.getPatientCode()
        metadata["gender"] = reader.getPatientGender()
        metadata["birth_date"] = reader.getPatientBirthDate()
        metadata["patient_additional"] = reader.getPatientAdditional()
        metadata["session_start"] = reader.getStartDateTime()
        metadata["technician"] = reader.getTechnician()
        metadata["equipment"] = reader.getEquipment()
        metadata["admin_code"] = reader.getAdministrationCode()
        metadata["file_duration"] = reader.getFileDuration()
        metadata["num_signals"] = reader.getNumSignals()
        metadata["num_data_records"] = reader.getNumDataRecords()
        metadata["long_data_record_duration"] = reader.getLongDataRecordDuration()

        # Signal-related metadata
        num_signals = reader.getNumSignals()
        metadata["signal_labels"] = [reader.getSignalLabel(i) for i in range(num_signals)]
        metadata["sampling_rates"] = [reader.getSampleFrequency(i) for i in range(num_signals)]
        metadata["physical_dimension"] = [reader.getPhysicalDimension(i) for i in range(num_signals)]
        metadata["transducer"] = [reader.getTransducer(i) for i in range(num_signals)]
        metadata["pre_filter"] = [reader.getPreFilter(i) for i in range(num_signals)]
        metadata["signal_reserved"] = [reader.getSignalReserved(i) for i in range(num_signals)]
        metadata["physical_min"] = [reader.getPhysicalMinimum(i) for i in range(num_signals)]
        metadata["physical_max"] = [reader.getPhysicalMaximum(i) for i in range(num_signals)]
        metadata["digital_min"] = [reader.getDigitalMinimum(i) for i in range(num_signals)]
        metadata["digital_max"] = [reader.getDigitalMaximum(i) for i in range(num_signals)]

        # Reserved data field from header
        metadata["header_reserved"] = reader.getReserved()

        # Close reader
        reader.close()

    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        metadata = {
            "subject_name": None,
            "patient_code": None,
            "gender": None,
            "birth_date": None,
            "patient_additional": None,
            "session_start": None,
            "technician": None,
            "equipment": None,
            "admin_code": None,
            "file_duration": None,
            "num_signals": None,
            "num_data_records": None,
            "long_data_record_duration": None,
            "signal_labels": None,
            "sampling_rates": None,
            "physical_dimension": None,
            "transducer": None,
            "pre_filter": None,
            "signal_reserved": None,
            "physical_min": None,
            "physical_max": None,
            "digital_min": None,
            "digital_max": None,
            "header_reserved": None,
        }

    return metadata

def scan_folder_for_edf(folder, output_file="edf_data.xlsx"):
    """
    Scans a folder for EDF files and extracts metadata into the chosen format.
    Supported formats: .xlsx, .xls, .csv, .json, .txt
    """
    edf_data = []

    # Recursively search for EDF files
    for root, _, files in os.walk(folder):
        for file in files:
            if file.lower().endswith('.edf'):
                file_path = os.path.join(root, file)
                file_size = os.path.getsize(file_path)

                # Extract metadata
                metadata = extract_edf_info(file_path)
                metadata["file_name"] = file
                metadata["file_path"] = file_path
                metadata["file_size_bytes"] = file_size
                edf_data.append(metadata)

    # Convert to Pandas DataFrame
    df = pd.DataFrame(edf_data)

    # Save based on file extension
    file_ext = Path(output_file).suffix.lower()

    if file_ext == ".xlsx":
        df.to_excel(output_file, index=False)
    elif file_ext == ".xls":
        df.to_excel(output_file, index=False, engine='xlwt')
    elif file_ext == ".csv":
        df.to_csv(output_file, index=False)
    elif file_ext == ".json":
        df.to_json(output_file, orient="records", indent=4)
    elif file_ext == ".txt":
        df.to_csv(output_file, index=False, sep="\t")
    else:
        print(f"Unsupported file format '{file_ext}'. Defaulting to .xlsx")
        df.to_excel("edf_data.xlsx", index=False)

    print(f"Data has been saved to {output_file}")

def main():
    parser = argparse.ArgumentParser(
        description="Recursively scan a folder for EDF files and extract metadata into a selected format."
    )
    parser.add_argument("folder", type=str, help="The folder to scan for EDF files.")
    parser.add_argument(
        "--output",
        type=str,
        default="edf_data.xlsx",
        help="Output file name with extension (.xlsx, .xls, .csv, .json, .txt). Default is 'edf_data.xlsx'."
    )
    args = parser.parse_args()

    scan_folder_for_edf(args.folder, args.output)

if __name__ == "__main__":
    main()
