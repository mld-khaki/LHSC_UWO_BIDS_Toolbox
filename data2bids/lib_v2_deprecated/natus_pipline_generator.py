        # Step 5: Generate pipeline
        output_lines = []  # List to store pipeline output lines
        for folder_name in contents:
            folder_path = os.path.join(input_folder, folder_name)
            # Check if the item is a directory and matches the naming pattern
            if os.path.isdir(folder_path) and folder_pattern.match(folder_name):
                eeg_file = os.path.join(folder_path, f"{folder_name}.eeg")  # Expected EEG file
                if not os.path.exists(eeg_file):  # Ensure the .eeg file exists
                    raise FileNotFoundError(f"The expected EEG file '{eeg_file}' does not exist.")
                # Format the output line
                output_line = f"{folder_path}\\{folder_name}.eeg, D:\\Neuroworks\\Settings\\quantum_new.exp"
                output_lines.append(output_line)

        # Raise an error if no valid folders are found
        if not output_lines:
            raise ValueError(f"No valid folders matching the naming pattern were found in '{input_folder}'.")

        # Step 6: Write the output to a file
        output_file = os.path.join(input_folder, "pipeline_output.txt")
        with open(output_file, "w") as f:
            f.write("\n".join(output_lines))  # Write all output lines to the file
        
        print(f"Pipeline file successfully created: {output_file}")

    except Exception as e:
        # Handle any exceptions and provide detailed error messages
        print(f"Error: {e}")

# Entry point for the script
if __name__ == "__main__":
    generate_pipeline()