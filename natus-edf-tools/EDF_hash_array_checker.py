#!/usr/bin/env python3

import os
import json
import hashlib
from pathlib import Path
from EDF_reader_mld import EDFreader

DEFAULT_CHUNK_SIZE = 100 * 1024  # 100 KB
DEFAULT_HASH_ALGO = "sha256"

def hash_bytes(data, algorithm=DEFAULT_HASH_ALGO):
    return hashlib.new(algorithm, data).hexdigest()

def load_edf_header_info(reader):
    return {
        "patient": reader.getPatient(),
        "recording": reader.getRecording(),
        "start_date": str(reader.getStartDateTime()),
        "num_signals": reader.getNumSignals(),
        "duration_seconds": reader.getFileDuration() / 10_000_000
    }

def compute_chunk_hashes(file_path, chunk_size=DEFAULT_CHUNK_SIZE, hash_func=DEFAULT_HASH_ALGO):
    file_path = Path(file_path)
    reader = EDFreader(str(file_path), read_annotations=False)
    header_size = reader._EDFreader__hdrsize
    header_info = load_edf_header_info(reader)

    chunk_hashes = []
    with open(file_path, "rb") as f:
        header = f.read(header_size)
        header_hash = hash_bytes(header, algorithm=hash_func)

        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            chunk_hashes.append(hash_bytes(chunk, algorithm=hash_func))

    return {
        "filename": file_path.name,
        "hash_algorithm": hash_func,
        "chunk_size_bytes": chunk_size,
        "header_size_bytes": header_size,
        "header_hash": header_hash,
        "edf_header_info": header_info,
        "chunk_hashes": chunk_hashes
    }

def verify_against_log(file_path, log_data):
    chunk_size = log_data["chunk_size_bytes"]
    header_size = log_data["header_size_bytes"]
    hash_func = log_data["hash_algorithm"]
    expected_header_hash = log_data["header_hash"]
    expected_chunks = log_data["chunk_hashes"]

    mismatches = {
        "header_mismatch": False,
        "chunk_mismatches": [],
        "total_chunks": len(expected_chunks)
    }

    reader = EDFreader(str(file_path), read_annotations=False)
    actual_header_size = reader._EDFreader__hdrsize
    if actual_header_size != header_size:
        raise ValueError(f"Header size mismatch: expected {header_size}, got {actual_header_size}")

    with open(file_path, "rb") as f:
        header = f.read(header_size)
        if hash_bytes(header, algorithm=hash_func) != expected_header_hash:
            mismatches["header_mismatch"] = True

        for idx, expected in enumerate(expected_chunks):
            chunk = f.read(chunk_size)
            if not chunk:
                mismatches["chunk_mismatches"].append((idx, "missing"))
                break
            actual = hash_bytes(chunk, algorithm=hash_func)
            if actual != expected:
                mismatches["chunk_mismatches"].append((idx, "mismatch"))

    return mismatches

def main(file_path: str, force: bool = False):
    file_path = Path(file_path)
    log_path = file_path.with_suffix(file_path.suffix + ".shalog")

    if log_path.exists() and not force:
        print(f"📄 Found existing SHA log: {log_path.name}")
        with open(log_path, "r") as f:
            log_data = json.load(f)
        result = verify_against_log(file_path, log_data)
        print("\n🧾 Verification Result:")
        if result["header_mismatch"]:
            print("❌ Header mismatch.")
        else:
            print("✅ Header matches.")
        if result["chunk_mismatches"]:
            print(f"❌ {len(result['chunk_mismatches'])} chunk mismatches:")
            for idx, reason in result["chunk_mismatches"]:
                print(f"  - Chunk {idx}: {reason}")
        else:
            print(f"✅ All {result['total_chunks']} chunks match.")
    else:
        print(f"🔐 Generating SHA log for: {file_path.name}")
        result = compute_chunk_hashes(file_path)
        with open(log_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"✅ SHA log saved to: {log_path}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate or verify chunk-level SHA log for EDF files.")
    parser.add_argument("edf_file", help="Path to EDF file")
    parser.add_argument("--force", action="store_true", help="Force regeneration of the .shalog file")
    args = parser.parse_args()

    main(args.edf_file, args.force)
