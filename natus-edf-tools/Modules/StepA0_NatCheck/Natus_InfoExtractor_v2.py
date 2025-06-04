import re
import pandas as pd
from pathlib import Path
import os
from datetime import datetime, timedelta

EXCEL_EPOCH = datetime(1899, 12, 30)  # Base date for Excel/Natus timestamps
# Define start position to skip binary header - adjusted to exactly match where metadata starts
BINARY_HEADER_SIZE = 361  # Adjusted from 360 to 361 based on analysis

def convert_excel_date(excel_time):
    """Convert Excel-style floating point date to YYYY-MM-DD HH:MM:SS format safely."""
    try:
        # Extract numeric part if it's within a complex structure
        if isinstance(excel_time, str):
            # Try to extract a number from the string
            match = re.search(r'(\d+\.\d+)', excel_time)
            if match:
                excel_time = float(match.group(1))
            else:
                # If no floating point number, try to find any number
                match = re.search(r'(\d+)', excel_time)
                if match:
                    excel_time = float(match.group(1))
                else:
                    return excel_time  # Return as is if no number found
        
        excel_time = float(excel_time)  # Ensure it's a float
        
        # Ensure the timestamp is within a reasonable range (Natus timestamps should be within 1800-2100)
        if excel_time < 0 or excel_time > 80000:  # Approx 2199-12-31 in Excel format
            return str(excel_time)  # Return as string if out of range

        converted_time = EXCEL_EPOCH + timedelta(days=excel_time)
        return converted_time.strftime("%Y-%m-%d %H:%M:%S")
    
    except (ValueError, TypeError, OverflowError):
        return str(excel_time)  # Return as string if conversion fails

def get_folder_stats(folder_path):
    """Calculate folder size, number of files, and number of EEG files."""
    folder = Path(folder_path)
    total_size = sum(f.stat().st_size for f in folder.glob("**/*") if f.is_file())  # Total size in bytes
    num_files = sum(1 for f in folder.glob("**/*") if f.is_file())  # Total number of files
    num_eeg_files = sum(1 for f in folder.glob("**/*.eeg"))  # Number of .eeg files
    num_eeg_files += sum(1 for f in folder.glob("**/*.ent"))  # Number of .ent files

    return total_size, num_files, num_eeg_files

def find_matching_parenthesis(s, start_pos):
    """Find the position of the matching closing parenthesis."""
    count = 1  # We start after an opening parenthesis
    i = start_pos
    
    while i < len(s) and count > 0:
        if s[i] == '(':
            count += 1
        elif s[i] == ')':
            count -= 1
        i += 1
        
    return i - 1 if count == 0 else -1

def is_binary_or_large(value):
    """Check if a value is binary data or too large to process."""
    # Check if it's a hex value prefixed with "0x"
    if isinstance(value, str):
        if value.startswith("0x"):
            # If it's longer than 128 bytes (256 hex chars plus '0x'), skip it
            if len(value) > 258:  # 0x + 256 chars
                return True
        
        # Skip values with lots of hex-looking data
        if len(value) > 128 and re.search(r'[0-9a-f]{32,}', value.lower()):
            return True
            
        # Skip values that look like binary data dumps
        binary_indicators = ['Bin', 'Montage', 'Data']
        hex_pattern = r'[0-9a-f]{8,}'
        if len(value) > 128 and any(indicator in value for indicator in binary_indicators) and re.search(hex_pattern, value.lower()):
            return True
    
    return False

def direct_extract_simple_value(text, key):
    """Extract a value directly using regex for common patterns."""
    pattern = r'(?:\(\."{0}", "([^"]+)"\))|(?:\(\."{0}", ([0-9.-]+)\))'.format(re.escape(key))
    matches = re.findall(pattern, text)
    if not matches:
        return None
    
    # Return all found values as a list
    values = []
    for match in matches:
        value = match[0] if match[0] else match[1]
        if value and value not in values:
            values.append(value)
    
    if not values:
        return None
    elif len(values) == 1:
        return values[0]
    else:
        return values  # Return a list of multiple values

def extract_simple_value(value_str):
    """Extract a simple value from a string like 'value' or 'number' or nested structure."""
    # If it's binary or too large, return a placeholder
    if is_binary_or_large(value_str):
        return "[BINARY_DATA]"
    
    # If it's a simple quoted string
    if value_str.startswith('"') and value_str.endswith('"'):
        return value_str[1:-1]  # Remove quotes
    
    # If it's a simple number
    if re.match(r'^-?\d+(\.\d+)?$', value_str):
        try:
            return float(value_str)
        except:
            return value_str
    
    # If it starts with "(." it's a nested structure
    if value_str.startswith('(.'):
        # Try to extract the innermost value
        pattern = r'\(\."([^"]+)"\s*,\s*([^)]+)\)'
        matches = re.findall(pattern, value_str)
        if matches:
            # Look for specific key-value pairs that might contain the actual data
            for key, val in matches:
                if key in ['Attributes', 'Value', 'Data'] and not is_binary_or_large(val):
                    return val.strip()
            
            # If no specific key found, return the value part of the last match
            return matches[-1][1].strip()
    
    # Return as is if we can't determine a better value
    return value_str

def extract_all_occurrences(text_content, key_pattern):
    """Extract all occurrences of a key pattern, including variations."""
    # Create a pattern that matches both exact and approximate matches of the key
    base_key = key_pattern.lower()
    
    # Build a comprehensive pattern for different variations of the key
    patterns = [
        r'\(\."{}",\s*"([^"]+)"\)'.format(re.escape(key_pattern)),  # Exact match with quoted value
        r'\(\."{}",\s*([0-9.-]+)\)'.format(re.escape(key_pattern)),  # Exact match with numeric value
        r'\(\."([^"]*{}[^"]*)",\s*"([^"]+)"\)'.format(re.escape(base_key)),  # Partial case-insensitive match with quoted value
        r'\(\."([^"]*{}[^"]*)",\s*([0-9.-]+)\)'.format(re.escape(base_key))   # Partial case-insensitive match with numeric value
    ]
    
    results = []
    
    for pattern in patterns:
        matches = re.finditer(pattern, text_content, re.IGNORECASE)
        for match in matches:
            groups = match.groups()
            if len(groups) == 1:  # Exact key match
                results.append({"key": key_pattern, "value": groups[0]})
            elif len(groups) == 2:  # Partial key match
                results.append({"key": groups[0], "value": groups[1]})
    
    return results

def extract_eeg_metadata(directory):
    """Extract metadata from all .eeg files in directory."""
    all_metadata = []
    
    count = 0
    all_files = []
    for eeg_file in Path(directory).rglob('*.eeg'):
        count += 1
        all_files.append(eeg_file)
    for ent_file in Path(directory).rglob('*.ent'):
        count += 1
        all_files.append(ent_file)

    cnt = 0
    for eeg_file in all_files:
        cnt += 1
        try:
            eeg_name = os.path.basename(eeg_file)
            print(f"({cnt:3.0f}/{count} - {cnt*100/count:.2f}%) Processing: {eeg_file}")
            # Read file content
            with open(eeg_file, 'rb') as f:
                content_bytes = f.read()
                
            # Convert to text, skipping binary header
            text_content = content_bytes[BINARY_HEADER_SIZE:].decode('utf-8', errors='ignore')
            
            # Define critical fields with default values
            critical_fields = {
                'StudyName': None, 'EegNo': None, 'Machine': None, 
                'FirstName': None, 'LastName': None, 'PatientGUID': None,
                'ChartNo': None, 'RecordingStartTime': None, 'RecordingEndTime': None,
                'RecordingTimeSpan': None, 'BirthDate': None, 'Gender': None, 'Age': None,
                'SamplingFreq': None,
                'Creator': None,
                'Reviewer': None,
                'EEG Classification': None,
                'Clinical Interpretation': None,
                'Abnormal Features': None,
                'Normal Background Features': None,
                'Technologist\'s Impression': None,
                'Sleep Features': None,
                'Hyperventilation': None,
                'Photic Stimulation': None,
                'DiagnosisText': None,
                'UseNicoletCortStim': False,
                'Photic Stimulation': None,
                'DiagnosisText': "",
                'FINDINGS': None,
                'LOCATION': None,
            }
            
            # New multi-version storage dictionary
            multi_version_fields = {}
            
            # Direct extraction for key values - store multiple versions
            for key in critical_fields.keys():
                result = direct_extract_simple_value(text_content, key)
                critical_fields[key] = result  # Store in original format for compatibility
                
                # Store all versions found (including variations) in the multi-version dict
                variations = extract_all_occurrences(text_content, key)
                if variations:
                    # Create a normalized key without special characters or spaces for consistent mapping
                    norm_key = re.sub(r'[^a-zA-Z0-9]', '', key).lower()
                    multi_version_fields[norm_key] = []
                    
                    # Add all found variations
                    for var in variations:
                        # Normalize the variation key for matching
                        var_norm_key = re.sub(r'[^a-zA-Z0-9]', '', var["key"]).lower()
                        
                        # Only include if it's close enough to our target key
                        if norm_key in var_norm_key or var_norm_key in norm_key:
                            if isinstance(var["value"], str) and var["value"].strip():
                                multi_version_fields[norm_key].append({
                                    "original_key": var["key"],
                                    "value": var["value"]
                                })
            
            # Special handling for Values section which contains important timestamps
            values_section = re.search(r'\(\."Values", \(\.(.*?)\)\)', text_content, re.DOTALL)
            if values_section:
                values_content = values_section.group(1)
                # Extract recording timestamps - look for all instances
                recording_starts = re.findall(r'"(?:RECORDINGSTARTTIME|StartTime|Start_Time|RecStart)", ([0-9.]+)', values_content, re.IGNORECASE)
                recording_ends = re.findall(r'"(?:RECORDINGENDTIME|EndTime|End_Time|RecEnd)", ([0-9.]+)', values_content, re.IGNORECASE)
                recording_timespans = re.findall(r'"(?:RECORDINGTIMESPAN|TimeSpan|Duration)", "([^"]+)"', values_content, re.IGNORECASE)
                
                # Store all versions of recording times found
                if recording_starts:
                    all_starts = [convert_excel_date(start) for start in recording_starts]
                    critical_fields['RecordingStartTime'] = all_starts[0]  # Original behavior
                    multi_version_fields['recordingstarttime'] = [{"original_key": "RecordingStartTime", "value": start} for start in all_starts]
                
                if recording_ends:
                    all_ends = [convert_excel_date(end) for end in recording_ends]
                    critical_fields['RecordingEndTime'] = all_ends[0]  # Original behavior
                    multi_version_fields['recordingendtime'] = [{"original_key": "RecordingEndTime", "value": end} for end in all_ends]
                
                if recording_timespans:
                    critical_fields['RecordingTimeSpan'] = recording_timespans[0]  # Original behavior
                    multi_version_fields['recordingtimespan'] = [{"original_key": "RecordingTimeSpan", "value": span} for span in recording_timespans]
            
            # Parse metadata recursively
            metadata = parse_metadata(text_content)
            
            # Update metadata with directly extracted critical values (backwards compatibility)
            for key, value in critical_fields.items():
                if value is not None:
                    metadata[key] = value
            
            # Get folder stats
            folder_name = eeg_file.parent.name
            total_size, num_files, num_eeg_files = get_folder_stats(eeg_file.parent)
            
            # Create a structure with important metadata first
            primary_metadata = {
                "StudyName": metadata.get("StudyName", "Unknown"),
                "FolderName": folder_name,
                "FolderSize GB": total_size / (1024**3),
                "NumFiles": num_files,
                "NumEEGFiles": num_eeg_files,
                "EegNo": metadata.get("EegNo", "Unknown"),
                "Machine": metadata.get("Machine", "Unknown"),
                "FirstName": metadata.get("FirstName", ""),
                "LastName": metadata.get("LastName", ""),
                "PatientGUID": metadata.get("PatientGUID", ""),
                "ChartNo": metadata.get("ChartNo", ""),
                "RecordingStartTime": metadata.get("RecordingStartTime", ""),
                "RecordingEndTime": metadata.get("RecordingEndTime", ""),
                "RecordingTimeSpan": metadata.get("RecordingTimeSpan", ""),
                "BirthDate": metadata.get("BirthDate", ""),
                "Gender": metadata.get("Gender", ""),
                "Age": metadata.get("Age", ""),
                "FINDINGS": metadata.get("FINDINGS", ""),
                "LOCATION": metadata.get("LOCATION", ""),
                "SamplingFreq": metadata.get("SamplingFreq", ""),
                "Creator": metadata.get("Creator", ""),
                "Reviewer": metadata.get("Reviewer", ""),
                "EEG_Classification": metadata.get("EEG Classification", ""),
                "Clinical_Interpretation": metadata.get("Clinical Interpretation", ""),
                "Abnormal_Features": metadata.get("Abnormal Features", ""),
                "Normal_Background_Features": metadata.get("Normal Background Features", ""),
                "Technologist_Impression": metadata.get("Technologist's Impression", ""),
                "Sleep_Features": metadata.get("Sleep Features", ""),
                "Hyperventilation": metadata.get("Hyperventilation", ""),
                "Photic_Stimulation": metadata.get("Photic Stimulation", ""),
                "Diagnosis": metadata.get("DiagnosisText", "")                
            }
            
            # Add multi-version fields to the metadata with special prefixes
            for norm_key, versions in multi_version_fields.items():
                # Sort versions to ensure consistency
                versions = sorted(versions, key=lambda x: x["original_key"])
                
                # Add each version with a numeric suffix
                for idx, version in enumerate(versions, 1):
                    # Create a display key that shows both the original key and version number
                    display_key = f"V{idx}_{version['original_key']}"
                    primary_metadata[display_key] = version["value"]
            
            # Extract all duration fields
            duration_keys = [k for k in metadata if "timespan" in k.lower() or "Duration" in k]
            durations = {f"Duration_{i+1}": metadata[k] for i, k in enumerate(duration_keys)}
            
            # Extract all timestamps and dates
            date_keys = []
            for k in metadata:
                kk = k.lower()
                if ("date" in kk) or ("time" in kk) or ("timestamp" in kk):
                    date_keys.append(k)
                    
            print(f"Found {len(date_keys)} date/time fields")
            date_metadata = {k: str(metadata[k]) for k in date_keys}  # Ensure all dates are strings
            
            # Order DataFrame: Primary metadata, Durations, Dates, then others
            ordered_metadata = {}
            ordered_metadata.update(primary_metadata)  # Primary fields first
            ordered_metadata.update(durations)  # Include all extracted duration fields
            ordered_metadata.update(date_metadata)  # Insert extracted timestamps next
            
            # Filter out binary data and add remaining metadata 
            filtered_metadata = {k: v for k, v in metadata.items() 
                              if not is_binary_or_large(str(v)) and 
                              not any(bin_key in k for bin_key in ['Bin', 'Montage', 'DSP', 'Data']) and
                              k not in ordered_metadata}
            ordered_metadata.update(filtered_metadata)  # Append remaining metadata
            
            ordered_metadata["source_file"] = str(eeg_file)  # Track source file
            all_metadata.append(ordered_metadata)
            
        except Exception as e:
            print(f"Error processing {eeg_file}: {e}")
            import traceback
            traceback.print_exc()
            
    return all_metadata
    
def parse_metadata(content, parent_key=""):
    """Extracts key-value pairs recursively from structured data with proper value extraction."""
    metadata = {}
    i = 0
    
    while i < len(content):
        # Look for the pattern (."Key", Value)
        if i+3 < len(content) and content[i:i+3] == '(."':
            # Found a potential key-value pair
            key_start = i + 3
            key_end = content.find('"', key_start)
            
            if key_end != -1:
                key = content[key_start:key_end]
                # Skip to the comma after the key
                comma_pos = content.find(',', key_end)
                
                if comma_pos != -1:
                    # Find the matching closing parenthesis for this entire key-value pair
                    value_start = comma_pos + 1
                    closing_pos = find_matching_parenthesis(content, i+1)
                    
                    if closing_pos != -1:
                        # Extract the value part (between comma and closing parenthesis)
                        value = content[value_start:closing_pos].strip()
                        full_key = f"{parent_key}_{key}" if parent_key else key
                        
                        # Skip binary data and excessively large values (>1024 characters)
                        if len(value) <= 1024 and not is_binary_or_large(value):
                            # Try to get a simple value if possible
                            if value.startswith('(.'):
                                # For nested structures, we extract both the raw value and attempt to parse subcomponents
                                
                                # Check if this is a binary structure we should skip
                                if not any(bin_key in full_key for bin_key in ['Bin', 'Montage', 'DSP']):
                                    # First, parse the nested structure recursively to get all sub-fields
                                    sub_metadata = parse_metadata(value, full_key)
                                    metadata.update(sub_metadata)
                                
                                # For important fields like timestamps, attempt to extract a direct value
                                simple_value = extract_simple_value(value)
                                
                                # Skip binary data placeholder
                                if simple_value != "[BINARY_DATA]":
                                    # Store the extracted value instead of the raw complex structure
                                    metadata[full_key] = simple_value
                                    
                                    # Additional handling for specific fields
                                    if "TimeSpan" in full_key:
                                        # For timespan fields, keep the raw value
                                        metadata[full_key] = value
                                    elif "Time" in full_key or "Date" in full_key or "Timestamp" in full_key:
                                        # For time fields, try to convert extracted value
                                        try:
                                            metadata[full_key] = convert_excel_date(simple_value)
                                        except:
                                            # If conversion fails, keep the simple extracted value
                                            pass
                            else:
                                # For simple values, store them directly
                                # Skip any binary data
                                if not is_binary_or_large(value):
                                    metadata[full_key] = value.strip('"')  # Remove quotes if present
                                    
                                    # Convert timestamps stored as floats
                                    if "Time" in full_key or "Date" in full_key or "Timestamp" in full_key:
                                        if "timespan" not in full_key.lower():
                                            try:
                                                metadata[full_key] = convert_excel_date(value)
                                            except:
                                                # Keep the original value if conversion fails
                                                pass
                        
                        i = closing_pos + 1
                        continue
        i += 1
    
    return metadata
    
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract metadata from Natus EEG files")
    parser.add_argument('-o', '--output', default='eeg_metadata.xlsx', help="Output Excel file")
    parser.add_argument('input_dir', help="Directory containing .eeg files")

    args = parser.parse_args()

    print(f"Processing files in {args.input_dir}")
    metadata_list = extract_eeg_metadata(args.input_dir)

    if metadata_list:
        # Convert to DataFrame
        df = pd.DataFrame(metadata_list)

        # Save to Excel
        print(f"Saving to {args.output}")
        df.to_excel(args.output, index=False)
        print(f"Processed {len(metadata_list)} files")
        print("\nExtracted fields (ordered):")
        print("\n".join(df.columns))
    else:
        print("No data found")