# Wireless Rejection Bin Configuration

Windows desktop tool for reading and writing the **Network ID**, **Unique ID** and **DID** of a
Wireless Rejection Bin device over a USB serial (COM) port.

Built with PyQt5 and pyserial by Controlytics AI Private Limited.

## Download

Get the ready-to-run `.exe` from the [Releases](../../releases) page. It is a single file and needs
no Python installation.

## Using the app

1. Plug in the device and pick its COM port (click ⟳ to refresh the list).
2. Click **Connect**.
3. Click **Read from device**. The current values appear in the three dropdowns.
4. Choose new values (1 – 1000; you can also type a number to jump to it).
5. Click **Write to device**, then **Read from device** again to confirm. Each field shows
   "Matches device" when the write took effect.

The activity log shows every frame sent (TX) and received (RX) in hex. A log file is also written to
`logs/app.log` next to the exe.

## Serial protocol

Port settings: **9600 baud, 8 data bits, no parity, 1 stop bit**.

| Direction | Frame |
|---|---|
| Read request | `A1 A1 A1` |
| Read reply (7 bytes) | `NID(2) UID(2) DID(2) CRC(1)` |
| Write (10 bytes) | `70 75 62` ("pub") `NID(2) UID(2) DID(2) CRC(1)` |

- Values are 2-byte big-endian integers (e.g. 500 → `01 F4`).
- CRC is CRC-8, polynomial `0x07`, initial value `0x00`.
- **The read reply CRC covers the 6 data bytes only, while the write CRC covers the `pub` header and
  the data.** The device silently ignores writes with any other CRC.

Example write of NID 2, UID 3, DID 2:

```
70 75 62 00 02 00 03 00 02 62
```

## Running from source

```
pip install -r requirements.txt
python app.py
```

## Building the exe

```
python -m PyInstaller --noconfirm "Wireless Rejection Bin Configuration.spec"
```

The exe is written to `dist/`. The spec bundles `logo.png`, `icon.ico` and `arrow_down.png`.
