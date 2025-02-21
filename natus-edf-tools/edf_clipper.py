import numpy as np
from tqdm import tqdm
import time
import argparse
import json
from datetime import datetime, timedelta
import sys
from pathlib import Path
import os

# External dependencies
from ext_lib.edflibpy import EDFwriter, EDFreader
from _lhsc_lib.EDF_reader_mld import EDFreader as FastEDFReader

debug = True

class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def format_timestamp(seconds):
    """
    Formats a timestamp like the C++ version: "1d 02:34:56.789".
    """
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    sec = seconds % 60
    millisec = int((seconds % 1) * 1000)
    if days > 0:
        return f"{days}d {hours:02}:{minutes:02}:{sec:02}.{millisec:03}"
    else:
        return f"{hours:02}:{minutes:02}:{sec:02}.{millisec:03}"

def adjust_annotation_onset(annot, time_diff, scaling_factor):
    """
    Adjusts the onset timestamp of annotations, based on time shift.
    """
    new_onset = annot.onset - time_diff
    if new_onset < 0:
        return None  # Ignore annotations that would be negative
    annot.onset = new_onset
    return annot

def clip_edf(input_edf_path: str, output_edf_path: str, clip_metadata: dict):
    try:
        print(f"Opening EDF file: {input_edf_path}")
        reader = EDFreader(input_edf_path)  # EDFreader automatically reads annotations
        file_info = clip_metadata['file_info']

        # Validate time parameters
        total_duration = reader.getFileDuration() / EDFreader.EDFLIB_TIME_DIMENSION
        print(f"Total Duration: {total_duration} seconds")

        file_info = field_check_update('clip_begin_sec', file_info, -1, 0)
        file_info = field_check_update('clip_end_sec', file_info, -1, total_duration)

        # Ensure valid clipping boundaries
        clip_begin_sec = max(file_info.get('clip_begin_sec', 0), 0)
        clip_end_sec = min(file_info.get('clip_end_sec', total_duration), total_duration)

        if clip_end_sec <= clip_begin_sec:
            raise ValueError(f"Invalid clipping range: {clip_begin_sec} to {clip_end_sec} seconds")

        print(f"Clipping from {format_timestamp(clip_begin_sec)} to {format_timestamp(clip_end_sec)}")

        # Select signals
        selected_signals = set(s.strip() for s in file_info['selected_signals'])
        original_signals = [reader.getSignalLabel(i).strip() for i in range(reader.getNumSignals())]
        signal_indices = [i for i, label in enumerate(original_signals) if label in selected_signals]

        if not signal_indices:
            raise ValueError("No valid signals selected for clipping")

        # Initialize EDF writer
        file_type = reader.getFileType()
        writer = EDFwriter(output_edf_path, file_type, len(signal_indices))

        # Copy signal parameters for selected signals
        signal_sample_rates = []
        for new_idx, orig_idx in enumerate(signal_indices):
            writer.setSignalLabel(new_idx, reader.getSignalLabel(orig_idx))
            writer.setPhysicalDimension(new_idx, reader.getPhysicalDimension(orig_idx))
            writer.setSampleFrequency(new_idx, int(reader.getSampleFrequency(orig_idx)))
            signal_sample_rates.append(int(reader.getSampleFrequency(orig_idx)))

        # Adjust annotations
        if reader.getFileType() in [EDFreader.EDFLIB_FILETYPE_EDFPLUS, EDFreader.EDFLIB_FILETYPE_BDFPLUS]:
            print("Processing annotations...")
            time_diff = clip_begin_sec * EDFreader.EDFLIB_TIME_DIMENSION
            for annot in reader.annotationslist:
                adjusted_annot = adjust_annotation_onset(annot, time_diff, EDFreader.EDFLIB_TIME_DIMENSION)
                if adjusted_annot:
                    writer.writeAnnotation(adjusted_annot.onset, adjusted_annot.duration, adjusted_annot.description)

        # Process signals
        buffer = np.zeros(1000, dtype=np.int16)
        with tqdm(total=sum(signal_sample_rates), desc="Processing EDF", unit="samples") as pbar:
            for new_idx, orig_idx in enumerate(signal_indices):
                total_samples = int((clip_end_sec - clip_begin_sec) * signal_sample_rates[new_idx])
                start_sample = int(clip_begin_sec * signal_sample_rates[new_idx])

                current_sample = 0
                while current_sample < total_samples:
                    chunk_size = min(buffer_size, total_samples - current_sample)

                    reader.fseek(orig_idx, start_sample + current_sample, EDFreader.EDFSEEK_SET)
                    samples_read = reader.readSamples(orig_idx, buffer, chunk_size)
                    if samples_read > 0:
                        writer.writeSamples(buffer[:samples_read])
                        current_sample += samples_read
                    else:
                        print(f"Warning: No samples read for signal {original_signals[orig_idx]} at position {start_sample + current_sample}")

                    elapsed = time.time() - start_time
                    rate = current_sample / elapsed if elapsed > 0 else 0
                    eta = (total_samples_to_extract - pbar.n) / rate if rate > 0 else 0
                    pbar.set_postfix({"Rate": f"{rate:.0f}", "ETA": f"{eta:.1f}s"})
                    pbar.update(samples_read)

        reader.close()
        writer.close()
        elapsed = time.time() - start_time
        print(f"Clipping completed in {elapsed:.1f}s")

    except Exception as e:
        if debug:
            raise e
        print(f"Error during EDF clipping: {e}")
        raise e



def main():
    """
    Command-line utility for processing EDF files.

    Usage:
        Generate metadata:
            python script.py --input input.edf --metadata --output metadata.json

        Clip EDF file:
            python script.py --input input.edf --clip clip_params.json --output clipped.edf

    Arguments:
        --input, -i   (str)  : Input EDF file path (Required).
        --metadata, -m       : Generate metadata JSON.
        --clip, -c    (str)  : JSON file with clipping parameters.
        --output, -o  (str)  : Output file path.

    Example:
        python script.py -i input.edf -m -o metadata.json
        python script.py -i input.edf -c clip_params.json -o clipped.edf
    """
    # clear_screen()
    
    parser = argparse.ArgumentParser(description='EDF File Processor')
    parser.add_argument('--input', '-i', type=str, required=True, help='Input EDF file path')
    parser.add_argument('--metadata', '-m', action='store_true', help='Generate metadata JSON')
    parser.add_argument('--clip', '-c', type=str, help='JSON file with clipping parameters')
    parser.add_argument('--output', '-o', type=str, help='Output file path')
    args = parser.parse_args()
    
    if not Path(args.input).exists():
        print(f"Input file not found: {args.input}")
        return 1
    
    if args.metadata:
        output = args.output or str(Path(args.input).with_suffix('.json'))
        generate_edf_metadata(args.input, output)
        print(f"Metadata saved to: {output}")
    
    if args.clip:
        try:
            with open(args.clip) as f:
                clip_metadata = json.load(f)

            output = args.output or str(Path(args.input).with_stem(f"{Path(args.input).stem}_clipped"))
            clip_edf(args.input, output, clip_metadata)
            print(f"Clipped EDF saved to: {output}")
        except Exception as e:
            if debug:
                raise e
            print(f"Error processing clip request: {e}")
            return 1
    
    return 0


if __name__ == '__main__':
    clip_metadata = json.load(open("C:/temp/temp_edf/sub-P153_ses-014_task-ccep_run-01_ieeg.json"))
    clip_edf("C:/temp/temp_edf/sub-P153_ses-014_task-ccep_run-01_ieeg.edf","C:/temp/temp_edf/sub-P153_ses-014_task-ccep_run-01_ieeg_clipping_v21.edf",clip_metadata)
