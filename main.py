import sys
import os
import serial
import serial.tools.list_ports
import csv
from datetime import datetime
import threading
import time

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QComboBox, QPushButton, QTextEdit, QGroupBox,
    QMessageBox, QInputDialog, QFrame, QLineEdit, QFileDialog
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread, QSettings
from PyQt6.QtGui import QFont

BAUD = 9600
TARE_COMMAND = b'*1T\r'  # Default Custom ASCII command for hardware tare

class LivePreviewWorker(QObject):
    """Background worker for polling serial ports when LOGGING IS OFF."""
    preview_reading_signal = pyqtSignal(str, str)  # Emits (sensor_type, display_value)
    message_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, load_port, torque_port, get_offset_func):
        super().__init__()
        self.load_port = load_port
        self.torque_port = torque_port
        self.get_offset_func = get_offset_func
        self.stop_event = threading.Event()

    def run(self):
        threads = []
        if self.load_port:
            t1 = threading.Thread(target=self.poll_preview, args=(self.load_port, 'load'), daemon=True)
            threads.append(t1)
            t1.start()
        if self.torque_port and self.torque_port != self.load_port:
            t2 = threading.Thread(target=self.poll_preview, args=(self.torque_port, 'torque'), daemon=True)
            threads.append(t2)
            t2.start()

        while not self.stop_event.is_set():
            time.sleep(0.05)

        for t in threads:
            t.join(timeout=0.2)
            
        self.finished_signal.emit()

    def poll_preview(self, port, sensor_type):
        try:
            with serial.Serial(port, baudrate=BAUD, timeout=0.1) as ser:
                while not self.stop_event.is_set():
                    ser.write(b'*1B1\r')
                    raw_line = ser.read_until(b'\r')
                    if raw_line:
                        line = raw_line.decode('utf-8', errors='ignore').strip()
                        if line:
                            raw_val_str = line.replace('->', '').strip()
                            try:
                                raw_val = float(raw_val_str)
                                offset = self.get_offset_func(sensor_type)
                                tared_val = raw_val - offset
                                display_str = f"{tared_val:.3f}"
                            except ValueError:
                                display_str = raw_val_str

                            self.preview_reading_signal.emit(sensor_type, display_str)
                    time.sleep(0.05)  # 20 Hz preview polling rate
        except Exception:
            pass  # Suppress serial disconnect errors during preview mode

    def stop(self):
        self.stop_event.set()


class LoggerWorker(QObject):
    """Background worker managing high-speed serial polling, CSV writing, event logging, and taring."""
    message_signal = pyqtSignal(str)
    reading_signal = pyqtSignal(str, str)  # Emits (sensor_type, display_value)
    finished_signal = pyqtSignal(str)

    def __init__(self, load_port, torque_port, csv_filename, event_filename, get_offset_func, update_offset_func):
        super().__init__()
        self.load_port = load_port
        self.torque_port = torque_port
        self.csv_filename = csv_filename
        self.event_filename = event_filename
        self.get_offset_func = get_offset_func
        self.update_offset_func = update_offset_func
        
        self.stop_event = threading.Event()
        self.csv_lock = threading.Lock()
        
        self.latest_readings = {
            'load': "",
            'torque': ""
        }
        self.raw_latest = {
            'load': 0.0,
            'torque': 0.0
        }
        self.pending_event_note = ""
        self.start_perf_counter = None
        self.active_serial = {}
        
        self.event_file = None
        self.event_writer = None

    def run(self):
        try:
            self.message_signal.emit(f"Connecting devices -> Load Cell: {self.load_port} | Torque Cell: {self.torque_port} at {BAUD} baud...")
            
            # Open both main data CSV and separate Events CSV
            with open(self.csv_filename, mode='w', newline='') as csv_file, \
                 open(self.event_filename, mode='w', newline='') as self.event_file:
                
                writer = csv.writer(csv_file)
                self.event_writer = csv.writer(self.event_file)
                
                # Write headers
                writer.writerow([
                    "Timestamp", 
                    "Elapsed_us", 
                    f"Load_Cell ({self.load_port})", 
                    f"Torque_Cell ({self.torque_port})", 
                    "Event_Note"
                ])
                
                self.event_writer.writerow([
                    "Timestamp",
                    "Elapsed_us",
                    f"Load_Cell ({self.load_port})",
                    f"Torque_Cell ({self.torque_port})",
                    "Event_Comment"
                ])
                self.event_file.flush()
                
                self.message_signal.emit(f"Maximum-speed logging active!\n -> Stream: {self.csv_filename}\n -> Events: {self.event_filename}")
                
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
            self.message_signal.emit(f"Error handling CSV files: {e}")
        finally:
            self.event_file = None
            self.event_writer = None
        
        self.finished_signal.emit(self.csv_filename)

    def log_port(self, port, sensor_type, writer, csv_file):
        counter = 0
        sensor_name = "Load Cell" if sensor_type == 'load' else "Torque Cell"
        self.message_signal.emit(f"[{sensor_name} @ {port}] High-speed logging active...")
        
        try:
            with serial.Serial(port, baudrate=BAUD, timeout=0.05) as ser:
                with self.csv_lock:
                    self.active_serial[sensor_type] = ser

                while not self.stop_event.is_set():
                    ser.write(b'*1B1\r')
                    raw_line = ser.read_until(b'\r')
                    
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                    current_perf = time.perf_counter()
                    
                    if raw_line:
                        line = raw_line.decode('utf-8', errors='ignore').strip()
                        if line:
                            raw_val_str = line.replace('->', '').strip()
                            
                            try:
                                raw_num = float(raw_val_str)
                                self.raw_latest[sensor_type] = raw_num
                                offset = self.get_offset_func(sensor_type)
                                tared_num = raw_num - offset
                                display_reading = f"{tared_num:.3f}"
                            except ValueError:
                                display_reading = raw_val_str

                            # Emit signal for live viewing
                            self.reading_signal.emit(sensor_type, display_reading)
                            
                            with self.csv_lock:
                                if self.start_perf_counter is None:
                                    self.start_perf_counter = current_perf
                                
                                elapsed_us = int((current_perf - self.start_perf_counter) * 1_000_000)
                                self.latest_readings[sensor_type] = display_reading
                                
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
                                    f"[{sensor_name}] (+{elapsed_us} µs) Reading: {display_reading} (Count: {counter})"
                                )
        except serial.SerialException as e:
            self.message_signal.emit(f"[{sensor_name} @ {port}] Serial Error: {e}")
        finally:
            with self.csv_lock:
                if sensor_type in self.active_serial:
                    del self.active_serial[sensor_type]

    def record_event_snapshot(self, note):
        """Captures a snapshot point and writes it directly to the separate events CSV file."""
        with self.csv_lock:
            if not self.event_writer or not self.event_file:
                return
            
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            current_perf = time.perf_counter()
            elapsed_us = int((current_perf - self.start_perf_counter) * 1_000_000) if self.start_perf_counter else 0
            
            load_val = self.latest_readings['load'] if self.latest_readings['load'] != "" else "0.000"
            torque_val = self.latest_readings['torque'] if self.latest_readings['torque'] != "" else "0.000"
            comment = note.strip() if note else ""
            
            # Write to separate events CSV file
            self.event_writer.writerow([
                timestamp,
                elapsed_us,
                load_val,
                torque_val,
                comment
            ])
            self.event_file.flush()
            
            # Also attach marker reference for the main stream row
            self.pending_event_note = f"MARKER: {comment}" if comment else "MARKER"

    def tare_sensor(self, sensor_type):
        """Applies software offset tare and sends hardware tare command simultaneously."""
        sensor_name = "Load Cell" if sensor_type == 'load' else "Torque Cell"
        
        current_raw = self.raw_latest[sensor_type]
        self.update_offset_func(sensor_type, current_raw)
        self.message_signal.emit(f"*** {sensor_name} Software Tared to 0.000 (Offset: {current_raw:.3f}) ***")

        with self.csv_lock:
            ser = self.active_serial.get(sensor_type)
            if ser and ser.is_open:
                try:
                    ser.write(TARE_COMMAND)
                    self.message_signal.emit(f"*** Hardware TARE command sent to {sensor_name} ({ser.port}) ***")
                except Exception as e:
                    self.message_signal.emit(f"Hardware tare note: {e}")

    def stop(self):
        self.stop_event.set()


class LoadCellLoggerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ERAU Prescott - Wind Tunnel Thrust Stand DAQ Tool")
        self.resize(780, 720)

        self.settings = QSettings("ERAU_Prescott", "ThrustStandDAQ")

        self.offsets = {
            'load': 0.0,
            'torque': 0.0
        }

        self.worker = None
        self.thread = None
        
        self.preview_worker = None
        self.preview_thread = None
        
        self.is_logging = False
        self.csv_filename = None
        self.event_filename = None

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
        self.load_combo.currentIndexChanged.connect(self.restart_live_preview)
        port_layout.addWidget(self.load_combo, 0, 1)

        port_layout.addWidget(QLabel("Torque Cell Port:"), 1, 0)
        self.torque_combo = QComboBox()
        self.torque_combo.currentIndexChanged.connect(self.restart_live_preview)
        port_layout.addWidget(self.torque_combo, 1, 1)

        refresh_btn = QPushButton("Refresh Ports")
        refresh_btn.clicked.connect(self.refresh_ports)
        port_layout.addWidget(refresh_btn, 0, 2, 2, 1)

        port_group.setLayout(port_layout)
        main_layout.addWidget(port_group)

        # --- DIRECTORY CONFIGURATION GROUP ---
        dir_group = QGroupBox("Data Storage Directory")
        dir_layout = QHBoxLayout()

        self.dir_input = QLineEdit()
        last_dir = self.settings.value("last_output_dir", "")
        if not last_dir:
            last_dir = os.path.join(os.getcwd(), "Data")
        self.dir_input.setText(last_dir)
        dir_layout.addWidget(self.dir_input)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_directory)
        dir_layout.addWidget(browse_btn)

        dir_group.setLayout(dir_layout)
        main_layout.addWidget(dir_group)

        # --- LIVE READINGS DISPLAY GROUP ---
        live_group = QGroupBox("Live Sensor Readings")
        live_layout = QHBoxLayout()

        load_frame = QFrame()
        load_frame.setFrameShape(QFrame.Shape.StyledPanel)
        load_frame.setStyleSheet("background-color: #252526; border-radius: 5px;")
        load_layout_inner = QVBoxLayout(load_frame)
        load_layout_inner.addWidget(QLabel("Load Cell Live Reading:", alignment=Qt.AlignmentFlag.AlignCenter))
        self.load_live_label = QLabel("---", alignment=Qt.AlignmentFlag.AlignCenter)
        self.load_live_label.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.load_live_label.setStyleSheet("color: #4ec9b0;")
        load_layout_inner.addWidget(self.load_live_label)

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
        self.tare_load_btn.setEnabled(True)
        self.tare_load_btn.clicked.connect(lambda: self.tare_sensor('load'))
        control_layout.addWidget(self.tare_load_btn, 1, 0)

        self.tare_torque_btn = QPushButton("Tare Torque Cell")
        self.tare_torque_btn.setEnabled(True)
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

    def get_offset(self, sensor_type):
        return self.offsets.get(sensor_type, 0.0)

    def update_offset(self, sensor_type, raw_value):
        self.offsets[sensor_type] = raw_value

    def log_message(self, message):
        self.log_text.append(message)

    def update_live_reading(self, sensor_type, value):
        if sensor_type == 'load':
            self.load_live_label.setText(value)
        elif sensor_type == 'torque':
            self.torque_live_label.setText(value)

    def browse_directory(self):
        current_dir = self.dir_input.text().strip()
        dir_name = QFileDialog.getExistingDirectory(self, "Select Output Directory", current_dir)
        if dir_name:
            self.dir_input.setText(dir_name)
            self.settings.setValue("last_output_dir", dir_name)
            self.log_message(f"Output directory updated: {dir_name}")

    def refresh_ports(self):
        self.stop_live_preview()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        
        self.load_combo.blockSignals(True)
        self.torque_combo.blockSignals(True)
        
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

        self.load_combo.blockSignals(False)
        self.torque_combo.blockSignals(False)

        self.log_message(f"Discovered COM ports: {ports}")
        self.start_live_preview()

    def start_live_preview(self):
        """Starts preview polling when logging is idle."""
        if self.is_logging or self.preview_thread is not None:
            return

        load_port = self.load_combo.currentText()
        torque_port = self.torque_combo.currentText()

        if not load_port and not torque_port:
            return

        self.preview_thread = QThread()
        self.preview_worker = LivePreviewWorker(load_port, torque_port, self.get_offset)
        self.preview_worker.moveToThread(self.preview_thread)

        self.preview_thread.started.connect(self.preview_worker.run)
        self.preview_worker.preview_reading_signal.connect(self.update_live_reading)
        
        self.preview_worker.finished_signal.connect(self.preview_thread.quit)
        self.preview_worker.finished_signal.connect(self.preview_worker.deleteLater)
        self.preview_thread.finished.connect(self.preview_thread.deleteLater)

        self.preview_thread.start()

    def stop_live_preview(self):
        """Stops preview polling so high-speed logging thread can take over serial ports."""
        if self.preview_worker:
            self.preview_worker.stop()
            if self.preview_thread and self.preview_thread.isRunning():
                self.preview_thread.quit()
                self.preview_thread.wait(1000)
            self.preview_worker = None
            self.preview_thread = None

    def restart_live_preview(self):
        if not self.is_logging:
            self.stop_live_preview()
            self.start_live_preview()

    def start_logging(self):
        load_port = self.load_combo.currentText()
        torque_port = self.torque_combo.currentText()

        if not load_port or not torque_port:
            QMessageBox.critical(self, "Error", "Please select COM ports for both Load Cell and Torque Cell.")
            return
        if load_port == torque_port:
            QMessageBox.warning(self, "Warning", "Load Cell and Torque Cell must be assigned to distinct COM ports.")
            return

        output_dir = self.dir_input.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "Directory Required", "Please specify an output directory before starting logging.")
            return

        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create or access directory:\n{e}")
            return

        self.settings.setValue("last_output_dir", output_dir)
        self.stop_live_preview()  # Release serial ports from preview worker

        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.csv_filename = os.path.join(output_dir, f"thrust_stand_data_{timestamp_str}.csv")
        self.event_filename = os.path.join(output_dir, f"thrust_stand_events_{timestamp_str}.csv")

        self.thread = QThread()
        self.worker = LoggerWorker(
            load_port, torque_port, self.csv_filename, self.event_filename,
            self.get_offset, self.update_offset
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.message_signal.connect(self.log_message)
        self.worker.reading_signal.connect(self.update_live_reading)
        self.worker.finished_signal.connect(self.on_logging_finished)

        self.worker.finished_signal.connect(self.thread.quit)
        self.worker.finished_signal.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.is_logging = True
        self.start_btn.setEnabled(False)
        self.load_combo.setEnabled(False)
        self.torque_combo.setEnabled(False)
        self.dir_input.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.event_btn.setEnabled(True)

        self.log_message(f"\n--- Starting High-Speed Data Acquisition ---")
        self.thread.start()

    def tare_sensor(self, sensor_type):
        """Tares sensor whether currently logging or idle in preview mode."""
        sensor_name = "Load Cell" if sensor_type == 'load' else "Torque Cell"
        
        if self.is_logging and self.worker:
            self.worker.tare_sensor(sensor_type)
        else:
            current_disp = self.load_live_label.text() if sensor_type == 'load' else self.torque_live_label.text()
            try:
                val = float(current_disp)
                self.offsets[sensor_type] += val
                self.log_message(f"*** {sensor_name} Preview Tared to 0.000 ***")
            except ValueError:
                self.log_message(f"Could not tare {sensor_name}: invalid numerical reading.")

    def log_specific_point(self):
        """Prompts user for an optional comment and records an event snapshot to the separate events CSV."""
        if not self.is_logging or not self.worker:
            return

        note, ok = QInputDialog.getText(self, "Log Specific Point", "Enter event marker comment (optional):")
        if ok:
            comment = note.strip()
            self.worker.record_event_snapshot(comment)
            display_tag = f"MARKER: {comment}" if comment else "MARKER"
            self.log_message(f"*** EVENT SNAPSHOT SAVED TO EVENTS CSV: {display_tag} ***")

    def stop_logging(self):
        if not self.is_logging or not self.worker:
            return

        self.log_message("\nStopping data acquisition...")
        self.worker.stop()
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait(2000)

    def on_logging_finished(self, filename):
        self.is_logging = False
        self.start_btn.setEnabled(True)
        self.load_combo.setEnabled(True)
        self.torque_combo.setEnabled(True)
        self.dir_input.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.event_btn.setEnabled(False)

        self.log_message(f"Logging stopped. Files saved safely:\n -> {filename}\n -> {self.event_filename}\n")
        QMessageBox.information(self, "Complete", f"Logging stopped.\nData saved successfully.")
        
        self.start_live_preview()

    def closeEvent(self, event):
        self.stop_live_preview()
        if self.is_logging:
            self.stop_logging()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LoadCellLoggerApp()
    window.show()
    sys.exit(app.exec())