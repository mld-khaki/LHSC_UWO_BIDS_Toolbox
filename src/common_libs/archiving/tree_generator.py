import os
import fnmatch
import argparse


def parse_patterns(pattern_string):
    """
    Parse inclusion and exclusion wildcard patterns.
    Anything after "|" is treated as exclusion.
    """
    include_patterns = []
    exclude_patterns = []

    if "|" in pattern_string:
        include_part, exclude_part = pattern_string.split("|", 1)
        include_patterns = [p.strip() for p in include_part.split(",") if p.strip()]
        exclude_patterns = [p.strip() for p in exclude_part.split(",") if p.strip()]
    else:
        include_patterns = [p.strip() for p in pattern_string.split(",") if p.strip()]

    return include_patterns, exclude_patterns


def matches_patterns(filename, include_patterns, exclude_patterns):
    """
    Check if filename matches include patterns and does not match exclude patterns.
    """
    included = any(fnmatch.fnmatch(filename, pattern) for pattern in include_patterns) if include_patterns else True
    excluded = any(fnmatch.fnmatch(filename, pattern) for pattern in exclude_patterns)

    return included and not excluded


def build_tree(root_path, include_patterns, exclude_patterns):
    """
    Walk directory and build a minimal text tree structure.
    """
    tree_lines = []
    root_path = os.path.abspath(root_path)

    for current_root, dirs, files in os.walk(root_path):
        # Sort alphabetically
        dirs.sort()
        files.sort()

        # Determine depth for indentation
        relative_path = os.path.relpath(current_root, root_path)
        depth = 0 if relative_path == "." else relative_path.count(os.sep) + 1

        indent = "    " * depth
        folder_name = os.path.basename(current_root)

        # Only print folder if root or if it contains matching files
        matching_files = [
            f for f in files
            if matches_patterns(f, include_patterns, exclude_patterns)
        ]

        if depth == 0:
            tree_lines.append(folder_name + "/")

        if matching_files:
            if depth > 0:
                tree_lines.append(indent + folder_name + "/")

            file_indent = "    " * (depth + 1)
            for file in matching_files:
                tree_lines.append(file_indent + file)

    return tree_lines


def main():
    parser = argparse.ArgumentParser(description="Minimal Tree View with Wildcard Include/Exclude")
    parser.add_argument("path", help="Root folder path")
    parser.add_argument(
        "-p",
        "--pattern",
        default="*",
        help="Wildcard patterns. Use '|' for exclusions. Example: '*.edf,*.tsv | *_bad.*'"
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Optional output text file"
    )

    args = parser.parse_args()

    include_patterns, exclude_patterns = parse_patterns(args.pattern)

    tree = build_tree(args.path, include_patterns, exclude_patterns)

    output_text = "\n".join(tree)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"Tree written to {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
