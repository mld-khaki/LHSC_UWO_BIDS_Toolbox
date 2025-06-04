import os
import fnmatch
import argparse

def read_patterns_from_file(file_path):
    """
    Read search patterns from a file. Each line should be either a filename or a folder name.
    To specify folders, end the line with a backslash (e.g., "foldername\\").
    """
    with open(file_path, 'r') as f:
        patterns = [line.strip() for line in f if line.strip()]
    return patterns

def match_patterns(patterns, base_folder):
    """
    Match each pattern in the list to files or folders in the base folder.
    """
    found = []
    not_found = []

    print(f"\nSearching in base directory: {os.path.abspath(base_folder)}")
    print("Note:")
    print("  - Use exact filenames or folder names (no wildcards)")
    print("  - To match folders, append a backslash at the end (e.g., 'myfolder\\')\n")

    try:
        candidates = os.listdir(base_folder)
    except FileNotFoundError:
        print(f"Error: The directory '{base_folder}' does not exist.")
        return found, patterns

    for pattern in patterns:
        is_folder = pattern.endswith("\\")
        clean_pattern = pattern.rstrip("\\")

        print(f"Checking: '{pattern}' ...", end=" ")

        matched = fnmatch.filter(candidates, clean_pattern)
        matched_valid = []

        for m in matched:
            full_path = os.path.join(base_folder, m)
            if is_folder and os.path.isdir(full_path):
                matched_valid.append(m)
            elif not is_folder and os.path.isfile(full_path):
                matched_valid.append(m)

        if matched_valid:
            print("Found")
            found.append(pattern)
        else:
            print("Not Found")
            not_found.append(pattern)

    return found, not_found

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Check if files or folders listed in a text file exist in a target directory.\n"
            "Instructions:\n"
            "  - Each line in the list should be an exact name.\n"
            "  - End folder names with a backslash to indicate directory (e.g., 'data\\').\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--list", required=True, help="Path to .txt file containing list of names (e.g., files or folders)")
    parser.add_argument("--dir", required=True, help="Directory to search in")

    args = parser.parse_args()

    if not os.path.isfile(args.list):
        print(f"Error: List file '{args.list}' does not exist.")
        return

    patterns = read_patterns_from_file(args.list)
    found, not_found = match_patterns(patterns, args.dir)

    print("\n=== FOUND ITEMS ===")
    for f in found:
        print(f"  {f}")

    print("\n=== MISSING ITEMS ===")
    for nf in not_found:
        print(f"  {nf}")

if __name__ == "__main__":
    main()
