import os
from pathlib import Path
import shutil
import random
import json
import time

def create_dummy_file(path: Path, size: int = 2048, content: bytes = None):
    with open(path, 'wb') as f:
        if content:
            # If content is shorter than size, repeat it to fill
            data = (content * ((size // len(content)) + 1))[:size]
            f.write(data)
        else:
            f.write(os.urandom(size))


def create_session_folder(root: Path, name: str, content: bytes = None, add_json=True, add_tsv=True, add_log=False):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    edf = folder / f"{name}.edf"
    create_dummy_file(edf, size=120048000, content=content)

    if add_json:
        meta_json = folder / f"{name}.json"
        meta_json.write_text(json.dumps({"Recording": name, "Dummy": True}, indent=2))

    if add_tsv:
        meta_tsv = folder / f"{name}.tsv"
        meta_tsv.write_text("column1\tcolumn2\nval1\tval2\n")

    if add_log:
        log_file = folder / f"{name}.log"
        log_file.write_text("This is a log file.\n")

    print(f"Created session: {folder}")
    return folder

def generate_test_dataset(root: str, num_folders: int = 9, num_duplicates: int = 3):
    root_path = Path(root)
    if root_path.exists():
        shutil.rmtree(root_path)
    root_path.mkdir(parents=True)

    # Create a few folders with identical EDF content to simulate duplicates
    shared_content = os.urandom(2048)

    for i in range(num_folders):
        name = f"trial_{i+1:02d}"
        if i < num_duplicates:
            # Duplicates
            create_session_folder(root_path, name, content=shared_content, add_log=(i % 2 == 0))
        else:
            # Unique content
            create_session_folder(root_path, name, content=os.urandom(2048), add_log=(i % 2 == 0))

    print(f"\n✅ Test data created under: {root_path.absolute()}\n")

if __name__ == '__main__':
    generate_test_dataset('./test_sessions', num_folders=6, num_duplicates=2)
