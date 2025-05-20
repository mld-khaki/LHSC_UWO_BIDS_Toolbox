#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session_schema_generator.py

Generates a schema for organizing EDF sessions from arbitrary subfolders,
detects duplicate sessions, optionally simulates or applies a standardized BIDS-like
folder/file structure, and extracts EDF header metadata for scans.tsv/json.
"""

import os
import sys
import argparse
import logging
import hashlib
import shutil
import json
import struct
from pathlib import Path
import pandas as pd
import zipfile
import rarfile
import py7zr

# Ensure local EDF reader is on path
cur_path = r'../../'
sys.path.append(os.path.abspath(cur_path))
os.environ['PATH'] += os.pathsep + cur_path
from _lhsc_lib.EDF_reader_mld import EDFreader

# EDF file extensions (including archives)
EDF_EXTS = ['.edf', '.edf.gz', '.edf.zip', '.edf.rar', '.edf.7z']

# Logging setup
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def compute_md5(path: Path) -> str:
    md5_file = path.with_suffix(path.suffix + '.md5')
    if md5_file.exists():
        try:
            return md5_file.read_text().strip().split()[0]
        except Exception:
            pass
    hash_md5 = hashlib.md5()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_md5.update(chunk)
    checksum = hash_md5.hexdigest()
    try:
        md5_file.write_text(f"{checksum}  {path.name}\n")
    except Exception as e:
        logger.warning(f"Could not write MD5 file {md5_file}: {e}")
    return checksum


def get_uncompressed_size(path: Path) -> int:
    ext = ''.join(path.suffixes).lower()
    try:
        if ext.endswith('.gz'):
            with open(path, 'rb') as f:
                f.seek(-4, os.SEEK_END)
                return struct.unpack('<I', f.read(4))[0]
        if ext.endswith('.zip'):
            with zipfile.ZipFile(path, 'r') as zf:
                return sum(info.file_size for info in zf.infolist())
        if ext.endswith('.rar'):
            with rarfile.RarFile(path) as rf:
                return sum(info.file_size for info in rf.infolist())
        if ext.endswith('.7z'):
            with py7zr.SevenZipFile(path, 'r') as z:
                return sum(entry.uncompressed for entry in z.list())
    except Exception as e:
        logger.warning(f"Error getting size for {path}: {e}")
    return path.stat().st_size


def parse_input_dirs(input_dirs: list, subject: str) -> pd.DataFrame:
    """Scan each input root, parse all immediate subfolders as sessions, extract EDF metadata."""
    records = []
    for root in input_dirs:
        root = Path(root)
        if not root.is_dir():
            logger.error(f"Input root {root} is not a directory")
            continue
        for sess in sorted([d for d in root.iterdir() if d.is_dir()]):
            sess_files = list(sess.iterdir())
            # locate EDF file
            
            def is_edf_like(f: Path) -> bool:
                return ''.join(f.suffixes).lower() in EDF_EXTS

            edf_files = [f for f in sess_files if is_edf_like(f)]

            
            edf_path = edf_files[0] if edf_files else None
            if not edf_path:
                logger.warning(f"No EDF found in {sess}")
            elif len(edf_files) > 1:
                logger.warning(f"Multiple EDFs in {sess}, using {edf_path.name}")
            # metadata presence
            tsv_present = any(f.suffix.lower() == '.tsv' for f in sess_files)
            json_present = any(f.suffix.lower() == '.json' for f in sess_files)
            # unexpected files
            other = [f.name for f in sess_files if edf_path and f != edf_path and f.suffix.lower() not in ['.tsv', '.json']]
            # defaults
            size = None; checksum = None; acq_time = None; duration = None
            if edf_path and edf_path.exists():
                size = get_uncompressed_size(edf_path)
                checksum = compute_md5(edf_path)
                try:
                    reader = EDFreader(str(edf_path), read_annotations=False)
                    acq_time = reader.getStartDateTime().isoformat()
                    duration = reader.getFileDuration()
                except Exception as e:
                    logger.warning(f"EDF header parse error for {edf_path}: {e}")
            task_guess = sess.name.split('_')[0] if '_' in sess.name else 'unknown'
            records.append({
                'subject': subject,
                'source_root': str(root),
                'session_folder': sess.name,
                'edf_path': str(edf_path) if edf_path else '',
                'tsv_present': tsv_present,
                'json_present': json_present,
                'other_files': ';'.join(other),
                'file_size': size,
                'checksum': checksum,
                'acq_time': acq_time,
                'duration': duration,
                'task': task_guess
            })
    return pd.DataFrame(records)


def detect_duplicate_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """Group sessions by file size + checksum to detect duplicates."""
    df = df.copy()
    df['group_id'] = df.groupby(['file_size', 'checksum'], sort=False).ngroup() + 1
    df['action'] = 'keep'
    for gid, grp in df.groupby('group_id'):
        for dup_idx in grp.index[1:]:
            df.at[dup_idx, 'action'] = 'skip'
    return df


def assign_global_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """Assign BIDS-style global session numbers based on group_id."""
    df = df.copy()
    df['global_ses'] = df['group_id'].apply(lambda x: f"{x:03d}")
    return df



def generate_schema(df: pd.DataFrame, subject: str, schema_out: str):
    df = df.copy()

    def compute_target_filename(row):
        edf_path = Path(row['edf_path']) if row['edf_path'] else None
        if not edf_path:
            return ""

        basename = edf_path.name
        task = str(row['task']).strip() if pd.notna(row['task']) and str(row['task']).strip() else 'unknown'

        if '_task-' in basename:
            parts = basename.split('_task-')
            left = parts[0]
            right = parts[1]
            if '_' in right:
                suffix = right.split('_', 1)[1]
                return f"{left}_task-{task}_{suffix}"
            else:
                return f"{left}_task-{task}_{right}"
        else:
            ext = ''.join(edf_path.suffixes)
            ses = str(row['global_ses']).zfill(3)
            return f"sub-{subject}_ses-{ses}_task-{task}_run-01{ext}"

    df['target_filename'] = df.apply(compute_target_filename, axis=1)

    schema_cols = [
        'source_root', 'session_folder', 'edf_path', 'target_filename', 'action', 'group_id',
        'tsv_present', 'json_present', 'other_files', 'file_size', 'checksum',
        'acq_time', 'duration', 'task', 'subject', 'global_ses'
    ]

    schema_df = df[schema_cols]
    schema_df.to_excel(schema_out, index=False, sheet_name='Schema')
    logger.info(f"Schema written to {schema_out}")



def apply_schema(schema_excel: str, proceed: bool):
    df = pd.read_excel(schema_excel, sheet_name='Schema')
    root = Path(schema_excel).parent

    scans_records = []

    for _, r in df.iterrows():
        if r['action'] != 'keep':
            continue

        subj = str(r['subject'])
        global_ses = str(r['global_ses']).zfill(3)

        edf_path = Path(r['edf_path'])
        src_folder = Path(r['source_root']) / r['session_folder']
        dest_ieeg = root / f"sub-{subj}" / f"ses-{global_ses}" / "ieeg"
        dest_ieeg.mkdir(parents=True, exist_ok=True)

        target_filename = r['target_filename']
        target_stem = Path(target_filename).stem
        original_stem = edf_path.stem

        for f in src_folder.iterdir():
            if not f.is_file():
                continue

            suffixes = ''.join(f.suffixes).lower()
            ext = f.suffix.lower()

            if suffixes in EDF_EXTS:
                dst = dest_ieeg / target_filename
                if r['acq_time'] and r['duration']:
                    scans_records.append({
                        'filename': target_filename,
                        'file_size': r['file_size'],
                        'checksum': r['checksum'],
                        'acq_time': r['acq_time'],
                        'duration': r['duration']
                    })
            elif ext in ['.tsv', '.json', '.log', '.md5'] and original_stem in f.stem:
                extra = f.name.replace(original_stem, '')
                dst = dest_ieeg / (target_stem + extra)
            else:
                logger.warning(f"Unexpected or unmatched file {f.name} in {src_folder}")
                dst = dest_ieeg / f.name

            logger.info(f"{'DRY-RUN: ' if not proceed else ''}Moving {f} -> {dst}")
            if proceed:
                shutil.move(str(f), str(dst))

        if proceed:
            try:
                src_folder.rmdir()
            except OSError:
                pass

    # Write scans.tsv and scans.json into subject root
    if proceed and scans_records:
        scans_df = pd.DataFrame(scans_records)
        scans_tsv = root / f"sub-{subj}" / f"sub-{subj}_scans.tsv"
        scans_json = root / f"sub-{subj}" / f"sub-{subj}_scans.json"
        scans_df.to_csv(scans_tsv, sep='\t', index=False)
        scans_df.to_json(scans_json, orient='records', indent=2)
        logger.info(f"Scans TSV and JSON written to {scans_tsv.parent}")



def main():
    parser = argparse.ArgumentParser(
        description='Generate, simulate, or apply BIDS-like session schema from arbitrary folders.'
    )
    parser.add_argument('--input', nargs='+', required=True,
                        help='Input root directories containing session subfolders.')
    parser.add_argument('--subject', required=True,
                        help='Subject identifier (e.g. 001)')
    parser.add_argument('--schema-output', required=True,
                        help='Path to write schema Excel file.')
    parser.add_argument('--proceed-with-moving', action='store_true',
                        help='If set, move files according to schema.')
    parser.add_argument('--simulate', action='store_true',
                        help='Simulate file moves without performing them.')
    args = parser.parse_args()

    if args.simulate:
        apply_schema(args.schema_output, proceed=False)
        logger.info('Simulation complete: no files were moved.')
    elif args.proceed_with_moving:
        apply_schema(args.schema_output, proceed=True)
    else:
        df = parse_input_dirs(args.input, args.subject)
        df = detect_duplicate_sessions(df)
        df = assign_global_sessions(df)
        generate_schema(df, args.subject, args.schema_output)

if __name__ == '__main__':
    main()
