import sys
import serial
import serial.tools.list_ports
import csv
from datetime import datetime
import threading
import time

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QComboBox, QPushButton, QTextEdit, QGroupBox,
    QMessageBox, QInputDialog, QFrame
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread
from PyQt6.QtGui import QFont

BAUD = 9600
TARE_COMMAND = b'*1T\r'  # Default Custom ASCII Tare command for address 1

class LoggerWorker(QObject):
    """Background worker that manages serial port polling, taring, and CSV writing."""
    message_signal = pyqtSignal(str)
    reading_signal = pyqtSignal(str, str)  # Emits (sensor_type, reading_value) for live view
    finished_signal = pyqtSignal(str)

    def __init__(self, load_port, torque_port, csv_filename):
        super().__init__()
        self.load_port = load_port
        self.torque_port = torque_port
        self.csv_filename = csv_filename
        self.stop_event = threading.Event()
        self.csv_lock = threading.Lock()
        
        # Store latest readings mapped by role
        self.latest_readings = {
            'load': "",
            'torque': ""
        }
        self.pending_event_note = ""
        self.start_perf_counter = None
        
        # Dictionary to hold active serial port instances for remote commands (like Tare)
        self.active_serial = {}

    def run(self):
        try:
            self.message_signal.emit(f"Connecting devices -> Load Cell: {self.load_port} | Torque Cell: {self.torque_port} at {BAUD} baud...")
            with open(self.csv_filename, mode='w', newline='') as csv_file:
                writer = csv.writer(csv_file)
                
                # Write header mapping Load Cell and Torque Cell to their COM ports
                writer.writerow([
                    "Timestamp", 
                    "Elapsed_us", 
                    f"Load_Cell ({self.load_port})", 
                    f"Torque_Cell ({self.torque_port})", 
                    "Event_Note"
                ])
                
                self.message_signal.emit(f"Maximum-speed logging active! Saving stream to {self.csv_filename}")
                
                # Start dedicated background threads for each sensor
                t_load = threading.Thread(
                    target=self.log_port, 
                    args=(self.load_port, 'load', writer, csv_file), 
                    daemon=True
                )
                t_torque = threading.Thread(
                    target=self.log_port, 
                    args=(self.torque_port, 'torque', writer, csv_file), 
                    daemon=True
                )
                
                t_load.start()
                t_torque.start()
                    
                while not self.stop_event.is_set():
                    time.sleep(0.05)
                    
                t_load.join(timeout=1.0)
                t_torque.join(timeout=1.0)
                    
        except Exception as e:
            self.message_signal.emit(f"Error handling CSV file: {e}")
        
        self.finished_signal.emit(self.csv_filename)

    def log_port(self, port, sensor_type, writer, csv_file):
        """Worker loop for a single serial port assigned to load or torque cell."""
        counter = 0
        sensor_name = "Load Cell" if sensor_type == 'load' else "Torque Cell"
        self.message_signal.emit(f"[{sensor_name} @ {port}] High-speed logging active...")
        
        try:
            with serial.Serial(port, baudrate=BAUD, timeout=0.05) as ser:
                # Register active serial connection for thread-safe command writing (Tare)
                with self.csv_lock:
                    self.active_serial[sensor_type] = ser

                while not self.stop_event.is_set():
                    # 1. Send poll command
                    ser.write(b'*1B1\r')
                    
                    # 2. Read until carriage return terminator
                    raw_line = ser.read_until(b'\r')
                    
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                    current_perf = time.perf_counter()
                    
                    if raw_line:
                        line = raw_line.decode('utf-8', errors='ignore').strip()
                        if line:
                            reading = line.replace('->', '').strip()
                            
                            # Emit live reading signal to GUI
                            self.reading_signal.emit(sensor_type, reading)
                            
                            with self.csv_lock:
                                if self.start_perf_counter is None:
                                    self.start_perf_counter = current_perf
                                
                                elapsed_us = int((current_perf - self.start_perf_counter) * 1_000_000)
                                self.latest_readings[sensor_type] = reading
                                
                                # Write row once both load and torque cells have reported data
                                if self.latest_readings['load'] != "" and self.latest_readings['torque'] != "":
                                    event_note = self.pending_event_note
                                    self.pending_event_note = ""
                                    
                                    row = [
                                        timestamp,
                                        elapsed_us,
                                        self.latest_readings['load'],
                                        self.latest_readings['torque'],
                                        event_note
                                    ]
                                    writer.writerow(row)
                                    csv_file.flush()
                            
                            counter += 1
                            if counter % 100 == 0:
                                self.message_signal.emit(
                                    f"[{sensor_name}] (+{elapsed_us} µs) Reading: {reading} (Count: {counter})"
                                )
        except serial.SerialException as e:
            self.message_signal.emit(f"[{sensor_name} @ {port}] Serial Error: {e}")
        finally:
            with self.csv_lock:
                if sensor_type in self.active_serial:
                    del self.active_serial[sensor_type]

    def tare_sensor(self, sensor_type):
        """Sends the tare command to a specific sensor's active serial connection."""
        with self.csv_lock:
            ser = self.active_serial.get(sensor_type)
            sensor_name = "Load Cell" if sensor_type == 'load' else "Torque Cell"
            if ser and ser.is_open:
                try:
                    ser.write(TARE_COMMAND)
                    self.message_signal.emit(f"*** TARE command sent to {sensor_name} ({ser.port}) ***")
                except Exception as e:
                    self.message_signal.emit(f"Error sending tare to {sensor_name}: {e}")
            else:
                self.message_signal.emit(f"Warning: Cannot tare {sensor_name} — port is not active.")

    def stop(self):
        self.stop_event.set()

    def add_event_marker(self, note):
        with self.csv_lock:
            self.pending_event_note = f"MARKER: {note}" if note.strip() else "MARKER"


class LoadCellLoggerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ERAU Prescott - Wind Tunnel Thrust Stand DAQ Tool")
        self.resize(780, 650)

        self.worker = None
        self.thread = None
        self.is_logging = False
        self.csv_filename = None

        self.init_ui()
        self.refresh_ports()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- PORT SELECTION GROUP ---
        port_group = QGroupBox("COM Port Configuration")
        port_layout = QGridLayout()

        port_layout.addWidget(QLabel("Load Cell Port:"), 0, 0)
        self.load_combo = QComboBox()
        port_layout.addWidget(self.load_combo, 0, 1)

        port_layout.addWidget(QLabel("Torque Cell Port:"), 1, 0)
        self.torque_combo = QComboBox()
        port_layout.addWidget(self.torque_combo, 1, 1)

        refresh_btn = QPushButton("Refresh Ports")
        refresh_btn.clicked.connect(self.refresh_ports)
        port_layout.addWidget(refresh_btn, 0, 2, 2, 1)

        port_group.setLayout(port_layout)
        main_layout.addWidget(port_group)

        # --- LIVE READINGS DISPLAY GROUP ---
        live_group = QGroupBox("Live Sensor Readings")
        live_layout = QHBoxLayout()

        # Load Cell Display Box
        load_frame = QFrame()
        load_frame.setFrameShape(QFrame.Shape.StyledPanel)
        load_frame.setStyleSheet("background-color: #252526; border-radius: 5px;")
        load_layout_inner = QVBoxLayout(load_frame)
        load_layout_inner.addWidget(QLabel("Load Cell Live Reading:", alignment=Qt.AlignmentFlag.AlignCenter))
        self.load_live_label = QLabel("---", alignment=Qt.AlignmentFlag.AlignCenter)
        self.load_live_label.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.load_live_label.setStyleSheet("color: #4ec9b0;")
        load_layout_inner.addWidget(self.load_live_label)

        # Torque Cell Display Box
        torque_frame = QFrame()
        torque_frame.setFrameShape(QFrame.Shape.StyledPanel)
        torque_frame.setStyleSheet("background-color: #252526; border-radius: 5px;")
        torque_layout_inner = QVBoxLayout(torque_frame)
        torque_layout_inner.addWidget(QLabel("Torque Cell Live Reading:", alignment=Qt.AlignmentFlag.AlignCenter))
        self.torque_live_label = QLabel("---", alignment=Qt.AlignmentFlag.AlignCenter)
        self.torque_live_label.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.torque_live_label.setStyleSheet("color: #dcdcaa;")
        torque_layout_inner.addWidget(self.torque_live_label)

        live_layout.addWidget(load_frame)
        live_layout.addWidget(torque_frame)
        live_group.setLayout(live_layout)
        main_layout.addWidget(live_group)

        # --- CONTROLS GROUP ---
        control_group = QGroupBox("Logging & Hardware Controls")
        control_layout = QGridLayout()

        self.start_btn = QPushButton("Start Logging")
        self.start_btn.clicked.connect(self.start_logging)
        control_layout.addWidget(self.start_btn, 0, 0)

        self.stop_btn = QPushButton("Stop Logging")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_logging)
        control_layout.addWidget(self.stop_btn, 0, 1)

        self.tare_load_btn = QPushButton("Tare Load Cell")
        self.tare_load_btn.setEnabled(False)
        self.tare_load_btn.clicked.connect(lambda: self.tare_sensor('load'))
        control_layout.addWidget(self.tare_load_btn, 1, 0)

        self.tare_torque_btn = QPushButton("Tare Torque Cell")
        self.tare_torque_btn.setEnabled(False)
        self.tare_torque_btn.clicked.connect(lambda: self.tare_sensor('torque'))
        control_layout.addWidget(self.tare_torque_btn, 1, 1)

        self.event_btn = QPushButton("Log Specific Point (Event)")
        self.event_btn.setEnabled(False)
        self.event_btn.clicked.connect(self.log_specific_point)
        control_layout.addWidget(self.event_btn, 2, 0)

        quit_btn = QPushButton("Quit Application")
        quit_btn.clicked.connect(self.close)
        control_layout.addWidget(quit_btn, 2, 1)

        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)

        # --- LIVE LOG OUTPUT ---
        log_group = QGroupBox("System Status & Log")
        log_layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: Consolas; font-size: 9pt;")
        log_layout.addWidget(self.log_text)

        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

    def log_message(self, message):
        """Append messages securely to the text widget."""
        self.log_text.append(message)

    def update_live_reading(self, sensor_type, value):
        """Updates the live view display labels for load or torque."""
        if sensor_type == 'load':
            self.load_live_label.setText(value)
        elif sensor_type == 'torque':
            self.torque_live_label.setText(value)

    def refresh_ports(self):
        """Scan and populate available system serial COM ports."""
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.load_combo.clear()
        self.torque_combo.clear()
        self.load_combo.addItems(ports)
        self.torque_combo.addItems(ports)

        if 'COM5' in ports:
            self.load_combo.setCurrentText('COM5')
        if 'COM7' in ports:
            self.torque_combo.setCurrentText('COM7')
        elif len(ports) > 1:
            self.torque_combo.setCurrentIndex(1)

        self.log_message(f"Discovered COM ports: {ports}")

    def start_logging(self):
        load_port = self.load_combo.currentText()
        torque_port = self.torque_combo.currentText()

        if not load_port or not torque_port:
            QMessageBox.critical(self, "Error", "Please select COM ports for both Load Cell and Torque Cell.")
            return
        if load_port == torque_port:
            QMessageBox.warning(self, "Warning", "Load Cell and Torque Cell must be assigned to distinct COM ports.")
            return

        self.csv_filename = f"thrust_stand_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        # Setup worker thread and QThread container
        self.thread = QThread()
        self.worker = LoggerWorker(load_port, torque_port, self.csv_filename)
        self.worker.moveToThread(self.thread)

        # Connect signals
        self.thread.started.connect(self.worker.run)
        self.worker.message_signal.connect(self.log_message)
        self.worker.reading_signal.connect(self.update_live_reading)
        self.worker.finished_signal.connect(self.on_logging_finished)

        # Update UI state
        self.is_logging = True
        self.start_btn.setEnabled(False)
        self.load_combo.setEnabled(False)
        self.torque_combo.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.tare_load_btn.setEnabled(True)
        self.tare_torque_btn.setEnabled(True)
        self.event_btn.setEnabled(True)

        self.log_message(f"\n--- Starting Data Acquisition ---")
        self.thread.start()

    def tare_sensor(self, sensor_type):
        """Trigger tare command on the specific active sensor worker."""
        if self.is_logging and self.worker:
            self.worker.tare_sensor(sensor_type)

    def log_specific_point(self):
        """Prompt user for a note and mark the current point in data stream."""
        if not self.is_logging or not self.worker:
            return

        note, ok = QInputDialog.getText(self, "Log Specific Point", "Enter event marker note (optional):")
        if ok:
            self.worker.add_event_marker(note)
            tag = f"MARKER: {note}" if note.strip() else "MARKER"
            self.log_message(f"*** EVENT MARKER LOGGED: {tag} ***")

    def stop_logging(self):
        if not self.is_logging or not self.worker:
            return

        self.log_message("\nStopping data acquisition...")
        self.worker.stop()
        if self.thread:
            self.thread.quit()
            self.thread.wait(2000)

    def on_logging_finished(self, filename):
        self.is_logging = False
        self.start_btn.setEnabled(True)
        self.load_combo.setEnabled(True)
        self.torque_combo.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.tare_load_btn.setEnabled(False)
        self.tare_torque_btn.setEnabled(False)
        self.event_btn.setEnabled(False)

        # Reset live displays
        self.load_live_label.setText("---")
        self.torque_live_label.setText("---")

        self.log_message(f"Logging stopped. Saved safely to: {filename}\n")
        QMessageBox.information(self, "Complete", f"Logging stopped.\nSaved to: {filename}")

    def closeEvent(self, event):
        """Safely clean up threads on application close."""
        if self.is_logging:
            reply = QMessageBox.question(
                self, "Quit", "Logging is currently active. Stop and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_logging()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LoadCellLoggerApp()
    window.show()
    sys.exit(app.exec())