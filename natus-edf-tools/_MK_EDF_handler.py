import PySimpleGUI as sg
import subprocess
import sys

# Define tools and arguments
tools = {
    "EDF_dir_scanner": {
        "usage": "EDF_dir_scanner.py [-h] [--output OUTPUT] folder",
        "args": ["--output (File)", "folder (Folder)"],
        "arg_name": ["--output", ""]
    },
    "TSV_JSON_redacting_tool": {
        "usage": "TSV_JSON_redacting_tool.py [-h] excel_path folder_path",
        "args": ["excel_path (File)", "folder_path (Folder)"],
        "arg_name": ["--output", ""]
    },
    "Natus_InfoExtractor": {
        "usage": "Natus_InfoExtractor.py [-h] [-o OUTPUT] input_dir",
        "args": ["-o OUTPUT (File)", "input_dir (Folder)"],
        "arg_name": ["--output", ""]
    },
    "NatusExportList_Generator": {
        "usage": "python script.py <main_folder> <output_file> [constant_path]",
        "args": ["main_folder (Folder)", "output_file (File)", "constant_path (Optional File)"],
        "arg_name": ["--output", ""]        
    },
    "FolderAnalysis": {
        "usage": "(placeholder for now)",
        "args": [],
        "arg_name": ["--output", ""]        
    },
    "TSV_Participant_Merger": {
        "usage": "TSV_Participant_Merger.py [-h] file1 file2 output_file",
        "args": ["file1 (File)", "file2 (File)", "output_file (File)"],
        "arg_name": ["--output", ""]        
    },
    "EDF_RAR_archive_purger": {
        "usage": "EDF_RAR_archive_purger.py [-h] <folder> output_file",
        "args": ["search_folder (Folder)", "out_log_file (File)"],
        "arg_name": ["", ""]        
    }
}

# GUI Layout
layout = [
    [sg.Text("Select a tool:")],
    [sg.Listbox(values=list(tools.keys()), size=(40, 6), key="TOOL", enable_events=True)],
    [sg.Text("Arguments:"), sg.Button("Show Help", key="HELP")],
    [sg.Multiline("", size=(60, 4), key="ARGS", disabled=True)],
    [sg.Text("Select files and folders based on required arguments:")],
    [sg.Column([], key="DYNAMIC_INPUTS")],
    [sg.Button("Run"), sg.Button("Exit")],
    [sg.Multiline(size=(60, 10), key="OUTPUT", autoscroll=True, disabled=True)]
]

# Create window
window = sg.Window("Generalized Script Launcher", layout)

def update_dynamic_inputs(tool_name):
    """Dynamically update the input fields based on the selected tool."""
    window["DYNAMIC_INPUTS"].update(visible=False)
    inputs = []
    for arg in tools[tool_name]["args"]:
        arg_name, arg_type = arg.rsplit(" ", 1)
        if "(File)" in arg_type:
            inputs.append([sg.Text(arg_name), sg.Input(key=arg_name), sg.FileSaveAs()])
        elif "(Folder)" in arg_type:
            inputs.append([sg.Text(arg_name), sg.Input(key=arg_name), sg.FolderBrowse()])
    window.extend_layout(window["DYNAMIC_INPUTS"], inputs)
    window["DYNAMIC_INPUTS"].update(visible=True)

# Event Loop
while True:
    event, values = window.read()
    if event in (sg.WINDOW_CLOSED, "Exit"):
        break
    elif event == "TOOL":
        selected_tool = values["TOOL"][0] if values["TOOL"] else ""
        window["ARGS"].update(tools.get(selected_tool, {}).get("usage", ""))
        update_dynamic_inputs(selected_tool)
    elif event == "HELP":
        selected_tool = values["TOOL"][0] if values["TOOL"] else ""
        if selected_tool:
            sg.popup("Usage Help", tools[selected_tool]["usage"])
    elif event == "Run":
        tool = values["TOOL"][0] if values["TOOL"] else None
        if tool:
            args = []
            for cnt in range(len(tools[tool]["args"])):
                arg_tmp = tools[tool]["args"][cnt]
                arg_val = tools[tool]["arg_name"][cnt]
                arg_name = arg_tmp.rsplit(" ", 1)[0]
                if values.get(arg_name):
                    if arg_val != "":
                        args.append(arg_val)
                    args.append(values[arg_name])
            
            # Run selected script with arguments
            script_path = f"./{tool}.py"  # Adjust if scripts are in a different directory
            command = [sys.executable, script_path] + args

            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                while True:
                    line = process.stdout.readline()
                    if not line:
                        break
                    window["OUTPUT"].update(line, append=True)
                process.wait()
                if process.returncode != 0:
                    window["OUTPUT"].update("Error Output:\n" + process.stderr.read(), append=True)
            except subprocess.CalledProcessError as e:
                sg.popup_error("Execution Failed", f"Error:\n{e.stderr}, error={process.stderr.read()}")
        else:
            sg.popup("Error", "Please select a tool before running.")

window.close()
