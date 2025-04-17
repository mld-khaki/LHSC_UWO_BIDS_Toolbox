import PySimpleGUI as sg
import subprocess
import sys
import os
import re
import json
import datetime
from datetime import datetime
from _MK_EDF_handler_data import tools

try:
    from _MK_EDF_defaults import default_args
except ImportError:
    default_args = {}


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

# Get screen resolution of primary monitor
screen_width = 1200 #, screen_height = sg.Window.get_screen_size()
window_width = 500
# Calculate centered position
x_left = (screen_width - window_width) // 2
print(screen_width,x_left)

# Main GUI Layout

tools = dict(sorted(tools.items()))
list_main = list(tools.keys())
print(list_main)
layout = [
    [sg.Text("Select a tool:")],
    [sg.Listbox(values=list_main, size=(60, 6), key="TOOL", enable_events=True,expand_x=True),
        sg.Column([
                [sg.Button("Show Help", key="HELP")], 
                [sg.Button("Refresh Arg List", key="REFRESH")],
                [sg.Button("Exit")],
                [sg.Checkbox("Save output with conf.", key="SAVE_OUTPUT_WITH_CONFIG", default=False)]
        ])],
    [],
    [sg.Text("Arguments:"),sg.Multiline("", size=(60, 4), key="ARGS", disabled=True,expand_x=True)],
    [sg.Text("Select files and folders based on required arguments:")],
    *dynamic_inputs,
    [sg.Text("Generated Command:")],
    [sg.Multiline("", size=(60, 3), key="COMMAND_PREVIEW", disabled=True,expand_x=True, font=('Courier New', 8))],
    [sg.Button("Run"), sg.Button("Save Output", key="SAVE_OUTPUT", disabled=True), 
     sg.Button("Save Config", key="SAVE_CONFIG"), sg.Button("Load Config", key="LOAD_CONFIG"), 
     sg.Button("Copy Command", key="COPY_COMMAND")],
    [sg.Multiline(size=(100, 15), key="OUTPUT", autoscroll=True, disabled=True,expand_x=True, font=('Courier New', 8))]
,]

# Create window
window = sg.Window("Generalized Script Launcher", layout, finalize=True,
    resizable=True,
    location=(400,0)
    )

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

        label_text = f"{arg_name}{' (Optional)' if is_optional else ''}"
        window[f"ARG_LABEL_{i}"].update(visible=True, value=label_text)

        default_val = default_args.get(tool_name, {}).get(i, "")
        window[f"ARG_INPUT_{i}"].update(visible=True, value=default_val)

        if "(Folder)" in arg_type:
            window[f"ARG_FOLDER_{i}"].update(visible=True)
        elif is_output:
            window[f"ARG_SAVE_{i}"].update(visible=True)
        else:
            window[f"ARG_BROWSE_{i}"].update(visible=True)

    # Fill initial values into command preview
    arg_values = {}
    for i in range(len(tools[tool_name]["args"])):
        input_val = default_args.get(tool_name, {}).get(i, "")
        arg_values[f"ARG_INPUT_{i}"] = input_val

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
    elif event == "REFRESH":
        tools = dict(sorted(tools.items()))
        list_main = list(tools.keys())
        sg.popup("Updated Tools")
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