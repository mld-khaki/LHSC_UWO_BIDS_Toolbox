#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import shutil
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from tqdm import tqdm

TIME_THRESHOLD_HOURS = 36
IGNORE_AGE_YEARS = 4

# === Database Setup ===
def initialize_db(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS sync_log (
        relative_path TEXT PRIMARY KEY,
        file_name TEXT,
        size INTEGER,
        creation_time TEXT,
        modification_time TEXT,
        access_time TEXT
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS event_log (
        timestamp TEXT,
        action TEXT,
        relative_path TEXT,
        size INTEGER,
        reason TEXT
    )''')
    conn.commit()
    return conn

def get_file_info(path: Path):
    stat = path.stat()
    return {
        'file_name': path.name,
        'relative_path': str(path.relative_to(path.anchor)),
        'size': stat.st_size,
        'creation_time': datetime.fromtimestamp(stat.st_ctime).isoformat(),
        'modification_time': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        'access_time': datetime.fromtimestamp(stat.st_atime).isoformat()
    }

def log_event(conn, action, rel_path, size, reason):
    cur = conn.cursor()
    cur.execute('''INSERT INTO event_log (timestamp, action, relative_path, size, reason)
                   VALUES (?, ?, ?, ?, ?)''',
                (datetime.now().isoformat(), action, rel_path, size, reason))
    conn.commit()

def file_exists(conn, rel_path):
    cur = conn.cursor()
    cur.execute('SELECT size FROM sync_log WHERE relative_path = ?', (rel_path,))
    return cur.fetchone()

def insert_file_record(conn, file_info):
    cur = conn.cursor()
    cur.execute('''INSERT OR REPLACE INTO sync_log
        (relative_path, file_name, size, creation_time, modification_time, access_time)
        VALUES (?, ?, ?, ?, ?, ?)''',
        (file_info['relative_path'], file_info['file_name'], file_info['size'],
         file_info['creation_time'], file_info['modification_time'], file_info['access_time']))
    conn.commit()

def sync_files(conn, server_folder, local_repo):
    conflict_rows = []
    for root, _, files in os.walk(server_folder):
        print(f"\n→ Processing folder: {root}")
        for file in tqdm(files, desc=f"Files in {Path(root).name}", unit="file"):
            src = Path(root) / file
            file_info = get_file_info(src)
            rel_path = file_info['relative_path']
            existing = file_exists(conn, rel_path)

            creation_time = datetime.fromisoformat(file_info['creation_time'])
            file_age = datetime.now() - creation_time
            
            if file_age.total_seconds() > IGNORE_AGE_YEARS * 365 * 24 * 3600:
                log_event(conn, 'ignored', rel_path, file_info['size'], 'file older than 4 years')
                continue

            if existing:
                if existing[0] != file_info['size']:
                    file_info['logged_size'] = existing[0]
                    file_info['action'] = 'skip'
                    conflict_rows.append(file_info)
                    log_event(conn, 'conflict', rel_path, file_info['size'], 'size mismatch')
                continue

            if file_age.total_seconds() > TIME_THRESHOLD_HOURS * 3600:
                dst = Path(local_repo) / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                insert_file_record(conn, file_info)
                log_event(conn, 'copied', rel_path, file_info['size'], 'new file')
            else:
                log_event(conn, 'skipped', rel_path, file_info['size'], 'file too new')

    if conflict_rows:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        pd.DataFrame(conflict_rows).to_csv(f"sync_conflicts_{ts}.csv", index=False)

def assume_previously_synced(conn, server_folder):
    for root, _, files in os.walk(server_folder):
        print(f"\n→ Scanning folder: {root}")
        for file in tqdm(files, desc=f"Marking in {Path(root).name}", unit="file"):
            src = Path(root) / file
            file_info = get_file_info(src)
            insert_file_record(conn, file_info)
            log_event(conn, 'assume_synced', file_info['relative_path'], file_info['size'], 'initial snapshot')

def update_differences(conn, csv_file, server_folder, local_repo):
    df = pd.read_csv(csv_file)
    updated = 0
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Applying updates", unit="file"):
        if str(row.get('action')).strip().lower() != 'update':
            continue
        rel_path = Path(row['relative_path'])
        src = Path(server_folder).drive + os.sep + str(rel_path)
        dst = Path(local_repo) / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        file_info = get_file_info(Path(src))
        insert_file_record(conn, file_info)
        log_event(conn, 'updated', str(rel_path), file_info['size'], 'manual update')
        updated += 1

def export_log_table(conn, table_name):
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
    df.to_csv(f"{table_name}_{ts}.csv", index=False)

def main():
    parser = argparse.ArgumentParser(description="Sync files using SQLite as backend with conflict and event logging")
    parser.add_argument("server_folder", type=str)
    parser.add_argument("local_repo", type=str)
    parser.add_argument("sync_db", type=str)

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sync", action="store_true")
    group.add_argument("--update-differences", type=str, metavar="CSV_FILE")
    group.add_argument("--assume-previously-synced", action="store_true")

    parser.add_argument("--export-log", action="store_true", help="Export event_log table to CSV")
    parser.add_argument("--export-sync", action="store_true", help="Export sync_log table to CSV")

    args = parser.parse_args()
    conn = initialize_db(args.sync_db)

    if args.sync:
        sync_files(conn, args.server_folder, args.local_repo)
    elif args.update_differences:
        update_differences(conn, args.update_differences, args.server_folder, args.local_repo)
    elif args.assume_previously_synced:
        assume_previously_synced(conn, args.server_folder)

    if args.export_log:
        export_log_table(conn, "event_log")
    if args.export_sync:
        export_log_table(conn, "sync_log")

if __name__ == "__main__":
    main()
