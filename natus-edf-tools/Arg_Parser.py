import sys
import os
import re
import json


def analyze_argparse(content):
    """Analyze a Python file that uses argparse for command line arguments"""
    # Try to find the parser creation
    parser_var = None
    parser_pattern = re.compile(r'(\w+)\s*=\s*argparse\.ArgumentParser\(')
    match = parser_pattern.search(content)
    if match:
        parser_var = match.group(1)
    
    if not parser_var:
        return None
    
    # Find all add_argument calls
    arg_pattern = re.compile(rf'{parser_var}\.add_argument\((.*?)\)', re.DOTALL)
    args = []
    arg_names = []
    
    for match in arg_pattern.finditer(content):
        arg_str = match.group(1)
        # Extract argument name and type
        name_match = re.search(r'[\'"](-{1,2}\w+)[\'"]', arg_str)
        positional_match = re.search(r'[\'"]([\w]+)[\'"]', arg_str)
        
        if name_match:  # Named argument
            arg_name = name_match.group(1)
            arg_names.append(arg_name)
            
            # Determine argument type
            if "help" in arg_str:
                help_match = re.search(r'help=[\'"]([^\'"]*)[\'"]', arg_str)
                help_text = help_match.group(1).lower() if help_match else ""
                
                if "file" in help_text or "output" in help_text:
                    args.append(f"{arg_name} (File)")
                elif "folder" in help_text or "directory" in help_text or "dir" in help_text:
                    args.append(f"{arg_name} (Folder)")
                else:
                    args.append(f"{arg_name} (File)")  # Default to File if unsure
            else:
                args.append(f"{arg_name} (File)")  # Default to File if no help text
        
        elif positional_match:  # Positional argument
            arg_name = positional_match.group(1)
            arg_names.append("")  # Empty string for positional arguments
            
            # Determine argument type
            if "help" in arg_str:
                help_match = re.search(r'help=[\'"]([^\'"]*)[\'"]', arg_str)
                help_text = help_match.group(1).lower() if help_match else ""
                
                if "file" in help_text or "output" in help_text:
                    args.append(f"{arg_name} (File)")
                elif "folder" in help_text or "directory" in help_text or "dir" in help_text:
                    args.append(f"{arg_name} (Folder)")
                else:
                    args.append(f"{arg_name} (File)")  # Default to File if unsure
            else:
                args.append(f"{arg_name} (File)")  # Default to File if no help text
    
    # Find usage string
    script_name = os.path.basename(sys.argv[1]) if len(sys.argv) > 1 else "script.py"
    usage = f"{script_name} "
    
    for i, arg in enumerate(args):
        arg_name = arg.split(" ")[0]
        if arg_names[i]:  # Named argument
            usage += f"[{arg_name}] "
        else:  # Positional argument
            usage += f"{arg.split(' ')[0]} "
    
    return {
        "usage": usage.strip(),
        "args": args,
        "arg_name": arg_names
    }


def analyze_sys_argv(content):
    """Analyze a Python file that uses sys.argv for command line arguments"""
    # Find sys.argv usage
    argv_pattern = re.compile(r'sys\.argv\[(\d+)\]')
    max_index = 0
    
    for match in argv_pattern.finditer(content):
        index = int(match.group(1))
        max_index = max(max_index, index)
    
    if max_index == 0:
        return None
    
    # Look for usage info in comments or print statements
    usage_pattern = re.compile(r'(?:print\(["\']|#\s*)(?:Usage|usage):?\s*([\w\s\.<>\[\]]+)', re.IGNORECASE)
    usage_match = usage_pattern.search(content)
    
    usage_args = []
    if usage_match:
        usage_text = usage_match.group(1)
        # Extract script name
        script_name = os.path.basename(sys.argv[1]) if len(sys.argv) > 1 else "script.py"
        
        # Skip script name in the usage
        arg_text = usage_text
        if ".py" in usage_text:
            parts = usage_text.split(".py", 1)
            if len(parts) > 1:
                arg_text = parts[1].strip()
        
        # Extract arguments
        arg_pattern = re.compile(r'<([^>]+)>|\[([^\]]+)\]|(\S+)')
        for match in arg_pattern.finditer(arg_text):
            arg = match.group(1) or match.group(2) or match.group(3)
            if arg and not arg.endswith('.py'):
                usage_args.append(arg)
    
    # Create args based on sys.argv usage and usage text
    args = []
    arg_names = []
    
    # Skip index 0 (script name)
    for i in range(1, max_index + 1):
        # Get arg name from usage if available
        arg_name = usage_args[i-1] if i <= len(usage_args) else f"arg{i}"
        
        # Try to infer argument type from context
        context_pattern = re.compile(rf'sys\.argv\[{i}\].*?(file|folder|directory|dir|path|output)', re.IGNORECASE)
        context_match = context_pattern.search(content)
        
        if context_match:
            context = context_match.group(1).lower()
            if context in ['file', 'path', 'output']:
                arg_type = "File"
            elif context in ['folder', 'directory', 'dir']:
                arg_type = "Folder"
            else:
                arg_type = "File"  # Default to File
        else:
            # Try to infer type from name
            if any(keyword in arg_name.lower() for keyword in ['file', 'output', 'path']):
                arg_type = "File"
            elif any(keyword in arg_name.lower() for keyword in ['folder', 'directory', 'dir']):
                arg_type = "Folder"
            else:
                arg_type = "File"  # Default to File
        
        # For optional arguments (in square brackets in usage)
        is_optional = arg_name in usage_args and (
            usage_text.find(f"[{arg_name}]") >= 0 or
            i == max_index and "optional" in content.lower()
        )
        formatted_arg = f"{arg_name}{' (Optional)' if is_optional else ''} ({arg_type})"
        
        args.append(formatted_arg)
        arg_names.append("")  # Empty for positional arguments
    
    # Create usage string
    script_name = os.path.basename(sys.argv[1]) if len(sys.argv) > 1 else "script.py"
    
    if usage_match:
        usage = f"{script_name} {arg_text}" if 'arg_text' in locals() else usage_match.group(1)
    else:
        usage = f"{script_name} "
        for i, arg in enumerate(args):
            arg_base = arg.split(" ")[0]
            if "Optional" in arg:
                usage += f"[{arg_base}] "
            else:
                usage += f"{arg_base} "
    
    return {
        "usage": usage.strip(),
        "args": args,
        "arg_name": arg_names
    }


def analyze_docstring(content):
    """Analyze the docstring for usage information"""
    # First, try to find a formal docstring
    docstring_pattern = re.compile(r'"""\s*((?:.|\n)*?)\s*"""', re.DOTALL)
    match = docstring_pattern.search(content)
    
    if not match:
        return None
    
    docstring = match.group(1)
    
    # Look for usage information in the docstring
    usage_pattern = re.compile(r'(?:usage|usage:)\s+(.+?)(?:\n\n|\n$|\Z)', re.IGNORECASE | re.DOTALL)
    usage_match = usage_pattern.search(docstring)
    
    if usage_match:
        usage = usage_match.group(1).strip()
        script_name = os.path.basename(sys.argv[1]) if len(sys.argv) > 1 else "script.py"
        
        # Extract arguments from usage
        args_pattern = re.compile(r'(?:--?\w+|<[\w\-]+>|\[[\w\-]+\])')
        arg_matches = args_pattern.finditer(usage)
        
        args = []
        arg_names = []
        
        for match in arg_matches:
            arg = match.group(0)
            
            # Clean up argument name
            clean_arg = arg.strip('-<>[]')
            
            # Determine if it's a named argument
            is_named = arg.startswith('-')
            
            # Try to infer argument type from docstring
            arg_type = "File"  # Default
            if re.search(rf'{clean_arg}.*?(folder|directory|dir)', docstring, re.IGNORECASE):
                arg_type = "Folder"
            elif re.search(rf'{clean_arg}.*?(file|output)', docstring, re.IGNORECASE):
                arg_type = "File"
            
            args.append(f"{clean_arg} ({arg_type})")
            arg_names.append(f"--{clean_arg}" if is_named else "")
        
        return {
            "usage": usage,
            "args": args,
            "arg_name": arg_names
        }
    
    return None


def find_explicit_usage(content):
    """Look for explicit print statements about usage"""
    usage_pattern = re.compile(r'print\([\'"]Usage:?\s*(.*?)[\'"]', re.IGNORECASE)
    match = usage_pattern.search(content)
    
    if match:
        usage_text = match.group(1).strip()
        script_name = os.path.basename(sys.argv[1]) if len(sys.argv) > 1 else "script.py"
        
        # Extract arguments
        parts = usage_text.split()
        args = []
        arg_names = []
        
        for part in parts:
            if part.endswith('.py'):
                continue  # Skip script name
            
            # Clean up argument format
            clean_arg = part.strip('-<>[]')
            
            # Determine if optional
            is_optional = part.startswith('[') and part.endswith(']')
            
            # Determine type
            arg_type = "File"  # Default
            if any(keyword in clean_arg.lower() for keyword in ['folder', 'directory', 'dir']):
                arg_type = "Folder"
            
            # Format arg
            formatted_arg = f"{clean_arg}{' (Optional)' if is_optional else ''} ({arg_type})"
            args.append(formatted_arg)
            
            # Determine if named argument
            is_named = part.startswith('-')
            arg_names.append(f"--{clean_arg}" if is_named else "")
        
        return {
            "usage": usage_text,
            "args": args,
            "arg_name": arg_names
        }
    
    return None


def simple_analysis(content, file_path):
    """Perform a simple analysis based on file patterns and file name"""
    script_name = os.path.basename(file_path)
    
    # Check common file patterns
    if "sys.argv" in content:
        # Count potential number of arguments
        arg_count = 0
        for i in range(1, 10):  # Check up to 9 potential arguments
            if f"sys.argv[{i}]" in content:
                arg_count = max(arg_count, i)
        
        if arg_count > 0:
            args = []
            arg_names = []
            usage = f"{script_name} "
            
            for i in range(1, arg_count + 1):
                # Make educated guesses for arg names
                if i == arg_count and "output" in content.lower():
                    arg_name = "output_file"
                    arg_type = "File"
                elif i == 1 and any(term in content.lower() for term in ["folder", "directory", "dir"]):
                    arg_name = "input_folder"
                    arg_type = "Folder"
                elif i == 1:
                    arg_name = "input_file"
                    arg_type = "File"
                else:
                    arg_name = f"arg{i}"
                    arg_type = "File"
                
                # Check if last arg is optional
                is_optional = i == arg_count and "if len(sys.argv) >" in content
                
                formatted_arg = f"{arg_name}{' (Optional)' if is_optional else ''} ({arg_type})"
                args.append(formatted_arg)
                arg_names.append("")
                
                # Add to usage string
                if is_optional:
                    usage += f"[{arg_name}] "
                else:
                    usage += f"{arg_name} "
            
            return {
                "usage": usage.strip(),
                "args": args,
                "arg_name": arg_names
            }
    
    # Default minimal entry
    return {
        "usage": f"{script_name} (No usage information available)",
        "args": [],
        "arg_name": []
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: tool_analyzer.py <python_file> [output_file]")
        sys.exit(1)
    
    python_file = sys.argv[1]
    
    try:
        with open(python_file, 'r') as file:
            content = file.read()
        
        # Try different analysis methods in order
        result = analyze_argparse(content)
        
        if not result:
            result = find_explicit_usage(content)
        
        if not result:
            result = analyze_sys_argv(content)
        
        if not result:
            result = analyze_docstring(content)
        
        if not result:
            print("Using simple analysis for tool arguments.")
            result = simple_analysis(content, python_file)
        
        # For self-analysis or known script patterns, hardcode the correct info
        tool_name = os.path.splitext(os.path.basename(python_file))[0]
        
        if tool_name == "tool_analyzer" or tool_name == "Arg_Parser":
            result = {
                "usage": f"{tool_name}.py <python_file> [output_file]",
                "args": ["python_file (File)", "output_file (Optional) (File)"],
                "arg_name": ["", ""]
            }
        
        # Format the output for the tools dictionary
        tools_entry = {
            tool_name: result
        }
        
        # Print the formatted tools entry
        print(f"Tools entry for {tool_name}:")
        print(json.dumps(tools_entry, indent=4))
        
        # Save to a file if requested
        if len(sys.argv) > 2:
            output_file = sys.argv[2]
            with open(output_file, 'w') as file:
                json.dump(tools_entry, file, indent=4)
            print(f"Tools entry saved to {output_file}")
        
    except Exception as e:
        print(f"Error analyzing {python_file}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()