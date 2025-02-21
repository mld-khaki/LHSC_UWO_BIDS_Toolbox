## merge_tsv.py
# Author: Dr. Milad Khaki
# Date: 2025-02-21
# Description: This script merges two TSV files row-wise and saves the output as a new TSV file.
# Usage: python merge_tsv.py <file1> <file2> <output_file>
# License: MIT License

import pandas as pd
import argparse

def merge_tsv_files(file1, file2, output_file):
    """
    Merges two TSV files row-wise and saves the output as a new TSV file.

    Args:
        file1 (str): Path to the first TSV file.
        file2 (str): Path to the second TSV file.
        output_file (str): Path to save the merged TSV file.
    """
    # Read the TSV files
    df1 = pd.read_csv(file1, sep='\t')
    df2 = pd.read_csv(file2, sep='\t')

    # Merge the dataframes row-wise
    merged_df = pd.concat([df1, df2], ignore_index=True)

    # Save the merged dataframe to a new TSV file
    merged_df.to_csv(output_file, sep='\t', index=False)

    print(f"Merged file saved as: {output_file}")

def main():
    parser = argparse.ArgumentParser(description="Merge two TSV files row-wise.")
    parser.add_argument("file1", help="Path to the first TSV file.")
    parser.add_argument("file2", help="Path to the second TSV file.")
    parser.add_argument("output_file", help="Path to save the merged TSV file.")

    args = parser.parse_args()

    merge_tsv_files(args.file1, args.file2, args.output_file)

if __name__ == "__main__":
    main()
