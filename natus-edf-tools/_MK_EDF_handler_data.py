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
        "usage": "TSV_JSON_redacting_tool.py [-h] excel_path folder_path",
        "args": ["excel_path (File)", "folder_path (Folder)"],
        "arg_name": ["", ""]
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
        "usage": "python script.py <main_folder> <output_file> [constant_path]",
        "args": ["main_folder (Folder)", "output_file (File)", "constant_path (Optional File)"],
        "arg_name": ["", "", ""]        
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
        "usage": "TSV_dates_checker.py tsv_file log_file",
        "args": [
            "tsv_file (File)",
            "log_file (File)"
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
    }    
}
