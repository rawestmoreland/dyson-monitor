#!/usr/bin/env python3
"""
Dyson Air Purifier local MQTT monitor.

First run: authenticates with your Dyson account (email + OTP emailed to you),
then caches the local MQTT credentials to disk so future runs skip the login
flow entirely and connect directly over the LAN.

Env vars required (put these in a .env file or export them):
    DYSON_EMAIL      - your Dyson account email
    DYSON_PASSWORD   - your Dyson account password
    DYSON_COUNTRY    - two-letter country code, e.g. CH
    DYSON_DEVICE_IP  - local IP of the purifier on your LAN
"""

import os
import sys
import json
import time
from getpass import getpass
from pathlib import Path

from libdyson.cloud.device_info import DysonDeviceInfo
from libdyson import get_device

from dyson_api import dyson_login, dyson_get_devices_raw, load_env

CREDENTIALS_CACHE = Path(__file__).parent / "device_credentials.json"


def dyson_get_devices(auth_info):
    """Fetch and parse the device list using the authenticated token."""
    raw_devices = dyson_get_devices_raw(auth_info)

    devices = []
    for raw in raw_devices:
        if raw.get("LocalCredentials") is None:
            continue  # devices without local MQTT creds aren't supported here
        devices.append(DysonDeviceInfo.from_raw(raw))
    return devices


def get_device_info():
    """
    Returns (serial, credentials, product_type, device_ip) for the target device.
    Uses a local cache after the first successful login so subsequent runs
    never need to touch the Dyson cloud API or ask for an OTP again.
    """
    device_ip = os.environ["DYSON_DEVICE_IP"]

    if CREDENTIALS_CACHE.exists():
        cached = json.loads(CREDENTIALS_CACHE.read_text())
        return (
            cached["serial"],
            cached["credentials"],
            cached["product_type"],
            device_ip,
        )

    # No cache yet -> do the full cloud login + OTP flow once.
    email = os.environ["DYSON_EMAIL"]
    country = os.environ["DYSON_COUNTRY"]
    password = os.environ.get("DYSON_PASSWORD") or getpass("Dyson account password: ")

    auth_info = dyson_login(email, country, password)
    devices = dyson_get_devices(auth_info)
    if not devices:
        sys.exit("No devices found on this Dyson account.")

    target_serial = os.environ.get("DYSON_SERIAL")
    if target_serial:
        device = next((d for d in devices if d.serial == target_serial), None)
        if device is None:
            sys.exit(f"No device found with serial {target_serial}")
    else:
        if len(devices) > 1:
            print("Multiple devices found, using the first one:")
            for d in devices:
                print(f"  {d.serial} - {d.name}")
        device = devices[0]

    # Cache so we never need to hit the cloud API / OTP flow again.
    CREDENTIALS_CACHE.write_text(json.dumps({
        "serial": device.serial,
        "credentials": device.credential,
        "product_type": device.product_type,
        "name": device.name,
    }))
    print(f"Cached local credentials to {CREDENTIALS_CACHE}")

    return device.serial, device.credential, device.product_type, device_ip


def on_message(message):
    """Called on every pushed MQTT update from the device."""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] update received")

    env = getattr(device, "environmental_state", None)
    if env:
        print(f"  Temperature: {env.temperature - 273.15:.1f} C"
              if hasattr(env, "temperature") else "", end="")
        print(f"  Humidity: {env.humidity}%" if hasattr(env, "humidity") else "")
        print(f"  PM2.5: {getattr(env, 'particulate_matter_25', 'n/a')}")
        print(f"  PM10: {getattr(env, 'particulate_matter_10', 'n/a')}")

    state = getattr(device, "state", None)
    if state:
        print(f"  Fan speed: {getattr(state, 'speed', 'n/a')}")
        print(f"  Fan on: {getattr(state, 'is_on', 'n/a')}")


def main():
    global device

    load_env()

    serial, credentials, product_type, device_ip = get_device_info()

    device = get_device(serial, credentials, product_type)

    connected = device.connect(device_ip)
    if not connected:
        sys.exit(f"Could not connect to device at {device_ip}")

    print(f"Connected to {serial} at {device_ip}")

    device.add_message_listener(on_message)

    # Request an initial reading, then poll periodically.
    device.request_environmental_state()

    try:
        while True:
            time.sleep(30)
            device.request_environmental_state()
    except KeyboardInterrupt:
        print("\nShutting down.")
        device.disconnect()


if __name__ == "__main__":
    main()
