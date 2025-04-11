## NatusExportList_Generator_FromList
# Author: Dr. Milad Khaki
# Date: 2025-04-09
# Description: This script reads folder names from an input .txt file and checks if valid EEG files exist within a specified main folder. 
#              If matching EEG files are found, it generates a list with a constant path in an output file.
# Usage: python NatusExportList_Generator_FromList.py --main_folder <path> --folder_list <file.txt> --output <output.txt> [--constant_path <path>]
# License: MIT License

import os
import re
import argparse



def generate_text_file_from_list(main_folder, folder_list_file, output_file, constant_path):
    """
    Reads folder names from a text file, checks if each folder exists in main_folder,
    matches naming pattern, and if the corresponding .eeg file exists, writes the path
    to output file along with a constant path.
    """
    main_folder = main_folder if main_folder != None else ""
    folder_list_file = folder_list_file if folder_list_file != None else ""
        
    Folder_available = False
    if os.path.exists(main_folder) and os.path.isdir(main_folder):
        Folder_available = True
        
    File_available = False
    if os.path.isfile(folder_list_file):
        File_available = True
        
       
    if File_available == False and Folder_available == False:
        raise ValueError(f"Either Folder list file does not exist: {folder_list_file} or Invalid main folder path: {main_folder}")
    
    if File_available:
        with open(folder_list_file, 'r') as flf:
            folder_names = [line.strip() for line in flf if line.strip()]


    
    if Folder_available and File_available == False:
        folder_names = []
        for folder in os.listdir(main_folder):
            folder_path = os.path.join(main_folder, folder)
            folder_names.append(folder_path)
            
    pattern = re.compile(r"^[^\\/]*~[^\\/]*_[^\\/]*-[^\\/]*-[^\\/]*-[^\\/]*-[^\\/]*$")
    
    print("Found folders are:")
    for qCtr in folder_names:
        print(f"{qCtr}")
        
    with open(output_file, 'w') as of:
        for folder in folder_names:
            folder_tmp = os.path.join(main_folder, folder)
            
            if os.path.isdir(folder_tmp) and pattern.match(folder):
                eeg_file = os.path.join(folder_tmp, f"{folder}.eeg")
                eeg_file = eeg_file.replace("/",f"\\")
                if os.path.isfile(eeg_file):
                    of.write(f"{eeg_file}, {constant_path}\n")
            else: 
                print(f"Error! folder <{folder_tmp}> does not exist!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate EEG file list from folder names in a text file.")
    parser.add_argument('--main_folder', required=False, help="Main folder containing EEG subdirectories.")
    parser.add_argument('--folder_list', required=False, help="Text file with folder names (one per line).")
    parser.add_argument('--output', required=True, help="Output text file to write valid EEG file paths.")
    parser.add_argument('--constant_path', default="D:\\Neuroworks\\Settings\\quant_new_256_with_photic.exp", help="Constant path to append to each line.")

    args = parser.parse_args()

    try:
        generate_text_file_from_list(args.main_folder, args.folder_list, args.output, args.constant_path)
        print(f"Output file generated: {args.output}")
    except Exception as e:
        raise(e)
        print(f"Error: {e}")
        exit(1)
