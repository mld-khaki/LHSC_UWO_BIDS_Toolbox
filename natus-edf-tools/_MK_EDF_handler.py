import PySimpleGUI as sg
import subprocess
import sys
import os
import re
import json
import datetime
from datetime import datetime

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
    }    
}


# GUI Layout with fixed inputs for all possible arguments
# We'll hide/show them based on the selected tool
max_args = max([len(tool["args"]) for tool in tools.values()])
dynamic_inputs = []

for i in range(max_args):
    row = [
        sg.Text("", size=(20, 1), key=f"ARG_LABEL_{i}", visible=False),
        sg.Input(key=f"ARG_INPUT_{i}", visible=False, size=(30, 1), enable_events=True),
        sg.FileBrowse(key=f"ARG_BROWSE_{i}", visible=False, target=f"ARG_INPUT_{i}"),
        sg.FolderBrowse(key=f"ARG_FOLDER_{i}", visible=False, target=f"ARG_INPUT_{i}"),
        sg.FileSaveAs(key=f"ARG_SAVE_{i}", visible=False, target=f"ARG_INPUT_{i}")
    ]
    dynamic_inputs.append(row)

# Main GUI Layout

tools = dict(sorted(tools.items()))
list_main = list(tools.keys())
print(list_main)
layout = [
    [sg.Text("Select a tool:")],
    [sg.Listbox(values=list_main, size=(40, 6), key="TOOL", enable_events=True)],
    [sg.Text("Arguments:"), sg.Button("Show Help", key="HELP")],
    [sg.Multiline("", size=(60, 4), key="ARGS", disabled=True)],
    [sg.Text("Select files and folders based on required arguments:")],
    *dynamic_inputs,
    [sg.Text("Generated Command:")],
    [sg.Multiline("", size=(60, 3), key="COMMAND_PREVIEW", disabled=True)],
    [sg.Checkbox("Save output with configuration", key="SAVE_OUTPUT_WITH_CONFIG", default=False)],
    [sg.Button("Run"), sg.Button("Save Output", key="SAVE_OUTPUT", disabled=True), 
     sg.Button("Save Config", key="SAVE_CONFIG"), sg.Button("Load Config", key="LOAD_CONFIG"), 
     sg.Button("Copy Command", key="COPY_COMMAND"), sg.Button("Exit")],
    [sg.Multiline(size=(60, 10), key="OUTPUT", autoscroll=True, disabled=True)]
]

# Create window
window = sg.Window("Generalized Script Launcher", layout, finalize=True)

def determine_arg_properties(arg_str):
    """Determine the properties of an argument based on its string representation."""
    # Split the argument string into name and type
    if " (" in arg_str:
        arg_name, arg_type = arg_str.rsplit(" (", 1)
        arg_type = "(" + arg_type  # Add the opening parenthesis back
    else:
        arg_name = arg_str
        arg_type = "(File)"  # Default type
    
    # Determine if it's an input or output file
    is_output = False
    is_optional = False
    
    # Check for explicit output indicators
    if "output" in arg_name.lower() or "out" in arg_name.lower():
        is_output = True
    
    # Check if it's marked as optional
    if "optional" in arg_type.lower():
        is_optional = True
        # Clean up the arg type (remove 'Optional' from display)
        arg_type = re.sub(r'\(Optional\)\s*', '', arg_type)
    
    return arg_name, arg_type, is_output, is_optional

def update_dynamic_inputs(tool_name):
    """Dynamically show/hide input fields based on the selected tool."""
    # Hide all input elements first
    for i in range(max_args):
        window[f"ARG_LABEL_{i}"].update(visible=False)
        window[f"ARG_INPUT_{i}"].update(visible=False, value="")
        window[f"ARG_BROWSE_{i}"].update(visible=False)
        window[f"ARG_FOLDER_{i}"].update(visible=False)
        window[f"ARG_SAVE_{i}"].update(visible=False)
    
    # Show only needed input elements
    for i, arg in enumerate(tools[tool_name]["args"]):
        arg_name, arg_type, is_output, is_optional = determine_arg_properties(arg)
        
        # Create appropriate label with optional indicator if needed
        label_text = f"{arg_name}{' (Optional)' if is_optional else ''}"
        window[f"ARG_LABEL_{i}"].update(visible=True, value=label_text)
        window[f"ARG_INPUT_{i}"].update(visible=True)
        
        # Show the appropriate browse button
        if "(Folder)" in arg_type:
            window[f"ARG_FOLDER_{i}"].update(visible=True)
        elif is_output:
            window[f"ARG_SAVE_{i}"].update(visible=True)
        else:
            window[f"ARG_BROWSE_{i}"].update(visible=True)
    
    # Initialize command preview with empty values
    arg_values = {}
    for i in range(len(tools[tool_name]["args"])):
        arg_values[f"ARG_INPUT_{i}"] = ""
    
    update_command_preview(tool_name, arg_values)

def save_output_to_file(output_text, suggested_filename=None):
    """Save the console output to a text file."""
    try:
        if suggested_filename:
            initial_folder, initial_file = os.path.split(suggested_filename)
        else:
            initial_folder = ""
            initial_file = ""
            
        filename = sg.popup_get_file(
            'Save Output As', 
            save_as=True, 
            file_types=(('Text Files', '*.txt'), ('All Files', '*.*')),
            default_extension='.txt',
            initial_folder=initial_folder,
            default_path=initial_file
        )
        
        if filename:
            with open(filename, 'w') as file:
                file.write(output_text)
            sg.popup(f"Output saved to {filename}")
            return filename
        return None
    except Exception as e:
        sg.popup_error(f"Error saving output: {str(e)}")
        return None

def save_configuration(values, output_text=None):
    """Save the current tool configuration to a JSON file."""
    try:
        # Get the selected tool
        tool = values["TOOL"][0] if "TOOL" in values and values["TOOL"] else None
        
        if not tool:
            sg.popup_warning("No tool selected. Cannot save configuration.")
            return None
            
        # Prepare the configuration data
        config = {
            "tool": tool,
            "arguments": {},
            "save_output_with_config": values.get("SAVE_OUTPUT_WITH_CONFIG", False),
            "timestamp": datetime.now().isoformat(),
        }
        
        # Get all the argument values for the selected tool
        if tool in tools:
            for i, arg in enumerate(tools[tool]["args"]):
                arg_name, _, _, _ = determine_arg_properties(arg)
                input_key = f"ARG_INPUT_{i}"
                if input_key in values:
                    config["arguments"][i] = values[input_key]
        
        # Include output if requested
        if values.get("SAVE_OUTPUT_WITH_CONFIG", False) and output_text:
            config["output"] = output_text
            
        # Get filename from user
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"{tool}_config_{timestamp}.json"
        
        filename = sg.popup_get_file(
            'Save Configuration As', 
            save_as=True, 
            file_types=(('JSON Files', '*.json'), ('All Files', '*.*')),
            default_extension='.json',
            default_path=default_filename
        )
        
        if filename:
            with open(filename, 'w') as file:
                json.dump(config, file, indent=4)
            sg.popup(f"Configuration saved to {filename}")
            return filename
        return None
    except Exception as e:
        sg.popup_error(f"Error saving configuration: {str(e)}")
        return None

def load_configuration():
    """Load a previously saved configuration."""
    try:
        filename = sg.popup_get_file(
            'Load Configuration File', 
            file_types=(('JSON Files', '*.json'), ('All Files', '*.*'))
        )
        
        if not filename:
            return None
            
        with open(filename, 'r') as file:
            config = json.load(file)
            
        return config
    except Exception as e:
        sg.popup_error(f"Error loading configuration: {str(e)}")
        return None

def update_command_preview(tool, values):
    """Update the command preview box with the current command."""
    if not tool:
        window["COMMAND_PREVIEW"].update("")
        return
    
    # Build arguments list
    args = []
    
    # Make sure we don't exceed the length of the arg_name list
    for i in range(len(tools[tool]["args"])):
        arg_tmp = tools[tool]["args"][i]
        arg_name, _, _, _ = determine_arg_properties(arg_tmp)
        input_key = f"ARG_INPUT_{i}"
        
        # Check if we have the corresponding arg_name (handles case where arg_name list is shorter)
        arg_val = ""
        if i < len(tools[tool]["arg_name"]):
            arg_val = tools[tool]["arg_name"][i]
        
        if input_key in values and values[input_key]:
            if arg_val:
                args.append(arg_val)
            args.append(values[input_key])
    
    # Construct the command
    script_path = f"./{tool}.py"
    cmd_parts = [f'"{sys.executable}"', f'"{script_path}"']
    for arg in args:
        cmd_parts.append(f'"{arg}"')
    
    cmd_string = " ".join(cmd_parts)
    window["COMMAND_PREVIEW"].update(cmd_string)
    window["COPY_COMMAND"].update(disabled=False)

def apply_configuration(config, window):
    """Apply a loaded configuration to the UI."""
    try:
        # Check if the tool exists
        tool = config.get("tool")
        if not tool or tool not in tools:
            sg.popup_error(f"Tool '{tool}' not found in the current configuration.")
            return False
            
        # Select the tool in the listbox
        window["TOOL"].update(set_to_index=[list(tools.keys()).index(tool)])
        window["ARGS"].update(tools[tool]["usage"])
        
        # Update the dynamic inputs
        update_dynamic_inputs(tool)
        
        # Apply the saved argument values
        arguments = config.get("arguments", {})
        for i, value in arguments.items():
            input_key = f"ARG_INPUT_{int(i)}"
            if input_key in window.AllKeysDict:
                window[input_key].update(value)
                
        # Set the save output checkbox
        if "save_output_with_config" in config:
            window["SAVE_OUTPUT_WITH_CONFIG"].update(config["save_output_with_config"])
            
        # Display the saved output if available
        if "output" in config and config["output"]:
            window["OUTPUT"].update(config["output"])
            window["SAVE_OUTPUT"].update(disabled=False)
            
        # Update command preview with the current values
        current_values = window.read(timeout=0)[1]
        update_command_preview(tool, current_values)
            
        # Show configuration timestamp if available
        if "timestamp" in config:
            try:
                dt = datetime.fromisoformat(config["timestamp"])
                timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                sg.popup(f"Configuration loaded successfully!\nCreated on: {timestamp_str}")
            except:
                sg.popup("Configuration loaded successfully!")
        else:
            sg.popup("Configuration loaded successfully!")
            
        return True
    except Exception as e:
        sg.popup_error(f"Error applying configuration: {str(e)}")
        return False

# Event Loop
while True:
    event, values = window.read()
    
    if event in (sg.WINDOW_CLOSED, "Exit"):
        break
    elif event == "TOOL":
        selected_tool = values["TOOL"][0] if values["TOOL"] else ""
        window["ARGS"].update(tools.get(selected_tool, {}).get("usage", ""))
        if selected_tool:
            update_dynamic_inputs(selected_tool)
    elif event == "HELP":
        selected_tool = values["TOOL"][0] if values["TOOL"] else ""
        if selected_tool:
            sg.popup("Usage Help", tools[selected_tool]["usage"])
    elif event == "SAVE_OUTPUT":
        output_text = window["OUTPUT"].get()
        if output_text.strip():
            save_output_to_file(output_text)
        else:
            sg.popup_warning("There is no output to save.")
    elif event == "COPY_COMMAND":
        command_text = window["COMMAND_PREVIEW"].get()
        if command_text:
            sg.clipboard_set(command_text)
            sg.popup("Command copied to clipboard!")
        else:
            sg.popup_warning("No command to copy.")
    elif event == "SAVE_CONFIG":
        output_text = window["OUTPUT"].get() if values.get("SAVE_OUTPUT_WITH_CONFIG") else None
        save_configuration(values, output_text)
    elif event == "LOAD_CONFIG":
        config = load_configuration()
        if config:
            apply_configuration(config, window)
    elif event == "Run":
        tool = values["TOOL"][0] if values["TOOL"] else None
        if tool:
            args = []
            for i in range(len(tools[tool]["args"])):
                arg_tmp = tools[tool]["args"][i]
                arg_name, _, _, _ = determine_arg_properties(arg_tmp)
                input_key = f"ARG_INPUT_{i}"
                
                # Check if we have the corresponding arg_name (handles case where arg_name list is shorter)
                arg_val = ""
                if i < len(tools[tool]["arg_name"]):
                    arg_val = tools[tool]["arg_name"][i]
                
                if input_key in values and values[input_key]:
                    if arg_val:
                        args.append(arg_val)
                    args.append(values[input_key])
            
            # Run selected script with arguments
            script_path = f"./{tool}.py"  # Adjust if scripts are in a different directory
            
            # Check if script exists before running
            if not os.path.exists(script_path):
                sg.popup_error("Script Not Found", f"The script file '{script_path}' was not found.")
                continue
                
            command = [sys.executable, script_path] + args
            
            # Update command preview
            cmd_string = " ".join([f'"{c}"' for c in command])
            window["COMMAND_PREVIEW"].update(cmd_string)
            window["COPY_COMMAND"].update(disabled=False)
            
            # Clear previous output
            window["OUTPUT"].update("")
            window["SAVE_OUTPUT"].update(disabled=True)

            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                
                # Read stdout in real-time
                while True:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if line:
                        window["OUTPUT"].update(line, append=True)
                        window.refresh()
                
                # Get final return code and stderr
                return_code = process.wait()
                stderr_output = process.stderr.read()
                
                if return_code != 0:
                    window["OUTPUT"].update("\nError Output:\n" + stderr_output, append=True)
                    sg.popup_error("Process Error", f"The script returned with error code {return_code}")
                
                # Enable Save Output button if there's any output
                if window["OUTPUT"].get().strip():
                    window["SAVE_OUTPUT"].update(disabled=False)
            except Exception as e:
                sg.popup_error("Execution Failed", f"Error: {str(e)}")
        else:
            sg.popup("Error", "Please select a tool before running.")
    # Update command preview whenever an input changes
    elif event.startswith("ARG_INPUT_"):
        selected_tool = values["TOOL"][0] if values["TOOL"] else None
        if selected_tool:
            update_command_preview(selected_tool, values)

window.close()