"""Optional serial-to-HTTP bridge for instruments/gateways that emit JSON lines.

This is a transport example only. Configure the optical instrument or its
controller to output calibrated measurements using the field names below.
It does not measure OSNR/BER itself and is not an OTDR driver.

Install optional dependency: pip install pyserial
Example: python device_gateway_serial.py --port COM4 --baud 115200
"""
from __future__ import annotations
import argparse
import json
import sys
import time

import requests


def main():
    parser = argparse.ArgumentParser(description="Forward serial JSON telemetry to FiberWatch")
    parser.add_argument("--port", required=True, help="Serial port, e.g. COM4 or /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/live/telemetry")
    args = parser.parse_args()
    try:
        import serial
    except ImportError:
        print("Install the optional serial package first: pip install pyserial", file=sys.stderr)
        raise SystemExit(2)

    print(f"Forwarding JSON-line measurements from {args.port} to {args.api}")
    with serial.Serial(args.port, args.baud, timeout=1) as port:
        while True:
            raw = port.readline().decode("utf-8", errors="replace").strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
                payload.setdefault("source", "hardware")
                response = requests.post(args.api, json=payload, timeout=5)
                response.raise_for_status()
                print(f"stored {payload.get('link_id')} at {payload.get('observed_at', 'server time')}")
            except (json.JSONDecodeError, requests.RequestException, ValueError) as exc:
                print(f"Skipped line ({exc}): {raw[:160]}", file=sys.stderr)
                time.sleep(0.1)


if __name__ == "__main__":
    main()
