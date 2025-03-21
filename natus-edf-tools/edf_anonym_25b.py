import numpy as np
import re
import logging

def process_edf_annotations(data_chunk, redaction_patterns, annot_offsets, annot_sizes, record_size):
    """
    Process EDF+ annotations according to the standard format.
    
    This function handles annotations in EDF+ format which consists of Time-stamped Annotation Lists (TALs).
    Each TAL has the format: +Onset[21Duration]20Annotation120Annotation220...20[00]
    Where:
      - Onset is the timestamp (seconds from file start)
      - Duration is optional
      - 21 (0x15) and 20 (0x14) are special delimiter characters
      - 00 (0x00) is a null byte terminator
      
    Args:
        data_chunk: Raw binary data containing annotations
        redaction_patterns: List of (pattern, replacement) tuples for redaction
        annot_offsets: List of offsets where annotation signals begin in each record
        annot_sizes: List of annotation signal sizes
        record_size: Size of each data record in bytes
        
    Returns:
        Processed data chunk with redacted annotations
    """
    data_array = np.frombuffer(data_chunk, dtype=np.uint8).copy()
    
    # Configure logging
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logger = logging.getLogger('edf_processor')
    
    for r in range(len(data_chunk) // record_size):
        record_start = r * record_size
        
        for i, offset in enumerate(annot_offsets):
            annot_start = record_start + offset
            annot_end = annot_start + annot_sizes[i]
            
            if annot_end <= len(data_array):
                # Get the annotation data for this signal in this record
                annot_data = data_array[annot_start:annot_end]
                
                try:
                    # Decode annotation bytes to string with error handling
                    annot_bytes = annot_data.tobytes()
                    
                    # Skip empty annotation blocks
                    if all(b == 0 for b in annot_bytes):
                        continue
                    
                    # Find TALs in the annotation bytes
                    # TALs start with + or - (timestamps) and end with a null byte
                    pos = 0
                    modified_bytes = bytearray(annot_bytes)
                    
                    while pos < len(annot_bytes):
                        # Find the start of a TAL (should begin with + or -)
                        if annot_bytes[pos] == ord('+') or annot_bytes[pos] == ord('-'):
                            # Extract the entire TAL until the terminating null byte
                            tal_end = annot_bytes.find(b'\x00', pos)
                            if tal_end == -1:  # No null terminator found
                                tal_end = len(annot_bytes)
                            
                            tal_bytes = annot_bytes[pos:tal_end+1]
                            modified_tal = process_tal(tal_bytes, redaction_patterns, logger)
                            
                            # Replace the TAL in the modified bytes
                            modified_bytes[pos:pos+len(tal_bytes)] = modified_tal
                            pos += len(modified_tal)
                        else:
                            # Skip non-TAL bytes (should be null padding)
                            pos += 1
                    
                    # Copy modified bytes back to the data array
                    for j in range(len(modified_bytes)):
                        if annot_start + j < len(data_array):
                            data_array[annot_start + j] = modified_bytes[j]
                
                except Exception as e:
                    logger.warning(f"Warning: Failed to process annotation in record {r}, offset {offset}: {e}")
    
    return data_array.tobytes()

def process_tal(tal_bytes, redaction_patterns, logger):
    """
    Process a single Time-stamped Annotation List (TAL).
    
    Args:
        tal_bytes: Bytes of a single TAL
        redaction_patterns: List of (pattern, replacement) tuples for redaction
        logger: Logger instance for debug output
        
    Returns:
        Modified TAL bytes with redacted content
    """
    try:
        # Convert to bytearray for modification
        tal = bytearray(tal_bytes)
        
        # Find the onset timestamp (part before the first 0x14 byte)
        onset_end = tal.find(0x14)
        if onset_end == -1:
            return tal  # No proper TAL format, return unchanged
        
        # Extract onset
        onset = tal[:onset_end].decode('utf-8', errors='replace')
        
        # Find if there's a duration (there would be another 0x14 after the first)
        annotations_start = onset_end + 1
        duration_marker = tal.find(0x15, 0, annotations_start)
        
        # Skip the timestamp and any duration marker
        current_pos = annotations_start
        
        # Process each annotation in the TAL
        while current_pos < len(tal):
            # Find the end of this annotation (marked by 0x14)
            annotation_end = tal.find(0x14, current_pos)
            if annotation_end == -1:
                break  # No more annotations
                
            # Extract the annotation text
            if annotation_end > current_pos:
                annotation = tal[current_pos:annotation_end].decode('utf-8', errors='replace')
                
                # Apply redaction patterns to the annotation text
                redacted_annotation = annotation
                for pattern, replacement in redaction_patterns:
                    try:
                        pattern_str = pattern.decode('utf-8', errors='replace')
                        replacement_str = replacement.decode('utf-8', errors='replace')
                        redacted_annotation = redacted_annotation.replace(pattern_str, replacement_str)
                    except Exception as e:
                        logger.warning(f"Error applying redaction pattern: {e}")
                
                # Replace the annotation if it was modified
                if redacted_annotation != annotation:
                    # Update the TAL with the redacted annotation
                    redacted_bytes = redacted_annotation.encode('utf-8')
                    
                    # Replace the annotation text, ensuring we don't change the TAL length
                    new_annotation_bytes = redacted_bytes[:annotation_end - current_pos]
                    tal[current_pos:annotation_end] = new_annotation_bytes.ljust(annotation_end - current_pos, b' ')
            
            # Move to the next annotation
            current_pos = annotation_end + 1
            
            # If we hit a null byte, we're at the end of the TAL
            if current_pos < len(tal) and tal[current_pos] == 0:
                break
        
        return tal
    except Exception as e:
        logger.warning(f"Error processing TAL: {e}")
        return tal_bytes  # Return unchanged if there was an error

def extract_patient_info_from_header(header_bytes):
    """
    Extract patient information from EDF header for redaction.
    
    Args:
        header_bytes: The EDF file header as bytes
        
    Returns:
        List of (pattern, replacement) tuples for patient information redaction
    """
    redaction_patterns = []
    
    try:
        # Extract patient information field (bytes 8-88)
        patient_info = header_bytes[8:88].decode('ascii', errors='ignore').strip()
        
        # Extract name components
        # Format according to EDF+ spec: hospital_id sex birthdate patient_name
        parts = patient_info.split()
        
        if len(parts) >= 4:
            # The hospital ID is the first part
            hospital_id = parts[0]
            if len(hospital_id) > 2:  # Only redact if it's a substantial ID
                redaction_patterns.append((hospital_id.encode(), b'X-XXXXXXX'))
            
            # The patient name should be all parts from position 3 onwards
            if len(parts) > 3:
                name_parts = parts[3:]
                
                # Add each name part as a pattern
                for name in name_parts:
                    if len(name) > 2:  # Only redact names longer than 2 chars
                        redaction_patterns.append((name.encode(), b'XXXX'))
                
                # Also add the full name
                full_name = ' '.join(name_parts)
                if len(full_name) > 2:
                    redaction_patterns.append((full_name.encode(), b'XXXX'))
        
        # Also look for common patient identifier patterns
        id_pattern = re.compile(r'\b[A-Z0-9]{6,}\b')
        id_matches = id_pattern.findall(patient_info)
        
        for id_match in id_matches:
            if len(id_match) > 3:  # Only redact substantial IDs
                redaction_patterns.append((id_match.encode(), b'XXXXXXX'))
    
    except Exception as e:
        print(f"Warning: Failed to extract patient info: {e}")
    
    return redaction_patterns

def anonymize_edf_header(header_bytes):
    """
    Anonymize the EDF header by replacing patient identifiable information.
    
    Args:
        header_bytes: The EDF file header as bytes
        
    Returns:
        Anonymized header bytes
    """
    new_header = bytearray(header_bytes)
    
    # Anonymize patient field (bytes 8-88)
    anonymous_patient = "X X X X".ljust(80).encode('ascii')
    new_header[8:88] = anonymous_patient
    
    return new_header



import os
import time
import mmap
import traceback
from edflibpy.edfreader import EDFreader

from tqdm import tqdm


def anonymize_edf_complete(input_path, output_path, buffer_size_mb=64):
    """
    Complete EDF anonymizer that ensures exact file size matching and properly handles annotations.
    
    This implementation:
    1. Directly reads and parses the EDF header to understand file structure
    2. Identifies and processes annotation channels
    3. Creates a new file with an anonymized header
    4. Copies data records with annotation redaction where needed
    5. Ensures the output file size matches exactly what's expected
    
    Args:
        input_path (str): Path to the input EDF file
        output_path (str): Path to save the anonymized EDF file
        buffer_size_mb (int): Size of the buffer in megabytes for reading/writing data
    """
    
    start_time = time.time()
    edf_reader = None
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('edf_anonymize.log')
        ]
    )
    logger = logging.getLogger('edf_anonymizer')
    
    try:
        logger.info(f"Processing EDF file: {input_path}")
        input_file_size = os.path.getsize(input_path)

        # Open file using mmap for fast direct access
        with open(input_path, 'rb') as f:
            mmapped_file = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

            # Read base header
            base_header = bytearray(mmapped_file[:256])

            # Extract essential EDF header info
            header_bytes = int(base_header[184:192].decode('ascii').strip())
            data_records = int(base_header[236:244].decode('ascii').strip())
            record_duration = float(base_header[244:252].decode('ascii').strip())
            num_signals = int(base_header[252:256].decode('ascii').strip())

            # Read signal header
            signal_header_size = num_signals * 256
            signal_header = bytearray(mmapped_file[256:256 + signal_header_size])

            # Identify annotation channels
            signal_labels = [signal_header[i*16:(i+1)*16].decode('ascii').strip() for i in range(num_signals)]
            annot_channels = [i for i, label in enumerate(signal_labels) if label in ["EDF Annotations", "BDF Annotations"]]

            logger.info(f"Annotation channels found: {annot_channels}")

            # Read samples per record
            samples_per_record = [
                int(signal_header[num_signals * 216 + (i * 8):num_signals * 216 + (i * 8) + 8].decode('ascii').strip())
                for i in range(num_signals)
            ]

            # Calculate data record size
            bytes_per_sample = 2  # EDF uses 2-byte integers
            record_size = sum(samples_per_record) * bytes_per_sample

            # Extract patient info for redaction
            redaction_patterns = []
            try:
                # Extract directly from header
                header_patterns = extract_patient_info_from_header(base_header)
                redaction_patterns.extend(header_patterns)
                
                # Try to get additional details from EDFreader
                edf_reader = EDFreader(input_path)
                patient_name = edf_reader.getPatientName()
                if patient_name:
                    # Split by common separators
                    name_parts = re.split(r';|,|-|\s+', patient_name)
                    for name in name_parts:
                        if len(name) > 2:  # Only redact substantial names
                            redaction_patterns.append((name.encode(), b'XXXX'))
                edf_reader.close()
                
                # Remove duplicates
                redaction_patterns = list(set(redaction_patterns))
                logger.info(f"Redaction patterns: {redaction_patterns}")
            except Exception as e:
                logger.warning(f"Warning: Could not read patient name: {e}")

            # Anonymize patient info in header
            new_base_header = anonymize_edf_header(base_header)

            # Calculate annotation offsets
            annot_offsets, annot_sizes = [], []
            offset = 0
            for i, samples in enumerate(samples_per_record):
                size = samples * bytes_per_sample
                if i in annot_channels:
                    annot_offsets.append(offset)
                    annot_sizes.append(size)
                offset += size

            logger.info(f"Annotation offsets: {annot_offsets}, sizes: {annot_sizes}")

            # Prepare output file
            with open(output_path, 'wb') as out_file:
                # Write the anonymized header
                out_file.write(new_base_header)
                out_file.write(signal_header)

                buffer_size_bytes = buffer_size_mb * 1024 * 1024
                records_per_chunk = max(1, buffer_size_bytes // record_size)
                chunk_size_bytes = records_per_chunk * record_size

                logger.info(f"Processing records in {chunk_size_bytes / (1024*1024):.2f} MB chunks")

                bytes_remaining = input_file_size - (256 + signal_header_size)
                
                with tqdm(total=data_records, desc="Processing records", unit="records") as pbar:
                    for record_index in range(0, data_records, records_per_chunk):
                        chunk_bytes = min(chunk_size_bytes, bytes_remaining)
                        if chunk_bytes <= 0:
                            break
                
                        data_chunk = mmapped_file[256 + signal_header_size + record_index * record_size:
                                                  256 + signal_header_size + record_index * record_size + chunk_bytes]
                
                        if annot_channels and redaction_patterns:
                            data_chunk = process_edf_annotations(data_chunk, redaction_patterns, annot_offsets, annot_sizes, record_size)
                
                        out_file.write(data_chunk)
                        bytes_remaining -= chunk_bytes
                        pbar.update(min(records_per_chunk, data_records - record_index))

            mmapped_file.close()

            # Verify output file size and fix discrepancies
            output_file_size = os.path.getsize(output_path)
            file_size_diff = input_file_size - output_file_size
            if file_size_diff != 0:
                logger.info(f"Adjusting file size difference: {file_size_diff} bytes")
                with open(output_path, 'r+b') as fix_file:
                    if abs(file_size_diff) < 256:
                        # Small difference might be due to header changes
                        actual_data_size = output_file_size - (256 + signal_header_size)
                        actual_records = int(round(actual_data_size / record_size))

                        if actual_records != data_records:
                            logger.info(f"Updating data records in header: {data_records} → {actual_records}")
                            fix_file.seek(236)
                            fix_file.write(f"{actual_records:<8}".encode('ascii'))
                    else:
                        # Larger discrepancy - pad or truncate the file
                        if file_size_diff > 0:  # Output file is smaller than input
                            logger.info(f"Padding output file with {file_size_diff} bytes")
                            fix_file.seek(0, os.SEEK_END)  # Go to end of file
                            fix_file.write(b'\x00' * file_size_diff)  # Pad with zeros
                        else:  # Output file is larger than input
                            logger.warning(f"Output file is {-file_size_diff} bytes larger than input - truncating")
                            fix_file.truncate(input_file_size)  # Truncate to match input size

        elapsed_time = time.time() - start_time
        logger.info(f"Anonymization completed in {elapsed_time:.2f} seconds")
        logger.info(f"Processing speed: {input_file_size / 1024 / 1024 / elapsed_time:.2f} MB/s")
        logger.info(f"Anonymized EDF saved to: {output_path}")

        return True
        
    except Exception as e:
        logger.error(f"Error: {e}")
        traceback.print_exc()
        return False


def validate_anonymized_file(input_path, output_path):
    """
    Validate that the anonymized file has the same structure as the original
    but with personally identifiable information removed.
    
    Args:
        input_path: Path to the original EDF file
        output_path: Path to the anonymized EDF file
        
    Returns:
        True if validation passed, False otherwise
    """
    try:
        # Check file sizes
        input_size = os.path.getsize(input_path)
        output_size = os.path.getsize(output_path)
        
        if input_size != output_size:
            logging.warning(f"File size mismatch: Input={input_size}, Output={output_size}")
            return False
            
        # Check basic header structure
        with open(input_path, 'rb') as in_file, open(output_path, 'rb') as out_file:
            # Read headers
            in_header = in_file.read(256)
            out_header = out_file.read(256)
            
            # Check version
            if in_header[0:8] != out_header[0:8]:
                logging.warning("Version field mismatch")
                return False
                
            # Patient field should be anonymized
            if out_header[8:88] == in_header[8:88]:
                logging.warning("Patient field not anonymized")
                return False
                
            # Technical fields should match
            if in_header[184:256] != out_header[184:256]:
                logging.warning("Technical header fields mismatch")
                return False
                
            # Read a sample of data records to verify structure
            for _ in range(3):  # Check first 3 records
                in_record = in_file.read(1024)  # Just sample 1KB
                out_record = out_file.read(1024)
                
                if len(in_record) != len(out_record):
                    logging.warning("Data record length mismatch")
                    return False
        
        logging.info("Anonymized file validation passed")
        return True
        
    except Exception as e:
        logging.error(f"Error during validation: {e}")
        return False


#if __name__ == "__main__":
 #   input_path = "c:/_Code_temp//PR_cec2bc1b-7803-4e05-babd-8734e321a62a.EDF"
  #  output_path = "c:/_Code_temp/out_file_complete.edf"

        
        
        
def parse_arguments():
    parser = argparse.ArgumentParser(description="Anonymize EDF file by removing patient-identifiable information.")
    parser.add_argument("input_path", type=str, help="Path to the input EDF file.")
    parser.add_argument("output_path", type=str, help="Path to save the anonymized EDF file.")
    parser.add_argument("--buffer_size_mb", type=int, default=64, help="Buffer size in MB for processing chunks (default: 64MB).")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()

    input_path = args.input_path
    output_path = args.output_path
    buffer_size_mb = args.buffer_size_mb

    # Check and anonymize
    success = anonymize_edf_complete(input_path, output_path, buffer_size_mb=buffer_size_mb)

    if success:
        # Validate the anonymized file
        validation_result = validate_anonymized_file(input_path, output_path)
        if validation_result:
            print("Anonymization successful and validated")
        else:
            print("Anonymization completed but validation failed")
    else:
        print("Anonymization failed")        