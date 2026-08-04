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

import requests
from libdyson.cloud.device_info import DysonDeviceInfo
from libdyson import get_device

CREDENTIALS_CACHE = Path(__file__).parent / "device_credentials.json"

DYSON_API_HOST = "https://appapi.cp.dyson.com"
DYSON_API_HEADERS = {"User-Agent": "android client"}


def api_request(method, path, retries=3, delay=2, **kwargs):
    """
    Make a request to the Dyson API with retries and clear error output
    on any non-JSON response, instead of letting requests/json blow up
    with an opaque JSONDecodeError like the library does.
    """
    headers = {**DYSON_API_HEADERS, **kwargs.pop("headers", {})}
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.request(
                method, DYSON_API_HOST + path, headers=headers, **kwargs
            )
        except requests.RequestException as e:
            last_error = e
            print(f"  [attempt {attempt}/{retries}] network error: {e}")
            time.sleep(delay * attempt)
            continue

        if response.status_code >= 400:
            print(f"  [attempt {attempt}/{retries}] HTTP {response.status_code} "
                  f"from {path}: {response.text[:300]}")
            last_error = RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")

            if response.status_code == 429:
                # A 429 here is a Dyson-side (often WAF-level) rate limit,
                # not a transient blip - short retries just add to the count
                # against the same limit. Honor Retry-After if given, else
                # back off much longer than the generic error case.
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = int(retry_after)
                else:
                    wait = max(delay * attempt, 30) * attempt
                if attempt < retries:
                    print(f"  rate limited - waiting {wait}s before retrying "
                          "(repeated 429s usually mean you need to stop and "
                          "wait several minutes, not just retry)")
                time.sleep(wait)
                continue

            time.sleep(delay * attempt)
            continue

        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            print(f"  [attempt {attempt}/{retries}] non-JSON response from {path}: "
                  f"{response.text[:300]!r}")
            last_error = RuntimeError(f"Non-JSON response from {path}: {response.text[:300]!r}")
            time.sleep(delay * attempt)
            continue

    sys.exit(f"Giving up on {path} after {retries} attempts: {last_error}")


def dyson_login(email, country, password):
    """
    Hand-rolled version of the login flow, since the library's version
    doesn't retry or surface the actual response body when something
    other than a clean 200+JSON comes back.
    """
    print("Provisioning API access...")
    api_request("GET", "/v1/provisioningservice/application/Android/version")

    print("Checking account status...")
    status = api_request(
        "POST", "/v3/userregistration/email/userstatus",
        params={"country": country}, json={"email": email},
    )
    if status.get("accountStatus") != "ACTIVE":
        sys.exit(f"Account status is not ACTIVE: {status}")

    print("Requesting OTP email...")
    challenge = api_request(
        "POST", "/v3/userregistration/email/auth",
        params={"country": country, "culture": "en-US"}, json={"email": email},
    )
    challenge_id = challenge["challengeId"]

    otp = input("Enter the OTP emailed to you: ").strip()

    print("Verifying OTP...")
    auth_info = api_request(
        "POST", "/v3/userregistration/email/verify",
        json={
            "email": email,
            "password": password,
            "challengeId": challenge_id,
            "otpCode": otp,
        },
    )
    return auth_info  # contains {"token": ..., "tokenType": "Bearer", ...}


def dyson_get_devices(auth_info):
    """Fetch and parse the device list using the authenticated token."""
    headers = {**DYSON_API_HEADERS, "Authorization": f"Bearer {auth_info['token']}"}
    raw_devices = api_request("GET", "/v2/provisioningservice/manifest", headers=headers)

    devices = []
    for raw in raw_devices:
        if raw.get("LocalCredentials") is None:
            continue  # devices without local MQTT creds aren't supported here
        devices.append(DysonDeviceInfo.from_raw(raw))
    return devices


def load_env():
    """Minimal .env loader so we don't need python-dotenv as a dependency."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


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
