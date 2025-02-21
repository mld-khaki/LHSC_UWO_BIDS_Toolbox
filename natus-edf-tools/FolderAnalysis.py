# -*- coding: utf-8 -*-
"""
Created on Mon Dec 16 13:57:16 2024

@author: Dr. Milad Khaki
"""

import os
import re

# def count_matching_subfolders(main_folder):
    # Regex pattern for folders named "sub-???", where ? is a digit
    # pattern = re.compile(r"sub-\d{3}.*")
    
main_folder = "y:\\ieeg_dataset_a\\bids\\" #input("Enter the path to the main folder: ").strip()

if 1:
    matching_folders_count = 0
    stat = []
    # Walk through the folder structure recursively
    for folder_name in os.listdir(main_folder):
        if folder_name == "code" or os.path.isdir(os.path.join(main_folder,folder_name)) == False:
            continue
        folder_path = os.path.join(main_folder, folder_name)
        cnt = 0
        for folder_path2 in os.listdir(folder_path):
            print(folder_path2)
            if os.path.isdir(os.path.join(folder_path,folder_path2)): #and pattern.fullmatch(folder_name):
                matching_folders_count += 1
                cnt += 1
        stat.append(cnt)
            
#     return matching_folders_count

if __name__ == "__main__":
    main_folder_path = "y:\\ieeg_dataset_a\\bids\\" #input("Enter the path to the main folder: ").strip()

    if os.path.exists(main_folder_path) and os.path.isdir(main_folder_path):
        # matching_folders_count = count_matching_subfolders(main_folder_path)
        print(f"Number of subfolders matching 'sub-???': {matching_folders_count}")
    else:
        print("The provided path is invalid or not a directory.")
