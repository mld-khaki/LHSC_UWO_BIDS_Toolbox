import re
import pandas as pd
from pathlib import Path

def parse_key_tree(content):
    """Parse nested key-tree format into flattened dictionary"""
    def clean_value(val):
        if isinstance(val, str):
            val = val.strip('"')
            try:
                if '.' in val:
                    return float(val)
                return int(val)
            except ValueError:
                return val
        return val

    def parse_node(text, prefix=''):
        results = {}
        pattern = r'\(\."([^"]+)"[,\s]+([^()]+)\)'
        nested_pattern = r'\(\."([^"]+)"[\s,]+\((.*?)\)\)'
        
        # First find all nested structures
        for match in re.finditer(nested_pattern, text, re.DOTALL):
            key, nested_content = match.groups()
            nested_key = f"{prefix}{key}_" if prefix else f"{key}_"
            results.update(parse_node(nested_content, nested_key))
            
        # Then find simple key-value pairs
        for match in re.finditer(pattern, text):
            key, value = match.groups()
            full_key = f"{prefix}{key}" if prefix else key
            results[full_key] = clean_value(value.strip())
            
        return results

    try:
        return parse_node(content)
    except Exception as e:
        print(f"Error parsing key-tree: {e}")
        return {}

def extract_eeg_metadata(directory):
    """Extract metadata from all .eeg files in directory"""
    all_metadata = []
    
    # Find all .eeg files
    for eeg_file in Path(directory).rglob('*.eeg'):
        try:
            # Read file content
            with open(eeg_file, 'rb') as f:
                content = f.read().decode('utf-8', errors='ignore')
            
            # Extract key-tree structures
            metadata = parse_key_tree(content)
            metadata['source_file'] = str(eeg_file)
            all_metadata.append(metadata)
            
        except Exception as e:
            print(f"Error processing {eeg_file}: {e}")
    
    return all_metadata

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Extract metadata from Natus EEG files")
    parser.add_argument('input_dir', help="Directory containing .eeg files")
    parser.add_argument('-o', '--output', default='eeg_metadata.xlsx', help="Output Excel file")
    
    args = parser.parse_args()
    
    # Extract metadata
    print(f"Processing files in {args.input_dir}")
    metadata_list = extract_eeg_metadata(args.input_dir)
    
    if metadata_list:
        # Convert to DataFrame
        df = pd.DataFrame(metadata_list)
        
        # Save to Excel
        print(f"Saving to {args.output}")
        df.to_excel(args.output, index=False)
        print(f"Processed {len(metadata_list)} files")
        print("\nExtracted fields:")
        print("\n".join(sorted(df.columns)))
    else:
        print("No data found")