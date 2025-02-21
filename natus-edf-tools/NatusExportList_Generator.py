import os
import re
import sys

def generate_text_file(main_folder, output_file, constant_path):
    """
    Scans the given main folder for subdirectories matching the pattern containing:
    - One '~'
    - One '_'
    - Four '-'
    
    If a matching subdirectory contains a file with the same name and '.eeg' extension, 
    it writes the file path along with a constant path to the output file.
    
    Args:
        main_folder (str): Path to the main folder containing subdirectories.
        output_file (str): Path to the output text file.
        constant_path (str): Constant path to append in each line of the output file.
    """
    
    if not os.path.exists(main_folder) or not os.path.isdir(main_folder):
        raise ValueError(f"Invalid main folder path: {main_folder}")
    
    pattern = re.compile(r"^[^\\/]*~[^\\/]*_[^\\/]*-[^\\/]*-[^\\/]*-[^\\/]*-[^\\/]*$")
    
    with open(output_file, 'w') as file:
        for folder in os.listdir(main_folder):
            folder_path = os.path.join(main_folder, folder)
            
            if os.path.isdir(folder_path) and pattern.match(folder):
                eeg_file = os.path.join(folder_path, f"{folder}.eeg")
                if os.path.isfile(eeg_file):
                    file.write(f"{eeg_file}, {constant_path}\n")

if __name__ == "__main__":
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print("Usage: python script.py <main_folder> <output_file> [constant_path]")
        sys.exit(1)
    
    main_folder = sys.argv[1]
    output_file = sys.argv[2]
    constant_path = sys.argv[3] if len(sys.argv) == 4 else "D:\\Neuroworks\\Settings\\quantum_new.exp"
    
    try:
        generate_text_file(main_folder, output_file, constant_path)
        print(f"Output file generated: {output_file}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
