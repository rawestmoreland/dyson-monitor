#!/usr/bin/env python3
"""
Test whether a Dyson device's local MQTT broker is actually reachable,
independent of whatever the official app happens to choose to use.

Passive traffic sniffing only shows what the app decides to do - some Dyson
units keep a local broker listening on the LAN even when the app defaults to
cloud control, others have no local broker at all. This logs in once to get
the real decrypted local credential, then makes a direct connection attempt
to settle it either way.

Env vars (put these in a .env file or export them):
    DYSON_EMAIL      - your Dyson account email
    DYSON_PASSWORD   - your Dyson account password
    DYSON_COUNTRY    - two-letter country code, e.g. CH
    DYSON_DEVICE_IP  - local IP of the device on your LAN
    DYSON_SERIAL     - the device's serial number
"""
import os
import socket
import sys
import time
from getpass import getpass

import paho.mqtt.client as mqtt
from libdyson.cloud.device_info import DysonDeviceInfo

from dyson_api import dyson_login, dyson_get_devices_raw, load_env

TCP_PROBE_TIMEOUT = 5
MQTT_RESPONSE_TIMEOUT = 10


def find_device(serial, raw_devices):
    for raw in raw_devices:
        if raw.get("Serial") == serial:
            if raw.get("LocalCredentials") is None:
                sys.exit(
                    f"Device {serial} has no LocalCredentials on the cloud "
                    "manifest at all - the account itself has no local "
                    "control info for this device."
                )
            return DysonDeviceInfo.from_raw(raw)
    sys.exit(f"No device with serial {serial} found on this account.")


def probe_tcp_port(device_ip, port):
    try:
        with socket.create_connection((device_ip, port), timeout=TCP_PROBE_TIMEOUT):
            return True
    except OSError as e:
        print(f"  port {port}: closed/unreachable ({e})")
        return False


def probe_mqtt(serial, credential, device_ip, port):
    result = {"rc": None}

    def on_connect(client, userdata, flags, rc):
        result["rc"] = rc

    client = mqtt.Client(protocol=mqtt.MQTTv31)
    client.username_pw_set(serial, credential)
    client.on_connect = on_connect
    if port == 8883:
        client.tls_set()
        client.tls_insecure_set(True)

    client.connect_async(device_ip, port)
    client.loop_start()

    deadline = time.time() + MQTT_RESPONSE_TIMEOUT
    while time.time() < deadline and result["rc"] is None:
        time.sleep(0.2)

    client.loop_stop()
    client.disconnect()
    return result["rc"]


def describe_rc(rc):
    if rc is None:
        return "port was open, but no MQTT CONNACK came back within the timeout"
    if rc == mqtt.CONNACK_ACCEPTED:
        return "SUCCESS - local broker accepted the credentials"
    if rc == mqtt.CONNACK_REFUSED_BAD_USERNAME_PASSWORD:
        return "broker IS listening, but rejected the serial/credential as bad username/password"
    return f"broker responded but refused the connection (rc={rc})"


def main():
    load_env()

    device_ip = os.environ.get("DYSON_DEVICE_IP") or input("Device LAN IP: ").strip()
    serial = os.environ.get("DYSON_SERIAL") or input("Device serial: ").strip()
    email = os.environ.get("DYSON_EMAIL") or input("Dyson account email: ").strip()
    country = os.environ.get("DYSON_COUNTRY") or input("Country code (e.g. CH): ").strip()
    password = os.environ.get("DYSON_PASSWORD") or getpass("Dyson account password: ")

    auth_info = dyson_login(email, country, password)
    raw_devices = dyson_get_devices_raw(auth_info)
    device = find_device(serial, raw_devices)

    print(f"Got decrypted local credential for {device.serial} ({device.product_type}).")

    for port in (1883, 8883):
        print(f"Testing {device_ip}:{port} ...")
        if not probe_tcp_port(device_ip, port):
            continue
        rc = probe_mqtt(device.serial, device.credential, device_ip, port)
        print(f"  {describe_rc(rc)}")


if __name__ == "__main__":
    main()
