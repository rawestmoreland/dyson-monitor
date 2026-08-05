"""
Low-level Dyson cloud API client, shared by get-device-data.py and monitor.py.

libdyson's own HTTP client (DysonAccount.login_email_otp in particular) calls
response.json() without checking the status code first, so when the API (or
an intervening WAF) returns anything other than a clean 200 + JSON body -
most commonly a 429 rate limit rendered as an HTML block page - it blows up
with an opaque requests.exceptions.JSONDecodeError instead of a useful error.
This module retries and surfaces the real response body instead.
"""
import sys
import time

import requests

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
                  f"from {path}: {response.text[:300]!r}")
            print(f"  response headers: {dict(response.headers)}")
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


def dyson_get_devices_raw(auth_info):
    """Fetch the raw device manifest using the authenticated token."""
    headers = {**DYSON_API_HEADERS, "Authorization": f"Bearer {auth_info['token']}"}
    return api_request("GET", "/v2/provisioningservice/manifest", headers=headers)
