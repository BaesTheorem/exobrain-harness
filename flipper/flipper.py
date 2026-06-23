#!/usr/bin/env python3
"""
flipper.py — drive a Flipper Zero from the command line over its USB serial CLI.

This talks to the Flipper's built-in text CLI (the same REPL you get over
`screen /dev/cu.usbmodemflip_xxxx`). No protobuf, no external Flipper libs —
just pyserial against the device's command prompt. Works on stock or any
custom firmware (Unleashed/Momentum/RogueMaster) since the CLI is upstream.

Transport is USB right now. The same command layer can later point at a
serial-over-WiFi bridge (ESP32) by pointing --port at a socket:// URL that
pyserial understands, but that's not wired up here.

Usage:
    flipper.py info
    flipper.py list [/ext]
    flipper.py read /ext/subghz/foo.sub
    flipper.py write ./local.sub /ext/subghz/foo.sub
    flipper.py delete /ext/subghz/foo.sub
    flipper.py tx-subghz /ext/subghz/foo.sub [repeat]
    flipper.py tx-ir /ext/infrared/tv.ir "Samsung" 0x07 0x02   # see notes
    flipper.py raw "storage list /ext/nfc"

Notes:
  - Reads work great for text-y files (.sub, .ir, BadUSB .txt, logs). Binary
    dumps (.nfc/.rfid) come back as the CLI renders them; fine for inspection,
    not guaranteed byte-perfect. Use `read --raw` to get exactly what the CLI emits.
  - The exact tx verbs can vary by firmware. tx-subghz / tx-ir are thin wrappers
    over `raw`; if your firmware names them differently, use `raw` directly and
    we'll adjust the wrapper.
  - While this tool holds the CLI, the Flipper shows a CLI/remote session and
    can't be hand-used at the same time. It releases on exit.
"""
import argparse
import glob
import sys
import time

try:
    import serial  # pyserial
except ImportError:
    sys.exit("pyserial not installed. Run: python3 -m pip install --break-system-packages pyserial")

PROMPT = b">: "
DEFAULT_BAUD = 115200


def find_port(explicit=None):
    """Locate the Flipper's serial port. Prefer the flip-named device."""
    if explicit:
        return explicit
    candidates = glob.glob("/dev/cu.usbmodemflip_*") or glob.glob("/dev/tty.usbmodemflip_*")
    if candidates:
        return sorted(candidates)[0]
    # Fall back to any usbmodem that isn't an obvious non-Flipper device.
    generic = [p for p in glob.glob("/dev/cu.usbmodem*")]
    if len(generic) == 1:
        return generic[0]
    if generic:
        raise SystemExit(
            "Multiple usbmodem ports found and none are flip-named:\n  "
            + "\n  ".join(generic)
            + "\nPass the right one with --port."
        )
    raise SystemExit(
        "No Flipper serial port found. Plug the Flipper in via USB, unlock it, "
        "and make sure no other program (qFlipper, the mobile app) holds the port."
    )


class Flipper:
    def __init__(self, port, baud=DEFAULT_BAUD, timeout=2.0, retries=4):
        self.port = port
        # macOS re-enumerates the Flipper's USB CDC when the port closes, so a
        # fresh open right after a previous session can land mid-reset
        # ("Device not configured", Errno 6). Retry the open a few times.
        last = None
        for attempt in range(retries):
            try:
                self.ser = serial.Serial(port, baud, timeout=timeout,
                                         dsrdtr=False, rtscts=False)
                time.sleep(0.4)
                self.ser.reset_input_buffer()
                self._drain_banner()
                return
            except (serial.SerialException, OSError) as e:
                last = e
                try:
                    self.ser.close()
                except Exception:
                    pass
                time.sleep(0.6)
        raise SystemExit(f"Could not open {port} after {retries} tries: {last}\n"
                         "Is qFlipper or the mobile app holding the port? "
                         "Unplug/replug and retry.")

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _read_until_prompt(self, idle=3.0):
        """Read until the CLI prompt returns, or we go `idle` seconds with no data."""
        buf = bytearray()
        last = time.time()
        while True:
            try:
                chunk = self.ser.read(256)
            except (serial.SerialException, OSError):
                # Device dropped the port mid-stream (re-enumeration). Return
                # whatever we got rather than crashing.
                break
            if chunk:
                buf.extend(chunk)
                last = time.time()
                if buf.endswith(PROMPT):
                    break
            else:
                if time.time() - last > idle:
                    break
        return bytes(buf)

    def _drain_banner(self):
        # Nudge the prompt and swallow the welcome banner.
        self.ser.write(b"\r")
        self._read_until_prompt(idle=1.5)

    def cmd(self, command, idle=3.0):
        """Run a CLI command, return its output (echo + trailing prompt stripped)."""
        self.ser.reset_input_buffer()
        self.ser.write(command.encode() + b"\r")
        raw = self._read_until_prompt(idle=idle)
        text = raw.decode("utf-8", errors="replace")
        # Strip the echoed command line.
        lines = text.split("\n")
        if lines and command in lines[0]:
            lines = lines[1:]
        out = "\n".join(lines)
        # Strip the trailing prompt.
        if out.rstrip().endswith(">:"):
            out = out.rstrip()[:-2]
        return out.strip("\r\n")

    def write_file(self, local_path, flipper_path):
        """Push a local file to the Flipper via `storage write`."""
        with open(local_path, "rb") as f:
            data = f.read()
        self.ser.reset_input_buffer()
        self.ser.write(f"storage write {flipper_path}\r".encode())
        time.sleep(0.4)
        self.ser.read(512)  # swallow the "type your data / Ctrl+C to end" notice
        self.ser.write(data)
        time.sleep(0.2)
        self.ser.write(b"\x03")  # Ctrl+C ends the write
        return self._read_until_prompt(idle=3.0).decode("utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description="Drive a Flipper Zero from the CLI over USB serial.")
    ap.add_argument("--port", help="serial port (default: auto-detect flip-named usbmodem)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="device_info")
    p_list = sub.add_parser("list", help="storage list <path>")
    p_list.add_argument("path", nargs="?", default="/ext")
    p_read = sub.add_parser("read", help="storage read <path>")
    p_read.add_argument("path")
    p_write = sub.add_parser("write", help="push a local file to the Flipper")
    p_write.add_argument("local")
    p_write.add_argument("flipper_path")
    p_del = sub.add_parser("delete", help="storage remove <path>")
    p_del.add_argument("path")
    p_txs = sub.add_parser("tx-subghz", help="transmit a saved .sub file")
    p_txs.add_argument("path")
    p_txs.add_argument("repeat", nargs="?", default="10")
    p_txi = sub.add_parser("tx-ir", help="transmit an IR signal (verb varies by firmware)")
    p_txi.add_argument("ir_args", nargs=argparse.REMAINDER)
    p_raw = sub.add_parser("raw", help="send any CLI command verbatim")
    p_raw.add_argument("command", nargs=argparse.REMAINDER)

    args = ap.parse_args()
    port = find_port(args.port)

    with Flipper(port) as fz:
        if args.cmd == "info":
            print(fz.cmd("device_info"))
        elif args.cmd == "list":
            print(fz.cmd(f"storage list {args.path}"))
        elif args.cmd == "read":
            print(fz.cmd(f"storage read {args.path}"))
        elif args.cmd == "write":
            print(fz.write_file(args.local, args.flipper_path))
        elif args.cmd == "delete":
            print(fz.cmd(f"storage remove {args.path}"))
        elif args.cmd == "tx-subghz":
            # tx_from_file <file> <repeat> <device: 0=CC1101_INT, 1=CC1101_EXT>
            print(fz.cmd(f"subghz tx_from_file {args.path} {args.repeat} 0", idle=5.0))
        elif args.cmd == "tx-ir":
            print(fz.cmd("ir tx " + " ".join(args.ir_args), idle=5.0))
        elif args.cmd == "raw":
            print(fz.cmd(" ".join(args.command), idle=5.0))


if __name__ == "__main__":
    main()
