import os
import numpy as np
import sys

cur_path = r'../../../../'
sys.path.append(os.path.abspath(cur_path))
os.environ['PATH'] += os.pathsep + cur_path

from _lhsc_lib.edfwriter import EDFwriter
from _lhsc_lib.EDF_reader_mld import EDFreader

profiler = None
args = None

SEEK_SET = EDFreader.EDFSEEK_SET

def is_gap(block, threshold=0.01):
    return np.all(np.abs(block) < threshold, axis=0).all()

def split_edf_streaming(input_path, output_dir, gap_sec=2.0, chunk_sec=1.0):
    import time
    last_profile_dump = time.time()

    os.makedirs(output_dir, exist_ok=True)
    reader = EDFreader(input_path)
    num_signals = reader.getNumSignals()
    sample_rate = reader.getSampleFrequency(0)
    total_samples = reader.getTotalSamples(0)
    total_secs = total_samples // sample_rate
    samples_per_chunk = int(chunk_sec * sample_rate)
    gap_chunks = int(gap_sec // chunk_sec)
    total_samples_per_channel = [reader.getTotalSamples(ch) for ch in range(num_signals)]

    segment_index = 0
    writing = False
    zero_count = 0
    segment_writer = None

    tmp_buffers = [np.zeros(samples_per_chunk, dtype=np.float64) for _ in range(num_signals)]
    padded = np.zeros(samples_per_chunk, dtype=np.float64)
    print(f"Streaming and splitting: {total_secs} seconds total")

    for i in range(0, total_samples, samples_per_chunk):
        if args.profile and time.time() - last_profile_dump > 30:
            profiler.dump_stats("edf_split_midrun.prof")
            print(f"[Profiler] Interim stats saved at t={i // sample_rate}s")
            last_profile_dump = time.time()

        actual_len = min(samples_per_chunk, total_samples - i)
        chunk = np.zeros((num_signals, actual_len), dtype=np.float64)

        if (i // sample_rate) % 5 == 0:
            print(f"Progress: t = {i // sample_rate} seconds ({100 * i / total_samples:.2f}%)", flush=True)

        for ch in range(num_signals):
            available = total_samples_per_channel[ch]
            if i >= available:
                chunk[ch, :] = 0
                continue

            safe_len = min(samples_per_chunk, available - i)
            reader.fseek(ch, i, SEEK_SET)
            tmp = tmp_buffers[ch][:safe_len]
            reader.readSamples(ch, tmp, safe_len)
            if safe_len < samples_per_chunk:
                padded[:safe_len] = tmp
                padded[safe_len:] = 0
                chunk[ch, :] = padded
            else:
                chunk[ch, :] = tmp

        chunk_is_zero = np.all(np.abs(chunk) < 1e-9)

        if not chunk_is_zero:
            if not writing:
                segment_index += 1
                out_path = os.path.join(
                    output_dir,
                    f"{os.path.splitext(os.path.basename(input_path))[0]}_part{segment_index}.edf"
                )
                print(out_path)
                segment_writer = EDFwriter(out_path, EDFwriter.EDFLIB_FILETYPE_EDFPLUS, num_signals)
                for ch in range(num_signals):
                    segment_writer.setSampleFrequency(ch, sample_rate)
                    segment_writer.setPhysicalMinimum(ch, reader.getPhysicalMinimum(ch))
                    segment_writer.setPhysicalMaximum(ch, reader.getPhysicalMaximum(ch))
                    segment_writer.setDigitalMinimum(ch, reader.getDigitalMinimum(ch))
                    segment_writer.setDigitalMaximum(ch, reader.getDigitalMaximum(ch))
                    segment_writer.setPhysicalDimension(ch, reader.getPhysicalDimension(ch))
                    segment_writer.setSignalLabel(ch, reader.getSignalLabel(ch))
                writing = True
                print(f"Started segment {segment_index} at t={i // sample_rate}s")

            zero_count = 0
            segment_writer.writeSamples(chunk)
        else:
            if writing:
                zero_count += 1
                if zero_count >= gap_chunks:
                    segment_writer.close()
                    print(f"Closed segment {segment_index} at t={i // sample_rate}s")
                    writing = False
                    zero_count = 0

    if writing and segment_writer:
        segment_writer.close()
        print(f"Closed final segment {segment_index}.")

    reader.close()

if __name__ == "__main__":
    import argparse
    import cProfile

    parser = argparse.ArgumentParser(description="Split EDF file by detecting long zero gaps.")
    parser.add_argument("input", help="Input EDF file")
    parser.add_argument("output", help="Output folder for split segments")
    parser.add_argument("--gap", type=float, default=10.0)
    parser.add_argument("--chunk", type=float, default=1.0)
    parser.add_argument("--profile", action="store_true", help="Enable profiling and save stats")
    args = parser.parse_args()

    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()

    split_edf_streaming(args.input, args.output, args.gap, args.chunk)

    if args.profile:
        profiler.disable()
        profiler.dump_stats("edf_split_final.prof")
        print("Final profiling saved to: edf_split_final.prof")