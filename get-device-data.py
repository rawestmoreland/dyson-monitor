#!/usr/bin/env python3
"""
List devices on a Dyson account.

Talks to the Dyson cloud API directly via dyson_api.py instead of going
through libdyson.cloud.DysonAccount.login_email_otp, which crashes with an
opaque requests.exceptions.JSONDecodeError whenever the API returns
anything other than a clean 200 + JSON body (most commonly a 429 rate
limit rendered as an HTML block page).
"""
from getpass import getpass

from libdyson.cloud.device_info import DysonDeviceInfo

from dyson_api import dyson_login, dyson_get_devices_raw

EMAIL = "rawestmoreland@gmail.com"
COUNTRY = "CH"

password = getpass("Dyson account password: ")

auth_info = dyson_login(EMAIL, COUNTRY, password)

raw_devices = dyson_get_devices_raw(auth_info)
for raw in raw_devices:
    if raw.get("LocalCredentials") is None:
        continue  # Lightcycle lights and similar aren't supported here
    d = DysonDeviceInfo.from_raw(raw)
    print(d.name, d.serial, d.product_type)
