# ERAU Prescott's 4x4 Wind Tunnel Thrust Stand DAQ Tool

A multi-threaded Python desktop application for high-speed, microsecond-precision data acquisition from serial load cells and torque cells (SST-HV models or compatible hardware). Built with **PyQt6** for a native user interface and **PySerial** for low-latency serial communication.

## Key Features

* **Microsecond Precision**: Tracks high-resolution timestamps (`YYYY-MM-DD HH:MM:SS.ffffff`) alongside relative elapsed microseconds (`Elapsed_us`) calculated via `time.perf_counter()`.

* **Sensor-Specific Logging**: Prompts for distinct Load Cell and Torque Cell COM ports, logging measurements under dedicated CSV headers.

* **Multi-Port Parallel Logging**: Dedicated background threads handle continuous polling across multiple serial COM ports simultaneously.

* **Dynamic Serial Port Discovery**: Auto-detects available active system COM ports on startup with a manual **Refresh Ports** option.

* **Live Event Point Marking**: Allows users to inject instant event tags and custom notes (e.g., *"Yield Point"*, *"Rupture Test"*) directly into the CSV stream at any moment.

* **Non-Blocking PyQt6 Interface**: Built on `QThread` and signal/slot architectures to ensure the interface stays responsive during heavy data streaming.

* **Embedded Terminal Output**: Integrated dark-mode live console log with throttled print loops to avoid window lag.

## Hardware & Command Protocol

The default application communicates at **9600 Baud** using the following protocol:

* **Polling Command**: `*1B1\r`

* **Terminator**: Carriage Return (`\r`)

* **Expected Output**: Standard raw reading response (e.g., `-> 123.45` cleaned to `123.45`).

## Prerequisites

Ensure you have Python **3.8+** installed on your system.

### Dependencies

Install the required Python packages using `pip`:

```bash
pip install PyQt6 pyserial
```

## Installation & Setup

1. **Clone or Download the Repository**:
   Save the application code as `main.py`.

2. **Connect Hardware**:
   Plug in your load cell and torque cell serial adapters (e.g., USB-to-RS232/RS485 converters).

3. **Run the Application**:

   ```bash
   python main.py
   ```

## Compiling to Standalone Executable (.exe)

You can package this application into a single standalone `.exe` using **PyInstaller** so that it can be run on computers without Python installed.

### 1. Install PyInstaller

```bash
pip install pyinstaller
```

### 2. Build the Executable

Run the following command in the directory containing `main.py`:

```bash
pyinstaller --noconsole --onefile --collect-all serial --collect-all PyQt6 main.py
```

#### Why these flags are required:
* **`--onefile`**: Bundles the entire application and Python interpreter into a single `.exe`.
* **`--noconsole`**: Hides the background terminal window, leaving only the clean PyQt GUI.
* **`--collect-all serial`**: Forces PyInstaller to include hidden OS-specific modules in `pyserial` necessary for COM port enumeration.
* **`--collect-all PyQt6`**: Ensures all Qt plugins, DLLs, and widget rendering drivers are gathered correctly.

### 3. Output Location

Once compilation finishes, your standalone executable will be generated inside the `dist/` directory:

```text
dist/
└── main.exe
```

## How to Use

1. **Select COM Ports**:
   * Select your **Load Cell Port** and **Torque Cell Port** from their respective dropdown menus.
   * Click **Refresh Ports** if you plugged in devices after opening the app.

2. **Start Logging**:
   * Click **Start Logging**.
   * The app generates a timestamped CSV file formatted as `thrust_stand_data_YYYYMMDD_HHMMSS.csv`.

3. **Log Event Points**:
   * While logging, click **Log Specific Point (Event)** to tag significant testing milestones.
   * An optional popup prompt lets you tag the point with custom text notes.

4. **Stop Logging & Exit**:
   * Click **Stop Logging** to safely flush data to disk and terminate worker threads.
   * Click **Quit Application** (or close the window) to shut down cleanly.

## Output CSV Format

The generated CSV output contains the following columns:

| Timestamp | Elapsed_us | Load_Cell (COM5) | Torque_Cell (COM7) | Event_Note | 
| ----- | ----- | ----- | ----- | ----- | 
| `2026-10-30 09:30:00.123456` | `0` | `10.25` | `1.45` |  | 
| `2026-10-30 09:30:00.174821` | `51365` | `12.80` | `1.82` |  | 
| `2026-10-30 09:30:00.225103` | `101647` | `15.40` | `2.10` | `MARKER: Max Throttle` | 

## File Structure

```text
.
├── main.py        # Complete PyQt6 application and threading logic
└── README.md      # Application documentation
```

## License

This project is licensed under the MIT License — free to use and adapt for academic, personal, or commercial load cell testing projects.