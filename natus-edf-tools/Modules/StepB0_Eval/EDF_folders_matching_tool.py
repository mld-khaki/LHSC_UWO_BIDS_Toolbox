import os
import hashlib
import argparse
import pandas as pd
from datetime import datetime
from collections import defaultdict
from tqdm import tqdm
import uuid
import re


def parse_filename(file):
    pattern = re.compile(
        r"sub-(?P<subject>[^_]+)_ses-(?P<session>[^_]+)_task-(?P<task>[^_]+)_run-(?P<run>[^_]+)_(?P<signal>[^.]+)\.edf",
        re.IGNORECASE
    )
    match = pattern.match(file)
    if match:
        return match.groupdict()
    return {
        'subject': '', 'session': '', 'task': '', 'run': '', 'signal': ''
    }

def get_file_info(folder, checksum_type=''):
    file_data = []
    if checksum_type != '':
        hash_func = hashlib.sha256 if checksum_type == 'sha256' else hashlib.md5
    else:
        hash_func = None

    for root, _, files in os.walk(folder):
        for file in files:
            if file.lower().endswith('.edf'):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, folder)
                stat = os.stat(full_path)
                size = stat.st_size
                ctime = datetime.fromtimestamp(stat.st_mtime).isoformat()

            
                checksum = None
                if hash_func != None:
                    h = hash_func()
                    with open(full_path, 'rb') as f:
                        while chunk := f.read(8192):
                            h.update(chunk)
                    checksum = h.hexdigest()
                else:
                    checksum = ''

                info = parse_filename(file)

                file_data.append({
                    'filename': file,
                    'size': size,
                    'size_gb': round(size / (1024**3), 4),
                    'ctime': ctime,
                    'checksum': checksum,
                    'relative_path': rel_path,
                    'full_path': full_path,
                    'subject': info['subject'],
                    'session': info['session'],
                    'task': info['task'],
                    'run': info['run'],
                    'signal': info['signal'],
                })
    return file_data

def group_files_by_key(file_list, use_checksum):
    groups = defaultdict(list)
    for f in file_list:
        key = (f['size'], f['checksum']) if use_checksum else f['size']
        groups[key].append(f)
    return groups

def match_files(files_a, files_b, use_checksum):
    group_a = group_files_by_key(files_a, use_checksum)
    group_b = group_files_by_key(files_b, use_checksum)

    match_id = 1
    rows = []
    matched_keys = set(group_a.keys()).intersection(group_b.keys())

    for key in matched_keys:
        groupA = group_a[key]
        groupB = group_b[key]
        status = get_match_status(len(groupA), len(groupB))
        for a in groupA:
            for b in groupB:
                rows.append(build_row(a, b, status, match_id, use_checksum))
        match_id += 1

    unmatched_a = [f for k, v in group_a.items() if k not in matched_keys for f in v]
    unmatched_b = [f for k, v in group_b.items() if k not in matched_keys for f in v]

    return rows, unmatched_a, unmatched_b


def get_match_status(count_a, count_b):
    return {
        (1, 1): 'unique match',
        (1, 2): 'one-two match',
        (2, 1): 'two-one match',
        (2, 2): 'two-two match',
        (3, 1): 'three-one match',
        (1, 3): 'one-three match',
        (2, 3): 'two-three match',
        (3, 2): 'three-two match',
        (3, 3): 'three-three match',
    }.get((count_a, count_b), f'{count_a}-{count_b} match')

def build_row(file_a, file_b, status, match_id, use_checksum):
    return {
        'Filename A': file_a['filename'],
        'Filename B': file_b['filename'],
        'Match Status': status,
        'Match ID': match_id,
        'Subject A': file_a['subject'],
        'Subject B': file_b['subject'],
        'Session A': file_a['session'],
        'Session B': file_b['session'],
        'Task A': file_a['task'],
        'Task B': file_b['task'],
        'Run A': file_a['run'],
        'Run B': file_b['run'],
        'Signal Type A': file_a['signal'],
        'Signal Type B': file_b['signal'],
        'File A Size (GB)': file_a['size_gb'],
        'File B Size (GB)': file_b['size_gb'],
        'File A Creation Date': file_a['ctime'],
        'File B Creation Date': file_b['ctime'],
        'File A Checksum': file_a.get('checksum') if use_checksum else '',
        'File B Checksum': file_b.get('checksum') if use_checksum else '',
        'File A Relative Path': file_a['relative_path'],
        'File B Relative Path': file_b['relative_path'],
        'File A Size (bytes)': file_a['size'],
        'File B Size (bytes)': file_b['size'],
    }


def build_unmatched_row(file, side):
    return {
        'Filename A': file['filename'] if side == 'A' else '',
        'Filename B': file['filename'] if side == 'B' else '',
        'Match Status': 'unmatched',
        'Match ID': '',
        'Subject A': file['subject'] if side == 'A' else '',
        'Subject B': file['subject'] if side == 'B' else '',
        'Session A': file['session'] if side == 'A' else '',
        'Session B': file['session'] if side == 'B' else '',
        'Task A': file['task'] if side == 'A' else '',
        'Task B': file['task'] if side == 'B' else '',
        'Run A': file['run'] if side == 'A' else '',
        'Run B': file['run'] if side == 'B' else '',
        'Signal Type A': file['signal'] if side == 'A' else '',
        'Signal Type B': file['signal'] if side == 'B' else '',
        'File A Size (GB)': file['size_gb'] if side == 'A' else '',
        'File B Size (GB)': file['size_gb'] if side == 'B' else '',
        'File A Creation Date': file['ctime'] if side == 'A' else '',
        'File B Creation Date': file['ctime'] if side == 'B' else '',
        'File A Checksum': file.get('checksum') if side == 'A' else '',
        'File B Checksum': file.get('checksum') if side == 'B' else '',
        'File A Relative Path': file['relative_path'] if side == 'A' else '',
        'File B Relative Path': file['relative_path'] if side == 'B' else '',
        'File A Size (bytes)': file['size'] if side == 'A' else '',
        'File B Size (bytes)': file['size'] if side == 'B' else '',
    }


def main():
    parser = argparse.ArgumentParser(description='Compare EDF files in two folders')
    parser.add_argument('folder_a', type=str, help='Path to folder A')
    parser.add_argument('folder_b', type=str, help='Path to folder B')
    parser.add_argument('--checksum-type', choices=['sha256', 'md5'], help='Enable checksum matching with given type')
    parser.add_argument('output_file',type=str, help='Output table name/path')
    args = parser.parse_args()

    use_checksum = args.checksum_type is not None

    print("Scanning Folder A...")
    files_a = get_file_info(args.folder_a, args.checksum_type if use_checksum else '')

    print("Scanning Folder B...")
    files_b = get_file_info(args.folder_b, args.checksum_type if use_checksum else '')

    print("Matching files...")
    matched_rows, unmatched_a, unmatched_b = match_files(files_a, files_b, use_checksum)

    # Assemble final DataFrame
    all_rows = matched_rows
    all_rows.append({})  # Empty row
    all_rows.extend(build_unmatched_row(f, 'A') for f in unmatched_a)
    all_rows.append({})  # Empty row
    all_rows.extend(build_unmatched_row(f, 'B') for f in unmatched_b)
    
    Folders_Info = {
        'Filename A': '',
        'Filename B': 'Folder A',          
        'Match Status': args.folder_a , 
        'Match ID': '',
    }
    all_rows.append(Folders_Info)  # Empty row

    Folders_Info = {
        'Filename A': '', 
        'Filename B': 'Folder B',
        'Match Status': args.folder_b ,
        'Match ID': '',
    }    
    all_rows.append(Folders_Info)  # Empty row

    df = pd.DataFrame(all_rows)
    print(df)

    output_file = args.output_file
    if not output_file.lower().endswith('.xlsx'):
        output_file += '.xlsx'

    # Write to Excel using xlsxwriter
    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Matches')
        workbook  = writer.book
        worksheet = writer.sheets['Matches']
        bold_fmt = workbook.add_format({'bold': True})

        # Get column indices
        columns_to_check = [
            ('Subject A', 'Subject B'),
            ('Session A', 'Session B'),
            ('Task A', 'Task B'),
            ('Run A', 'Run B'),
            ('Signal Type A', 'Signal Type B'),
            ('File A Size (GB)', 'File B Size (GB)')
        ]

        # Apply bold formatting to mismatched cells
        for row_num in range(1, len(df) + 1):
            row = df.iloc[row_num - 1]
            if row.get('Match Status') == 'unmatched' or pd.isna(row.get('Match Status')):
                continue  # Skip unmatched and empty rows

            for col_a, col_b in columns_to_check:
                val_a = row.get(col_a)
                val_b = row.get(col_b)
                if pd.notna(val_a) and pd.notna(val_b) and val_a != val_b:
                    col_a_idx = df.columns.get_loc(col_a)
                    col_b_idx = df.columns.get_loc(col_b)
                    worksheet.write(row_num, col_a_idx, val_a, bold_fmt)
                    worksheet.write(row_num, col_b_idx, val_b, bold_fmt)

    print(f"\nResults saved to {output_file}")


if __name__ == "__main__":
    main()
