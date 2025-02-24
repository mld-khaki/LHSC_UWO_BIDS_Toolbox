**EDF Directory Scanner**

## **Overview**
This script recursively scans a folder for **EDF (European Data Format)** files and extracts their metadata. The extracted information is saved in an Excel, CSV, JSON, or TXT file.

## **Installation**
Make sure you have the required dependencies installed:

```sh
pip install pandas openpyxl
```

Ensure the **EDF_reader_mld** library is available in the system path.

## **Usage**
python EDF_dir_scanner.py <folder> --output <output_file>

### **Arguments**
- `folder`: The directory where EDF files are located.
- `--output`: (Optional) Output file format. Default is `edf_data.xlsx`.

### **Supported Output Formats**
- `.xlsx` (Excel)
- `.xls` (Excel, legacy)
- `.csv` (Comma-separated values)
- `.json` (JSON format)
- `.txt` (Tab-separated text)

## **Example**
Scan a directory and save metadata as an Excel file:

python EDF_dir_scanner.py /path/to/edf/files --output metadata.xlsx
```

Save metadata as a JSON file:

python EDF_dir_scanner.py /path/to/edf/files --output metadata.json
```

## **Features**
✅ Scans recursively for all `.edf` files  
✅ Extracts metadata including:
   - Subject details (name, patient code, gender, birth date)
   - Recording details (technician, equipment, session start)
   - Signal details (sampling rates, physical min/max, digital min/max)  
✅ Saves extracted metadata in **multiple formats**  
✅ Handles large datasets efficiently  

## **License**
This project is licensed under the **MIT License**.
