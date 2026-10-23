import serial
import csv
from datetime import datetime

# Configuration
PORT = 'COM5'
BAUD = 9600
CSV_FILENAME = f"load_cell_highspeed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

print(f"Connecting to SST-HV on {PORT} at {BAUD} baud...")

try:
    # Using a short timeout (0.1s) just in case
    with serial.Serial(PORT, baudrate=BAUD, timeout=0.1) as ser:
        print(f"High-speed logging active! Saving to {CSV_FILENAME}")
        print("Press Ctrl+C to stop and save.\n")
        
        # Open CSV file and write header
        with open(CSV_FILENAME, mode='w', newline='') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["Timestamp", "Reading"])  # CSV Headers
            
            counter = 0
            print("Logging at maximum speed... (Console view throttled)")
            
            while True:
                # 1. Send poll command
                ser.write(b'*1B1\r') 
                
                # 2. Read until the device's carriage return (\r) terminator
                raw_line = ser.read_until(b'\r')
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                
                if raw_line:
                    line = raw_line.decode('utf-8', errors='ignore').strip()
                    if line:
                        reading = line.replace('->', '').strip()
                        
                        # Write every single point to CSV immediately
                        writer.writerow([timestamp, reading])
                        csv_file.flush()
                        
                        # Throttle console printing (prints every 50th reading to prevent lag)
                        counter += 1
                        if counter % 50 == 0:
                            print(f"[{timestamp}] Reading: {reading} (Total logged: {counter})")

except serial.SerialException as e:
    print(f"\nSerial Error: {e}")
    print("-> Ensure DPM-3 is completely closed and no other app is using COM5.")
except KeyboardInterrupt:
    print(f"\nHigh-speed logging stopped. All data saved safely to: {CSV_FILENAME}")