import os
import gzip
import struct
import rarfile
import py7zr
import argparse

def get_gz_uncompressed_size(file_path):
    """Get uncompressed size of a gzip file without decompressing the entire thing."""
    try:
        # Read the last 4 bytes of the file which contain the uncompressed size (modulo 2^32)
        with open(file_path, 'rb') as f:
            f.seek(-4, 2)  # Seek to 4 bytes from the end
            size_bytes = f.read(4)
            return struct.unpack('<I', size_bytes)[0]  # Little-endian unsigned int
    except Exception as e:
        raise(e)
        print(f"Error getting size of {file_path}: {str(e)}")
        return 0

def get_rar_uncompressed_size(file_path):
    """Get uncompressed size of a RAR archive."""
    try:
        with rarfile.RarFile(file_path) as rf:
            # If we know there's only one file, we can just get the first item
            if len(rf.infolist()) == 1:
                return rf.infolist()[0].file_size
            # Otherwise sum up all files
            return sum(f.file_size for f in rf.infolist())
    except Exception as e:
        raise(e)    
        print(f"Error processing {file_path}: {str(e)}")
        return 0

def get_7z_uncompressed_size(file_path):
    """Get uncompressed size of a 7z archive."""
    try:
        with py7zr.SevenZipFile(file_path, mode='r') as archive:
            # Get file info without extracting
            file_list = list(archive.list())
            if len(file_list) == 1:
                return file_list[0].uncompressed
            return sum(f.uncompressed for f in file_list)
    except Exception as e:
        raise(e)
        print(f"Error processing {file_path}: {str(e)}")
        return 0

def analyze_folder(path):
    total_uncompressed = 0
    total_compressed = 0
    
    for root, _, files in os.walk(path):
        for file in files:
            full_path = os.path.join(root, file)
            try:
                size = os.path.getsize(full_path)
                ext = os.path.splitext(file)[1].lower()
                
                print(f"tot_comp = {total_compressed/1e9:10.2f}, tot_unc = {total_uncompressed/1e9:10.2f}, Checking file => <{file}>")
                
                if ext == '.gz':
                    total_compressed += size
                    uncompressed = get_gz_uncompressed_size(full_path)
                    total_uncompressed += uncompressed
                elif ext == '.rar':
                    total_compressed += size
                    total_uncompressed += get_rar_uncompressed_size(full_path)
                elif ext == '.7z':
                    total_compressed += size
                    total_uncompressed += get_7z_uncompressed_size(full_path)
                else:
                    total_uncompressed += size
                    total_compressed += size
            except Exception as e:
                print(f"Error processing {full_path}: {str(e)}")
                continue
    
    return total_uncompressed, total_compressed

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Calculate total uncompressed and compressed sizes of a folder")
    parser.add_argument("folder", help="Path to the folder to analyze")
    args = parser.parse_args()
    
    try:
        unc_size, comp_size = analyze_folder(args.folder)
        print(f"\nResults:")
        print(f"Uncompressed Size (incl. expanded archives): {unc_size / (1024 ** 3):.2f} GB")
        print(f"Compressed Archive Size: {comp_size / (1024 ** 3):.2f} GB")
        print(f"Compression ratio: {comp_size/unc_size:.4f} ({(1-comp_size/unc_size)*100:.2f}% space saving)")
    except Exception as e:
        print(f"An error occurred: {str(e)}")