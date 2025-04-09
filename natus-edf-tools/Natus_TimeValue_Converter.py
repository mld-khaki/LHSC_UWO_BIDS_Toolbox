from datetime import datetime, timedelta
import sys

def serial_to_datetime(serial_number):
    base_date = datetime(1899, 12, 30)
    return base_date + timedelta(days=serial_number)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python convert_date.py <serial_number>")
    else:
        try:
            serial = float(sys.argv[1])
            result = serial_to_datetime(serial)
            print("Date and Time:", result.strftime("%d %b %Y %H:%M:%S"))
        except ValueError:
            print("Please enter a valid number (int or float) for the serial date.")
