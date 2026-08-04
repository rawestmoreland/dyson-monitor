#!/usr/bin/env python3
"""Diagnose what the Dyson API is actually returning before login_email_otp."""
import requests

EMAIL = input("Email: ").strip()
COUNTRY = input("Country code (e.g. CH): ").strip()

HOST = "https://appapi.cp.dyson.com"
HEADERS = {"User-Agent": "android client"}

# Step 1: provision (this is called first internally)
r = requests.get(HOST + "/v1/provisioningservice/application/Android/version", headers=HEADERS)
print("provision_api status:", r.status_code)
print("provision_api body:", r.text[:300])
print()

# Step 2: user status check - this is where the crash happens
r = requests.post(
    HOST + "/v3/userregistration/email/userstatus",
    params={"country": COUNTRY},
    json={"email": EMAIL},
    headers=HEADERS,
)
print("userstatus status:", r.status_code)
print("userstatus headers:", dict(r.headers))
print("userstatus body:", r.text[:500])
