import os
import time
from datetime import datetime


def compare_dirs(inpA, inpB, log_file, ignore_ext):
    differences = []
    print(f"\nComparing folders:\nBase: {inpA}\nCompare: {inpB}\n")
    if ignore_ext:
        print(f"Ignoring files with extension: {ignore_ext}\n")

    for root, dirs, files in os.walk(inpA):
        rel_path = os.path.relpath(root, inpA)
        compare_root = os.path.join(inpB, rel_path)

        if not os.path.exists(compare_root):
            msg = f"Missing folder in inpB: {rel_path}"
            print(msg)
            differences.append(msg)
            continue

        # Compare files within matched directories
        for f in files:
            if ignore_ext and f.endswith(ignore_ext):
                continue

            base_file = os.path.join(root, f)
            compare_file = os.path.join(compare_root, f)
            rel_file = os.path.relpath(compare_file, inpB)

            if not os.path.exists(compare_file):
                msg = f"Missing file in inpB: {rel_file}"
                print(msg)
                differences.append(msg)
                continue

            base_stat = os.stat(base_file)
            compare_stat = os.stat(compare_file)

            size_diff = base_stat.st_size != compare_stat.st_size
            mtime_diff = abs(base_stat.st_mtime - compare_stat.st_mtime) > 1  # 1s tolerance

            if size_diff or mtime_diff:
                msg = f"Updated file in inpB: {rel_file}"
                if size_diff:
                    msg += f" (Size: A={base_stat.st_size}, B={compare_stat.st_size})"
                if mtime_diff:
                    msg += f" (Modified: A={datetime.fromtimestamp(base_stat.st_mtime)}, B={datetime.fromtimestamp(compare_stat.st_mtime)})"
                print(msg)
                differences.append(msg)

    # Save differences to file
    with open(log_file, 'w') as f:
        for line in differences:
            f.write(line + '\n')

    print(f"\nComparison complete. Differences saved to {log_file}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compare folders and log differences.")
    parser.add_argument("inpA", help="Path to original folder")
    parser.add_argument("inpB", help="Path to updated folder")
    parser.add_argument("--output", default="differences.txt", help="Output log file")
    parser.add_argument("--ignore_ext", default="", help="File extension to ignore (e.g., .tmp)")

    args = parser.parse_args()
    compare_dirs(args.inpA, args.inpB, args.output, args.ignore_ext)
