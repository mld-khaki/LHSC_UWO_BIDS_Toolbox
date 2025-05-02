import os
import gzip
import rarfile
import py7zr
import argparse


def get_gz_uncompressed_size(file_path):
    try:
        with gzip.open(file_path, 'rb') as f:
            f.read(1)  # trigger decompress header
            return f._buffer.raw._fp.tell()
    except Exception as e:
        raise(e)
        return 0


def get_rar_uncompressed_size(file_path):
    try:
        with rarfile.RarFile(file_path) as rf:
            return sum(f.file_size for f in rf.infolist())
    except Exception as e:
        raise(e)
        return 0


def get_7z_uncompressed_size(file_path):
    try:
        with py7zr.SevenZipFile(file_path, mode='r') as archive:
            return sum(f.uncompressed for f in archive.list())
    except Exception as e:
        raise(e)
        return 0


def analyze_folder(path):
    total_uncompressed = 0
    total_compressed = 0

    for root, _, files in os.walk(path):
        for file in files:
            print(f"tot_comp = {total_compressed/1e9:10.2f}, tot_unc ={total_uncompressed/1e9:10.2f}, Checking file => <{file}>")
            full_path = os.path.join(root, file)
            try:
                size = os.path.getsize(full_path)
                ext = os.path.splitext(file)[1].lower()

                if ext == '.gz':
                    total_compressed += size
                    total_uncompressed += get_gz_uncompressed_size(full_path)
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
                raise(e)
                pass  # ignore unreadable files

    return total_uncompressed, total_compressed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Calculate total uncompressed and compressed sizes of a folder")
    parser.add_argument("folder", help="Path to the folder to analyze")
    args = parser.parse_args()

    unc_size, comp_size = analyze_folder(args.folder)

    print(f"Uncompressed Size (incl. expanded archives): {unc_size / (1024 ** 3):.2f} GB")
    print(f"Compressed Archive Size: {comp_size / (1024 ** 3):.2f} GB")
