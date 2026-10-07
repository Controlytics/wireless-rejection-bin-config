import sys
import os
import logging
from datetime import datetime

import serial
import serial.tools.list_ports
from PyQt5 import QtCore, QtGui, QtWidgets

# Protocol
GET_COMMAND = bytes.fromhex("A1A1A1")   # Request: device replies NID(2) UID(2) DID(2) CRC(1)
SET_HEADER = b"pub"                     # 70 75 62, followed by NID(2) UID(2) DID(2) CRC(1)
# The Set CRC covers the header and the data; the device's Get reply CRC covers the data only
FIELD_BYTES = 2
VALUE_MIN, VALUE_MAX = 1, 1000          # selectable range for NID / UID / DID
REPLY_LENGTH = 3 * FIELD_BYTES + 1
BAUD_RATE = 9600

APP_TITLE = "Wireless Rejection Bin"

# Log next to the script / exe, not the current working directory
base_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
log_dir = os.path.join(base_dir, "logs")
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(log_dir, "app.log"),
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logging.info("Application started")


def resource_path(name):
    """Path to a bundled file, both from source and inside the PyInstaller exe."""
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), name)


def calculate_crc(data):
    """CRC-8, polynomial 0x07, initial value 0x00 (same as the GSM Pulse Totaliser)."""
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = (crc << 1) ^ 0x07
            else:
                crc <<= 1
            crc &= 0xFF
    return crc


def format_hex(data):
    return " ".join(format(byte, "02X") for byte in data)


# Brand colours taken from the Controlytics logo
BLUE = "#1A5CF5"
GREEN = "#2E7D32"
RED = "#D32F2F"
AMBER = "#B26A00"

STYLESHEET = f"""
QMainWindow, #body {{
    background: #F3F5F9;
}}
QWidget {{
    font-family: "Segoe UI";
    font-size: 10pt;
    color: #1F2937;
}}
#header {{
    background: white;
    border-bottom: 1px solid #E3E7EE;
}}
#appTitle {{
    font-size: 15pt;
    font-weight: 600;
    color: #111827;
}}
#appSubtitle {{
    color: #6B7280;
}}
#headerDivider {{
    background: #E3E7EE;
}}
#card {{
    background: white;
    border: 1px solid #E3E7EE;
    border-radius: 10px;
}}
#cardTitle {{
    font-size: 11pt;
    font-weight: 600;
    color: #111827;
}}
#cardHint, #fieldHint {{
    color: #6B7280;
    font-size: 9pt;
}}
#fieldLabel {{
    font-weight: 600;
}}
#statusPill {{
    border-radius: 14px;
    padding: 0px 14px;
    font-weight: 600;
}}
#statusPill[state="connected"] {{
    background: #E8F5E9;
    color: {GREEN};
}}
#statusPill[state="disconnected"] {{
    background: #F1F3F6;
    color: #6B7280;
}}
QComboBox {{
    background: white;
    border: 1px solid #CBD2DC;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 22px;
}}
QComboBox:focus {{
    border: 1px solid {BLUE};
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox::down-arrow {{
    image: url(ARROW_IMAGE);
    width: 12px;
    height: 8px;
}}
QComboBox::down-arrow:disabled {{
    image: none;
}}
QComboBox QAbstractItemView {{
    border: 1px solid #CBD2DC;
    selection-background-color: #E8EFFE;
    selection-color: #111827;
    outline: none;
}}
#valueCombo {{
    font-family: Consolas;
    font-size: 13pt;
}}
#valueCombo[valid="false"] {{
    border: 1px solid {RED};
}}
QPushButton {{
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: 600;
}}
#primaryButton {{
    background: {GREEN};
    color: white;
    border: 1px solid {GREEN};
}}
#primaryButton:hover {{
    background: #276C2B;
}}
#primaryButton:pressed {{
    background: #1F5A23;
}}
#secondaryButton {{
    background: white;
    color: {BLUE};
    border: 1px solid {BLUE};
}}
#secondaryButton:hover {{
    background: #EEF3FE;
}}
#dangerButton {{
    background: white;
    color: {RED};
    border: 1px solid {RED};
}}
#dangerButton:hover {{
    background: #FDECEC;
}}
#primaryButton:disabled, #secondaryButton:disabled, #dangerButton:disabled, #iconButton:disabled {{
    background: #F1F3F6;
    color: #A0A7B4;
    border: 1px solid #E3E7EE;
}}
#iconButton {{
    background: white;
    border: 1px solid #CBD2DC;
    border-radius: 6px;
    padding: 6px;
    font-size: 13pt;
    color: #4B5563;
}}
#iconButton:hover {{
    background: #F3F5F9;
}}
#linkButton {{
    background: transparent;
    border: none;
    color: {BLUE};
    padding: 2px 4px;
    font-weight: normal;
}}
#linkButton:hover {{
    text-decoration: underline;
}}
#console {{
    background: #0F172A;
    color: #CBD5E1;
    border: none;
    border-radius: 8px;
    font-family: Consolas;
    font-size: 10pt;
    padding: 8px;
}}
#infoValue {{
    font-weight: 600;
}}
QStatusBar {{
    background: white;
    border-top: 1px solid #E3E7EE;
    color: #4B5563;
}}
"""

LOG_COLOURS = {
    "TX": "#60A5FA",
    "RX": "#4ADE80",
    "ERR": "#F87171",
    "INFO": "#94A3B8",
}


def repolish(widget, name, value):
    """Set a dynamic property used by the stylesheet and re-apply styling."""
    widget.setProperty(name, "true" if value else "false")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class Card(QtWidgets.QFrame):
    """White rounded panel with a title row and a content layout."""

    def __init__(self, title, hint=None):
        super().__init__()
        self.setObjectName("card")
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 2)
        shadow.setColor(QtGui.QColor(15, 23, 42, 18))
        self.setGraphicsEffect(shadow)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 18)
        outer.setSpacing(12)

        self.titleRow = QtWidgets.QHBoxLayout()
        titleColumn = QtWidgets.QVBoxLayout()
        titleColumn.setSpacing(2)
        titleLabel = QtWidgets.QLabel(title)
        titleLabel.setObjectName("cardTitle")
        titleColumn.addWidget(titleLabel)
        if hint:
            hintLabel = QtWidgets.QLabel(hint)
            hintLabel.setObjectName("cardHint")
            titleColumn.addWidget(hintLabel)
        self.titleRow.addLayout(titleColumn)
        self.titleRow.addStretch()
        outer.addLayout(self.titleRow)

        self.body = QtWidgets.QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body)


class ValueField(QtWidgets.QWidget):
    """Labelled dropdown of VALUE_MIN..VALUE_MAX, sent to / read from the device as a 2-byte big-endian number."""

    changed = QtCore.pyqtSignal()

    def __init__(self, label, description):
        super().__init__()
        self.device_value = None

        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(2)

        nameLabel = QtWidgets.QLabel(label)
        nameLabel.setObjectName("fieldLabel")
        descLabel = QtWidgets.QLabel(description)
        descLabel.setObjectName("fieldHint")

        # Editable so a value can also be typed to jump straight to it
        self.combo = QtWidgets.QComboBox()
        self.combo.setObjectName("valueCombo")
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.combo.addItems([str(i) for i in range(VALUE_MIN, VALUE_MAX + 1)])
        self.combo.setMaxVisibleItems(12)
        self.combo.lineEdit().setValidator(QtGui.QIntValidator(0, 65535, self.combo))
        self.combo.setFixedWidth(170)
        self.combo.setCurrentIndex(-1)
        self.combo.lineEdit().setPlaceholderText("Select")

        self.readout = QtWidgets.QLabel()
        self.readout.setObjectName("fieldHint")
        self.readout.setMinimumWidth(170)

        layout.addWidget(nameLabel, 0, 0)
        layout.addWidget(descLabel, 1, 0)
        layout.addWidget(self.combo, 0, 1, 2, 1)
        layout.addWidget(self.readout, 0, 2, 2, 1)
        layout.setColumnStretch(0, 1)

        self.combo.currentTextChanged.connect(self.on_changed)
        self.refresh()

    def on_changed(self):
        self.refresh()
        self.changed.emit()

    def value(self):
        text = self.combo.currentText()
        return int(text) if text.isdigit() else None

    def is_valid(self):
        value = self.value()
        return value is not None and VALUE_MIN <= value <= VALUE_MAX

    def value_bytes(self):
        return self.value().to_bytes(FIELD_BYTES, "big")

    def set_from_device(self, data):
        self.device_value = int.from_bytes(data, "big")
        # Shown even when outside the dropdown range, so the user sees what the device holds
        self.combo.setCurrentText(str(self.device_value))
        self.refresh()

    def refresh(self):
        value = self.value()
        repolish(self.combo, "valid", value is None or self.is_valid())
        if value is None:
            self.readout.setText("")
        elif not self.is_valid():
            self.readout.setText(f"<span style='color:{RED}'>Choose {VALUE_MIN} – {VALUE_MAX}</span>")
        elif self.device_value is not None and value != self.device_value:
            self.readout.setText(f"Sent as 0x{value:04X}<br><span style='color:{AMBER}'>● Modified</span>")
        elif self.device_value is not None:
            self.readout.setText(f"Sent as 0x{value:04X}<br><span style='color:{GREEN}'>● Matches device</span>")
        else:
            self.readout.setText(f"Sent as 0x{value:04X}")


class SerialMonitorApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.setWindowTitle(f"{APP_TITLE} Configuration")
        self.setWindowIcon(QtGui.QIcon(resource_path("icon.ico")))
        self.resize(980, 680)
        self.setMinimumSize(880, 620)
        self.setup_ui()
        self.update_ports()
        self.set_connected(False)
        self.log("INFO", "Application started. Select a COM port and click Connect.")

    # ---------- UI construction ----------

    def setup_ui(self):
        root = QtWidgets.QWidget()
        rootLayout = QtWidgets.QVBoxLayout(root)
        rootLayout.setContentsMargins(0, 0, 0, 0)
        rootLayout.setSpacing(0)
        rootLayout.addWidget(self.build_header())

        body = QtWidgets.QWidget()
        body.setObjectName("body")
        bodyLayout = QtWidgets.QHBoxLayout(body)
        bodyLayout.setContentsMargins(20, 20, 20, 20)
        bodyLayout.setSpacing(20)

        leftColumn = QtWidgets.QVBoxLayout()
        leftColumn.setSpacing(20)
        leftColumn.addWidget(self.build_connection_card())
        leftColumn.addWidget(self.build_device_card())
        leftColumn.addStretch()
        leftWidget = QtWidgets.QWidget()
        leftWidget.setLayout(leftColumn)
        leftWidget.setFixedWidth(330)
        leftColumn.setContentsMargins(0, 0, 0, 0)

        rightColumn = QtWidgets.QVBoxLayout()
        rightColumn.setSpacing(20)
        rightColumn.addWidget(self.build_params_card())
        rightColumn.addWidget(self.build_log_card(), 1)

        bodyLayout.addWidget(leftWidget)
        bodyLayout.addLayout(rightColumn, 1)
        rootLayout.addWidget(body, 1)

        self.setCentralWidget(root)
        self.setStatusBar(QtWidgets.QStatusBar())

    def build_header(self):
        header = QtWidgets.QFrame()
        header.setObjectName("header")
        layout = QtWidgets.QHBoxLayout(header)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(18)

        logo = QtWidgets.QLabel()
        pixmap = QtGui.QPixmap(resource_path("logo.png"))
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaledToHeight(46, QtCore.Qt.SmoothTransformation))
        layout.addWidget(logo)

        divider = QtWidgets.QFrame()
        divider.setObjectName("headerDivider")
        divider.setFixedSize(1, 40)
        layout.addWidget(divider)

        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(0)
        title = QtWidgets.QLabel(APP_TITLE)
        title.setObjectName("appTitle")
        subtitle = QtWidgets.QLabel("Device configuration utility")
        subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        layout.addLayout(titles)
        layout.addStretch()

        self.statusPill = QtWidgets.QLabel()
        self.statusPill.setObjectName("statusPill")
        self.statusPill.setFixedHeight(28)
        layout.addWidget(self.statusPill)
        return header

    def build_connection_card(self):
        card = Card("Connection", f"{BAUD_RATE} baud · 8N1")

        portLabel = QtWidgets.QLabel("Serial port")
        portLabel.setObjectName("fieldLabel")
        card.body.addWidget(portLabel)

        portRow = QtWidgets.QHBoxLayout()
        portRow.setSpacing(8)
        self.portComboBox = QtWidgets.QComboBox()
        self.portComboBox.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.portComboBox.setMinimumContentsLength(10)
        self.refreshButton = QtWidgets.QPushButton("⟳")
        self.refreshButton.setObjectName("iconButton")
        self.refreshButton.setFixedSize(38, 38)
        self.refreshButton.setToolTip("Refresh port list")
        portRow.addWidget(self.portComboBox)
        portRow.addWidget(self.refreshButton)
        card.body.addLayout(portRow)

        self.connectButton = QtWidgets.QPushButton("Connect")
        self.connectButton.setCursor(QtCore.Qt.PointingHandCursor)
        card.body.addWidget(self.connectButton)

        self.refreshButton.clicked.connect(self.update_ports)
        self.connectButton.clicked.connect(self.toggle_connection)
        return card

    def build_device_card(self):
        card = Card("Device status")
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.lastReadTime = QtWidgets.QLabel("—")
        self.lastReadCrc = QtWidgets.QLabel("—")
        self.lastWriteTime = QtWidgets.QLabel("—")
        for row, (name, value) in enumerate((("Read at", self.lastReadTime),
                                              ("CRC check", self.lastReadCrc),
                                              ("Last write", self.lastWriteTime))):
            nameLabel = QtWidgets.QLabel(name)
            nameLabel.setObjectName("cardHint")
            value.setObjectName("infoValue")
            grid.addWidget(nameLabel, row, 0)
            grid.addWidget(value, row, 1, QtCore.Qt.AlignRight)
        card.body.addLayout(grid)
        return card

    def build_params_card(self):
        card = Card("Device parameters", f"Choose a value from {VALUE_MIN} to {VALUE_MAX} for each")

        self.nidField = ValueField("Network ID", "NID")
        self.uidField = ValueField("Unique ID", "UID")
        self.didField = ValueField("DID", "Device ID")
        self.fields = (("Network ID", self.nidField), ("Unique ID", self.uidField), ("DID", self.didField))

        for index, (_, field) in enumerate(self.fields):
            if index:
                line = QtWidgets.QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet("background: #EEF0F4;")
                card.body.addWidget(line)
            card.body.addWidget(field)
            field.changed.connect(self.update_buttons)

        buttonRow = QtWidgets.QHBoxLayout()
        buttonRow.setContentsMargins(0, 8, 0, 0)
        buttonRow.addStretch()
        self.getParamsButton = QtWidgets.QPushButton("Read from device")
        self.getParamsButton.setObjectName("secondaryButton")
        self.setParamsButton = QtWidgets.QPushButton("Write to device")
        self.setParamsButton.setObjectName("primaryButton")
        for button in (self.getParamsButton, self.setParamsButton):
            button.setCursor(QtCore.Qt.PointingHandCursor)
            button.setMinimumWidth(150)
            buttonRow.addWidget(button)
        card.body.addLayout(buttonRow)

        self.getParamsButton.clicked.connect(self.get_params)
        self.setParamsButton.clicked.connect(self.set_params)
        return card

    def build_log_card(self):
        card = Card("Activity log")
        clearButton = QtWidgets.QPushButton("Clear")
        clearButton.setObjectName("linkButton")
        clearButton.setCursor(QtCore.Qt.PointingHandCursor)
        card.titleRow.addWidget(clearButton)

        self.responseText = QtWidgets.QTextEdit()
        self.responseText.setObjectName("console")
        self.responseText.setReadOnly(True)
        self.responseText.setMinimumHeight(140)
        card.body.addWidget(self.responseText)

        clearButton.clicked.connect(self.responseText.clear)
        return card

    # ---------- UI state ----------

    def log(self, kind, message):
        """Append a timestamped, colour-coded line to the activity log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        colour = LOG_COLOURS[kind]
        message = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.responseText.append(
            f"<span style='color:#64748B'>{timestamp}</span>&nbsp;&nbsp;"
            f"<span style='color:{colour}; font-weight:bold'>{kind:<4}</span>&nbsp;"
            f"<span style='color:{colour if kind != 'INFO' else '#CBD5E1'}'>{message}</span>"
        )
        self.responseText.moveCursor(QtGui.QTextCursor.End)

    def set_connected(self, connected, port_name=""):
        self.statusPill.setProperty("state", "connected" if connected else "disconnected")
        self.statusPill.setText(f"●  Connected · {port_name}" if connected else "●  Disconnected")
        self.statusPill.style().unpolish(self.statusPill)
        self.statusPill.style().polish(self.statusPill)

        self.connectButton.setText("Disconnect" if connected else "Connect")
        self.connectButton.setObjectName("dangerButton" if connected else "primaryButton")
        self.connectButton.style().unpolish(self.connectButton)
        self.connectButton.style().polish(self.connectButton)
        self.connectButton.setEnabled(connected or self.portComboBox.currentData() is not None)
        self.portComboBox.setEnabled(not connected)
        self.refreshButton.setEnabled(not connected)
        self.update_buttons()

    def is_connected(self):
        return bool(self.serial_port and self.serial_port.is_open)

    def update_buttons(self):
        connected = self.is_connected()
        self.getParamsButton.setEnabled(connected)
        self.setParamsButton.setEnabled(connected and all(field.is_valid() for _, field in self.fields))

    def show_status(self, message, timeout=5000):
        self.statusBar().showMessage(message, timeout)

    # ---------- Serial ----------

    def update_ports(self):
        logging.info("Updating ports")
        self.portComboBox.clear()
        ports = serial.tools.list_ports.comports()
        if ports:
            for port in ports:
                self.portComboBox.addItem(f"{port.device} - {port.description}", port.device)
                self.portComboBox.setItemData(self.portComboBox.count() - 1, port.description, QtCore.Qt.ToolTipRole)
            logging.info(f"Available ports: {[port.device for port in ports]}")
            self.show_status(f"Found {len(ports)} port(s)")
        else:
            self.portComboBox.addItem("No ports available", None)
            logging.info("No COM ports found.")
            self.show_status("No COM ports found. Plug in the device and click ⟳")
        self.connectButton.setEnabled(bool(ports))

    def toggle_connection(self):
        if self.is_connected():
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        port = self.portComboBox.currentData()
        if not port:
            self.log("ERR", "Please select a valid COM port.")
            return

        logging.info(f"Connecting to {port}")
        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=BAUD_RATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1
            )
        except serial.SerialException as e:
            self.serial_port = None
            self.log("ERR", f"Could not open {port}: {e}")
            logging.error(f"Serial error: {e}")
            self.set_connected(False)
            return

        logging.info(f"Successfully connected to {port}.")
        self.log("INFO", f"Connected to {port} at {BAUD_RATE} baud.")
        self.show_status(f"Connected to {port}")
        self.set_connected(True, port)

    def disconnect_serial(self):
        port = self.serial_port.port if self.serial_port else ""
        if self.serial_port:
            try:
                self.serial_port.close()
            except serial.SerialException:
                pass
            logging.info("Serial port disconnected.")
            self.log("INFO", f"Disconnected from {port}.")
        self.serial_port = None
        self.set_connected(False)

    def handle_serial_error(self, error):
        """Device unplugged or port failed mid-transfer: report it and drop the connection."""
        self.log("ERR", f"Serial error: {error}")
        logging.error(f"Serial error: {error}")
        self.disconnect_serial()

    def get_params(self):
        if not self.is_connected():
            return

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.serial_port.reset_input_buffer()
            self.serial_port.write(GET_COMMAND)
            logging.info(f"Sent Get command: {GET_COMMAND.hex()}")
            self.log("TX", format_hex(GET_COMMAND))
            # Blocks until the full reply arrives or the 1 s timeout expires
            response = self.serial_port.read(REPLY_LENGTH)
        except serial.SerialException as e:
            self.handle_serial_error(e)
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        logging.info(f"Raw response: {response.hex()}")
        if not response:
            self.log("ERR", "No reply from device (timed out after 1 s).")
            self.show_status("No reply from device")
            return
        self.log("RX", format_hex(response))

        if len(response) < REPLY_LENGTH:
            self.log("ERR", f"Incomplete reply: expected {REPLY_LENGTH} bytes, got {len(response)}.")
            self.lastReadCrc.setText("Incomplete")
            return

        data, received_crc = response[:-1], response[-1]
        expected_crc = calculate_crc(data)
        self.lastReadTime.setText(datetime.now().strftime("%H:%M:%S"))
        if received_crc != expected_crc:
            self.log("ERR", f"CRC mismatch: received {received_crc:02X}, expected {expected_crc:02X}.")
            logging.warning(f"CRC mismatch: received {received_crc:02X}, expected {expected_crc:02X}")
            self.lastReadCrc.setText(f"<span style='color:{RED}'>Failed</span>")
            self.show_status("Read failed: CRC mismatch")
            return

        nid, uid, did = (data[i:i + FIELD_BYTES] for i in range(0, len(data), FIELD_BYTES))
        self.nidField.set_from_device(nid)
        self.uidField.set_from_device(uid)
        self.didField.set_from_device(did)
        self.lastReadCrc.setText(f"<span style='color:{GREEN}'>Passed ({received_crc:02X})</span>")
        self.update_buttons()
        values = [field.device_value for _, field in self.fields]
        self.log("INFO", "NID {} · UID {} · DID {}".format(*values))
        for (name, _), value in zip(self.fields, values):
            if not VALUE_MIN <= value <= VALUE_MAX:
                self.log("ERR", f"Device {name} is {value}, outside {VALUE_MIN} – {VALUE_MAX}. Choose a new value before writing.")
        logging.info(f"NID={nid.hex()} UID={uid.hex()} DID={did.hex()}")
        self.show_status("Parameters read from device")

    def set_params(self):
        logging.info("Setting params")
        for name, field in self.fields:
            if not field.is_valid():
                self.log("ERR", f"{name} must be between {VALUE_MIN} and {VALUE_MAX}.")
                field.combo.setFocus()
                return

        if not self.is_connected():
            self.log("ERR", "Serial port not open, unable to send command.")
            return

        data = b"".join(field.value_bytes() for _, field in self.fields)
        payload = SET_HEADER + data
        command = payload + bytes([calculate_crc(payload)])
        logging.info(f"Final Command with CRC: {command.hex()}")

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.serial_port.reset_input_buffer()
            self.serial_port.write(command)
            self.log("TX", format_hex(command))
            QtCore.QThread.msleep(500)
            response = self.serial_port.read_all()
        except serial.SerialException as e:
            self.handle_serial_error(e)
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        logging.info(f"Received response: {response.hex()}")
        if response:
            self.log("RX", format_hex(response))
        self.lastWriteTime.setText(datetime.now().strftime("%H:%M:%S"))
        self.show_status("Parameters written. Click Read from device to verify.")

    def closeEvent(self, event):
        if self.serial_port:
            self.serial_port.close()
        super().closeEvent(event)


if __name__ == "__main__":
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET.replace("ARROW_IMAGE", resource_path("arrow_down.png").replace("\\", "/")))
    window = SerialMonitorApp()
    window.show()
    sys.exit(app.exec_())
