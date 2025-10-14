import argparse
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import messagebox


def time_to_seconds(hhmmss):
    h, m, s = map(int, hhmmss.split(':'))
    return h * 3600 + m * 60 + s


def compute_record_indices(
    total_records,
    total_duration_str,
    recording_start_time_str,
    target_start_str,
    target_end_str,
    pre_offset_minutes=30,
    post_offset_minutes=30
):
    total_duration_seconds = time_to_seconds(total_duration_str)
    recording_start_seconds = time_to_seconds(recording_start_time_str)
    target_start_seconds = time_to_seconds(target_start_str)
    target_end_seconds = time_to_seconds(target_end_str)

    records_per_second = total_records / total_duration_seconds

    adjusted_start = target_start_seconds - (pre_offset_minutes * 60)
    adjusted_end = target_end_seconds + (post_offset_minutes * 60)

    if adjusted_start < recording_start_seconds:
        adjusted_start += 24 * 3600
    if adjusted_end < recording_start_seconds:
        adjusted_end += 24 * 3600

    seconds_from_start_to_adjusted_start = adjusted_start - recording_start_seconds
    seconds_from_start_to_adjusted_end = adjusted_end - recording_start_seconds

    record_start = round(seconds_from_start_to_adjusted_start * records_per_second)
    record_end = round(seconds_from_start_to_adjusted_end * records_per_second)-1

    actual_recording_start = datetime.strptime(recording_start_time_str, "%H:%M:%S")
    start_timestamp = actual_recording_start + timedelta(seconds=seconds_from_start_to_adjusted_start)
    end_timestamp = actual_recording_start + timedelta(seconds=seconds_from_start_to_adjusted_end)

    result = (
        f"Adjusted Start Time: {start_timestamp.time()} -> Record #{record_start}\n"
        f"Adjusted End Time:   {end_timestamp.time()} -> Record #{record_end}"
    )
    return result


def run_gui():
    def on_submit():
        try:
            total_records = int(entries['Total Records'].get())
            total_duration = entries['Total Duration (HH:MM:SS)'].get()
            recording_start = entries['Recording Start Time (HH:MM:SS)'].get()
            target_start = entries['Target Start Time (HH:MM:SS)'].get()
            target_end = entries['Target End Time (HH:MM:SS)'].get()
            pre_offset = int(entries['Pre-Offset (minutes)'].get())
            post_offset = int(entries['Post-Offset (minutes)'].get())

            result = compute_record_indices(
                total_records,
                total_duration,
                recording_start,
                target_start,
                target_end,
                pre_offset,
                post_offset
            )

            messagebox.showinfo("Result", result)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    root = tk.Tk()
    root.title("Record Index Calculator")

    fields = [
        'Total Records',
        'Total Duration (HH:MM:SS)',
        'Recording Start Time (HH:MM:SS)',
        'Target Start Time (HH:MM:SS)',
        'Target End Time (HH:MM:SS)',
        'Pre-Offset (minutes)',
        'Post-Offset (minutes)'
    ]
    entries = {}

    for i, field in enumerate(fields):
        tk.Label(root, text=field).grid(row=i, column=0, sticky='e', padx=5, pady=4)
        entry = tk.Entry(root)
        entry.grid(row=i, column=1, padx=5, pady=4)
        entries[field] = entry

    # Set defaults
    entries['Pre-Offset (minutes)'].insert(0, '30')
    entries['Post-Offset (minutes)'].insert(0, '30')

    submit_button = tk.Button(root, text="Calculate", command=on_submit)
    submit_button.grid(row=len(fields), column=0, columnspan=2, pady=10)

    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Calculate record range for a time window in a recording.")
    parser.add_argument("--total_records", type=int, help="Total number of records")
    parser.add_argument("--duration", type=str, help="Total duration in HH:MM:SS")
    parser.add_argument("--start_time", type=str, help="Recording start time in HH:MM:SS")
    parser.add_argument("--target_start", type=str, help="Target window start time in HH:MM:SS")
    parser.add_argument("--target_end", type=str, help="Target window end time in HH:MM:SS")
    parser.add_argument("--pre_offset", type=int, default=30, help="Minutes before target start")
    parser.add_argument("--post_offset", type=int, default=30, help="Minutes after target end")

    args = parser.parse_args()

    if all([args.total_records, args.duration, args.start_time, args.target_start, args.target_end]):
        result = compute_record_indices(
            args.total_records,
            args.duration,
            args.start_time,
            args.target_start,
            args.target_end,
            args.pre_offset,
            args.post_offset
        )
        print(result)
    else:
        run_gui()


if __name__ == "__main__":
    main()
