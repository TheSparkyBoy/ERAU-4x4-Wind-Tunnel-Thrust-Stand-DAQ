import serial
import time
import csv
from datetime import datetime

# Configuration
PORT = 'COM5'
BAUD = 9600
POLL_INTERVAL = 0.05  # Time between requests in seconds (~20 Hz)
CSV_FILENAME = f"load_cell_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

print(f"Connecting to SST-HV on {PORT} at {BAUD} baud...")

try:
    with serial.Serial(PORT, baudrate=BAUD, timeout=1) as ser:
        print(f"Connected! Logging data to {CSV_FILENAME}")
        print("Press Ctrl+C to stop and save.\n")
        
        # Open CSV file and write header
        with open(CSV_FILENAME, mode='w', newline='') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["Timestamp", "Reading"])  # CSV Headers
            
            print("Timestamp            | Reading")
            print("-" * 35)
            
            while True:
                # 1. Send poll command
                ser.write(b'*1B1\r') 
                
                # 2. Read response
                raw_line = ser.readline()
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                
                if raw_line:
                    line = raw_line.decode('utf-8', errors='ignore').strip()
                    if line:
                        # Clean up the output string (remove any trailing characters if needed)
                        reading = line.replace('->', '').strip()
                        
                        # Print live to console
                        print(f"{timestamp} | {reading}")
                        
                        # Write to CSV file
                        writer.writerow([timestamp, reading])
                        csv_file.flush()  # Ensures data is written immediately to disk
                
                # Control polling frequency
                time.sleep(POLL_INTERVAL)

except serial.SerialException as e:
    print(f"\nSerial Error: {e}")
    print("-> Ensure DPM-3 is completely closed and no other app is using COM5.")
except KeyboardInterrupt:
    print(f"\nData acquisition stopped. Log saved successfully to: {CSV_FILENAME}")