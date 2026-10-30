import serial
import csv
from datetime import datetime
import threading
import time

# Configuration
PORTS = ['COM5', 'COM7']
BAUD = 9600
CSV_FILENAME = f"load_cell_microseconds_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# Threading synchronization tools and shared state
csv_lock = threading.Lock()
stop_event = threading.Event()

# Dictionary to hold the latest reading for each port
latest_readings = {
    'COM5': "",
    'COM7': ""
}

# High-precision reference timer for elapsed microseconds
start_perf_counter = None

def log_port(port, writer, csv_file):
    """Worker function to handle maximum-speed logging for a single serial port."""
    global start_perf_counter
    counter = 0
    print(f"[{port}] High-speed logging active...")
    try:
        # Optimized timeout for fast serial polling
        with serial.Serial(port, baudrate=BAUD, timeout=0.05) as ser:
            while not stop_event.is_set():
                # 1. Send poll command
                ser.write(b'*1B1\r') 
                
                # 2. Read until the device's carriage return (\r) terminator
                raw_line = ser.read_until(b'\r')
                
                # Capture high-resolution timestamp and performance counter
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                current_perf = time.perf_counter()
                
                if raw_line:
                    line = raw_line.decode('utf-8', errors='ignore').strip()
                    if line:
                        reading = line.replace('->', '').strip()
                        
                        # Thread-safe update and CSV write
                        with csv_lock:
                            # Initialize the start anchor on the very first logged row
                            if start_perf_counter is None:
                                start_perf_counter = current_perf
                            
                            # Calculate elapsed microseconds since logging started
                            elapsed_us = int((current_perf - start_perf_counter) * 1_000_000)
                            
                            latest_readings[port] = reading
                            
                            # Only write to CSV once both ports have reported at least once
                            if latest_readings['COM5'] != "" and latest_readings['COM7'] != "":
                                row = [
                                    timestamp,
                                    elapsed_us,
                                    latest_readings['COM5'],
                                    latest_readings['COM7']
                                ]
                                writer.writerow(row)
                                csv_file.flush()
                        
                        # Throttle console printing per port (prints every 100th reading to prevent console lag)
                        counter += 1
                        if counter % 100 == 0:
                            print(f"[{port}] [{timestamp}] (+{elapsed_us} µs) Reading: {reading} (Total logged: {counter})")
                            
    except serial.SerialException as e:
        print(f"\n[{port}] Serial Error: {e}")
        print(f"-> Ensure device on {port} is completely closed and not used by another app.")

try:
    print(f"Connecting to SST-HV devices on {PORTS} at {BAUD} baud...")
    
    # Open CSV file and write wide-format headers including Elapsed_us
    with open(CSV_FILENAME, mode='w', newline='') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["Timestamp", "Elapsed_us", "COM5", "COM7"])  # Column headings
        
        print(f"Maximum-speed logging active! Saving stream to {CSV_FILENAME}")
        print("Press Ctrl+C to stop and save.\n")
        
        # Start a dedicated thread for each COM port
        threads = []
        for port in PORTS:
            t = threading.Thread(target=log_port, args=(port, writer, csv_file), daemon=True)
            threads.append(t)
            t.start()
            
        # Keep main thread running until interrupted
        while True:
            time.sleep(0.05)

except KeyboardInterrupt:
    print(f"\nStopping loggers...")
    stop_event.set()
    time.sleep(0.3)  # Give threads a brief moment to wind down
    print(f"\nMaximum-speed logging stopped. All data saved safely to: {CSV_FILENAME}")
except Exception as e:
    print(f"\nUnexpected Error: {e}")
    stop_event.set()