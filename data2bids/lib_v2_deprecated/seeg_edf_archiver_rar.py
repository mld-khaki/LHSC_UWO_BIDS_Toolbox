import os
import rarfile
import logging
from datetime import datetime

# Configure logging to write messages to a file with timestamps and levels
log_file = 'archive_log.txt'
logging.basicConfig(
    filename=log_file, 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Define the directories to search for files and store temporary data
search_dir = '/volume1/seeg_data/ieeg_dataset_a/bids/sub-137/'  # Directory containing EDF files
temp_dir = '/volume1/seeg_data/temp_rar/'  # Temporary directory (currently unused)

def archive_edf(edf_path, archive_path):
    """
    Archives a single EDF file into a RAR file.
    
    Args:
        edf_path (str): The full path of the EDF file to be archived.
        archive_path (str): The full path where the RAR archive will be saved.
    
    Raises:
        Exception: If any error occurs during the archiving process, it will be logged and raised.
    """
    try:
        logging.info(f"Starting to archive: {edf_path}")
        
        # Create a new RAR file and set the compression method to RAR_M3 (fast compression)
        with rarfile.RarFile(archive_path, 'w') as rar:
            rar.set_compression(rarfile.RAR_M3)  # Fast compression
            rar.write(edf_path, arcname=os.path.basename(edf_path))

        logging.info(f"Successfully archived: {edf_path}")
    except Exception as e:
        # Log and re-raise any exceptions that occur during the archiving process
        logging.error(f"Exception occurred while archiving {edf_path}: {str(e)}")
        raise

def search_and_archive(directory):
    """
    Searches a directory for EDF files and creates a RAR archive for each.
    
    Args:
        directory (str): The root directory to search for EDF files.
    
    Notes:
        - Archives are created in the same location as the original EDF files with '.rar' extension.
        - Skips files if an archive with the same name already exists.
    """
    for root, dirs, files in os.walk(directory):
        for file in files:
            # Process files with '.edf' extension (case-insensitive)
            if file.lower().endswith('.edf'):
                print(f"Working on file: {file}")
                edf_path = os.path.join(root, file)  # Full path to the EDF file
                archive_path = f"{edf_path}.rar"  # Archive path
                
                # Check if the archive already exists
                if not os.path.exists(archive_path):
                    archive_edf(edf_path, archive_path)
                else:
                    logging.info(f"Archive already exists, skipping: {archive_path}")

def main():
    """
    Main function to execute the archiving process.
    
    - Logs the start and end times of the script.
    - Calculates and logs the total execution time.
    """
    start_time = datetime.now()
    logging.info(f"Script started at {start_time}")

    # Start the search and archive process
    search_and_archive(search_dir)

    end_time = datetime.now()
    logging.info(f"Script ended at {end_time}")
    logging.info(f"Total execution time: {end_time - start_time}")

if __name__ == "__main__":
    main()
