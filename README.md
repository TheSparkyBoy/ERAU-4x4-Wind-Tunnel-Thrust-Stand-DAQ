# ERAU Prescott's 4x4 Wind Tunnel Thrust Stand DAQ Tool

A multi-threaded Python desktop application for high-speed, microsecond-precision data acquisition from serial load cells and torque cells (Transducer Techniques SST-HV models or compatible hardware). Built with **PyQt6** for a native user interface and **PySerial** for low-latency serial communication.

## Key Features

* **Microsecond Precision**: Tracks high-resolution timestamps (`YYYY-MM-DD HH:MM:SS.ffffff`) alongside relative elapsed microseconds (`Elapsed_us`) calculated via high-precision performance counters (`time.perf_counter()`).

* **Sensor-Specific Logging**: Configures distinct COM ports for the **Load Cell** and **Torque Cell**, outputting measurements under explicit column headers.

* **Dual-CSV Output System**:

  * **Data Stream File** (`thrust_stand_data_YYYYMMDD_HHMMSS.csv`): Logs continuous high-speed readings across both channels.

  * **Events Log File** (`thrust_stand_events_YYYYMMDD_HHMMSS.csv`): Records instant timestamped snapshots of both sensor channels and an optional comment whenever the **Log Specific Point (Event)** button is triggered.

* **Continuous Live Data Preview**: Real-time numerical display updating continuously on-screen both when idle and during active logging sessions.

* **Dual-Layer Tare System**: Independent **Tare Load Cell** and **Tare Torque Cell** controls that combine instantaneous software offset zeroing (for live GUI display & CSV output) with serial hardware tare commands (`*1T\r`) transmitted to the SST-HV signal conditioners.

* **Custom & Persistent Storage Directory**: Select any output folder on your computer via a folder browser. The application remembers your last used directory across sessions (`QSettings`).

* **Non-Blocking Architecture**: Utilizes Qt `QThread` signal/slot structures and thread-safe locks (`threading.Lock`) to ensure the GUI remains fluid and responsive during maximum polling rates.

## Hardware & Serial Protocol

The default application communicates at **9600 Baud** using the following protocol:

* **Polling Command**: `*1B1\r`

* **Hardware Tare Command**: `*1T\r`

* **Terminator**: Carriage Return (`\r`)

* **Expected Serial Output**: Raw reading string (e.g., `-> 123.45` sanitized to `123.45`).

## Prerequisites

Ensure you have Python **3.8+** installed on your system.

### Install Dependencies

Install the required Python packages using `pip`:

```
pip install PyQt6 pyserial

```

## Installation & Setup

1. **Save Application Code**:
   Save the Python script as `main.py` in your working directory.

2. **Connect Hardware**:
   Plug in your load cell and torque cell signal conditioners (USB-to-Serial adapters).

3. **Run the Application**:

   ```
   python main.py
   
   ```

## Compiling to Standalone Executable (.exe)

You can package this application into a single standalone `.exe` using **PyInstaller** to run it on testing PCs without needing Python installed.

### 1. Install PyInstaller

```
pip install pyinstaller

```

### 2. Build the Executable

Run the following command in the terminal directory containing `main.py`:

```
pyinstaller --noconsole --onefile --collect-all serial --collect-all PyQt6 main.py

```

#### Explanation of PyInstaller Flags:

* **`--onefile`**: Bundles the application into a single executable file.

* **`--noconsole`**: Suppresses the background terminal window, running only the GUI.

* **`--collect-all serial`**: Includes dynamic OS registry tools required for `pyserial` COM port enumeration.

* **`--collect-all PyQt6`**: Packages all necessary Qt rendering engines and widget plugins.

### 3. Executable Location

Once compilation finishes, your executable will be located in the `dist/` directory:

```
dist/
└── main.exe

```

## How to Use

1. **Select COM Ports**:

   * Select the appropriate serial ports for the **Load Cell** and **Torque Cell**.

   * Click **Refresh Ports** if devices were plugged in after opening the app.

2. **Select Output Directory**:

   * Enter a directory path or click **Browse...** to pick a destination folder for logged files. The app automatically saves this location for future launches.

3. **Tare Sensors**:

   * Click **Tare Load Cell** or **Tare Torque Cell** at any time (idle or logging) to zero out the live display and subsequent recorded data.

4. **Start Logging**:

   * Click **Start Logging**. The app generates both data and event CSV files in your selected directory.

5. **Log Specific Points (Events)**:

   * Click **Log Specific Point (Event)** during a test run to log a snapshot. An optional prompt lets you enter event markers (e.g., *"Throttle 50%"*, *"Peak Thrust"*).

6. **Stop & Exit**:

   * Click **Stop Logging** to safely flush file buffers and stop background acquisition.

   * Click **Quit Application** to terminate cleanly.

## Output CSV Formats

### 1. Main Continuous Stream CSV (`thrust_stand_data_YYYYMMDD_HHMMSS.csv`)

| Timestamp | Elapsed_us | Load_Cell (COM5) | Torque_Cell (COM7) | Event_Note | 
| ----- | ----- | ----- | ----- | ----- | 
| `2026-10-30 09:30:00.123456` | `0` | `0.000` | `0.000` |  | 
| `2026-10-30 09:30:00.174821` | `51365` | `12.800` | `1.820` |  | 
| `2026-10-30 09:30:00.225103` | `101647` | `15.400` | `2.100` | `MARKER: Throttle Step 1` | 

### 2. Events Snapshot CSV (`thrust_stand_events_YYYYMMDD_HHMMSS.csv`)

| Timestamp | Elapsed_us | Load_Cell (COM5) | Torque_Cell (COM7) | Event_Comment | 
| ----- | ----- | ----- | ----- | ----- | 
| `2026-10-30 09:30:00.225103` | `101647` | `15.400` | `2.100` | `Throttle Step 1` | 
| `2026-10-30 09:31:12.891230` | `72767827` | `45.210` | `6.830` | `Maximum RPM` | 

## Project Structure

```
.
├── main.py        # PyQt6 GUI, multithreading, and serial acquisition logic
├── README.md      # Tool documentation and compilation guide
└── Data/          # Default directory for generated CSV logs

```

## License

This project is open-source under the MIT License — designed for academic, laboratory, and research testing projects at Embry-Riddle Aeronautical University.