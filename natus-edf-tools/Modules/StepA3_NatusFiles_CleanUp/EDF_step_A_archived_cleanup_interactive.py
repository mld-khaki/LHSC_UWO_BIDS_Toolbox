import os
import argparse
import shutil

def find_rar_basenames(folder_a):
    rar_files = [f for f in os.listdir(folder_a) if f.endswith('.rar')]
    return set(os.path.splitext(f)[0] for f in rar_files)

def find_matching_folders(folder_b, rar_basenames):
    matches = []
    for entry in os.listdir(folder_b):
        full_path = os.path.join(folder_b, entry)
        if os.path.isdir(full_path):
            for rar_name in rar_basenames:
                if rar_name in entry:
                    matches.append((entry, full_path, rar_name))
                    break
    return matches

def prompt_user_and_delete(matches):
    delete_all = False
    skipped = []

    for name, path, matched_rar in matches:
        if delete_all:
            shutil.rmtree(path)
            print(f"  ✅ Deleted (auto): {path}")
            continue

        print(f"\n📂 Found folder:\r\n\t{name}\r\nmatches archive:\r\n\t{matched_rar}.rar")
        response = input("Delete? [y/n/All]: ").strip().lower()

        if response in ['y', 'yes']:
            shutil.rmtree(path)
            print(f"  ✅ Deleted: {path}")
        elif response == 'all':
            print("\n⚠️ You selected 'All'. The following folders will be deleted:")
            for name2, path2, _ in matches[matches.index((name, path, matched_rar)):]:
                print(f"  • {path2}")
            confirm = input("\nConfirm deletion of ALL remaining folders? [yes/no]: ").strip().lower()
            if confirm == 'yes':
                delete_all = True
                shutil.rmtree(path)
                print(f"  ✅ Deleted: {path}")
            else:
                print("  ❌ Cancelled bulk deletion.")
                skipped.append((name, path))
        else:
            print(f"  ❌ Skipped: {path}")
            skipped.append((name, path))

    print("\n📊 Summary:")
    print(f"✅ Deleted: {len(matches) - len(skipped)}")
    print(f"❌ Skipped: {len(skipped)}")
    if skipped:
        print("📁 Skipped folders:")
        for name, path in skipped:
            print(f"  • {path}")

def main(folder_a, folder_b):
    print(f"📦 Checking archive folder: {folder_a}")
    print(f"📂 Scanning target folders in: {folder_b}")

    rar_basenames = find_rar_basenames(folder_a)
    matches = find_matching_folders(folder_b, rar_basenames)

    if not matches:
        print("✅ No folders to delete.")
        return

    print(f"\n🔍 {len(matches)} folders matched .rar files.\n")
    prompt_user_and_delete(matches)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete folders in B if a matching .rar archive exists in A.")
    parser.add_argument("folder_a", help="Path to folder A (contains .rar archives)")
    parser.add_argument("folder_b", help="Path to folder B (contains folders that may be deleted)")

    args = parser.parse_args()
    main(args.folder_a, args.folder_b)
