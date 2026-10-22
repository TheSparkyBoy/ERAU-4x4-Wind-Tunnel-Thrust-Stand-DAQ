import re
import serial

# Configuration based on your setup
PORT = 'COM5'
BAUD = 9600

try:
  ser = serial.Serial(PORT, baudrate=BAUD, timeout=1)
  print(f'Connected to SST-HV on {PORT} at {BAUD} baud. Reading data...')

  with open('load_cell_data.csv', 'w') as f:
    f.write('Raw_String,Force_Value\n')  # CSV Header

    while True:
      # Read a full text line from the serial buffer
      raw_line = ser.readline()
      if raw_line:
        line = raw_line.decode('utf-8', errors='ignore').strip()

        # Extract the numerical force value using regex
        match = re.search(r'([+-]?\d*\.\d+|[+-]?\d+)', line)
        if match:
          force_value = float(match.group(1))
          print(f'Raw: {line:<15} | Parsed: {force_value}')

          # Log to file
          f.write(f'"{line}",{force_value}\n')
          f.flush()

except KeyboardInterrupt:
  print('\nStopping data acquisition.')
finally:
  if 'ser' in locals() and ser.is_open:
    ser.close()