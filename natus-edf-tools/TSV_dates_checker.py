import pandas as pd
import argparse
from datetime import datetime, timedelta

def log_message(message, log_file):
    """Prints a message to the console and appends it to a log file with a timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)  # Print to console
    with open(log_file, "a") as log:
        log.write(log_entry + "\n")  # Append to log file

def check_durations(tsv_file, log_file):
    # Read TSV file
    df = pd.read_csv(tsv_file, sep="\t")

    # Convert acquisition time to datetime
    df["acq_time"] = pd.to_datetime(df["acq_time"])

    # Extract date (YYYY-MM-DD) from acquisition time
    df["date"] = df["acq_time"].dt.date

    # Convert duration to float (assuming it's in seconds)
    df["duration"] = df["duration"].astype(float)  # Convert seconds to hours

    # Group filenames by date
    filenames_by_date = df.groupby("date")["filename"].apply(list)

    # Count the number of sessions per day
    session_counts = df.groupby("date")["filename"].count()

    # Group by date and sum durations
    daily_durations = df.groupby("date")["duration"].sum()

    # Get full date range
    first_day, last_day = daily_durations.index[0], daily_durations.index[-1]
    full_date_range = pd.date_range(start=first_day, end=last_day).date

    log_message(f"Processing file: {tsv_file}", log_file)
    log_message(f"Checking data from {first_day} to {last_day}...", log_file)

    # Identify missing dates
    missing_dates = set(full_date_range) - set(daily_durations.index)
    
    if missing_dates:
        log_message("ERROR: The following dates are completely missing:", log_file)
        for missing in sorted(missing_dates):
            log_message(f"  - {missing}", log_file)
    else:
        log_message("Perfect! No missing days found!", log_file)

    # Identify days with multiple sessions
    multiple_sessions = session_counts[session_counts > 1]
    if not multiple_sessions.empty:
        log_message("\nINFO: Days with multiple sessions recorded:", log_file)
        for date, count in multiple_sessions.items():
            log_message(f"  - {date}: {count} sessions", log_file)
            log_message(f"    Files: {', '.join(filenames_by_date[date])}", log_file)

    # Check total duration per day
    for date in full_date_range:
        if date in daily_durations:
            total_duration = daily_durations[date]
            filenames = ", ".join(filenames_by_date[date]) if date in filenames_by_date else "No files found"

            if date == first_day or date == last_day:
                if total_duration < 23:
                    log_message(f"WARNING: First/Last day {date} has only {total_duration:.2f} hours recorded.", log_file)
                    log_message(f"    Files: {filenames}", log_file)
            elif first_day < date < last_day and total_duration >= 23:
                log_message(f"All good for Day {date}!!!", log_file)
                log_message(f"    Files: {filenames}", log_file)
            else:
                if total_duration < 23:
                    log_message(f"ERROR: Day {date} has only {total_duration:.2f} hours recorded.", log_file)
                    log_message(f"    Files: {filenames}", log_file)
        else:
            log_message(f"ERROR: Missing data for {date}. No recordings found.", log_file)

    log_message(f"\nCheck completed. There are a total of {len(full_date_range)} days in the dataset.", log_file)

# Argument parser
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check if daily recording duration meets minimum requirements.")
    parser.add_argument("tsv_file", help="Path to the TSV file containing session information")
    parser.add_argument("log_file", help="Path to the log file (appends logs, does not overwrite)")
    args = parser.parse_args()

    # Run the check
    check_durations(args.tsv_file, args.log_file)
