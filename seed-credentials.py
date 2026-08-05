#!/usr/bin/env python3
"""
Seed device_credentials.json directly, bypassing the Dyson cloud login flow.

Useful when the cloud API is rate limiting you, or when you already have the
local MQTT credential from another source - e.g. sniffing the MQTT CONNECT
packet between the official app and the device on your LAN with Wireshark
(username = serial, password = credential).

Once this file exists, monitor.py skips the cloud entirely and connects
straight to the device over LAN.
"""
import argparse
import json
from pathlib import Path

CREDENTIALS_CACHE = Path(__file__).parent / "device_credentials.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="Device serial (MQTT username)")
    parser.add_argument("--credential", required=True, help="Local MQTT password")
    parser.add_argument(
        "--product-type", required=True,
        help="libdyson product type code, e.g. TP04, PH01, 438E - also visible "
             "in the MQTT topic names as <product_type>/<serial>/...",
    )
    parser.add_argument("--name", default=None, help="Optional friendly name")
    args = parser.parse_args()

    CREDENTIALS_CACHE.write_text(json.dumps({
        "serial": args.serial,
        "credentials": args.credential,
        "product_type": args.product_type,
        "name": args.name or args.serial,
    }))
    print(f"Wrote {CREDENTIALS_CACHE}")


if __name__ == "__main__":
    main()
