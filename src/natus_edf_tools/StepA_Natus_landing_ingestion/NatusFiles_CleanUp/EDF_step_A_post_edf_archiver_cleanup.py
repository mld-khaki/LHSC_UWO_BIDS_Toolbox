#!/usr/bin/env python3

import os
import shutil
import subprocess
import logging
import argparse
from pathlib import Path
from tqdm import tqdm

def setup_logger(log_file_path):
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("verify_and_archive")
    logger.setLevel(logging.DEBUG)

    if logger.hasHandlers():
        logger.handlers.clear()

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(message)s', "%H:%M:%S")
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    fh = logging.FileHandler(log_file_path)
    fh.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(file_formatter)
    logger.addHandler(fh)

    return logger

def folder_size(path):
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total += os.path.getsize(fp)
    return total

def move_files_to_parent_deletable(folder_path, deletable_root, extensions, logger, dry_run):
    subfolder_name = Path(folder_path).name
    deletable_target = Path(deletable_root) / "deletable" / subfolder_name
    deletable_target.mkdir(parents=True, exist_ok=True)

    logger.info(f"Moving deletable files from {folder_path} to {deletable_target}")
    for root, _, files in os.walk(folder_path):
        for file in files:
            if any(file.lower().endswith(ext) for ext in extensions):
                source_path = Path(root) / file
                destination_path = deletable_target / file
                if dry_run:
                    logger.info(f"[Dry Run] Would move: {source_path} -> {destination_path}")
                else:
                    try:
                        shutil.move(str(source_path), str(destination_path))
                        logger.info(f"Moved: {source_path} -> {destination_path}")
                    except Exception as e:
                        logger.error(f"Failed to move {source_path}: {e}")

def rar_compress(folder_path, output_rar, logger, dry_run):
    winrar_exe = r'"C:\Program Files\WinRAR\WinRAR.exe"'  # quoted for safety
    cmd = (
        f'start /min "" {winrar_exe} a -m3 -md1g -s -rr5% -df -t '
        f'"{output_rar}" "{folder_path}"'
    )

    if dry_run:
        logger.info(f"[Dry Run] Would run: {cmd}")
        return

    logger.info(f"Running RAR compression: {cmd}")
    try:
        subprocess.run(cmd, shell=True)
        logger.info(f"RAR archive started: {output_rar}")
    except subprocess.CalledProcessError as e:
        logger.error(f"RAR compression failed for {folder_path}: {e}")


def rename_file_with_suffix(file_path, suffix, logger, dry_run):
    file = Path(file_path)
    new_name = file.with_name(f"{file.stem}_{suffix}{file.suffix}")
    if dry_run:
        logger.info(f"[Dry Run] Would rename {file.name} -> {new_name.name}")
        return
    try:
        file.rename(new_name)
        logger.info(f"Renamed {file.name} -> {new_name.name}")
    except Exception as e:
        logger.error(f"Failed to rename {file.name}: {e}")

def main(folder_b, folder_a, dry_run):
    print(f"FoldA = {folder_a}, FoldB = {folder_b}")
    folder_b = Path(folder_b)
    folder_a = Path(folder_a)
    log_file = folder_b / "verification_archive.log"
    logger = setup_logger(log_file)

    edf_files = list(folder_b.glob("*.edf"))
    logger.info(f"Found {len(edf_files)} EDF files to process")

    for edf_file in tqdm(edf_files, desc="Processing EDFs", unit="file"):
        base_name = edf_file.stem
        logger.info(f"\n---\nProcessing {edf_file.name}")

        corresponding_folder = folder_a / base_name
        edf_pass_file = folder_b / f"{base_name}.edf_pass"

        if not corresponding_folder.is_dir():
            logger.info(f"Folder not found: {corresponding_folder}, skipping.")
            continue

        if not edf_pass_file.exists():
            logger.info(f"edf_pass file not found for {edf_file.name}, skipping.")
            continue

        edf_size = edf_file.stat().st_size
        folder_size_bytes = folder_size(corresponding_folder)

        if edf_size < folder_size_bytes:
            logger.info(f"{edf_file.name} is smaller than folder size, skipping.")
            continue

        move_files_to_parent_deletable(corresponding_folder, folder_a, [".avi", ".erd"], logger, dry_run)
        rar_output = folder_a / f"{base_name}.rar"
        rar_compress(str(corresponding_folder), str(rar_output), logger, dry_run)

        rename_file_with_suffix(edf_file, "verified_stpAcln", logger, dry_run)
        rename_file_with_suffix(edf_pass_file, "verified_stpAcln", logger, dry_run)

    logger.info("Processing complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verify, clean, compress, and rename EDF data folders."
    )
    parser.add_argument("--folder-a", type=str, required=True,
                        help="Path to Folder A (with corresponding subfolders)")
    parser.add_argument("--folder-b", type=str, required=True,
                        help="Path to Folder B (with .edf and .edf_pass files)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate actions without deleting or modifying anything")
    parser.add_argument("--real-del-mode", action="store_true",
                        help="Enable actual deletion and renaming")

    args = parser.parse_args()

    dry_run_mode = not args.real_del_mode
    main(args.folder_b, args.folder_a, dry_run_mode)
