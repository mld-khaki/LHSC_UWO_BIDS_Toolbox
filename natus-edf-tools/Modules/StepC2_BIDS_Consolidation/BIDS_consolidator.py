#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session_schema_generator.py

Generates a schema for organizing EDF sessions and optionally applies the schema to restructure data folders.
Includes MD5 checksum generation and duplicate detection by checksum.
"""
import os
import re
import sys
import argparse
import logging
import struct
import shutil
import hashlib
from pathlib import Path
import pandas as pd
import zipfile
import rarfile
import py7zr
import hashlib
from tqdm import tqdm

# Ensure local EDF reader is on path
cur_path = r'../../'
sys.path.append(os.path.abspath(cur_path))
os.environ['PATH'] += os.pathsep + cur_path

from _lhsc_lib.EDF_reader_mld import EDFreader

# ─── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# FILE_INFO_REGEX = re.compile(
#     r"sub-(?P<subj>\d+)_ses-(?P<ses>\d+)"
#     r"(?:_task-(?P<task>[^_]+))?"
#     r"(?:_run-(?P<run>\d+))?_(?P<suffix>.+)\."
#     r"(?P<ext>edf(?:\.[^\.]+)?|tsv|json|md5|rar|gz|7z)"
# )

# ─── Regex for BIDS‐style filenames ─────────────────────────────────────────────
FILE_INFO_REGEX = re.compile(
    r"sub-(?P<subj>\d+)_ses-(?P<ses>\d+)"
    r"(?:_task-(?P<task>[^_]+))?"
    r"(?:_run-(?P<run>\d+))?_(?P<suffix>.+)\.(?P<ext>edf(?:\.[^\.]+)?|tsv|json|md5|rar|gz|7z)"
)


# ─── Helper: read the scans.tsv for timestamps & durations ────────────────────
def read_scans_tsv(scans_path: Path) -> pd.DataFrame:
    df = pd.read_csv(scans_path, sep='\t')
    df['fullpath']  = df['filename'].apply(lambda x: scans_path.parent / x)
    df['acq_time']  = pd.to_datetime(df['acq_time'])
    df['duration']  = df['duration'].astype(float)
    return df.set_index('fullpath')



# ─── MD5 checksum utility with progress bar ────────────────────────────────────
def compute_md5(path: Path) -> str:
    md5_file = path.with_suffix(path.suffix + '.md5')
    # If .md5 exists, read it
    if md5_file.exists():
        try:
            line = md5_file.read_text().strip()
            return line.split()[0]
        except Exception:
            pass
    # Compute with tqdm
    hash_md5 = hashlib.md5()
    total = path.stat().st_size
    with path.open('rb') as f, tqdm(total=total, unit='B', unit_scale=True,
                                      desc=f"MD5 {path.name}") as pbar:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_md5.update(chunk)
            pbar.update(len(chunk))
    checksum = hash_md5.hexdigest()
    try:
        md5_file.write_text(f"{checksum}  {path.name}\n")
    except Exception as e:
        logger.warning(f"Failed to write md5 file {md5_file}: {e}")
    return checksum

# ─── Archive‐size helpers ─────────────────────────────────────────────────────
def get_gz_uncompressed_size(file_path: str) -> int:
    try:
        with open(file_path, 'rb') as f:
            f.seek(-4, os.SEEK_END)
            size_bytes = f.read(4)
        return struct.unpack('<I', size_bytes)[0]
    except Exception as e:
        logger.warning(f"gzip size error [{file_path}]: {e}")
        return 0

def get_zip_uncompressed_size(file_path: str) -> int:
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            return sum(info.file_size for info in zf.infolist())
    except Exception as e:
        logger.warning(f"zip size error [{file_path}]: {e}")
        return 0

def get_rar_uncompressed_size(file_path: str) -> int:
    try:
        with rarfile.RarFile(file_path) as rf:
            return sum(info.file_size for info in rf.infolist())
    except Exception as e:
        logger.warning(f"rar size error [{file_path}]: {e}")
        return 0

def get_7z_uncompressed_size(file_path: str) -> int:
    try:
        with py7zr.SevenZipFile(file_path, mode='r') as archive:
            return sum(entry.uncompressed for entry in archive.list())
    except Exception as e:
        logger.warning(f"7z size error [{file_path}]: {e}")
        return 0
    
    
# ─── Dispatcher for any file type ──────────────────────────────────────────────
def get_uncompressed_size(path: Path) -> int:
    ext = ''.join(path.suffixes).lower()
    if ext.endswith('.gz'):
        return get_gz_uncompressed_size(str(path))
    if ext.endswith('.zip'):
        return get_zip_uncompressed_size(str(path))
    if ext.endswith('.rar'):
        return get_rar_uncompressed_size(str(path))
    if ext.endswith('.7z'):
        return get_7z_uncompressed_size(str(path))
    # non‐archive or unknown: just file size
    return path.stat().st_size




# ─── Phase 1: build metadata table with checksum ──────────────────────────────
def parse_input_dirs(input_dirs):
    records = []
    inp_dir_cnt = 0
    for input_dir in input_dirs:
        inp_dir_cnt += 1
        input_dir = Path(input_dir)
        subs = list(input_dir.glob('sub-*'))
        if len(subs) != 1:
            logger.error(f"Expected one subject folder in {input_dir}, found {subs}")
            sys.exit(1)
        sub_dir = subs[0]
        subject = sub_dir.name
        scans_tsv = sub_dir / f"{subject}_scans.tsv"
        if not scans_tsv.exists():
            logger.error(f"Missing scans.tsv: {scans_tsv}")
            sys.exit(1)
        scans_df = read_scans_tsv(scans_tsv)

        for ses_dir in sub_dir.glob('ses-*'):
            ieeg_dir = ses_dir / 'ieeg'
            if not ieeg_dir.exists():
                continue
            for file_path in ieeg_dir.iterdir():
                if not file_path.is_file():
                    continue
                info = {
                    'input_folder': str(input_dir),
                    'subject':      subject,
                    'file_path':    str(file_path),
                    'file_name':    file_path.name,
                    'fld_grp':      inp_dir_cnt
                }
                m = FILE_INFO_REGEX.match(file_path.name)
                if m:
                    info['input_session'] = int(m.group('ses'))
                    info['run']           = int(m.group('run')) if m.group('run') else None
                    info['task']          = m.group('task')
                else:
                    parts = file_path.name.split('_')
                    info['input_session'] = int(parts[2])
                    info['run']           = None
                    info['task']          = None

                # Timestamp & duration from scans or EDF
                p = Path(info['file_path'])
                if p in scans_df.index:
                    info['acq_time'] = scans_df.loc[p, 'acq_time']
                    info['duration'] = scans_df.loc[p, 'duration']
                elif any(s in p.suffixes for s in ['.edf', '.gz']):
                    try:
                        reader = EDFreader(str(p), read_annotations=False)
                        info['acq_time'] = reader.getStartDateTime()
                        info['duration'] = reader.getFileDuration()
                    except Exception as e:
                        logger.error(f"EDF read error [{file_path}]: {e}")
                        info['acq_time'] = None
                        info['duration'] = None
                else:
                    logger.error(f"No date for {file_path}")
                    info['acq_time'] = None
                    info['duration'] = None

                info['file_size'] = get_uncompressed_size(p)
                info['file_ext']  = ''.join(p.suffixes)
                info['format']    = p.parent.name
                # Compute or read MD5 checksum
                info['checksum']  = compute_md5(p)

                records.append(info)
    return pd.DataFrame(records)


# ─── Phase 2: detect duplicates by checksum ───────────────────────────────────
def detect_duplicate_runs(df: pd.DataFrame) -> pd.DataFrame:
    # Build file-list per run keyed by checksum
    run_meta = {}
    for key, grp in df.groupby(['subject','input_session','run']):
        flist = sorted(
            grp[['file_ext','checksum']]
              .itertuples(index=False, name=None)
        )
        run_meta[key] = flist

    # Group identical-checksum runs
    dup_map = {}
    gid = 1
    for run1, fl1 in run_meta.items():
        if run1 in dup_map:
            continue
        dup_map[run1] = gid
        for run2, fl2 in run_meta.items():
            if run2 in dup_map:
                continue
            if fl1 == fl2:
                dup_map[run2] = gid
        gid += 1

    df['run_group_id'] = df.apply(
        lambda x: dup_map[(x['subject'],x['input_session'],x['run'])], axis=1
    )

    # Pick primary = largest run (by file count)
    primary = {}
    for rg, grp in df.groupby('run_group_id'):
        counts = grp.groupby(['subject','input_session','run']).size()
        primary[rg] = counts.idxmax()

    # Assign 'move' vs 'skip'
    df['action'] = df.apply(
        lambda x: 'move' if (
            x['subject'],x['input_session'],x['run']
        ) == primary[x['run_group_id']] else 'skip',
        axis=1
    )
    return df



# ─── Phase 3: expand session‐level files and assign global sessions ───────────
def expand_session_level_files(df: pd.DataFrame) -> pd.DataFrame:
    records = []
    for (subj, ses), grp in df.groupby(['subject','input_session']):
        runs = sorted(grp['run'].dropna().astype(int).unique())
        # run‐specific
        records.extend(grp[grp['run'].notna()].to_dict('records'))
        # session‐level -> replicate
        for row in grp[grp['run'].isna()].to_dict('records'):
            for r in runs:
                new = row.copy(); new['run'] = r
                records.append(new)
    return pd.DataFrame(records)


def assign_global_sessions(df: pd.DataFrame) -> pd.DataFrame:
    rt = df.groupby('run_group_id')['acq_time'].min().reset_index()
    rt = rt.sort_values('acq_time')
    rt['global_ses'] = [f"{i+1:03d}" for i in range(len(rt))]
    gmap = dict(zip(rt['run_group_id'], rt['global_ses']))
    df['global_ses'] = df['run_group_id'].map(gmap)
    return df



# ─── Phase 4: write schema XLSX ───────────────────────────────────────────────
def generate_schema(df: pd.DataFrame, output_excel: str):
    def tgt(r):
        subj = r['subject']; ses = f"ses-{r['global_ses']}"
        base = Path(subj)/ses/'ieeg'
        task = r['task'] or 'unknown'
        run  = f"{int(r['run']):02d}" if pd.notna(r['run']) else '00'
        ext  = r['file_ext']; fmt = r['format']
        name = f"{subj}_{ses}_task-{task}_run-{run}_{fmt}{ext}"
        return str(base/name)

    df['target_path'] = df.apply(tgt, axis=1)
    schema = df.rename(
        columns={'input_folder':'source_folder','file_path':'source_path'}
    )[[
        'source_folder','source_path','file_name','checksum','target_path',
        'action','run_group_id','global_ses','duration','file_size'
    ]]
    with pd.ExcelWriter(output_excel, engine='openpyxl') as w:
        schema.to_excel(w, index=False, sheet_name='Schema')
    logger.info(f"Schema written to {output_excel}")
    


# ─── Move files per schema (optional) ────────────────────────────────────────
def apply_schema(schema_excel: str, proceed: bool):
    df = pd.read_excel(schema_excel, sheet_name='Schema')
    for _, r in df.iterrows():
        if r['action'] == 'skip':
            continue
        src = Path(r['source_path']); dst = Path(r['target_path'])
        dst.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Moving {src} -> {dst}")
        if proceed:
            shutil.move(str(src), str(dst))


# ─── Utility: folder‐size analyzer (unchanged) ───────────────────────────────
def analyze_folder(path):
    total_uncompressed = 0
    total_compressed   = 0

    for root, _, files in os.walk(path):
        for file in files:
            full_path = os.path.join(root, file)
            try:
                size = os.path.getsize(full_path)
                ext  = os.path.splitext(file)[1].lower()

                print(f"tot_comp = {total_compressed/1e9:10.2f} GB, "
                      f"tot_unc  = {total_uncompressed/1e9:10.2f} GB, "
                      f"Checking file → {file}")

                if ext == '.gz':
                    total_compressed   += size
                    total_uncompressed += get_gz_uncompressed_size(full_path)
                elif ext == '.zip':
                    total_compressed   += size
                    total_uncompressed += get_zip_uncompressed_size(full_path)
                elif ext == '.rar':
                    total_compressed   += size
                    total_uncompressed += get_rar_uncompressed_size(full_path)
                elif ext == '.7z':
                    total_compressed   += size
                    total_uncompressed += get_7z_uncompressed_size(full_path)
                else:
                    total_compressed   += size
                    total_uncompressed += size

            except Exception as e:
                print(f"Error processing {full_path}: {e}")

    return total_uncompressed, total_compressed

def main():
    parser = argparse.ArgumentParser(description='Generate and apply session schema')
    parser.add_argument('--input',               nargs='+', required=True)
    parser.add_argument('--schema-output',       help='Write schema xlsx')
    parser.add_argument('--confirmed-schema',    help='Use existing schema')
    parser.add_argument('--proceed-with-moving', action='store_true')
    # args = parser.parse_args()

    if 0:# args.confirmed_schema:
        # apply_schema(args.confirmed_schema, args.proceed_with_moving)
        pass
    else:
        df = parse_input_dirs([r'X:\_pipeline\Step_C_EDF_anon\sub-167B',r'X:\_pipeline\Step_C_EDF_anon\sub-167',
                               r'X:\_pipeline\Step_C_EDF_anon\sub-167C']) #args.input)
        df = expand_session_level_files(df)

        df = detect_duplicate_runs(df)
        df = assign_global_sessions(df)
        generate_schema(df, r'.\output.xlsx')
        logger.info(
            'Schema generated. Review and rerun with --confirmed-schema '
            'and --proceed-with-moving to apply.'
        )

if __name__ == '__main__':
    main()


        # df = parse_input_dirs(r'z:\_pipeline\Step_C_EDF_anon\sub-167\sub-167\' #args.input)
        # df = detect_duplicate_runs(df)
        # df = assign_global_sessions(df)
        # generate_schema(df, args.schema_output)
        # logger.info(
        #     'Schema generated. Review and rerun with --confirmed-schema '
        #     'and --proceed-with-moving to apply.'
        # )
