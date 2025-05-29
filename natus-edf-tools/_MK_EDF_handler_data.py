# Define tools and arguments
tools = {
    "Arg_Parser": {
        "usage": "Arg_Parser.py <python_file> [output_file]",
        "args": ["python_file (File)","output_file (Optional) (File)"],
        "arg_name": ["",""]
    },
    "EDF_dir_scanner": {
        "usage": "EDF_dir_scanner.py [-h] [--output OUTPUT] folder",
        "args": ["--output (File)", "folder (Folder)"],
        "arg_name": ["--output", ""]
    },
    "redactor_TSV_JSON": {
        "usage": "redactor_TSV_JSON.py excel_path input_folder backup_folder_org backup_folder_upd",
        "args": [
            "excel_path (File)",
            "input_folder (File)",
            "backup_folder_org (File)",
            "backup_folder_upd (File)"
        ],
        "arg_name": ["","","",""]
    },
    "Natus_InfoExtractor": {
        "usage": "Natus_InfoExtractor.py [-h] [-o OUTPUT] input_dir",
        "args": ["-o OUTPUT (File)", "input_dir (Folder)"],
        "arg_name": ["-o", ""]
    },
    "Natus_InfoExtractor_v2": {
        "usage": "Natus_InfoExtractor.py [-h] [-o OUTPUT] input_dir",
        "args": ["-o OUTPUT (File)", "input_dir (Folder)"],
        "arg_name": ["-o", ""]
    },
        "NatusExportList_Generator": {
        "usage": "NatusExportList_Generator.py [--main_folder] [--folder_list] [--output] [--constant_path]",
        "args": [
            "--main_folder (Folder)",
            "--folder_list (File)",
            "--output (File)",
            "--constant_path (File)"
        ],
        "arg_name": ["--main_folder","--folder_list","--output","--constant_path"]
    },
    "TSV_Participant_Merger": {
        "usage": "TSV_Participant_Merger.py [-h] file1 file2 output_file",
        "args": ["file1 (File)", "file2 (File)", "output_file (File)"],
        "arg_name": ["", "", ""]        
    },
    "EDF_RAR_archive_purger": {
        "usage": "EDF_RAR_archive_purger.py [-h] <folder> output_file",
        "args": ["search_folder (Folder)", "out_log_file (File)"],
        "arg_name": ["", ""]        
    },
    "comparison__TextList_Folder": {
        "usage": "TextList_Folder_Comparison.py folder txtfile",
        "args": ["folder (Folder)","txtfile (File)"],
        "arg_name": ["",""]
    },
    "EDF_Anonymization_Scanner": {
        "usage": "EDF_Anonymization_Scanner.py directory [--output] [--log_dir] [--log_level] [--max_workers] [--skip_annotations]",
        "args": [
            "directory (File)",
            "--output (File)",
            "--log_dir (File)",
            "--log_level (File)",
            "--max_workers (File)",
            "--skip_annotations (File)"
        ],
        "arg_name": ["",
            "--output",
            "--log_dir",
            "--log_level",
            "--max_workers",
            "--skip_annotations"]
    },
    "comparison_two_massive_files": {
        "usage": "python compare_files_visual.py <file1> <file2>",
        "args": ["python (File)","file1 (File)","file2 (File)"],
        "arg_name": ["","",""]},
        
    "Server_update_check": {
        "usage": "Server_update_check.py inpA inpB [--output] [--ignore_ext]",
        "args": ["inpA (Folder)","inpB (Folder)","--output (File)","--ignore_ext (File)"],
        "arg_name": ["","","--output","--ignore_ext"]
    },   
    "TSV_dates_checker": {
        "usage": "TSV_dates_checker.py tsv_file <out_log_file>",
        "args": [
            "tsv_file (File)",
            "out_log_file (File)"
        ],
        "arg_name": ["",""]
    },
   "Natus_TimeValue_Converter": {
        "usage": "python convert_date.py <serial_number>",
        "args": [
            "python (File)",
            "serial_number (File)"
        ],
        "arg_name": ["",""]
    },
    "Natus_Log_Parser": {
        "usage": "Natus_Log_Parser.py log_file [--output_csv]",
        "args": [
            "log_file (File)",
            "--output_csv (File)"
        ],
        "arg_name": ["","--output_csv"]
    },
    "FolderFile_NameCheck": {
        "usage": "FolderFile_NameCheck.py [--list] [--dir]",
        "args": [
            "--list (File)",
            "--dir (Folder)"
        ],
        "arg_name": ["--list","--dir"]
    },
    "EDF_time_calculator": {
        "usage": "EDF_time_calculator.py [--total_records] [--duration] [--start_time] [--target_start] [--target_end] [--pre_offset] [--post_offset]",
        "args": [
            "--total_records (File)",
            "--duration (File)",
            "--start_time (File)",
            "--target_start (File)",
            "--target_end (File)",
            "--pre_offset (File)",
            "--post_offset (File)"
        ],
        "arg_name": ["--total_records","--duration","--start_time","--target_start","--target_end","--pre_offset","--post_offset"]
    },
    "EDF_folders_matching_tool": {
        "usage": "EDF_folders_matching_tool.py folder_a folder_b sha256 output_file",
        "args": [
            "folder_a (Folder)",
            "folder_b (Folder)",
            "sha256 (File)",
            "output_file (File)"
        ],
        "arg_name": ["","","",""]
    },
    "EDF_Compatibility_Check_Tool": {
        "usage": "EDF_Compatibility_Check_Tool.py [--edfbrowser] [--recursive] --folder <folder>",
        "args": [
            "--edfbrowser (File)",
            "--recursive (Flag)",
            "--folder (Folder)"
        ],
        "arg_name": ["--edfbrowser","--recursive","--folder"],
    },
    "EDF_dir_scanner_renamer": {
        "usage": "EDF_dir_scanner_renamer.py folder",
        "args": [
            "folder (File)"
        ],
        "arg_name": [""]
    },
    "EDF_step_A_cleanup": {
        "usage": "EDF_step_A_cleanup.py [--folder_a] [--folder_b] [--dry-run / --real-del-mode]",
        "args": [
            "--folder-a (Step A folder) (Folder)",
            "--folder-b (EDFs, Step B (Folder)",
            "--dry-run (Flag)",
            "--real-del-mode (Flag)"
        ],
        "arg_name": [
            "--folder-a",
            "--folder-b",
            "--dry-run",
            "--real-del-mode"
        ]
    },
    "redactor_EDF_EmbeddedAnnotations": {
        "usage": "redactor_EDF_EmbeddedAnnotations.py input_path output_path [--buffer_size_mb] [--verify] [--verify_level] [--log_dir] [--log_level]",
        "args": [
            "input_path (File)",
            "output_path (File)",
            "--buffer_size_mb (File)",
            "--verify (File)",
            "--verify_level (File)",
            "--log_dir (File)",
            "--log_level (File)"
        ],
        "arg_name": ["","","--buffer_size_mb","--verify","--verify_level","--log_dir","--log_level"]
    },
    "EDF_BIDS_Cleanup_Archive_post_step_C": {
        "usage": "EDF_BIDS_Cleanup_Archive_post_step_C.py [--excel] [--source] [--dest] store_true",
        "args": [
            "--excel (File)",
            "--source (File)",
            "--dest (Folder)",
            "store_true (File)"
        ],
        "arg_name": ["--excel","--source","--dest",""]
    }
}
