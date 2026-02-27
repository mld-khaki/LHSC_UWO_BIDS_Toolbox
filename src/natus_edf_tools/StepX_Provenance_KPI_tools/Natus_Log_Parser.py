import re
import pandas as pd
import argparse
import os

def extract_file_mappings(log_path):
    input_pattern = re.compile(r"anonymization of:\s+.*\\(?P<input_file>.+\.EDF)", re.IGNORECASE)
    output_pattern = re.compile(r"Output will be saved to:.*\\(?P<output_file>sub-.+?\.edf)", re.IGNORECASE)

    mappings = []
    current_input = None

    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            input_match = input_pattern.search(line)
            output_match = output_pattern.search(line)

            if input_match:
                current_input = input_match.group('input_file')

            if output_match and current_input:
                output_file = output_match.group('output_file')
                mappings.append((current_input, output_file))
                current_input = None

    df = pd.DataFrame(mappings, columns=['input', 'output'])
    return df

def main():
    parser = argparse.ArgumentParser(description="Extract input-output file mappings from an anonymization log.")
    parser.add_argument('log_file', help="Path to the .log or .txt file")
    parser.add_argument('--output_csv', help="Path to save the output CSV (optional)", default=None)

    args = parser.parse_args()

    if not os.path.exists(args.log_file):
        print(f"Error: Log file '{args.log_file}' not found.")
        return

    df = extract_file_mappings(args.log_file)
    print(df)

    if args.output_csv:
        df.to_csv(args.output_csv, index=False)
        print(f"\nSaved mappings to: {args.output_csv}")

if __name__ == "__main__":
    main()
