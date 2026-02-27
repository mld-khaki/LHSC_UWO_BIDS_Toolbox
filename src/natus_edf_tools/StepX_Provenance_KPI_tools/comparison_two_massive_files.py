#!/usr/bin/env python3
"""
compare_files_visual.py

Compare two files chunk by chunk, produce:
  1) A text-based map on stdout
  2) A matplotlib visualization (white=identical, black=diff)

USAGE:
    python compare_files_visual.py <file1> <file2>

NOTES:
  - For very large files, storing one "pixel" per byte in memory can be huge,
    so this script compares MD5 hashes of chunks by default. Each chunk is
    represented as a single pixel in the visualization.
  - If you only want to see the text-based map, you can comment out the
    matplotlib part.
  - If you prefer a more granular, byte-level comparison, you can modify
    the code to check each byte. But be aware of memory usage for big files.
"""

import sys
import os
import math
import hashlib

import numpy as np
import matplotlib.pyplot as plt
from tqdm import tqdm

def main():
    if len(sys.argv) != 3:
        print("Usage: python compare_files_visual.py <file1> <file2>")
        sys.exit(1)

    file1 = sys.argv[1]
    file2 = sys.argv[2]

    # -- Check files exist and are same size --
    if not os.path.isfile(file1):
        print(f"ERROR: '{file1}' not found or not a file.")
        sys.exit(1)
    if not os.path.isfile(file2):
        print(f"ERROR: '{file2}' not found or not a file.")
        sys.exit(1)

    size1 = os.path.getsize(file1)
    size2 = os.path.getsize(file2)
    if size1 != size2:
        print(f"ERROR: Files differ in size ({size1} vs {size2} bytes).")
        sys.exit(1)

    filesize = size1
    print(f"Comparing two files of {filesize} bytes each...")

    # -- Parameters --
    # chunk_size: number of bytes to read at once
    # wrap_width: how many chunk symbols per line in text output
    chunk_size = 2**20    # 1 MB per chunk (adjust as desired)
    wrap_width = 70

    # Number of chunks needed to cover entire file
    # We'll do math.ceil(...) in case filesize isn't perfectly divisible
    file_blocks = (filesize + chunk_size - 1) // chunk_size
    print(f"Reading in {file_blocks} chunk(s) of size {chunk_size} bytes each...\n")

    # We'll store 0=match, 1=difference for each chunk
    differences = np.zeros(file_blocks, dtype=np.uint8)

    # -- Open files and compare chunk by chunk --
    block_index = 0
    with open(file1, "rb") as f1, open(file2, "rb") as f2:
        with tqdm(total=file_blocks, desc="Comparing chunks") as pbar:
            while block_index < file_blocks:
                data1 = f1.read(chunk_size)
                data2 = f2.read(chunk_size)

                if not data1 or not data2:
                    # Shouldn't happen if sizes match, but just in case
                    break

                # Compute MD5 for each chunk and compare digest() values
                md5_1 = hashlib.md5(data1).digest()
                md5_2 = hashlib.md5(data2).digest()
                if md5_1 != md5_2:
                    differences[block_index] = 1  # chunk differs

                block_index += 1
                pbar.update(1)

    # -- Produce a textual map on stdout --
    # Each chunk => "." if same, "X" if different
    print("\nText-based chunk map ('.' = same, 'X' = different):")
    lines = []
    for i in range(0, file_blocks, wrap_width):
        row_slice = differences[i : i + wrap_width]
        # Convert 0->'.', 1->'X'
        row_str = "".join("." if x == 0 else "X" for x in row_slice)
        lines.append(row_str)
    for line in lines:
        print(line)

    # -- Visualization with matplotlib --
    # We only have 'file_blocks' data points, so let's shape them into a roughly
    # square 2D array, using sqrt of file_blocks, etc.
    width = int(math.sqrt(file_blocks))
    if width == 0:
        print("\nNo data to visualize. Exiting.")
        sys.exit(0)

    height = (file_blocks + width - 1) // width  # round up

    # If needed, pad the difference array so we can reshape
    padded_size = width * height
    if padded_size != file_blocks:
        padded = np.zeros(padded_size, dtype=np.uint8)
        padded[:file_blocks] = differences
        differences_2d = padded.reshape((height, width))
    else:
        differences_2d = differences.reshape((height, width))

    print(f"\nGenerating visualization with shape {height} x {width} ...")

    plt.figure(figsize=(8, 8))
    plt.rc('axes', labelsize=16)    # fontsize of the x and y labels
    plt.rc('xtick', labelsize=6)    # fontsize of the tick labels
    plt.rc('ytick', labelsize=6)    # fontsize of the tick labels

    
    # We'll show 0 as white and 1 as black (using 'gray_r' colormap)
    plt.imshow(differences_2d, cmap='viridis', aspect='equal', interpolation='nearest')
    plt.title(f"Visual Difference Map\n'{file1}' vs '{file2}'")
    plt.xlabel(f"Width ~ sqrt(num_chunks={file_blocks}) => {width}")
    plt.ylabel(f"Height => {height}")
    plt.colorbar(label="0=same chunk, 1=different chunk")
    plt.tight_layout()
    ax = plt.gca();
    ax.set_xticks(np.arange(0, width, 1)+0.5);
    ax.set_yticks(np.arange(0, height, 1)+0.5);
    ax.set_xticklabels(np.arange(1, width+1, 1));
    ax.set_yticklabels(np.arange(1, height+1, 1));
    ax.grid(color='w', linestyle='-', linewidth=0.1)

    plt.show()

if __name__ == "__main__":
    main()
